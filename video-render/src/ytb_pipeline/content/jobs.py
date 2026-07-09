"""Content pipeline job: script → voice → pexels → render (nối vào job render sẵn có).

Chạy nền trong 1 thread; mỗi bước ghi `stage`/`message` vào `_jobs` để UI poll
qua `/api/content/jobs/{id}`. Khi tới bước render, job này gọi callback
`start_render` (do `webui/content_routes.py` truyền vào, trỏ về đúng
`RenderRequest`/`run_render_job` có sẵn của `webui/jobs.py`) rồi trả
`render_job_id` — client chuyển sang poll `/api/jobs/{render_job_id}` như
render bình thường, không có luồng "content job" riêng thứ hai chạy song song.
"""

from __future__ import annotations

import threading
import uuid
from pathlib import Path
from typing import Any, Callable

from . import pexels_fetch, script_gen, voiceover
from .models import Script

_lock = threading.Lock()
_jobs: dict[str, dict[str, Any]] = {}

StartRenderFn = Callable[[Path, Path], dict[str, Any]]

DEFAULT_CANDIDATES_PER_SCENE = 3


def create_content_job() -> str:
    job_id = uuid.uuid4().hex
    with _lock:
        _jobs[job_id] = {
            "job_id": job_id,
            "stage": "pending",
            "message": "Đang chuẩn bị...",
            "render_job_id": None,
            "scenes_dir": None,
            "voice_track": None,
            "script": None,
            "error": None,
        }
    return job_id


def get_content_job(job_id: str) -> dict[str, Any] | None:
    with _lock:
        job = _jobs.get(job_id)
        return dict(job) if job else None


def _update(job_id: str, **fields: Any) -> None:
    with _lock:
        if job_id in _jobs:
            _jobs[job_id].update(fields)


def start_content_pipeline(
    *,
    topic: str,
    manual_script: Script | None,
    work_dir: Path,
    candidates_per_scene: int,
    landscape: bool,
    start_render: StartRenderFn,
) -> str:
    """Khởi chạy pipeline nền, trả về content_job_id ngay (không block).

    `work_dir` nên dựa trên chính job_id trả về để không lẫn giữa các lần
    submit — nhưng job_id chỉ biết SAU khi tạo, nên caller không tự đặt
    work_dir theo job_id được; hàm này tự tạo work_dir con theo job_id thật.
    """
    job_id = create_content_job()
    work_dir = work_dir / job_id
    thread = threading.Thread(
        target=_run_content_pipeline,
        args=(job_id, topic, manual_script, work_dir, candidates_per_scene, landscape, start_render),
        daemon=True,
    )
    thread.start()
    return job_id


def _run_content_pipeline(
    job_id: str,
    topic: str,
    manual_script: Script | None,
    work_dir: Path,
    candidates_per_scene: int,
    landscape: bool,
    start_render: StartRenderFn,
) -> None:
    try:
        if manual_script is not None:
            script = manual_script
        else:
            _update(job_id, stage="script", message="Claude đang sinh kịch bản...")
            script = script_gen.generate_script(topic)
        _update(
            job_id,
            script={
                "title": script.title,
                "description": script.description,
                "segments": [
                    {"narration": s.narration, "visual_keywords": list(s.visual_keywords)}
                    for s in script.segments
                ],
            },
        )

        _update(job_id, stage="voice", message="Đang tổng hợp giọng đọc edge-tts...")
        voice_result = voiceover.synthesize(script, work_dir / "voice")

        _update(job_id, stage="pexels", message="Đang tải B-roll từ Pexels...")
        scenes_dir = work_dir / "scenes"
        pexels_fetch.fetch_scenes(
            script,
            scenes_dir,
            candidates_per_scene=candidates_per_scene,
            landscape=landscape,
        )

        _update(
            job_id,
            stage="rendering",
            message="Đang chuyển sang render...",
            scenes_dir=str(scenes_dir),
            voice_track=str(voice_result.audio_path),
        )
        render_result = start_render(scenes_dir, voice_result.audio_path)
        _update(
            job_id,
            stage="done",
            message="Đã chuyển sang render — theo dõi tiếp ở render job.",
            render_job_id=render_result["job_id"],
        )
    except Exception as exc:  # noqa: BLE001 — job nền, phải ghi lỗi lại cho UI thay vì raise mất
        _update(job_id, stage="failed", message=f"Lỗi: {exc}", error=str(exc))
