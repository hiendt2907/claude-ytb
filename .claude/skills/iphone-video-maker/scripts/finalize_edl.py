#!/usr/bin/env python3
"""Nhận EDL hoàn chỉnh (Claude viết 1 lần sau khi xem frame), validate, ghi vào
edl.json chính thức, rồi TỰ chạy edit_render.py luôn — không cần Claude quay lại
sửa file hay gọi thêm lệnh nào.

Đây là ranh giới rõ giữa 2 việc:
- Python (auto_pipeline.py): tự dò điểm cắt ứng viên theo scene-change, trích 1
  frame đại diện/đoạn (_frame).
- Claude: xem frame đại diện từng đoạn → quyết giữ (gán scene/tinh chỉnh
  start-end-speed) hay cắt bỏ hẳn đoạn đó → viết JSON đầy đủ, xoá hết '_frame' →
  Write ra 1 file draft bất kỳ.
- Python (script này): validate + ghi edl.json + render — không cần Claude nữa.

Không có voice-over/text/badge/emoji — skill này chỉ cắt/ghép/render video.

Dùng:
    python3 finalize_edl.py <đường-dẫn-draft.json>
"""
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from extract_frames import IMPORT_DIR, WORKDIR, discover_clips  # noqa: E402

EDL_PATH = WORKDIR / "edl.json"
RENDER_SCRIPT = Path(__file__).parent / "edit_render.py"

_VALID_SCENES = {"hook", "unbox", "demo", "testimonial", "cta", None}


def log(msg: str) -> None:
    print(f"[finalize_edl] {msg}")


def validate(edl: dict) -> list[str]:
    errors = []
    if "clips" not in edl or not isinstance(edl["clips"], list) or not edl["clips"]:
        return ["thiếu 'clips' hoặc rỗng"]

    known_files = {c.name for c in discover_clips()}
    for i, clip in enumerate(edl["clips"]):
        prefix = f"clip[{i}]"
        leftover = {"_frame", "_frames", "_hint"} & clip.keys()
        if leftover:
            errors.append(f"{prefix}: còn field {sorted(leftover)} — phải xoá trước khi finalize")
        file_name = clip.get("file")
        if not file_name:
            errors.append(f"{prefix}: thiếu 'file'")
        elif Path(file_name).name not in known_files and not Path(file_name).is_absolute():
            errors.append(f"{prefix}: file '{file_name}' không có trong {IMPORT_DIR}")
        if clip.get("scene") not in _VALID_SCENES:
            errors.append(f"{prefix}: scene '{clip.get('scene')}' không hợp lệ "
                           f"(phải là một trong {sorted(s for s in _VALID_SCENES if s)} hoặc null)")
    return errors


def main() -> None:
    if len(sys.argv) != 2:
        print("Dùng: python3 finalize_edl.py <draft.json>", file=sys.stderr)
        sys.exit(1)

    draft_path = Path(sys.argv[1])
    edl = json.loads(draft_path.read_text())

    errors = validate(edl)
    if errors:
        print("Draft EDL không hợp lệ:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        sys.exit(1)

    EDL_PATH.write_text(json.dumps(edl, ensure_ascii=False, indent=2))
    log(f"Đã ghi {EDL_PATH}")
    log("Render...")
    subprocess.run([sys.executable, str(RENDER_SCRIPT), str(EDL_PATH)], check=True)


if __name__ == "__main__":
    main()
