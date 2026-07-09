"""FastAPI app: UI localhost để chạy assembler bằng chuột, không cần CLI."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import uuid
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.templating import Jinja2Templates

from ytb_pipeline.assembler.scanning import scan_scene_folders
from ytb_pipeline.assembler.manual_plan import preview_manual_plan
from ytb_pipeline.assembler.profiles import RenderTuning, list_profiles, resolve_profile
from ytb_pipeline.webui import content_routes
from ytb_pipeline.webui.browse import list_directory, make_directory
from ytb_pipeline.webui.estimate import estimate_all
from ytb_pipeline.webui.jobs import RenderRequest, run_cut_job, run_render_job, run_retry_job
from ytb_pipeline.webui.recommend import recommend_profile
from ytb_pipeline.webui.store import store
from ytb_pipeline.webui.templates_store import list_templates, load_template, save_template

app = FastAPI(title="video-render assembler")
app.include_router(content_routes.router)
_TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

_scan_lock = threading.Lock()
_scan_jobs: dict[str, dict[str, Any]] = {}


def _clip_ref(sub_index: tuple[int, ...]) -> str:
    return ".".join(str(part) for part in sub_index)


# (field trong RenderTuning) -> (min, max) hợp lệ để chặn giá trị làm ffmpeg lỗi
# hoặc ra video giật/nhoè quá mức.
_TUNING_BOUNDS: dict[str, tuple[float, float]] = {
    "scene_transition_duration": (0.0, 2.0),
    "clip_transition_duration": (0.0, 2.0),
    "motion_scale": (1.0, 1.3),
    "pan_strength_x": (0.0, 1.0),
    "pan_strength_y": (0.0, 1.0),
    "pan_speed_x": (0.0, 2.0),
    "pan_speed_y": (0.0, 2.0),
    "end_fade_duration": (0.0, 2.0),
}


def _parse_tuning_override(base_tuning: RenderTuning, raw_json: str) -> RenderTuning | None:
    """Ghép override do người dùng chỉnh (JSON field->value) lên tuning gốc của profile.

    Trả None nếu người dùng không tuỳ chỉnh gì (field rỗng), để jobs.py không
    tạo bản sao tuning thừa khi không cần.
    """
    if not raw_json.strip():
        return None
    try:
        raw_overrides = json.loads(raw_json)
    except ValueError as exc:
        raise HTTPException(400, f"tuning_overrides không phải JSON hợp lệ: {raw_json!r}") from exc
    if not isinstance(raw_overrides, dict):
        raise HTTPException(400, "tuning_overrides phải là object JSON dạng field->value")

    overrides: dict[str, float] = {}
    for field_name, raw_value in raw_overrides.items():
        if field_name not in _TUNING_BOUNDS:
            raise HTTPException(400, f"tuning_overrides có field không hợp lệ: {field_name!r}")
        try:
            value = float(raw_value)
        except (TypeError, ValueError) as exc:
            raise HTTPException(400, f"{field_name} phải là số: {raw_value!r}") from exc
        low, high = _TUNING_BOUNDS[field_name]
        if not (low <= value <= high):
            raise HTTPException(400, f"{field_name} phải trong khoảng [{low}, {high}]")
        overrides[field_name] = value
    return replace(base_tuning, **overrides) if overrides else None


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "index.html")


@app.get("/api/browse")
def browse(path: str = "", only_dirs: bool = False) -> dict:
    target = Path(path).expanduser() if path else Path.home()
    try:
        listing = list_directory(target, only_dirs=only_dirs)
    except PermissionError as exc:
        raise HTTPException(400, f"Không có quyền đọc thư mục: {target}") from exc
    except (NotADirectoryError, FileNotFoundError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return asdict(listing)


@app.post("/api/browse/mkdir")
def browse_mkdir(parent: str = Form(...), name: str = Form(...)) -> dict:
    parent_path = Path(parent).expanduser()
    try:
        new_dir = make_directory(parent_path, name)
    except (ValueError, NotADirectoryError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"path": str(new_dir)}


@app.get("/api/templates")
def get_templates() -> dict:
    return {"names": list_templates()}


@app.get("/api/edit-profiles")
def get_edit_profiles() -> dict:
    return {
        "profiles": [
            {
                "name": profile.name,
                "label": profile.label,
                "description": profile.description,
                "style_name": profile.style_name,
                "animation_names": profile.animation_names,
                "tuning": asdict(profile.tuning),
            }
            for profile in list_profiles()
        ]
    }


@app.get("/api/templates/{name}")
def get_template(name: str) -> dict:
    try:
        return load_template(name)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(404, str(exc)) from exc


@app.post("/api/templates/{name}")
def post_template(
    name: str,
    aspect_ratio: str = Form("16:9"),
    fit_mode: str = Form("pad"),
    duration_mode: str = Form("clip_length"),
    mode: str = Form("random"),
    edit_profile_name: str = Form("affiliate_default"),
) -> dict:
    try:
        save_template(
            name,
            {
                "aspect_ratio": aspect_ratio,
                "fit_mode": fit_mode,
                "duration_mode": duration_mode,
                "mode": mode,
                "edit_profile_name": edit_profile_name,
            },
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True}


@app.post("/api/scan")
def scan(
    scenes_dir: str = Form(...),
    aspect_ratio: str = Form("16:9"),
    mode: str = Form("random"),
) -> dict:
    path = Path(scenes_dir).expanduser()
    if not path.is_dir():
        raise HTTPException(400, f"Thư mục không tồn tại: {path}")
    return _scan_payload(path, aspect_ratio=aspect_ratio, mode=mode)


def _scan_payload(path: Path, *, aspect_ratio: str, mode: str, scan_job_id: str | None = None) -> dict:
    scenes = scan_scene_folders(path)

    def progress(done: int, total: int, clip_path: Path) -> None:
        if scan_job_id is None:
            return
        with _scan_lock:
            current = _scan_jobs.get(scan_job_id)
            if current is None:
                return
            current.update(
                {
                    "status": "running",
                    "completed_clips": done,
                    "total_clips": total,
                    "current_clip": clip_path.name,
                    "message": f"Đang phân tích chuyển động {done}/{total}: {clip_path.name}",
                }
            )

    suggestion = recommend_profile(
        scenes,
        aspect_ratio=aspect_ratio,
        mode=mode,
        progress_callback=progress,
    )
    return {
        "scenes": [
            {
                "scene_index": s.scene_index,
                "folder": s.path.name,
                "clip_count": len(s.clips),
                "clips": [
                    {"ref": _clip_ref(clip.sub_index), "filename": clip.path.name}
                    for clip in s.clips
                ],
            }
            for s in scenes
        ],
        "suggestion": asdict(suggestion),
    }


def _run_scan_job(scan_job_id: str, path: Path, aspect_ratio: str, mode: str) -> None:
    with _scan_lock:
        _scan_jobs[scan_job_id].update(
            {
                "status": "running",
                "message": "Đang đọc thư mục cảnh...",
            }
        )
    try:
        result = _scan_payload(path, aspect_ratio=aspect_ratio, mode=mode, scan_job_id=scan_job_id)
    except Exception as exc:  # noqa: BLE001
        with _scan_lock:
            _scan_jobs[scan_job_id].update(
                {
                    "status": "failed",
                    "message": f"Lỗi: {exc}",
                    "error": str(exc),
                }
            )
        return
    with _scan_lock:
        _scan_jobs[scan_job_id].update(
            {
                "status": "done",
                "completed_clips": _scan_jobs[scan_job_id].get("total_clips", 0),
                "message": "Đã phân tích xong video nguồn.",
                "result": result,
            }
        )


@app.post("/api/scan/jobs")
def start_scan_job(
    scenes_dir: str = Form(...),
    aspect_ratio: str = Form("16:9"),
    mode: str = Form("random"),
) -> dict:
    path = Path(scenes_dir).expanduser()
    if not path.is_dir():
        raise HTTPException(400, f"Thư mục không tồn tại: {path}")
    scan_job_id = uuid.uuid4().hex
    with _scan_lock:
        _scan_jobs[scan_job_id] = {
            "job_id": scan_job_id,
            "status": "pending",
            "completed_clips": 0,
            "total_clips": 0,
            "current_clip": "",
            "message": "Đang chuẩn bị phân tích video nguồn...",
            "result": None,
            "error": None,
        }
    threading.Thread(
        target=_run_scan_job,
        args=(scan_job_id, path, aspect_ratio, mode),
        daemon=True,
    ).start()
    return {"job_id": scan_job_id}


@app.get("/api/scan/jobs/{scan_job_id}")
def scan_job_status(scan_job_id: str) -> dict:
    with _scan_lock:
        job = _scan_jobs.get(scan_job_id)
        if job is None:
            raise HTTPException(404, "scan job không tồn tại")
        return dict(job)


@app.post("/api/manual-plan/preview")
def manual_plan_preview(
    scenes_dir: str = Form(...),
    manual_plan_text: str = Form(...),
) -> dict:
    path = Path(scenes_dir).expanduser()
    if not path.is_dir():
        raise HTTPException(400, f"Thư mục không tồn tại: {path}")
    try:
        scenes = scan_scene_folders(path)
        items = preview_manual_plan(manual_plan_text, scenes)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"items": items}


@app.post("/api/estimate")
def estimate(
    scenes_dir: str = Form(...),
    voice_tracks: list[str] = Form(...),
    product_name: str = Form(...),
    n_outputs: int = Form(1),
    duration_mode: str = Form("clip_length"),
    seed: str = Form(""),
    mode: str = Form("random"),
    manual_plan_text: str = Form(""),
) -> dict:
    scenes_path = Path(scenes_dir).expanduser()
    if not scenes_path.is_dir():
        raise HTTPException(400, f"scenes_dir không tồn tại: {scenes_path}")
    if mode == "random" and n_outputs < 1:
        raise HTTPException(400, "n_outputs phải >= 1")

    voice_paths = [Path(v).expanduser() for v in voice_tracks]
    for voice_path in voice_paths:
        if not voice_path.is_file():
            raise HTTPException(400, f"voice_track không tồn tại: {voice_path}")

    scenes = scan_scene_folders(scenes_path)
    try:
        result = estimate_all(
            scenes,
            voice_paths,
            product_name.strip(),
            n_outputs,
            duration_mode,
            int(seed) if seed.strip() else None,
            mode=mode,
            manual_plan_text=manual_plan_text,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    return {
        "items": [
            {
                "product_name": item.product_name,
                "voice_track": item.voice_track,
                "n_outputs": item.n_outputs,
                "estimated_seconds": item.estimated_seconds,
                "duplicate_output_groups": item.duplicate_output_groups,
            }
            for item in result.items
        ],
        "grand_total_estimated_seconds": result.grand_total_estimated_seconds,
    }


@app.post("/api/render")
def start_render(
    scenes_dir: str = Form(...),
    voice_track: str = Form(...),
    product_name: str = Form(...),
    n_outputs: int = Form(1),
    output_dir: str = Form("output"),
    duration_mode: str = Form("clip_length"),
    seed: str = Form(""),
    aspect_ratio: str = Form("16:9"),
    fit_mode: str = Form("pad"),
    mode: str = Form("random"),
    manual_plan_text: str = Form(""),
    watermark_path: str = Form(""),
    watermark_position: str = Form("bottom-right"),
    watermark_scale: float = Form(0.15),
    subtitle_path: str = Form(""),
    edit_profile_name: str = Form("affiliate_default"),
    tuning_overrides: str = Form(""),
    emoji_preset: str = Form("none"),
    trim_mode: str = Form("manual_review"),
) -> dict:
    return _start_render_job(
        scenes_dir=scenes_dir,
        voice_track=voice_track,
        product_name=product_name,
        n_outputs=n_outputs,
        output_dir=output_dir,
        duration_mode=duration_mode,
        seed=seed,
        aspect_ratio=aspect_ratio,
        fit_mode=fit_mode,
        mode=mode,
        manual_plan_text=manual_plan_text,
        watermark_path=watermark_path,
        watermark_position=watermark_position,
        watermark_scale=watermark_scale,
        subtitle_path=subtitle_path,
        edit_profile_name=edit_profile_name,
        tuning_overrides=tuning_overrides,
        emoji_preset=emoji_preset,
        trim_mode=trim_mode,
        job_kind="full",
    )


@app.post("/api/preview")
def start_preview(
    scenes_dir: str = Form(...),
    voice_track: str = Form(...),
    product_name: str = Form(...),
    n_outputs: int = Form(1),
    output_dir: str = Form("output"),
    duration_mode: str = Form("clip_length"),
    seed: str = Form(""),
    aspect_ratio: str = Form("16:9"),
    fit_mode: str = Form("pad"),
    mode: str = Form("random"),
    manual_plan_text: str = Form(""),
    watermark_path: str = Form(""),
    watermark_position: str = Form("bottom-right"),
    watermark_scale: float = Form(0.15),
    subtitle_path: str = Form(""),
    edit_profile_name: str = Form("affiliate_default"),
    tuning_overrides: str = Form(""),
    emoji_preset: str = Form("none"),
    trim_mode: str = Form("manual_review"),
) -> dict:
    return _start_render_job(
        scenes_dir=scenes_dir,
        voice_track=voice_track,
        product_name=product_name,
        n_outputs=n_outputs,
        output_dir=output_dir,
        duration_mode=duration_mode,
        seed=seed,
        aspect_ratio=aspect_ratio,
        fit_mode=fit_mode,
        mode=mode,
        manual_plan_text=manual_plan_text,
        watermark_path=watermark_path,
        watermark_position=watermark_position,
        watermark_scale=watermark_scale,
        subtitle_path=subtitle_path,
        edit_profile_name=edit_profile_name,
        tuning_overrides=tuning_overrides,
        emoji_preset=emoji_preset,
        trim_mode=trim_mode,
        job_kind="preview",
    )


def _start_render_job(
    scenes_dir: str,
    voice_track: str,
    product_name: str,
    n_outputs: int,
    output_dir: str,
    duration_mode: str,
    seed: str,
    aspect_ratio: str,
    fit_mode: str,
    mode: str,
    manual_plan_text: str,
    watermark_path: str,
    watermark_position: str,
    watermark_scale: float,
    subtitle_path: str,
    edit_profile_name: str,
    tuning_overrides: str,
    emoji_preset: str,
    trim_mode: str,
    job_kind: str,
) -> dict:
    scenes_path = Path(scenes_dir).expanduser()
    voice_path = Path(voice_track).expanduser()
    if not scenes_path.is_dir():
        raise HTTPException(400, f"scenes_dir không tồn tại: {scenes_path}")
    if not voice_path.is_file():
        raise HTTPException(400, f"voice_track không tồn tại: {voice_path}")
    if mode == "random" and n_outputs < 1:
        raise HTTPException(400, "n_outputs phải >= 1")
    if mode == "manual" and not manual_plan_text.strip():
        raise HTTPException(400, "Chế độ nhập tay cần manual_plan_text")
    if trim_mode not in {"manual_review", "auto_smart", "none"}:
        raise HTTPException(400, "trim_mode không hợp lệ")
    if not product_name.strip():
        raise HTTPException(400, "product_name không được rỗng")

    try:
        base_profile = resolve_profile(edit_profile_name)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    tuning_override = _parse_tuning_override(base_profile.tuning, tuning_overrides)

    watermark = Path(watermark_path).expanduser() if watermark_path.strip() else None
    if watermark is not None and not watermark.is_file():
        raise HTTPException(400, f"watermark không tồn tại: {watermark}")

    subtitle = Path(subtitle_path).expanduser() if subtitle_path.strip() else None
    if subtitle is not None and not subtitle.is_file():
        raise HTTPException(400, f"subtitle không tồn tại: {subtitle}")

    job_id = uuid.uuid4().hex
    output_root = Path(output_dir).expanduser()
    request = RenderRequest(
        scenes_dir=scenes_path,
        voice_track=voice_path,
        product_name=product_name.strip(),
        n_outputs=n_outputs,
        output_dir=output_root,
        tmp_dir=output_root / ".tmp" / job_id,
        duration_mode=duration_mode,
        seed=int(seed) if seed.strip() else None,
        aspect_ratio=aspect_ratio,
        fit_mode=fit_mode,
        mode=mode,
        manual_plan_text=manual_plan_text,
        watermark_path=watermark,
        watermark_position=watermark_position,
        watermark_scale=watermark_scale,
        subtitle_path=subtitle,
        edit_profile_name=edit_profile_name,
        tuning_override=tuning_override,
        emoji_preset=emoji_preset,
        trim_mode=trim_mode,
        job_kind=job_kind,
    )
    store.create(
        job_id,
        total_outputs=1 if job_kind == "preview" else n_outputs,
        job_kind=job_kind,
    )
    threading.Thread(target=run_render_job, args=(job_id, store, request), daemon=True).start()
    return {"job_id": job_id}


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str) -> dict:
    job = store.get(job_id)
    if job is None:
        raise HTTPException(404, "job không tồn tại")
    return asdict(job)


@app.get("/api/download/{job_id}/{index}")
def download(job_id: str, index: int) -> FileResponse:
    job = store.get(job_id)
    if job is None or index < 0 or index >= len(job.output_paths):
        raise HTTPException(404, "file không tồn tại")
    return FileResponse(job.output_paths[index])


@app.post("/api/jobs/{job_id}/open-output")
def open_output_folder(job_id: str) -> dict:
    job = store.get(job_id)
    if job is None or not job.output_paths:
        raise HTTPException(404, "thư mục output không tồn tại")
    folder = Path(job.output_paths[0]).parent
    _open_folder(folder)
    return {"ok": True, "path": str(folder)}


@app.post("/api/jobs/{job_id}/retry/{index}")
def retry_output(job_id: str, index: int) -> dict:
    job = store.get(job_id)
    if job is None or index < 0 or index >= len(job.render_plans):
        raise HTTPException(404, "render plan không tồn tại")
    retry_job_id = uuid.uuid4().hex
    store.create(retry_job_id, total_outputs=1, job_kind="full")
    threading.Thread(
        target=run_retry_job,
        args=(retry_job_id, store, job.render_plans[index]),
        daemon=True,
    ).start()
    return {"job_id": retry_job_id}


@app.post("/api/jobs/{job_id}/cut/{index}")
def cut_output(
    job_id: str,
    index: int,
    cut_ranges_text: str = Form(""),
) -> dict:
    job = store.get(job_id)
    if job is None or index < 0 or index >= len(job.render_plans):
        raise HTTPException(404, "render plan không tồn tại")
    cut_job_id = uuid.uuid4().hex
    store.create(cut_job_id, total_outputs=1, job_kind="full")
    threading.Thread(
        target=run_cut_job,
        args=(cut_job_id, store, job.render_plans[index], cut_ranges_text),
        daemon=True,
    ).start()
    return {"job_id": cut_job_id}


def _open_folder(folder: Path) -> None:
    if sys.platform == "win32":
        import os

        os.startfile(folder)  # type: ignore[attr-defined]
        return
    if sys.platform == "darwin":
        subprocess.run(["open", str(folder)], check=False)
        return
    subprocess.run(["xdg-open", str(folder)], check=False)


def main() -> None:
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
