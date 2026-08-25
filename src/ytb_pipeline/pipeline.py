"""Orchestrator: chạy 1 project qua WorkflowGraph 4 node (DAG + checkpoint).

`ytb batch start` là cổng ideation + QA đầu tiên. Node `input` ở đây chạy lại
`validate_script_payload` + `QAAgent` (strict nếu ruleset_id khớp) như một lớp
phòng thủ thứ hai ngay trước khi tốn TTS/render — không tin tưởng mù quáng vào
trạng thái đã duyệt lúc batch start, vì file script trên đĩa có thể đã đổi.

Trạng thái từng node persist vào `<projects_dir>/<slug>/project.json`
(CheckpointManager) — resume skip node DONE, node stale được reset qua
`load_or_create_project`. Đường linear `run()` cũ đã bỏ: `python -m
ytb_pipeline` giờ là caller duy nhất, đi qua `run_project`.

Voiceover/Render/Publish chọn provider qua `providers/registry.py` —
KHÔNG còn `if tts_provider == ...` / `if render_provider == ...` ở đây.
"""

from dataclasses import asdict, is_dataclass, replace
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any

from .analytics.quality_report import (
    QualityReportInput,
    RenderEvidence,
    ScriptSection,
    build_repair_brief,
    evaluate_pre_publish_quality,
    write_quality_report,
)
from .agents.base import AgentStatus
from .agents.qa_agent import QAAgent
from .content_contract import CONTRACT_VERSION
from .content_profiles import load_content_profile, profile_fingerprint
from .ideation.generator import load_script
from .ideation.script_contract import validate_script_payload
from .project.checkpoint import CheckpointManager
from .project.models import NodeStatus, Project
from .project.workflow import NodeDef, WorkflowGraph
from .providers.registry import get_render_provider, get_voice_provider
from .config.settings import settings
from .pkg.models import PublishResult, RenderedVideo, Voiceover
from .publish.multiplatform import publish_to_platforms
from .render.validation import validate_final_video
from .voiceover.quality import AudioQualityResult, FasterWhisperSttAdapter, run_audio_quality_gate
from .voiceover.validation import validate_audio

STAGE_ORDER = ("input", "voiceover", "render", "publish")


def enforce_audio_quality(result: AudioQualityResult) -> None:
    """Block failed post-TTS evidence only when the operator selected strict.

    The audio gate itself is local and cacheable.  Report mode deliberately
    preserves the current batch behaviour: it records evidence without
    rejecting a render.
    """
    if settings.quality_gate_mode == "strict" and not result.passed:
        details = "; ".join(
            f"{getattr(issue, 'code', 'UNKNOWN')}: {getattr(issue, 'message', '')}"
            for issue in result.issues
        )
        raise ValueError(f"Audio quality gate chặn render: {details or 'audio không đạt QA.'}")


def enforce_pre_publish_quality(status: str) -> None:
    """Release findings always block; report mode is only for measurements."""
    if status in {"blocked", "error"}:
        raise ValueError("Pre-publish quality gate chặn publish: report có lỗi cần sửa.")


def _quality_enabled() -> bool:
    return settings.quality_gate_mode != "off"


def _audio_quality_output(result: AudioQualityResult) -> dict[str, Any]:
    """Keep checkpoint output JSON-safe without changing the immutable model."""
    return {
        "passed": result.passed,
        "cache_key": result.cache_key,
        "cached": result.cached,
        "issues": [asdict(issue) if is_dataclass(issue) else vars(issue) for issue in result.issues],
        "metrics": result.metrics,
        "repair_payload": result.repair_payload,
    }


def _audio_quality_findings(result: AudioQualityResult | None) -> tuple[dict[str, Any], ...]:
    if result is None:
        return ()
    return tuple({
        "source": "audio",
        "rule": f"audio.{getattr(issue, 'code', 'unknown').lower()}",
        "severity": getattr(issue, "severity", "error"),
        "message": getattr(issue, "message", "Audio quality gate có lỗi."),
        "excerpt": json.dumps(getattr(issue, "repair", {}), ensure_ascii=False, sort_keys=True),
    } for issue in result.issues)


def _audio_quality_findings_from_output(data: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    """Rehydrate portable upstream findings from the checkpoint, not the model."""
    issues = data.get("issues", ())
    if not isinstance(issues, list):
        return ()
    return tuple({
        "source": "audio",
        "rule": f"audio.{str(issue.get('code', 'unknown')).lower()}",
        "severity": str(issue.get("severity", "error")),
        "message": str(issue.get("message", "Audio quality gate có lỗi.")),
        "excerpt": json.dumps(issue.get("repair", {}), ensure_ascii=False, sort_keys=True),
    } for issue in issues if isinstance(issue, dict))


def render_evidence_for(video: RenderedVideo) -> RenderEvidence:
    """Read dimensions from the rendered local artifact for the report."""
    if video.video_path is None:
        raise FileNotFoundError("Quality report: video_path trống.")
    try:
        completed = subprocess.run(
            [
                "ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-show_streams", "-of", "json", str(video.video_path),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        data = json.loads(completed.stdout)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        raise ValueError(f"Quality report: không đọc được render evidence: {exc}") from exc
    stream = next((item for item in data.get("streams", []) if item.get("codec_type") == "video"), None)
    if stream is None:
        raise ValueError("Quality report: render thiếu video stream.")
    return RenderEvidence(
        width=int(stream.get("width") or 0),
        height=int(stream.get("height") or 0),
        duration_sec=float(data.get("format", {}).get("duration") or 0) or None,
    )


def write_post_render_quality_report(
    project: Project,
    video: RenderedVideo,
    audio_result: AudioQualityResult | None = None,
    audio_output: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Persist local JSON/Markdown evidence and a bounded repair brief.

    This intentionally reports only.  Editorial scripts were already approved
    at batch start, so this stage must not re-open the batch gate or call an LLM.
    """
    sections = tuple(
        ScriptSection(segment.caption, segment.narration, segment.purpose)
        for segment in video.segments
    )
    report = evaluate_pre_publish_quality(QualityReportInput(
        slug=project.project_id,
        video_type=video.video_type,
        title=video.title,
        thumbnail_text=(
            video.thumbnail_brief.headline
            if video.thumbnail_brief is not None
            else ""
        ),
        hook_text=video.segments[0].narration if video.segments else "",
        sections=sections,
        render=render_evidence_for(video),
        upstream_findings=(
            _audio_quality_findings(audio_result)
            if audio_result is not None
            else _audio_quality_findings_from_output(audio_output or {})
        ),
    ))
    artifacts = write_quality_report(report, settings.quality_reports_dir)
    brief_path = artifacts.json_path.with_suffix(".repair.md")
    brief_path.write_text(build_repair_brief(report, max_items=3, max_excerpt_chars=160), encoding="utf-8")
    return {
        "quality_report_json": str(artifacts.json_path),
        "quality_report_markdown": str(artifacts.markdown_path),
        "quality_repair_brief": str(brief_path),
        "quality_status": report.status,
    }


def validate_render_orientation(video_type: str) -> None:
    """Chặn sai khung hình trước khi tốn chi phí dựng từng segment.

    Render provider lấy orientation từ settings, còn loại nội dung nằm trong
    script. Hai nguồn này phải khớp ở ranh giới pipeline; Final QA vẫn giữ vai
    trò phòng thủ cuối cùng cho các output cũ/resume.
    """
    expected = {"long": "landscape", "short": "portrait"}.get(video_type)
    if expected is None:
        raise ValueError(f"video_type không hợp lệ để render: {video_type!r}")
    if settings.orientation != expected:
        label = "Long" if video_type == "long" else "Short"
        raise ValueError(
            f"{label} phải render {expected}; cấu hình hiện tại là {settings.orientation}."
        )


def stage_names(through: str = "publish") -> tuple[str, ...]:
    """Stages needed to reach ``through`` from a batch-start-approved script."""
    try:
        return STAGE_ORDER[:STAGE_ORDER.index(through) + 1]
    except ValueError as exc:
        raise ValueError(f"Stage không hợp lệ: {through}") from exc


def load_or_create_project(script_source: str, checkpoint: CheckpointManager) -> Project:
    """Load project.json đã có (resume) hoặc tạo Project mới cho 1 kịch bản.

    Node stale được reset về PENDING trước khi trả (xem `_reset_stale_nodes`),
    và project được save lại ngay để trạng thái trên đĩa nhất quán.
    """
    from .ideation.generator import _resolve

    path = _resolve(script_source)
    script_sha256 = _script_sha256(path)
    script_ruleset_id = _script_ruleset_id(path)
    script_profile = _script_profile(path)
    existing = checkpoint.load(path.stem)
    if existing is None:
        project = Project(
            project_id=path.stem,
            script_path=str(path),
            metadata={
                "script_sha256": script_sha256,
                "ruleset_id": script_ruleset_id,
                **script_profile,
            },
        )
    else:
        metadata = dict(existing.metadata)
        if (
            metadata.get("script_sha256") != script_sha256
            or metadata.get("ruleset_id") != script_ruleset_id
            or metadata.get("content_profile_fingerprint")
            != script_profile.get("content_profile_fingerprint")
            # A legacy ruleset can reference audio rendered with an obsolete
            # F5 tempo or a superseded QA policy.  It must never resume a
            # DONE node simply because its on-disk script/checkpoint agree.
            # Clear nodes so the input contract gate can reject it before TTS.
            or script_ruleset_id != CONTRACT_VERSION
        ):
            # No downstream artifact may survive a script or contract change.
            # This is intentionally broader than file-existence stale checks:
            # otherwise old narration/render could be uploaded with new metadata.
            metadata.update({
                "script_sha256": script_sha256,
                "ruleset_id": script_ruleset_id,
                **script_profile,
            })
            project = replace(existing, script_path=str(path), nodes={}, metadata=metadata)
        else:
            metadata.update(script_profile)
            project = replace(existing, script_path=str(path), metadata=metadata)
    project = _reset_stale_nodes(project)
    checkpoint.save(project)
    return project


def _script_sha256(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"Không tìm thấy kịch bản: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _script_ruleset_id(path: Path) -> str:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Kịch bản không phải JSON hợp lệ: {path}") from exc
    return str(raw.get("ruleset_id", "")).strip()


def _script_profile(path: Path) -> dict[str, str]:
    """Persist the profile identity beside checkpoints for audit/resume."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Kịch bản không phải JSON hợp lệ: {path}") from exc
    profile_id = str(raw.get("profile_id") or settings.content_profile_id).strip()
    profile = load_content_profile(profile_id)
    return {
        "content_profile_id": profile_id,
        "content_profile_version": str(raw.get("profile_version") or "").strip(),
        "content_profile_fingerprint": profile_fingerprint(profile),
    }


def _reset_stale_nodes(project: Project) -> Project:
    """Đưa node DONE nhưng stale về PENDING trước khi resume.

    - `publish` DONE nhưng chưa từng upload thật (dry-run/export tay trước đó)
      -> luôn chạy lại publish; chỉ upload thật (uploaded=True) mới được skip.
    - `render`/`voiceover` DONE nhưng file output không còn trên đĩa (và khâu
      sau chưa DONE để rehydrate từ đó) -> phải chạy lại.
    """
    current = project

    publish = current.nodes.get("publish")
    if publish is not None and publish.status == NodeStatus.DONE:
        platforms = (publish.output_data or {}).get("platforms", {})
        if not any(entry.get("uploaded") for entry in platforms.values()):
            current = current.with_node(_pending_again(publish))

    for node_id, next_id in (("render", "publish"), ("voiceover", "render")):
        node = current.nodes.get(node_id)
        nxt = current.nodes.get(next_id)
        next_done = nxt is not None and nxt.status == NodeStatus.DONE
        if node is not None and node.status == NodeStatus.DONE and not next_done:
            if not node.output_ref or not Path(node.output_ref).exists():
                current = current.with_node(_pending_again(node))

    # QA nodes contain only a snapshot of local evidence.  When their
    # downstream boundary has not completed, retry QA on resume (using its
    # cache if content is unchanged) without ever re-running TTS or render.
    for node_id, next_id in (("audio_quality", "render"), ("render_quality", "publish")):
        node = current.nodes.get(node_id)
        nxt = current.nodes.get(next_id)
        next_done = nxt is not None and nxt.status == NodeStatus.DONE
        if node is not None and node.status == NodeStatus.DONE and not next_done:
            current = current.with_node(_pending_again(node))

    return current


def _pending_again(node):
    return replace(node, status=NodeStatus.PENDING, output_ref=None,
                   output_data={}, completed_at=None, error=None)


def publish_summary(project: Project, checkpoint: CheckpointManager) -> tuple[bool, str | None]:
    """(uploaded, url) của platform chính từ output node publish trong checkpoint."""
    platforms = checkpoint.get_output_data(project, "publish").get("platforms", {})
    entry: dict = {}
    for key in ("youtube_short", "youtube_long", "youtube"):
        if key in platforms:
            entry = platforms[key]
            break
    else:
        entry = next(iter(platforms.values()), {})
    return bool(entry.get("uploaded")), entry.get("url")


def _primary_publish_result(results: dict[str, PublishResult]) -> PublishResult:
    for key in ("youtube_short", "youtube_long", "youtube"):
        if key in results:
            return results[key]
    return next(iter(results.values()))


def _node_script_path(project: Project) -> str:
    """script_path đã được batch start chấp nhận — dùng làm input production."""
    if not project.script_path:
        raise ValueError(f"Project '{project.project_id}' thiếu script_path")
    return project.script_path


def _path_or_none(value: str | None) -> Path | None:
    return Path(value) if value else None


def _path_str(value: Path | None) -> str | None:
    return str(value) if value is not None else None


def _voiceover_output_data(voiceover: Voiceover) -> dict:
    return {
        "audio_path": _path_str(voiceover.audio_path),
        "duration_sec": voiceover.duration_sec,
        "segments": [
            {
                "index": index,
                "audio_path": _path_str(segment.audio_path),
                "duration_sec": segment.duration_sec,
            }
            for index, segment in enumerate(voiceover.segments)
        ],
    }


def _rendered_output_data(video: RenderedVideo) -> dict:
    return {
        **_voiceover_output_data(video),
        "video_path": _path_str(video.video_path),
        "thumbnail_path": _path_str(video.thumbnail_path),
    }


def _record_continuity(current: Project, result: PublishResult) -> None:
    """Ghi tập vừa lên sóng vào continuity ledger của profile.

    Chỉ chạy sau khi upload thật thành công: một dry-run không làm thay đổi
    lịch sử series. Lỗi ghi ledger KHÔNG được đánh hỏng một video đã publish —
    video đã ra ngoài rồi, còn ledger thì sửa tay được.
    """
    from .ideation.continuity import ContinuityError, record_published_episode

    try:
        payload = json.loads(Path(_node_script_path(current)).read_text(encoding="utf-8"))
        profile = load_content_profile(
            str(payload.get("profile_id") or "").strip() or None
        )
        changed = record_published_episode(
            profile,
            payload,
            slug=str(payload.get("slug") or current.project_id),
            title=str(payload.get("title") or ""),
            published_at=settings.youtube_publish_at or "",
            url=result.url or "",
        )
    except (OSError, ValueError, ContinuityError) as exc:
        print(f"  ⚠ Không ghi được continuity ledger (không chặn publish): {exc}")
        return
    if changed:
        print(f"  ✓ Đã ghi tập vào continuity ledger của profile '{profile.profile_id}'")


def _publish_results_output_data(results: dict[str, PublishResult]) -> dict:
    return {
        "platforms": {
            platform: {
                "uploaded": result.uploaded,
                "url": result.url,
                "youtube_id": result.youtube_id,
                "video_path": _path_str(result.video_path),
                "thumbnail_path": _path_str(result.thumbnail_path),
            }
            for platform, result in results.items()
        }
    }


async def run_project(project: Project, checkpoint: CheckpointManager, through: str = "publish") -> Project:
    """Chạy 1 Project qua input đã approved → voiceover → render → publish.

    Mỗi node skip nếu đã DONE trong checkpoint (resume). Object trung gian
    (Script/Voiceover/RenderedVideo) được giữ trong closure `state` — output_ref
    của node ghi vào project.json chỉ là path/identifier nhẹ để resume; object
    đầy đủ được tái tạo lại nếu cần load lại từ output_ref khi resume từ giữa.
    """
    state: dict[str, object] = {}

    def enforce_checkpointed_audio_quality(current: Project) -> None:
        """Fail closed before render while keeping the completed audio node.

        A real audio-content defect (`quality_status="failed"`, e.g. transcript
        mismatch, silence, low volume) always blocks render, in every
        `quality_gate_mode` — not just "strict". Rendering AI B-roll for a video
        whose audio is already known-bad wastes the most expensive compute step
        in the pipeline for no benefit: the render_quality gate would reject it
        at publish anyway (see `write_post_render_quality_report`'s upstream
        findings), so failing earlier only saves compute, it never changes which
        videos end up published.

        A local QA *tooling* crash (`quality_status="error"`, e.g. STT cache
        directory unwritable) is a different failure mode — the audio itself may
        be fine — so it only blocks in "strict"; `audio_quality_fn` already
        downgrades a crash to `"warning"` outside strict mode, which this
        function does not block on.
        """
        data = checkpoint.get_output_data(current, "audio_quality")
        if data.get("quality_status") not in {"failed", "error"}:
            return
        details = data.get("quality_warning")
        if not details:
            details = "; ".join(
                f"{issue.get('code', 'UNKNOWN')}: {issue.get('message', '')}"
                for issue in data.get("issues", ()) if isinstance(issue, dict)
            )
        raise ValueError(f"Audio quality gate chặn render: {details or 'audio không đạt QA.'}")

    def script_for(current: Project):
        script = state.get("script")
        if script is None:
            script = load_script(_node_script_path(current))
            state["script"] = script
        return script

    def voiceover_for(current: Project) -> Voiceover:
        voiceover = state.get("voiceover")
        if voiceover is not None:
            return voiceover  # type: ignore[return-value]
        ref = checkpoint.get_output(current, "voiceover")
        if not ref:
            raise ValueError("voiceover node chưa có output_ref để resume")
        script = replace(script_for(current), project_id=current.project_id)
        data = checkpoint.get_output_data(current, "voiceover")
        audio_path = Path(ref)
        voiced = []
        segment_data = data.get("segments") or []
        if segment_data:
            by_index = {int(item.get("index", index)): item for index, item in enumerate(segment_data)}
            for i, seg in enumerate(script.segments):
                item = by_index.get(i, {})
                voiced.append(
                    replace(
                        seg,
                        audio_path=_path_or_none(item.get("audio_path")),
                        duration_sec=float(item.get("duration_sec") or 0.0),
                    )
                )
            total = float(data.get("duration_sec") or sum(s.duration_sec for s in voiced))
        else:
            from .voiceover.tts import _probe_duration_or_zero, _segment_audio_path, _slugify, _voice_profile

            slug = _slugify(script.title)
            profile = _voice_profile(script)
            for i, seg in enumerate(script.segments):
                seg_path = _segment_audio_path(slug, profile, i, narration=seg.narration, voice=script.voice)
                dur = _probe_duration_or_zero(seg_path) if seg_path.exists() else 0.0
                voiced.append(replace(seg, audio_path=seg_path if seg_path.exists() else None, duration_sec=dur))
            total = _probe_duration_or_zero(audio_path) if audio_path.exists() else sum(s.duration_sec for s in voiced)

        enriched = replace(script, segments=tuple(voiced))
        voiceover = replace(Voiceover(**vars(enriched)), audio_path=audio_path, duration_sec=total)
        state["voiceover"] = voiceover
        return voiceover

    def rendered_for(current: Project) -> RenderedVideo:
        video = state.get("video")
        if video is not None:
            return video  # type: ignore[return-value]
        ref = checkpoint.get_output(current, "render")
        if not ref:
            raise ValueError("render node chưa có output_ref để resume")
        voiceover = voiceover_for(current)
        data = checkpoint.get_output_data(current, "render")
        path = Path(ref)
        thumb = _path_or_none(data.get("thumbnail_path")) or path.with_name(f"{path.stem}_thumb.jpg")

        rendered = replace(
            RenderedVideo(**vars(voiceover)),
            video_path=path,
            thumbnail_path=thumb if thumb.exists() else None,
        )
        state["video"] = rendered
        return rendered

    async def input_fn(current: Project):
        script_path = _node_script_path(current)
        try:
            raw_payload = json.loads(Path(script_path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Không đọc được script contract: {exc}") from exc
        contract = validate_script_payload(raw_payload)
        if not contract.publishable:
            details = "; ".join(f"{item.path}: {item.message}" for item in contract.findings)
            raise ValueError(f"Script contract chặn TTS: {details}")
        script = load_script(script_path)
        qa = await QAAgent().run({
            "script": script,
            "strict": script.ruleset_id == CONTRACT_VERSION,
        })
        if qa.status is not AgentStatus.SUCCESS:
            raise ValueError(f"Script QA không chạy được: {qa.error or 'unknown error'}")
        decision = qa.output or {}
        if not decision.get("passed"):
            details = "; ".join(
                f"{item.get('rule', 'rule')}: {item.get('detail', '')}"
                for item in decision.get("violations", [])
            )
            raise ValueError(f"Script QA chặn TTS: {details or 'unknown violation'}")
        print(f"[0/3] Input     ✓  {script.title} ({len(script.segments)} đoạn; approved by batch start)")
        state["script"] = script
        return _node_script_path(current), {
            "title": script.title,
            "segments": len(script.segments),
            "ruleset_id": script.ruleset_id,
            "script_sha256": current.metadata.get("script_sha256"),
            "qa_decision": "pass",
        }

    async def voiceover_fn(current: Project):
        script = state.get("script")
        if script is None:
            script = load_script(_node_script_path(current))
        # Keep the immutable editorial Script, but enrich this production copy
        # with the checkpoint/queue slug so artifact names remain stable when a
        # title is edited.
        script = replace(script, project_id=current.project_id)
        voice = get_voice_provider()
        print("[2/4] Voiceover ▶  đang tạo audio...")
        voiceover = await voice.synthesise(script, Path("assets/audio"))
        validate_audio(voiceover)
        print(f"[2/4] Voiceover ✓  {voiceover.audio_path}  ({voiceover.duration_sec:.1f}s)")
        state["voiceover"] = voiceover
        return str(voiceover.audio_path), _voiceover_output_data(voiceover)

    async def audio_quality_fn(current: Project):
        """Checkpoint audio QA separately so a strict failure never loses TTS."""
        voiceover = voiceover_for(current)
        output_ref = str(voiceover.audio_path)
        if not _quality_enabled():
            return output_ref, {"quality_status": "off"}
        try:
            result = run_audio_quality_gate(
                voiceover,
                stt_adapter=FasterWhisperSttAdapter(
                    model_path=settings.quality_stt_model_path,
                    device=settings.quality_stt_device,
                    compute_type=settings.quality_stt_compute_type,
                    cpu_threads=settings.quality_stt_cpu_threads,
                ),
                cache_dir=settings.quality_reports_dir / "audio_cache",
                require_transcript=settings.e2e_test,
            )
            state["audio_quality"] = result
            output_data = _audio_quality_output(result)
            output_data["quality_status"] = "pass" if result.passed else "failed"
        except Exception as exc:  # noqa: BLE001 - report mode is best-effort by contract.
            status = "error" if settings.quality_gate_mode == "strict" else "warning"
            print(f"  ⚠ Audio quality gate không chạy được: {exc}")
            return output_ref, {"quality_status": status, "quality_warning": str(exc)}

        if not result.passed:
            print("  ⚠ Audio quality gate phát hiện lỗi; đã lưu report cục bộ.")
        return output_ref, output_data

    async def render_fn(current: Project):
        voiceover = voiceover_for(current)
        enforce_checkpointed_audio_quality(current)
        validate_render_orientation(voiceover.video_type)
        renderer = get_render_provider()
        print(f"[3/4] Render    ▶  đang dựng video ({settings.render_provider}/{settings.orientation})...")
        video = await renderer.render(voiceover, Path("assets/output"))
        validate_final_video(video)
        print(f"[3/4] Render    ✓  ({settings.render_provider}/{settings.orientation}) {video.video_path}")
        state["video"] = video
        return str(video.video_path), _rendered_output_data(video)

    async def render_quality_fn(current: Project):
        """Persist QA artifacts after render without risking the video checkpoint."""
        video = rendered_for(current)
        output_ref = str(video.video_path)
        if not _quality_enabled():
            return output_ref, {"quality_status": "off"}
        try:
            return output_ref, write_post_render_quality_report(
                current,
                video,
                audio_output=checkpoint.get_output_data(current, "audio_quality"),
            )
        except Exception as exc:  # noqa: BLE001 - report mode must not fail production media.
            status = "error" if settings.quality_gate_mode == "strict" else "warning"
            print(f"  ⚠ Render quality report không ghi được: {exc}")
            return output_ref, {"quality_status": status, "quality_warning": str(exc)}

    async def publish_fn(current: Project):
        if _script_sha256(Path(_node_script_path(current))) != current.metadata.get("script_sha256"):
            raise ValueError("Release manifest không khớp script hiện tại; phải chạy lại từ Script QA.")
        input_data = checkpoint.get_output_data(current, "input")
        if (
            current.metadata.get("ruleset_id") != CONTRACT_VERSION
            or input_data.get("ruleset_id") != current.metadata.get("ruleset_id")
            or input_data.get("script_sha256") != current.metadata.get("script_sha256")
            or input_data.get("qa_decision") != "pass"
        ):
            raise ValueError("Release manifest thiếu Script QA/hashes hợp lệ; chặn publish.")
        video = rendered_for(current)
        # Resume có thể rehydrate render cũ mà không chạy lại render_fn; luôn
        # áp dụng final QA tại ranh giới publish để output stale không lọt ra ngoài.
        validate_final_video(video)
        if _quality_enabled():
            enforce_pre_publish_quality(
                str(checkpoint.get_output_data(current, "render_quality").get("quality_status", "error"))
            )
        print("[4/4] Publish   ▶  đang upload...")
        publish_results = await publish_to_platforms(video, project_id=current.project_id)
        result = _primary_publish_result(publish_results)
        print(f"[4/4] Publish   ✓  uploaded={result.uploaded}")

        if result.uploaded and settings.drive_backup:
            from .publish.drive import backup_to_drive
            try:
                backup_to_drive(result.video_path, move=True)
                _cleanup_after_success(result)
            except Exception as exc:  # noqa: BLE001
                print(f"  ⚠ Đưa lên Drive thất bại (giữ bản local): {exc}")

        if result.uploaded:
            _record_continuity(current, result)

        state["result"] = result
        return result.url or str(result.video_path), _publish_results_output_data(publish_results)

    node_map = {
        "input": NodeDef(node_id="input", stage="input", fn=input_fn, deps=[]),
        "voiceover": NodeDef(node_id="voiceover", stage="voiceover", fn=voiceover_fn, deps=["input"]),
        "audio_quality": NodeDef(node_id="audio_quality", stage="quality", fn=audio_quality_fn, deps=["voiceover"]),
        "render": NodeDef(node_id="render", stage="render", fn=render_fn, deps=["audio_quality"]),
        "render_quality": NodeDef(node_id="render_quality", stage="quality", fn=render_quality_fn, deps=["render"]),
        "publish": NodeDef(node_id="publish", stage="publish", fn=publish_fn, deps=["render_quality"]),
    }
    selected_stages = stage_names(through)
    node_names = list(selected_stages)
    if "render" in selected_stages:
        node_names.insert(node_names.index("render"), "audio_quality")
        node_names.insert(node_names.index("render") + 1, "render_quality")
    nodes = [node_map[name] for name in node_names]

    graph = WorkflowGraph(nodes, checkpoint)
    return await graph.execute(project)


def _cleanup_after_success(result: PublishResult) -> None:
    """Clean local render/audio artifacts only after YouTube upload + Drive backup."""
    import shutil

    paths: set[Path] = set()
    if result.thumbnail_path:
        paths.add(Path(result.thumbnail_path))
    if result.audio_path:
        paths.add(Path(result.audio_path))
    for segment in result.segments:
        if segment.audio_path:
            paths.add(Path(segment.audio_path))
    for path in paths:
        path.unlink(missing_ok=True)
    # Renderer AI tách workspace theo slug. Tuyệt đối không xoá cả `_frames_ai`:
    # batch có hai worker, nên workspace còn lại có thể đang là input ffmpeg.
    workspace_slug = (
        result.audio_path.stem if result.audio_path else
        result.video_path.stem if result.video_path else ""
    )
    if workspace_slug:
        shutil.rmtree(Path("assets/output") / "_frames_ai" / workspace_slug, ignore_errors=True)
    print("  ✓ Đã clean up audio/render artifacts sau khi backup Drive.")
