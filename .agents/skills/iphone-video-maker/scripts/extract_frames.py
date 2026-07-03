#!/usr/bin/env python3
"""Trích frame mẫu từ clip trong import/ để Claude xem và phân loại cảnh.

Không phân tích nội dung gì cả — chỉ liệt kê clip + xuất frame .jpg ra đĩa. Việc
"AI" thật (nhận diện sản phẩm, gán nhãn cảnh/hành vi, quyết giữ-cắt-tốc độ) do
Claude làm trong chat bằng cách Read các ảnh này, không gọi API ngoài. Xem SKILL.md
Bước 3.

Python chỉ làm phần máy làm tốt hơn người: dò ĐIỂM CẮT ỨNG VIÊN bằng phát hiện
scene-change + motion-magnitude (ffmpeg `select=gt(scene,X)` + `scdet`) — tức
những chỗ hình ảnh đổi đột ngột hoặc chuyển từ tĩnh sang động. Claude không cần
xem toàn bộ clip frame-by-frame nữa, chỉ cần xem 1 frame đại diện mỗi đoạn ứng viên
rồi quyết hành vi trong đoạn đó là gì.

Mỗi đoạn ứng viên cũng được cắt sẵn thành 1 file .mp4 ngắn thật vào
`stage/cuts/<tên clip>/beat_NN.mp4` (cùng số thứ tự với frame `beat_NN.jpg`) — để
NGƯỜI DÙNG xem nhanh bằng Finder/QuickTime, không phải chỉ tin vào 1 frame tĩnh.
Claude vẫn quyết bằng frame như cũ (không "xem" được video); các file ngắn này chỉ
là lớp xem-trước cho người, không phải input của edit_render.py.

Dùng:
    python3 extract_frames.py                  # quét toàn bộ import/
    python3 extract_frames.py "Library - 1.MOV"  # chỉ 1 clip

In ra đường dẫn từng frame để Claude Read trực tiếp.
"""
import re
import subprocess
import sys
from pathlib import Path

WORKDIR = Path.home() / "Movies" / "iphone-video-maker"
IMPORT_DIR = WORKDIR / "import"
FRAMES_DIR = WORKDIR / "stage" / "frames"
CUTS_DIR = WORKDIR / "stage" / "cuts"

INTERVAL_SEC = 3.0
MAX_FRAMES_PER_CLIP = 8
CLIP_EXTS = {".mov", ".mp4", ".m4v"}

# Phát hiện điểm cắt ứng viên theo chuyển động/đổi cảnh trong 1 clip gốc — 2 detector
# độc lập, hợp lại thành 1 danh sách ranh giới chung:
#   1. scene-change: bắt chỗ hình ảnh đổi ĐỘT NGỘT (đổi góc máy, cắt cảnh tự nhiên
#      do quay-dừng-quay lại). Không bắt được dead-air trong 1 cú quay liên tục.
#   2. motion-magnitude: bắt chỗ chuyển động chuyển từ TĨNH sang ĐỘNG (hoặc ngược
#      lại) trong cùng 1 cú quay liên tục — vd 2s đầu tay còn lóng ngóng chưa vào
#      khung (tĩnh) rồi mới bắt đầu hành động (động).
# Giới hạn đã biết: nếu cả đoạn dài chuyển động liên tục đều đặn (vd vừa lia máy
# vừa đọc nhãn sản phẩm) thì CẢ HAI detector đều không tách được — đó không phải
# "đoạn chết do đứng yên" mà là "nội dung thưa kéo dài", chỉ Claude phán đoán được
# bằng mắt khi xem frame, không phải tín hiệu hình ảnh đo được.
SCENE_THRESH = 0.12        # độ nhạy scene-change của ffmpeg (thấp = nhạy hơn)
MOTION_WINDOW_SEC = 0.5    # cửa sổ gộp trung bình mafd để tìm vùng tĩnh/động
LOW_MOTION_MAFD = 1.2      # mafd trung bình dưới ngưỡng này coi là "tĩnh"
MIN_BEAT_SEC = 1.2         # khoảng cách tối thiểu giữa 2 điểm cắt ứng viên
MAX_BEATS_PER_CLIP = 10    # chặn trên số đoạn/clip để Claude không phải xem quá nhiều frame
BEAT_FRAME_OFFSET = 0.3    # lấy frame đại diện lệch sau điểm cắt 0.3s, tránh khung mờ/nhoè ngay biên

_FFMPEG_FULL = "/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg"
FFMPEG_BIN = _FFMPEG_FULL if Path(_FFMPEG_FULL).exists() else "ffmpeg"
_FFPROBE_FULL = "/opt/homebrew/opt/ffmpeg-full/bin/ffprobe"
FFPROBE_BIN = _FFPROBE_FULL if Path(_FFPROBE_FULL).exists() else "ffprobe"


def log(msg: str) -> None:
    print(f"[extract_frames] {msg}")


def discover_clips() -> list[Path]:
    if not IMPORT_DIR.exists():
        return []
    return sorted(p for p in IMPORT_DIR.iterdir() if p.suffix.lower() in CLIP_EXTS)


def clip_duration(path: Path) -> float:
    out = subprocess.run(
        [FFPROBE_BIN, "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout
    return float(out.strip().rstrip(","))


def extract_clip_frames(path: Path) -> list[Path]:
    duration = clip_duration(path)
    timestamps = []
    t = 0.0
    while t < duration and len(timestamps) < MAX_FRAMES_PER_CLIP:
        timestamps.append(t)
        t += INTERVAL_SEC

    out_dir = FRAMES_DIR / path.stem
    out_dir.mkdir(parents=True, exist_ok=True)
    for f in out_dir.glob("*.jpg"):
        f.unlink()

    frames = []
    for i, ts in enumerate(timestamps):
        out_file = out_dir / f"f_{i:02d}.jpg"
        subprocess.run(
            [FFMPEG_BIN, "-y", "-loglevel", "error", "-ss", f"{ts:.3f}",
             "-i", str(path), "-frames:v", "1", str(out_file)],
            check=True,
        )
        frames.append(out_file)
    return frames


def _scene_change_times(path: Path) -> list[float]:
    """Thời điểm hình ảnh đổi đột ngột (cắt cảnh tự nhiên trong file gốc)."""
    cmd = [
        FFMPEG_BIN, "-i", str(path),
        "-vf", f"select='gt(scene,{SCENE_THRESH})',showinfo",
        "-f", "null", "-",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return [
        float(m.group(1))
        for line in result.stderr.splitlines()
        if (m := re.search(r"pts_time:([0-9.]+)", line))
    ]


def _motion_mafd_series(path: Path) -> list[tuple[float, float]]:
    """Chuỗi (thời điểm, mafd) — mafd = mean absolute frame difference, độ lớn
    chuyển động giữa 2 frame liên tiếp, lấy cho MỌI frame (threshold=0 không loại
    frame nào, chỉ dùng scdet để tính toán chỉ số)."""
    cmd = [
        FFMPEG_BIN, "-i", str(path),
        "-vf", "scdet=threshold=0,metadata=mode=print:file=-",
        "-f", "null", "-",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    text = result.stdout + result.stderr

    series = []
    cur_time = None
    for line in text.splitlines():
        m_t = re.search(r"pts_time:([0-9.]+)", line)
        if m_t:
            cur_time = float(m_t.group(1))
            continue
        m_v = re.search(r"lavfi\.scd\.mafd=([0-9.]+)", line)
        if m_v and cur_time is not None:
            series.append((cur_time, float(m_v.group(1))))
    return series


def _motion_transition_times(path: Path) -> list[float]:
    """Thời điểm chuyển động chuyển từ tĩnh sang động hoặc ngược lại, trong cùng
    1 cú quay liên tục (không có cắt cảnh đột ngột nào để scene-change bắt được)."""
    series = _motion_mafd_series(path)
    if not series:
        return []

    buckets: dict[int, list[float]] = {}
    for t, v in series:
        buckets.setdefault(int(t // MOTION_WINDOW_SEC), []).append(v)

    window_class = {
        idx: (vals and sum(vals) / len(vals) < LOW_MOTION_MAFD)
        for idx, vals in buckets.items()
    }
    sorted_idx = sorted(window_class)
    return [
        sorted_idx[i] * MOTION_WINDOW_SEC
        for i in range(1, len(sorted_idx))
        if window_class[sorted_idx[i - 1]] != window_class[sorted_idx[i]]
    ]


def _merge_boundaries(raw_times: list[float], duration: float) -> list[float]:
    boundaries = [0.0]
    for t in sorted(raw_times):
        if t - boundaries[-1] >= MIN_BEAT_SEC and duration - t >= MIN_BEAT_SEC:
            boundaries.append(t)
    boundaries.append(duration)

    # Nếu quá nhiều đoạn, gộp dần 2 ranh giới gần nhau nhất (khoảng cách nhỏ nhất)
    # cho tới khi còn <= MAX_BEATS_PER_CLIP đoạn — giữ lại những điểm cắt "khác biệt
    # nhất" thay vì cắt bớt máy móc theo thứ tự thời gian.
    while len(boundaries) - 1 > MAX_BEATS_PER_CLIP:
        gaps = [boundaries[i + 1] - boundaries[i] for i in range(len(boundaries) - 1)]
        drop_idx = gaps.index(min(gaps)) + 1
        boundaries.pop(drop_idx)

    return boundaries


def beat_segments(path: Path) -> list[tuple[float, float]]:
    duration = clip_duration(path)
    raw_times = _scene_change_times(path) + _motion_transition_times(path)
    boundaries = _merge_boundaries(raw_times, duration)
    return list(zip(boundaries[:-1], boundaries[1:]))


def cut_beat_clip(path: Path, start: float, end: float, out_path: Path) -> None:
    """Cắt 1 đoạn ứng viên ra thành file .mp4 ngắn thật trên đĩa — chỉ để người
    dùng xem nhanh bằng Finder/QuickTime (Space để Quick Look), không dùng để
    render bản chính thức (edit_render.py vẫn trim trực tiếp từ file gốc theo
    start/end trong edl.json, không đụng tới các file ngắn này). Dùng `-c copy`
    để cắt nhanh, không re-encode — đủ cho mục đích xem trước."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [FFMPEG_BIN, "-y", "-loglevel", "error", "-ss", f"{start:.3f}", "-to", f"{end:.3f}",
         "-i", str(path), "-c", "copy", "-avoid_negative_ts", "make_zero", str(out_path)],
        check=True,
    )


def extract_beat_frames(path: Path) -> list[tuple[float, float, Path, bool]]:
    """Mỗi đoạn ứng viên (start, end) trả về kèm 1 frame đại diện + cờ is_static
    (chuyển động trung bình trong đoạn dưới ngưỡng — gợi ý "có thể là đoạn chết",
    Claude vẫn tự quyết, đây chỉ là gợi ý). Frame lấy lệch sau start một chút
    (BEAT_FRAME_OFFSET) để tránh đúng khung chuyển cảnh mờ/nhoè. Đồng thời cắt
    luôn clip ngắn thật (cùng số thứ tự với frame) vào stage/cuts/<tên clip>/ để
    người dùng xem nhanh — xem cut_beat_clip()."""
    segments = beat_segments(path)

    out_dir = FRAMES_DIR / path.stem
    out_dir.mkdir(parents=True, exist_ok=True)
    for f in out_dir.glob("*.jpg"):
        f.unlink()

    cuts_dir = CUTS_DIR / path.stem
    if cuts_dir.exists():
        for f in cuts_dir.glob("*.mp4"):
            f.unlink()

    motion_series = _motion_mafd_series(path)

    results = []
    for i, (start, end) in enumerate(segments):
        frame_ts = min(start + BEAT_FRAME_OFFSET, max(end - 0.05, start))
        out_file = out_dir / f"beat_{i:02d}.jpg"
        subprocess.run(
            [FFMPEG_BIN, "-y", "-loglevel", "error", "-ss", f"{frame_ts:.3f}",
             "-i", str(path), "-frames:v", "1", str(out_file)],
            check=True,
        )
        cut_beat_clip(path, start, end, cuts_dir / f"beat_{i:02d}.mp4")
        vals = [v for t, v in motion_series if start <= t < end]
        is_static = bool(vals) and sum(vals) / len(vals) < LOW_MOTION_MAFD
        results.append((start, end, out_file, is_static))
    return results


def main() -> None:
    target = sys.argv[1] if len(sys.argv) > 1 else None
    clips = discover_clips()
    if target:
        clips = [c for c in clips if c.name == target]
        if not clips:
            print(f"Không tìm thấy clip '{target}' trong {IMPORT_DIR}", file=sys.stderr)
            sys.exit(1)
    if not clips:
        print(f"Không có clip nào trong {IMPORT_DIR}", file=sys.stderr)
        sys.exit(1)

    for clip in clips:
        log(f"Trích frame: {clip.name}")
        frames = extract_clip_frames(clip)
        print(f"\n=== {clip.name} ===")
        for f in frames:
            print(str(f))


if __name__ == "__main__":
    main()
