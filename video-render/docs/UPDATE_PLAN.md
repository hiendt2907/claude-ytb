# Update Plan

Tai lieu nay la ban do de update nhanh ve sau. Mission hien tai: render-only tool cho KOL/KOC/affiliate, khong ideation, khong TTS, khong publish.

## Version Hien Tai

- Package: `video-render`
- Version: `0.3.0`
- Metadata: `pyproject.toml` va `src/ytb_pipeline/__init__.py`
- Changelog: `CHANGELOG.md`

## Ban Do Module

- `src/ytb_pipeline/assembler/models.py`: frozen dataclasses cho Clip, ClipSegment, SceneFolder, ClipGroup, Assignment.
- `src/ytb_pipeline/assembler/scanning.py`: quet scene folders, sort folder/clip theo numeric natural sort.
- `src/ytb_pipeline/assembler/assignment.py`: sinh assignment random, giu thu tu clip trong group, dam bao coverage 100%.
- `src/ytb_pipeline/assembler/manual_plan.py`: parse/preview plan tu chon clip; nhan format ngan `1.1, 2.1, 3.2` va format cu `video 1: ...`.
- `src/ytb_pipeline/assembler/duration.py`: duration mode `clip_length` va `voice_silence`.
- `src/ytb_pipeline/assembler/profiles.py`: catalog animation/style/profile va tuning render.
- `src/ytb_pipeline/assembler/smart_trim.py`: heuristic chon ClipSegment, cache theo path/size/mtime.
- `src/ytb_pipeline/assembler/render_effects.py`: FPS, scale/crop/pad, motion, xfade helper.
- `src/ytb_pipeline/assembler/render.py`: ffmpeg pipeline chinh: concat clip, trim/loop, xfade scene, mux voice/watermark/subtitle.
- `src/ytb_pipeline/webui/app.py`: FastAPI routes.
- `src/ytb_pipeline/webui/jobs.py`: job runner, preview/full render, progress, quality summary.
- `src/ytb_pipeline/webui/quality.py`: ffprobe/freezedetect/blackdetect thanh thong diep user-facing.
- `src/ytb_pipeline/webui/templates/index.html`: UI single-page guided workflow.
- `src/ytb_pipeline/desktop.py`: packaged desktop entrypoint mo browser va chay uvicorn.
- `src/ytb_pipeline/ffmpeg_bin.py`: resolve ffmpeg/ffprobe tu env, PyInstaller bundle, hoac PATH.
- `scripts/`: install/run/build cho macOS/Windows, bundle static ffmpeg.

## Quy Trinh Update Nhanh

1. Xac dinh loai thay doi:
   - Render/muot/chuyen canh: bat dau o `profiles.py`, `render_effects.py`, `render.py`, test `tests/test_render_commands.py`.
   - Chon clip/coverage: `assignment.py`, `manual_plan.py`, test `tests/test_assembler.py`, `tests/test_manual_plan.py`.
   - Smart Trim/pacing: `smart_trim.py`, `jobs.py`, test `tests/test_smart_trim.py`, `tests/test_webui_jobs.py`.
   - UI/API: `webui/app.py`, `webui/templates/index.html`, test `tests/test_webui_app.py`.
   - Quality message: `webui/quality.py`, test `tests/test_webui_quality.py`.
   - Desktop/build: `desktop.py`, `ffmpeg_bin.py`, `scripts/`, test `tests/test_desktop.py`.
2. Sua code theo frozen dataclass pattern. Khi can enrich object, dung `dataclasses.replace()`.
3. Chay unit test lien quan truoc, sau do chay full `.venv/bin/pytest -q`.
4. Neu sua backend import boi web UI, restart server thu cong vi app khong auto reload.
5. Neu sua render thuc, verify bang ffmpeg tren `demo_data/`: fps 30, pix_fmt yuv420p, khong freezedetect warning.
6. Cap nhat `CHANGELOG.md`, `pyproject.toml`, `src/ytb_pipeline/__init__.py` khi release version moi.
7. Cap nhat memory project neu co quyet dinh san pham, bug root cause, hay workflow van hanh moi.

## Roadmap Gan

- v0.3 da release trong `CHANGELOG.md`: uu tien trai nghiem nguoi dung, flexible manual clip control, Smart Trim multi-segment, render plan metadata, retry dung output loi, preview dau/giua/cuoi, quick adjustment, va quality gate audio/video mismatch.
- Roadmap tiep theo nen bat dau tu disk cache Smart Trim, cleanup temp, parallel render co gioi han CPU, va packaging signed release.
- Packaging release: ky/notarize macOS va code-sign Windows neu phat hanh ngoai test noi bo.

## Dieu Khong Lam Neu Khong Co Yeu Cau Moi

- Khong cai ffmpeg-full de lam subtitle.
- Khong mo lai ideation/TTS/publish.
- Khong dua UI sang timeline manual kieu CapCut.
