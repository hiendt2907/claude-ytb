#!/usr/bin/env python3
"""Render 1 video hoàn chỉnh từ EDL (Edit Decision List) JSON.

Thuần cắt/ghép video: trim từng clip theo start/end, đổi speed, zoom Ken Burns nhẹ
theo scene, nối các đoạn bằng transition, mix nhạc nền (nếu có). KHÔNG có voice-over,
KHÔNG burn text/badge/emoji lên video — chỉ là edit + render.

Độc lập hoàn toàn với pipeline YouTube của project — không đọc/viết gì trong assets/,
data/, src/, scripts/ (kịch bản YouTube). Toàn bộ I/O của skill nằm trong
~/Movies/iphone-video-maker/ (import/ stage/ output/), trừ EDL json và file nhạc nền
(nếu có) có thể nằm bất kỳ đâu người dùng chỉ định.

EDL schema (xem edl.example.json):
{
  "output_name": "brand_ad_v1",
  "transition": "fade",        // kiểu xfade: fade, wipeleft, slideup, dissolve...
  "transition_duration": 0.6,
  "music": "/path/to/nhac.mp3",      // optional
  "music_volume_db": -18,            // optional, áp dụng nếu có music + duck audio gốc
  "clips": [
    {
      "file": "Library - 1 of 10.MOV",   // tên file trong import/ (hoặc path tuyệt đối)
      "start": "00:00:02.000",
      "end": "00:00:10.000",
      "speed": 1.0,                       // <1 = slow-mo, >1 = tua nhanh
      "scene": "unbox"                    // optional: hook/unbox/demo/testimonial/cta
                                           // — quyết định zoom/punch hình + color grade nhẹ.
                                           // Xem SCENE_STYLES. Claude gán nhãn này khi xem
                                           // frame mẫu (Bước 0 trong SKILL.md).
    }
  ]
}
"""
import json
import subprocess
import sys
from pathlib import Path

WORKDIR = Path.home() / "Movies" / "iphone-video-maker"
IMPORT_DIR = WORKDIR / "import"
STAGE_DIR = WORKDIR / "stage"
OUTPUT_DIR = WORKDIR / "output"

# Output cố định 2K dọc (QHD portrait) cho TikTok/Reels — không lấy theo khung của
# clip nguồn nữa, vì clip quay ngang/dọc lẫn lộn vẫn phải ra cùng 1 khung chuẩn.
TARGET_W = "1440"
TARGET_H = "2560"

# Style hình theo nhãn cảnh — Claude gán nhãn này khi xem frame mẫu (xem extract_frames.py
# + SKILL.md Bước 0). Chỉ ảnh hưởng color grade nhẹ + zoom Ken Burns/punch, không có
# text/badge/emoji nữa.
#   - zoom_end: hệ số zoom-in tối đa đạt được vào cuối đoạn (1.0 = không zoom)
#   - punch: cú "giật" zoom nhẹ ngay 0.25s đầu đoạn (0 = không có)
DEFAULT_SCENE = "demo"
SCENE_STYLES = {
    "hook": {
        "extra_vf": ["eq=contrast=1.08:saturation=1.15"],
        "zoom_end": 1.10,
        "punch": 0.05,
    },
    "unbox": {
        "extra_vf": ["eq=saturation=1.1:gamma=1.03"],
        "zoom_end": 1.0,
        "punch": 0.0,
    },
    "demo": {
        "extra_vf": [],
        "zoom_end": 1.12,
        "punch": 0.0,
    },
    "testimonial": {
        "extra_vf": ["eq=contrast=1.02"],
        "zoom_end": 1.0,
        "punch": 0.0,
    },
    "cta": {
        "extra_vf": ["vignette"],
        "zoom_end": 1.05,
        "punch": 0.06,
    },
}


def scene_style(scene: str | None) -> dict:
    return dict(SCENE_STYLES.get(scene, SCENE_STYLES[DEFAULT_SCENE]))


_FFMPEG_FULL = "/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg"
FFMPEG_BIN = _FFMPEG_FULL if Path(_FFMPEG_FULL).exists() else "ffmpeg"
_FFPROBE_FULL = "/opt/homebrew/opt/ffmpeg-full/bin/ffprobe"
FFPROBE_BIN = _FFPROBE_FULL if Path(_FFPROBE_FULL).exists() else "ffprobe"


def log(msg: str) -> None:
    print(f"[edit_render] {msg}")


def run(cmd: list[str]) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Lệnh thất bại: {' '.join(cmd)}\n{result.stderr}")


def ffprobe_value(path: Path, entries: str, stream: str | None = None) -> str:
    cmd = [FFPROBE_BIN, "-v", "error", "-show_entries", entries, "-of", "csv=p=0"]
    if stream:
        cmd += ["-select_streams", stream]
    cmd.append(str(path))
    out = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
    return out.strip().rstrip(",")


def resolve_clip_path(name: str) -> Path:
    p = Path(name)
    if p.is_absolute() and p.exists():
        return p
    candidate = IMPORT_DIR / name
    if not candidate.exists():
        raise FileNotFoundError(f"Không tìm thấy clip: {name} (đã tìm trong {IMPORT_DIR})")
    return candidate


def escape_expr(expr: str) -> str:
    """Escape dấu phẩy trong 1 expression ffmpeg để khỏi bị hiểu lầm là dấu ngăn filter."""
    return expr.replace(",", "\\,")


def timecode_to_seconds(tc: str) -> float:
    h, m, s = tc.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def zoom_punch_crop_filter(zoom_end: float, punch: float, ramp_duration: float) -> str | None:
    """Zoom-in dần (Ken Burns) trong suốt đoạn + cú giật nhẹ 0.25s đầu, áp trước khi
    scale/pad về khung chuẩn — crop dựa trên kích thước gốc của clip, không méo hình."""
    if zoom_end <= 1.0 and punch <= 0:
        return None
    ramp = max(ramp_duration, 0.01)
    # crop expr không cho dùng max() cùng biến t (libavfilter báo lỗi eval) — viết lại
    # punch = punch*(1-min(t/0.25,1)) thay cho max(0,1-t/0.25), tương đương về giá trị.
    zf = f"(1+({zoom_end - 1:.4f})*min(t/{ramp:.3f},1)+{punch:.4f}*(1-min(t/0.25,1)))"
    filt = f"crop=iw/{zf}:ih/{zf}:(iw-iw/{zf})/2:(ih-ih/{zf})/2"
    return escape_expr(filt)


def build_segment(index: int, clip: dict) -> Path:
    src = resolve_clip_path(clip["file"])
    start = clip.get("start", "00:00:00.000")
    end = clip.get("end")
    speed = float(clip.get("speed", 1.0))
    style = scene_style(clip.get("scene"))

    start_sec = timecode_to_seconds(start)
    end_sec = timecode_to_seconds(end) if end else float(ffprobe_value(src, "format=duration"))
    raw_duration = max(end_sec - start_sec, 0.01)

    out_path = STAGE_DIR / f"{index:02d}_styled.mp4"
    cmd = [FFMPEG_BIN, "-y", "-loglevel", "error", "-ss", start]
    if end:
        cmd += ["-to", end]
    cmd += ["-i", str(src)]

    vf_parts = []
    zoom_filter = zoom_punch_crop_filter(style["zoom_end"], style["punch"], raw_duration)
    if zoom_filter:
        vf_parts.append(zoom_filter)
    vf_parts += [
        f"scale={TARGET_W}:{TARGET_H}:force_original_aspect_ratio=decrease",
        f"pad={TARGET_W}:{TARGET_H}:(ow-iw)/2:(oh-ih)/2",
        "setsar=1",
        *style["extra_vf"],
    ]
    af_parts = []

    if speed != 1.0:
        vf_parts.append(f"setpts=PTS/{speed}")
        remaining = speed
        while remaining > 2.0:
            af_parts.append("atempo=2.0")
            remaining /= 2.0
        while remaining < 0.5:
            af_parts.append("atempo=0.5")
            remaining /= 0.5
        af_parts.append(f"atempo={remaining:.6f}")

    vf_parts.append("fps=30")
    cmd += ["-vf", ",".join(vf_parts)]
    if af_parts:
        cmd += ["-af", ",".join(af_parts)]
    cmd += ["-c:v", "libx264", "-preset", "fast", "-crf", "18",
            "-c:a", "aac", "-ar", "48000", "-ac", "2", str(out_path)]
    run(cmd)
    return out_path


def concat_with_crossfade(segments: list[Path], transition: str, duration: float) -> Path:
    if len(segments) == 1:
        return segments[0]

    current = segments[0]
    current_dur = float(ffprobe_value(current, "format=duration"))
    for i in range(1, len(segments)):
        nxt = segments[i]
        offset = max(current_dur - duration, 0)
        step_out = STAGE_DIR / f"step_{i:02d}.mp4"
        run([
            FFMPEG_BIN, "-y", "-loglevel", "error",
            "-i", str(current), "-i", str(nxt),
            "-filter_complex",
            f"[0:v][1:v]xfade=transition={transition}:duration={duration}:offset={offset}[v];"
            f"[0:a][1:a]acrossfade=d={duration}[a]",
            "-map", "[v]", "-map", "[a]",
            "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-c:a", "aac",
            str(step_out),
        ])
        current = step_out
        current_dur = float(ffprobe_value(current, "format=duration"))
    return current


def mix_music(video_path: Path, music_path: str, music_volume_db: float, out_path: Path) -> None:
    run([
        FFMPEG_BIN, "-y", "-loglevel", "error",
        "-i", str(video_path), "-i", music_path,
        "-filter_complex",
        f"[1:a]volume={music_volume_db}dB[music];"
        "[0:a][music]amix=inputs=2:duration=first:dropout_transition=2[a]",
        "-map", "0:v", "-map", "[a]",
        "-c:v", "copy", "-c:a", "aac",
        str(out_path),
    ])


def main() -> None:
    edl_path = Path(sys.argv[1]) if len(sys.argv) > 1 else WORKDIR / "edl.json"
    if not edl_path.exists():
        print(f"Không thấy EDL: {edl_path}. Tạo file JSON theo edl.example.json trước.", file=sys.stderr)
        sys.exit(1)

    edl = json.loads(edl_path.read_text())
    clips = edl.get("clips", [])
    if not clips:
        print("EDL không có clip nào trong 'clips'.", file=sys.stderr)
        sys.exit(1)

    STAGE_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for f in STAGE_DIR.glob("*"):
        if f.is_file():
            f.unlink()

    log(f"Khung hình chuẩn: {TARGET_W}x{TARGET_H} (2K dọc)")

    segments = []
    for i, clip in enumerate(clips, start=1):
        log(f"Dựng đoạn {i}/{len(clips)}: {clip['file']} [{clip.get('start','0')} -> {clip.get('end','hết')}]"
            f" scene={clip.get('scene', DEFAULT_SCENE)}")
        segments.append(build_segment(i, clip))

    transition = edl.get("transition", "fade")
    duration = float(edl.get("transition_duration", 0.6))
    log(f"Nối {len(segments)} đoạn với transition={transition} ({duration}s)...")
    merged = concat_with_crossfade(segments, transition, duration)

    output_name = edl.get("output_name", "edit")
    final_out = OUTPUT_DIR / f"{output_name}.mp4"

    music = edl.get("music")
    if music:
        log(f"Mix nhạc nền: {music}")
        mix_music(merged, music, float(edl.get("music_volume_db", -18)), final_out)
    else:
        run([FFMPEG_BIN, "-y", "-loglevel", "error", "-i", str(merged), "-c", "copy", str(final_out)])

    log(f"Xong! Video: {final_out}")
    subprocess.run(["open", str(OUTPUT_DIR)])


if __name__ == "__main__":
    main()
