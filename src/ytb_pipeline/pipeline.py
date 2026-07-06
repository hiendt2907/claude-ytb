"""Orchestrator: nối 4 khâu thành pipeline tuần tự.

Ideation = nạp kịch bản Claude viết sẵn (scripts/*.json). Mỗi khâu sau là hàm
thuần nhận model trước, trả model làm giàu thêm qua replace().

Voiceover/Render/Publish chọn provider qua `providers/registry.py` —
KHÔNG còn `if tts_provider == ...` / `if render_provider == ...` ở đây.
"""

import asyncio
from dataclasses import replace
from pathlib import Path

from .ideation.generator import load_script
from .ideation.approval import gate
from .project.checkpoint import CheckpointManager
from .project.models import Project
from .project.workflow import NodeDef, WorkflowGraph
from .providers.registry import get_publish_provider, get_render_provider, get_voice_provider
from .config.settings import settings
from .pkg.models import PublishResult, RenderedVideo, Voiceover
from .publish.multiplatform import publish_to_platforms


def run(script_source: str) -> PublishResult:
    """Chạy pipeline từ 1 kịch bản Claude đã viết sẵn (scripts/*.json)."""
    script = load_script(script_source)
    print(f"[1/4] Ideation  ✓  {script.title} ({len(script.segments)} đoạn)")
    script = gate(script)  # cổng duyệt Telegram (bỏ qua nếu TELEGRAM_APPROVAL=false)

    voice = get_voice_provider()
    print("[2/4] Voiceover ▶  đang tạo audio...")
    voiceover = asyncio.run(voice.synthesise(script, Path("assets/audio")))
    print(f"[2/4] Voiceover ✓  {voiceover.audio_path}  ({voiceover.duration_sec:.1f}s)")

    renderer = get_render_provider()
    print(f"[3/4] Render    ▶  đang dựng video ({settings.render_provider}/{settings.orientation})...")
    video = asyncio.run(renderer.render(voiceover, Path("assets/output")))
    print(f"[3/4] Render    ✓  ({settings.render_provider}/{settings.orientation}) {video.video_path}")

    print("[4/4] Publish   ▶  đang upload...")
    result = _primary_publish_result(asyncio.run(publish_to_platforms(video)))
    print(f"[4/4] Publish   ✓  uploaded={result.uploaded}")

    # Sau khi upload thật, MOVE video lên Drive (xoá local). Lỗi Drive không hỏng pipeline
    # và KHÔNG xoá local (move chỉ chạy khi Drive nhận file thành công).
    if result.uploaded and settings.drive_backup:
        from .publish.drive import backup_to_drive
        try:
            backup_to_drive(result.video_path, move=True)
        except Exception as exc:  # noqa: BLE001
            print(f"  ⚠ Đưa lên Drive thất bại (giữ bản local): {exc}")

    return result


def _primary_publish_result(results: dict[str, PublishResult]) -> PublishResult:
    for key in ("youtube_short", "youtube_long", "youtube"):
        if key in results:
            return results[key]
    return next(iter(results.values()))


def _node_script_path(project: Project) -> str:
    """script_path khai báo trên Project — dùng làm input cho node ideation."""
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


async def run_project(project: Project, checkpoint: CheckpointManager) -> Project:
    """Chạy 1 Project qua WorkflowGraph 4 node (ideation→voiceover→render→publish).

    Mỗi node skip nếu đã DONE trong checkpoint (resume). Object trung gian
    (Script/Voiceover/RenderedVideo) được giữ trong closure `state` — output_ref
    của node ghi vào project.json chỉ là path/identifier nhẹ để resume; object
    đầy đủ được tái tạo lại nếu cần load lại từ output_ref khi resume từ giữa.
    """
    state: dict[str, object] = {}

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
        script = script_for(current)
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
                seg_path = _segment_audio_path(slug, profile, i)
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

    async def ideation_fn(current: Project):
        script = load_script(_node_script_path(current))
        print(f"[1/4] Ideation  ✓  {script.title} ({len(script.segments)} đoạn)")
        script = gate(script)
        state["script"] = script
        return _node_script_path(current), {"title": script.title, "segments": len(script.segments)}

    async def voiceover_fn(current: Project):
        script = state.get("script")
        if script is None:
            script = load_script(_node_script_path(current))
            if not checkpoint.is_done(current, "ideation"):
                script = gate(script)
        voice = get_voice_provider()
        print("[2/4] Voiceover ▶  đang tạo audio...")
        voiceover = await voice.synthesise(script, Path("assets/audio"))
        print(f"[2/4] Voiceover ✓  {voiceover.audio_path}  ({voiceover.duration_sec:.1f}s)")
        state["voiceover"] = voiceover
        return str(voiceover.audio_path), _voiceover_output_data(voiceover)

    async def render_fn(current: Project):
        voiceover = voiceover_for(current)
        renderer = get_render_provider()
        print(f"[3/4] Render    ▶  đang dựng video ({settings.render_provider}/{settings.orientation})...")
        video = await renderer.render(voiceover, Path("assets/output"))
        print(f"[3/4] Render    ✓  ({settings.render_provider}/{settings.orientation}) {video.video_path}")
        state["video"] = video
        return str(video.video_path), _rendered_output_data(video)

    async def publish_fn(current: Project):
        video = rendered_for(current)
        print("[4/4] Publish   ▶  đang upload...")
        publish_results = await publish_to_platforms(video)
        result = _primary_publish_result(publish_results)
        print(f"[4/4] Publish   ✓  uploaded={result.uploaded}")

        if result.uploaded and settings.drive_backup:
            from .publish.drive import backup_to_drive
            try:
                backup_to_drive(result.video_path, move=True)
            except Exception as exc:  # noqa: BLE001
                print(f"  ⚠ Đưa lên Drive thất bại (giữ bản local): {exc}")

        state["result"] = result
        return result.url or str(result.video_path), _publish_results_output_data(publish_results)

    nodes = [
        NodeDef(node_id="ideation", stage="ideation", fn=ideation_fn, deps=[]),
        NodeDef(node_id="voiceover", stage="voiceover", fn=voiceover_fn, deps=["ideation"]),
        NodeDef(node_id="render", stage="render", fn=render_fn, deps=["voiceover"]),
        NodeDef(node_id="publish", stage="publish", fn=publish_fn, deps=["render"]),
    ]

    graph = WorkflowGraph(nodes, checkpoint)
    return await graph.execute(project)
