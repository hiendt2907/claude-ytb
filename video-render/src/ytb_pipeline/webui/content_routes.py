"""Endpoint content pipeline: script (Claude/tự nhập) → voice (edge-tts) →
pexels (tự động đổ vào scene folders) → render (dùng lại đúng
`RenderRequest`/`run_render_job` có sẵn, KHÔNG viết lại logic render).

Sau khi pipeline chuyển sang bước render, client chuyển qua poll
`/api/jobs/{render_job_id}` như render bình thường — `/api/content/jobs/{id}`
chỉ theo dõi 3 bước đầu (script/voice/pexels).
"""

from __future__ import annotations

import threading
import uuid
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException

from ytb_pipeline.content.jobs import (
    DEFAULT_CANDIDATES_PER_SCENE,
    get_content_job,
    start_content_pipeline,
)
from ytb_pipeline.content.ledger import load_ledger
from ytb_pipeline.content.models import Script, ScriptSegment
from ytb_pipeline.content.publish import publish_video
from ytb_pipeline.content.script_gen import generate_script, generate_script_auto, script_to_dict
from ytb_pipeline.webui.jobs import RenderRequest, run_render_job
from ytb_pipeline.webui.store import store

router = APIRouter(prefix="/api/content", tags=["content"])


_CONTENT_WORK_ROOT = Path("output") / ".content"


@router.post("/generate-script")
def generate_script_endpoint(topic: str = Form(...), num_segments: int = Form(6)) -> dict:
    """Sinh thử kịch bản để user xem/sửa trước khi submit pipeline (không bắt buộc)."""
    try:
        script = generate_script(topic, num_segments=num_segments)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"Sinh kịch bản thất bại: {exc}") from exc
    return script_to_dict(script)


@router.post("/discover-topic")
def discover_topic_endpoint(num_segments: int = Form(6)) -> dict:
    """Tự tìm chủ đề trending (YouTube) + để Claude chọn 1 chưa có trong ledger
    rồi viết luôn kịch bản — trả cùng shape với /generate-script để user xem/sửa
    trước khi submit."""
    ledger = load_ledger()
    try:
        script = generate_script_auto(ledger, num_segments=num_segments)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"Tự tìm chủ đề thất bại: {exc}") from exc
    return script_to_dict(script)


def _script_from_json(data: dict) -> Script:
    try:
        segments = tuple(
            ScriptSegment(
                narration=seg["narration"],
                visual_keywords=tuple(seg.get("visual_keywords", [])),
            )
            for seg in data["segments"]
        )
        if not segments:
            raise ValueError("segments rỗng")
        return Script(title=data["title"], description=data.get("description", ""), segments=segments)
    except (KeyError, TypeError) as exc:
        raise HTTPException(400, f"script JSON không hợp lệ: {exc}") from exc


@router.post("/jobs")
def start_pipeline(
    topic: str = Form(""),
    script_json: str = Form(""),
    product_name: str = Form(...),
    n_outputs: int = Form(1),
    output_dir: str = Form("output"),
    aspect_ratio: str = Form("9:16"),
    fit_mode: str = Form("pad"),
    mode: str = Form("random"),
    edit_profile_name: str = Form("affiliate_default"),
    candidates_per_scene: int = Form(DEFAULT_CANDIDATES_PER_SCENE),
) -> dict:
    """Submit: nếu `script_json` có nội dung thì dùng thẳng (user tự nhập/sửa),
    ngược lại bắt Claude tự sinh từ `topic`."""
    if not topic.strip() and not script_json.strip():
        raise HTTPException(400, "Cần topic (để Claude tự sinh) hoặc script_json (đã nhập tay)")
    if not product_name.strip():
        raise HTTPException(400, "product_name không được rỗng")

    manual_script: Script | None = None
    if script_json.strip():
        import json

        try:
            parsed = json.loads(script_json)
        except json.JSONDecodeError as exc:
            raise HTTPException(400, f"script_json không phải JSON hợp lệ: {exc}") from exc
        manual_script = _script_from_json(parsed)

    landscape = aspect_ratio == "16:9"
    output_root = Path(output_dir).expanduser()

    def _start_render(scenes_dir: Path, voice_track: Path) -> dict:
        render_job_id = uuid.uuid4().hex
        request = RenderRequest(
            scenes_dir=scenes_dir,
            voice_track=voice_track,
            product_name=product_name.strip(),
            n_outputs=n_outputs,
            output_dir=output_root,
            tmp_dir=output_root / ".tmp" / render_job_id,
            duration_mode="voice_silence",
            aspect_ratio=aspect_ratio,
            fit_mode=fit_mode,
            mode=mode,
            edit_profile_name=edit_profile_name,
        )
        store.create(render_job_id, total_outputs=n_outputs, job_kind="full")
        threading.Thread(
            target=run_render_job, args=(render_job_id, store, request), daemon=True
        ).start()
        return {"job_id": render_job_id}

    content_job_id = start_content_pipeline(
        topic=topic.strip(),
        manual_script=manual_script,
        work_dir=_CONTENT_WORK_ROOT,
        candidates_per_scene=candidates_per_scene,
        landscape=landscape,
        start_render=_start_render,
    )
    return {"content_job_id": content_job_id}


@router.get("/jobs/{content_job_id}")
def content_job_status(content_job_id: str) -> dict:
    job = get_content_job(content_job_id)
    if job is None:
        raise HTTPException(404, "content job không tồn tại")
    return job


@router.post("/publish/{render_job_id}/{index}")
def publish_output(
    render_job_id: str,
    index: int,
    title: str = Form(...),
    description: str = Form(""),
    tags: str = Form(""),
    publish_at: str = Form(""),
) -> dict:
    """Upload thẳng output `index` của render job `render_job_id` lên YouTube,
    thay vì chỉ tải file về máy (`/api/download/{job_id}/{index}`).

    `publish_at`: RFC3339 (vd "2026-07-10T09:00:00Z") để lên lịch tự công
    khai; để trống thì dùng `youtube_privacy` mặc định (private) ngay lập tức.
    """
    job = store.get(render_job_id)
    if job is None or index < 0 or index >= len(job.output_paths):
        raise HTTPException(404, "output không tồn tại")
    if not title.strip():
        raise HTTPException(400, "title không được rỗng")

    video_path = Path(job.output_paths[index])
    tag_list = tuple(t.strip() for t in tags.split(",") if t.strip())

    try:
        result = publish_video(
            video_path,
            title.strip(),
            description,
            tag_list,
            publish_at=publish_at.strip() or None,
        )
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 — lỗi OAuth/API cần hiện rõ cho user, không nuốt
        raise HTTPException(502, f"Upload YouTube thất bại: {exc}") from exc

    return {"youtube_id": result.youtube_id, "url": result.url}
