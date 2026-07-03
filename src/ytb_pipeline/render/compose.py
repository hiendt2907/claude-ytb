"""Khâu 3 — Dựng video Short dọc (1080x1920): caption (Pillow) + audio (ffmpeg)."""

import subprocess
import tempfile
from dataclasses import replace
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from ..config.settings import settings
from ..pkg.models import RenderedVideo, Voiceover
from ..providers.registry import get_image_provider

OUTPUT_DIR = Path("assets/output")
W, H = 1080, 1920
BG_TOP = (13, 17, 23)        # GitHub dark
BG_BOTTOM = (22, 27, 34)
FG = (240, 246, 252)
ACCENT = (88, 166, 255)       # xanh dev
DANGER = (248, 81, 73)        # đỏ cảnh báo
TERM_BG = (1, 4, 9)
PROMPT = (63, 185, 80)        # xanh lá $ prompt

FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/Library/Fonts/Arial.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
]
MONO_CANDIDATES = [
    "/System/Library/Fonts/Menlo.ttc",
    "/System/Library/Fonts/Monaco.ttf",
    "/System/Library/Fonts/SFNSMono.ttf",
]


def render_video(voiceover: Voiceover) -> RenderedVideo:
    """Ghép từng segment (ảnh caption + audio) thành .mp4, sinh thumbnail."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    work = OUTPUT_DIR / "_frames"
    work.mkdir(exist_ok=True)
    slug = _slug(voiceover)

    clips: list[Path] = []
    for i, seg in enumerate(voiceover.segments):
        clip = work / f"{slug}_{i:02d}.mp4"
        _render_segment(seg, index=i, total=len(voiceover.segments),
                        work=work, prefix=f"{slug}_{i:02d}", out=clip)
        clips.append(clip)

    video_path = OUTPUT_DIR / f"{slug}.mp4"
    _concat_clips(clips, video_path)

    thumb = OUTPUT_DIR / f"{slug}_thumb.jpg"
    _caption_image(voiceover.title, index=0, total=1, thumbnail=True,
                   danger=True).convert("RGB").save(thumb, quality=90)

    return replace(
        RenderedVideo(**vars(voiceover)),
        video_path=video_path,
        thumbnail_path=thumb,
    )


def _render_segment(seg, index: int, total: int, work: Path,
                    prefix: str, out: Path) -> None:
    """Dựng clip cho 1 segment.

    - Đoạn có code: terminal card tĩnh (1 frame, giữ nguyên).
    - Đoạn caption thuần: caption hiện dần từng từ ở lower-third như chú thích
      chạy theo lời nói (nhiều frame Pillow ghép theo thời lượng audio).
    """
    if seg.code:
        png = work / f"{prefix}.png"
        _terminal_segment(seg, index, total).save(png)
        _image_audio_clip(png, seg.audio_path, out)
        return

    caption = (seg.caption or "").strip()
    prompt = caption or (seg.narration or "")[:80]
    bg = _background_image(index, total, prompt=prompt)
    # Không caption HOẶC tắt caption chạy (settings.show_captions) → nền trơn,
    # không chữ chạy theo lời nói. Mặt video sạch.
    if not caption or not settings.show_captions:
        png = work / f"{prefix}.png"
        bg.save(png)
        _image_audio_clip(png, seg.audio_path, out)
        return

    duration = _audio_duration(seg.audio_path)
    steps = _reveal_steps(caption, duration)
    frames: list[tuple[Path, float]] = []
    for k, (text, dur) in enumerate(steps):
        frame = bg.copy()
        _draw_caption(frame, text, danger=seg.danger)
        png = work / f"{prefix}_w{k:02d}.png"
        frame.save(png)
        frames.append((png, dur))
    _caption_clip(frames, seg.audio_path, out)


def _background_image(index: int, total: int, prompt: str = "") -> Image.Image:
    """Nền sinh từ ImageProvider (mặc định "pillow" = gradient gốc) — caption
    phủ động ở lower-third (KHÔNG hiện số thứ tự).

    Backward-compat: provider "pillow" tái lập đúng gradient GitHub dark gốc
    khi prompt rỗng/không khớp từ khoá màu, nên hành vi mặc định KHÔNG đổi.
    """
    provider = get_image_provider()
    with tempfile.TemporaryDirectory() as tmp:
        out_path = Path(tmp) / "bg.png"
        provider.generate(prompt=prompt, width=W, height=H, output_path=out_path)
        return Image.open(out_path).convert("RGB")


def _caption_image(text: str, index: int, total: int, thumbnail: bool = False,
                   danger: bool = False) -> Image.Image:
    img = _gradient()
    draw = ImageDraw.Draw(img)
    font = _font(96 if not thumbnail else 104)

    lines = _wrap(draw, text, font, max_width=W - 160)
    line_h = font.getbbox("Ag")[3] + 28
    total_h = line_h * len(lines)
    y = (H - total_h) / 2
    for line in lines:
        draw.text((W / 2, y + line_h / 2), line, font=font,
                  fill=DANGER if danger else FG, anchor="mm")
        y += line_h
    return img


def _terminal_segment(seg, index: int, total: int) -> Image.Image:
    """Caption phía trên + terminal card hiển thị lệnh ở giữa."""
    img = _gradient()
    draw = ImageDraw.Draw(img)

    # caption (tiêu đề đoạn) — KHÔNG hiện số thứ tự
    cap_font = _font(78)
    cap_lines = _wrap(draw, seg.caption, cap_font, max_width=W - 140)
    cap_h = (cap_font.getbbox("Ag")[3] + 18)
    y = 360
    for line in cap_lines:
        draw.text((W / 2, y, ), line, font=cap_font,
                  fill=DANGER if seg.danger else FG, anchor="ma")
        y += cap_h

    # terminal card
    _draw_terminal(img, draw, seg.code, top=y + 90, danger=seg.danger)
    return img


def _draw_terminal(img, draw, code: str, top: int, danger: bool) -> None:
    mono = _mono(58)
    pad = 60
    card_w = W - 120
    x0 = 60
    # đo chiều cao theo số dòng (wrap lệnh dài)
    code_lines = _wrap_mono(draw, code, mono, card_w - 2 * pad - 40)
    line_h = mono.getbbox("Ag")[3] + 22
    bar_h = 90
    card_h = bar_h + pad + line_h * len(code_lines) + pad
    y0 = top
    radius = 32

    # thân terminal
    draw.rounded_rectangle([x0, y0, x0 + card_w, y0 + card_h],
                           radius=radius, fill=TERM_BG,
                           outline=DANGER if danger else (48, 54, 61), width=3)
    # thanh title + 3 chấm
    draw.rounded_rectangle([x0, y0, x0 + card_w, y0 + bar_h],
                           radius=radius, fill=(33, 38, 45))
    draw.rectangle([x0, y0 + bar_h - radius, x0 + card_w, y0 + bar_h], fill=(33, 38, 45))
    for i, col in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]):
        draw.ellipse([x0 + 40 + i * 56, y0 + 30, x0 + 70 + i * 56, y0 + 60], fill=col)
    draw.text((x0 + card_w - 40, y0 + bar_h / 2), "bash", font=_mono(40),
              fill=(139, 148, 158), anchor="rm")

    # các dòng lệnh
    cy = y0 + bar_h + pad
    for i, line in enumerate(code_lines):
        prefix = "$ " if i == 0 else "  "
        draw.text((x0 + pad, cy), prefix, font=mono, fill=PROMPT, anchor="la")
        pw = draw.textlength(prefix, font=mono)
        draw.text((x0 + pad + pw, cy), line, font=mono,
                  fill=DANGER if danger else FG, anchor="la")
        cy += line_h


def _wrap_mono(draw, text: str, font, max_width: int) -> list[str]:
    if draw.textlength(text, font=font) <= max_width:
        return [text]
    out, cur = [], ""
    for ch in text:
        if draw.textlength(cur + ch, font=font) <= max_width:
            cur += ch
        else:
            out.append(cur)
            cur = ch
    if cur:
        out.append(cur)
    return out


def _gradient() -> Image.Image:
    base = Image.new("RGB", (W, H), BG_TOP)
    top, bottom = BG_TOP, BG_BOTTOM
    px = base.load()
    for y in range(H):
        t = y / H
        row = tuple(int(top[c] + (bottom[c] - top[c]) * t) for c in range(3))
        for x in range(W):
            px[x, y] = row
    return base


def _wrap(draw, text: str, font, max_width: int) -> list[str]:
    words = text.split()
    lines, cur = [], ""
    for w in words:
        trial = f"{cur} {w}".strip()
        if draw.textlength(trial, font=font) <= max_width:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines or [text]


def _font(size: int) -> ImageFont.FreeTypeFont:
    for path in FONT_CANDIDATES:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def _mono(size: int) -> ImageFont.FreeTypeFont:
    for path in MONO_CANDIDATES:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return _font(size)


CAPTION_Y = 0.74           # tâm khối caption ở ~74% chiều cao (lower-third)
CAPTION_SIZE = 84
CAPTION_BAND = (13, 17, 23, 175)   # dải nền mờ phía sau cho dễ đọc


def _image_audio_clip(png: Path, audio: Path, out: Path) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-loop", "1", "-i", str(png), "-i", str(audio),
         "-c:v", "libx264", "-tune", "stillimage", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-b:a", "192k", "-shortest", str(out)],
        capture_output=True, check=True,
    )


def _caption_clip(frames: list[tuple[Path, float]], audio: Path,
                  out: Path) -> None:
    """Ghép các frame caption (hiện dần) theo thời lượng + mux audio."""
    listfile = out.with_suffix(".concat")
    lines = []
    for png, dur in frames:
        lines.append(f"file '{png.resolve()}'")
        lines.append(f"duration {dur:.3f}")
    lines.append(f"file '{frames[-1][0].resolve()}'")  # concat demuxer cần lặp frame cuối
    listfile.write_text("\n".join(lines) + "\n")
    subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listfile),
         "-i", str(audio), "-c:v", "libx264", "-pix_fmt", "yuv420p",
         "-r", "30", "-c:a", "aac", "-b:a", "192k", "-shortest", str(out)],
        capture_output=True, check=True,
    )
    listfile.unlink(missing_ok=True)


def _audio_duration(audio: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(audio)],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())


def _reveal_steps(caption: str, duration: float) -> list[tuple[str, float]]:
    """Chia caption thành các mốc hiện dần từng từ, chia đều thời lượng.

    Mốc i hiển thị các từ [0..i]; mốc cuối nhận phần dư để tổng = duration.
    """
    words = caption.split()
    n = max(1, len(words))
    step = duration / n
    steps: list[tuple[str, float]] = []
    for i in range(n):
        dur = duration - step * (n - 1) if i == n - 1 else step
        steps.append((" ".join(words[: i + 1]), dur))
    return steps


def _draw_caption(img: Image.Image, text: str, *, danger: bool = False) -> None:
    """Vẽ caption ở lower-third kèm dải nền mờ (chú thích chạy theo lời nói)."""
    draw = ImageDraw.Draw(img, "RGBA")
    font = _font(CAPTION_SIZE)
    lines = _wrap(draw, text, font, max_width=W - 200)
    line_h = font.getbbox("Ag")[3] + 24
    total_h = line_h * len(lines)
    y0 = int(H * CAPTION_Y) - total_h // 2

    pad = 36
    draw.rounded_rectangle(
        [80, y0 - pad, W - 80, y0 + total_h + pad],
        radius=28, fill=CAPTION_BAND,
    )
    y = y0
    for line in lines:
        draw.text((W / 2, y + line_h / 2), line, font=font,
                  fill=DANGER if danger else FG, anchor="mm")
        y += line_h


def _concat_clips(clips: list[Path], out: Path) -> None:
    listfile = out.with_suffix(".txt")
    listfile.write_text("".join(f"file '{c.resolve()}'\n" for c in clips))
    subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listfile),
         "-c", "copy", str(out)],
        capture_output=True, check=True,
    )
    listfile.unlink(missing_ok=True)


def _slug(v: Voiceover) -> str:
    return v.audio_path.stem if v.audio_path else "video"
