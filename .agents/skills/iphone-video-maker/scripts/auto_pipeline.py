#!/usr/bin/env python3
"""Tự động hoá toàn bộ phần code-làm-được: quét import/, dò điểm cắt ứng viên theo
scene-change trong từng clip, trích 1 frame đại diện/đoạn, và viết sẵn DRAFT
edl.json — MỖI CLIP GỐC RA NHIỀU ENTRY (1 entry/đoạn ứng viên), không phải 1
entry/clip nữa.

Việc DUY NHẤT bàn giao cho Claude là phần code không "nhìn" được: với mỗi đoạn ứng
viên, xem 1 frame đại diện rồi quyết GIỮ (gán scene, tinh chỉnh start/end/speed)
hay CẮT BỎ (xoá entry đó khỏi draft) — xem SKILL.md Bước 3. Claude Write (không
Edit) một bản EDL hoàn chỉnh ra file draft riêng, rồi gọi finalize_edl.py — script
đó tự validate, ghi edl.json chính thức, và tự render luôn, không cần Claude quay
lại. Không có voice-over/text/badge/emoji — chỉ cắt/ghép/render video thuần.

Dùng:
    python3 auto_pipeline.py              # build draft edl.json mới từ toàn bộ import/
"""
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from extract_frames import (  # noqa: E402
    IMPORT_DIR,
    WORKDIR,
    discover_clips,
    extract_beat_frames,
    log,
)

EDL_PATH = WORKDIR / "edl.json"


def seconds_to_timecode(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}"


def build_draft_beats(clip: Path) -> list[dict]:
    beats = extract_beat_frames(clip)
    drafts = []
    for start, end, frame, is_static in beats:
        draft = {
            "file": clip.name,
            "start": seconds_to_timecode(start),
            "end": seconds_to_timecode(end),
            "speed": 1.0,
            "scene": None,
            "_frame": str(frame),
        }
        if is_static:
            draft["_hint"] = "ít chuyển động — có thể là đoạn chờ/chết, xem kỹ trước khi giữ"
        drafts.append(draft)
    return drafts


def main() -> None:
    clips = discover_clips()
    if not clips:
        print(f"Không có clip nào trong {IMPORT_DIR}")
        sys.exit(1)

    edl_clips = []
    for clip in clips:
        log(f"Dò điểm cắt: {clip.name}")
        beats = build_draft_beats(clip)
        log(f"  -> {len(beats)} đoạn ứng viên")
        edl_clips.extend(beats)

    edl = {
        "output_name": f"brand_ad_{datetime.now():%Y%m%d_%H%M%S}",
        "transition": "fade",
        "transition_duration": 0.6,
        "music": None,
        "music_volume_db": -18,
        "clips": edl_clips,
    }
    EDL_PATH.write_text(json.dumps(edl, ensure_ascii=False, indent=2))

    print(f"\nĐã viết draft: {EDL_PATH} ({len(edl_clips)} đoạn ứng viên)")
    print(f"Clip ngắn để xem trước (Finder/QuickTime, Space để Quick Look): {WORKDIR / 'stage' / 'cuts'}")
    print("Claude: Read frame đại diện ('_frame') của từng đoạn (chú ý '_hint' nếu có —")
    print("gợi ý ít chuyển động, có thể là đoạn chờ/chết), rồi với mỗi đoạn:")
    print("  - GIỮ: gán 'scene', tinh chỉnh start/end/speed nếu cần, xoá '_frame'/'_hint'")
    print("  - CẮT BỎ (đoạn chết/dư): xoá hẳn entry đó khỏi danh sách 'clips'")
    print("Write (không Edit) bản EDL đã quyết xong ra 1 file draft mới")
    print("(vd stage/edl_draft.json), rồi chạy: python3 finalize_edl.py <draft.json>")
    print("Script đó tự validate, ghi edl.json chính thức, và tự render luôn.")


if __name__ == "__main__":
    main()
