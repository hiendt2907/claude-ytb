"""Khâu 3 (biến thể AI) — dựng video với nền B-roll stock + overlay caption/terminal.

Khác `compose.py`: thay nền gradient tĩnh bằng video B-roll tải từ Pexels
(`stock.fetch_broll`), phủ một lớp overlay RGBA (veil tối + caption + terminal card)
để chữ luôn đọc rõ. Nếu thiếu key Pexels -> fail fast (theo convention ranh giới).

Hỗ trợ 2 hướng (theo settings.orientation):
  - portrait  1080x1920  -> Short dọc (mặc định)
  - landscape 1920x1080  -> clip dài ngang
Tái dùng helper vẽ của `compose.py` để không lặp code.
"""

from __future__ import annotations

import subprocess
from dataclasses import replace
from pathlib import Path

from PIL import Image, ImageDraw

from ..config.settings import settings
from ..pkg.models import RenderedVideo, Voiceover
from . import compose as slide
from . import stock
from . import transitions

OUTPUT_DIR = Path("assets/output")
PORTRAIT_WH = (1080, 1920)
LANDSCAPE_WH = (1920, 1080)
VEIL = (10, 14, 20, 55)  # lớp phủ tối ~22% cho dễ đọc chữ trên B-roll (giảm từ 110/43% — video bị tối hơn kênh khác)
BRIGHTNESS_BOOST = 0.08  # bù sáng B-roll (trước là 0.0 -> video tối hơn nguồn gốc)

# Nhịp cắt cảnh (đồng bộ transcript): không để một cảnh tĩnh quá ~6s.
BEAT_TARGET_SEC = 6.0     # cadence cắt cảnh thường
HOOK_BEAT_SEC = 2.5       # segment đầu cắt nhanh -> hook năng lượng cao
MAX_VARIANTS = 4          # tối đa số shot tải/segment (round-robin nếu cần nhiều beat hơn)
FPS = 30
COLD_BEAT_SEC = 1.3       # nhịp cắt cold-open hook (cảnh hành động dồn lên đầu)
MAX_COLD_SHOTS = 3        # số cảnh hành động tối đa trong cold-open


def _valid_clip(path: Path) -> bool:
    """True nếu `path` là video đọc được, có duration > 0 — chặn file dở dang do bị kill giữa lúc ghi."""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", str(path)],
            capture_output=True, text=True, check=True,
        )
        return float(out.stdout.strip()) > 0
    except (subprocess.CalledProcessError, ValueError):
        return False


def _dims() -> tuple[int, int, bool]:
    """(W, H, is_landscape) theo settings.orientation."""
    landscape = settings.orientation == "landscape"
    w, h = LANDSCAPE_WH if landscape else PORTRAIT_WH
    return w, h, landscape


def render_video_ai(voiceover: Voiceover) -> RenderedVideo:
    """Ghép từng segment (B-roll nền + overlay + audio) thành .mp4, sinh thumbnail."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    work = OUTPUT_DIR / "_frames_ai"
    work.mkdir(exist_ok=True)
    slug = slide._slug(voiceover)
    w, h, landscape = _dims()
    fallback_query = _fallback_query(voiceover.title)

    # Bộ đếm link B-roll đã dùng — chống lặp clip XUYÊN SUỐT video (nhiều segment
    # trùng từ khoá vẫn ra cảnh khác nhau). Truyền qua mọi lần fetch trong video.
    used_broll: set[str] = set()

    clips: list[Path] = []
    whoosh_before: list[bool] = []
    for i, seg in enumerate(voiceover.segments):
        query = seg.broll.strip() or fallback_query
        clip = work / f"{slug}_{i:02d}.mp4"
        # Resume: segment đã render xong hợp lệ ở lần chạy trước (bị dừng giữa
        # render) -> bỏ qua, không tải B-roll/dựng lại clip này.
        if not (clip.exists() and _valid_clip(clip)):
            _render_broll_segment(seg, index=i, total=len(voiceover.segments),
                                  query=query, work=work, prefix=f"{slug}_{i:02d}",
                                  out=clip, dims=(w, h), landscape=landscape,
                                  used=used_broll)
        clips.append(clip)
        whoosh_before.append(seg.transition)

    # Cold-open hook: dồn các cảnh hành động (seg.hook) lên đầu video.
    cold = _hook_coldopen(voiceover, dims=(w, h), landscape=landscape,
                          work=work, slug=slug, used=used_broll)
    if cold is not None:
        clips.insert(0, cold)
        whoosh_before.insert(0, False)
        whoosh_before[1] = False  # cold-open -> câu chuyện: đã là cú cắt, không whoosh

    video_path = OUTPUT_DIR / f"{slug}.mp4"
    transitions.concat_with_transitions(clips, whoosh_before, video_path)

    thumb = OUTPUT_DIR / f"{slug}_thumb.jpg"
    _thumbnail(voiceover.title, dims=(w, h)).convert("RGB").save(thumb, quality=90)

    return replace(
        RenderedVideo(**vars(voiceover)),
        video_path=video_path,
        thumbnail_path=thumb,
    )


def _render_broll_segment(seg, index: int, total: int, query: str, work: Path,
                          prefix: str, out: Path, dims: tuple[int, int],
                          landscape: bool, used: set[str]) -> None:
    """Dựng clip B-roll cho 1 segment.

    Nền là một chuỗi beat cắt cảnh (mỗi shot ≤ ~6s, có Ken Burns motion) xếp
    theo thời lượng narration -> không còn cảnh tĩnh dài. Segment đầu cắt nhanh
    để tạo hook năng lượng cao.

    - Đoạn code (dạng dọc): overlay tĩnh terminal card (giữ nguyên).
    - Đoạn caption thuần: caption hiện dần từng từ ở lower-third như chú thích
      chạy theo lời nói (giống clip tham khảo).
    """
    w, h = dims
    caption = (seg.caption or "").strip()
    duration = slide._audio_duration(seg.audio_path)
    bg = _moving_background(query, duration, index=index, dims=dims,
                            landscape=landscape, work=work, prefix=prefix,
                            used=used)

    show_cap = settings.show_captions and bool(caption)

    # Đoạn code dọc: terminal card tĩnh (giữ nguyên, không phải caption chạy).
    if seg.code and not landscape:
        png = work / f"{prefix}.png"
        _static_overlay(seg, index, total, dims).save(png)
        _broll_clip(bg, png, seg.audio_path, out, dims=dims)
        return

    # Tắt caption chạy: nền B-roll + veil trơn, CHỈ giữ emphasis chip từ khoá.
    if not show_cap:
        base_png = work / f"{prefix}_base.png"
        _static_overlay(seg, index, total, dims).save(base_png)  # veil trơn (non-code)
        emph = _emphasis_overlays(seg.emphasis, duration, dims, work, prefix)
        if not emph:
            _broll_clip(bg, base_png, seg.audio_path, out, dims=dims)
        else:
            _broll_caption_clip(bg, base_png, emph, seg.audio_path, out, dims=dims)
        return

    steps = slide._reveal_steps(caption, duration)
    base_png = work / f"{prefix}_base.png"
    _base_overlay(caption, dims, badge=None).save(base_png)

    overlays: list[tuple[Path, float, float]] = []
    t = 0.0
    for k, (text, dur) in enumerate(steps):
        png = work / f"{prefix}_w{k:02d}.png"
        _text_overlay(text, caption, dims, danger=seg.danger).save(png)
        overlays.append((png, t, t + dur))
        t += dur

    # Text nhấn từ khoá (visual aid): pop chip lớn ở upper-third đúng lúc.
    overlays += _emphasis_overlays(seg.emphasis, duration, dims, work, prefix)
    _broll_caption_clip(bg, base_png, overlays, seg.audio_path, out, dims=dims)


def _emphasis_windows(n: int, duration: float) -> list[tuple[float, float]]:
    """Chia đều thời lượng cho `n` từ khoá nhấn; mỗi từ hiện ~tối đa 2s giữa slot."""
    if n <= 0:
        return []
    slot = duration / n
    show = min(2.0, slot * 0.8)
    return [(slot * j + (slot - show) / 2, slot * j + (slot - show) / 2 + show)
            for j in range(n)]


def _emphasis_overlays(terms: tuple[str, ...], duration: float,
                       dims: tuple[int, int], work: Path,
                       prefix: str) -> list[tuple[Path, float, float]]:
    out: list[tuple[Path, float, float]] = []
    for j, (term, (start, end)) in enumerate(
            zip(terms, _emphasis_windows(len(terms), duration))):
        png = work / f"{prefix}_emph{j:02d}.png"
        _emphasis_overlay(term, dims).save(png)
        out.append((png, start, end))
    return out


def _emphasis_overlay(term: str, dims: tuple[int, int]) -> Image.Image:
    """Chip nhấn từ khoá: nền accent + chữ đậm tối, đặt ở upper-third."""
    w, h = dims
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    font = slide._font(84 if w > h else 92)
    lines = slide._wrap(draw, term, font, max_width=w - 240)
    line_h = font.getbbox("Ag")[3] + 20
    total_h = line_h * len(lines)
    y0 = int(h * 0.30) - total_h // 2
    pad = 30
    draw.rounded_rectangle(
        [w * 0.12, y0 - pad, w * 0.88, y0 + total_h + pad],
        radius=26, fill=(*slide.ACCENT, 220),
    )
    y = y0
    for line in lines:
        draw.text((w / 2, y + line_h / 2), line, font=font,
                  fill=(13, 17, 23, 255), anchor="mm")
        y += line_h
    return img


def _beat_durations(total: float, hook: bool) -> list[float]:
    """Chia thời lượng segment thành các beat đều nhau (tổng giữ nguyên).

    hook=True -> cadence nhanh hơn (cắt cảnh dày) cho segment mở đầu.
    """
    target = HOOK_BEAT_SEC if hook else BEAT_TARGET_SEC
    n = max(1, round(total / target))
    base = total / n
    durs = [base] * n
    durs[-1] = total - base * (n - 1)  # beat cuối nhận phần dư -> tổng chính xác
    return durs


def _moving_background(query: str, duration: float, *, index: int,
                       dims: tuple[int, int], landscape: bool, work: Path,
                       prefix: str, used: set[str]) -> Path:
    """Nền động: chuỗi beat (shot khác nhau + Ken Burns) dài đúng `duration`."""
    hook = index == 0
    durs = _beat_durations(duration, hook)
    n_variants = min(len(durs), MAX_VARIANTS)
    min_dur = max(HOOK_BEAT_SEC if hook else BEAT_TARGET_SEC, 2.0)
    variants = stock.fetch_broll_variants(query, n_variants,
                                          min_duration=min_dur, landscape=landscape,
                                          exclude=used)

    beats = [(variants[i % len(variants)], d, i) for i, d in enumerate(durs)]
    bg_out = work / f"{prefix}_bg.mp4"
    _build_background(beats, dims, bg_out)
    return bg_out


def _build_background(beats: list[tuple[Path, float, int]], dims: tuple[int, int],
                      out: Path) -> None:
    """Dựng Ken Burns cho từng beat rồi nối thành một nền câm dài đúng tổng."""
    parts: list[Path] = []
    for src, dur, idx in beats:
        part = out.with_name(f"{out.stem}_b{idx:02d}.mp4")
        _kenburns_beat(src, dur, dims, idx, part)
        parts.append(part)
    slide._concat_clips(parts, out)


def _kenburns_beat(src: Path, dur: float, dims: tuple[int, int], idx: int,
                   out: Path) -> None:
    """Một beat câm dài `dur`s: zoom/pan chậm trên B-roll (đỡ cảnh tĩnh).

    Beat chẵn zoom-in, beat lẻ zoom-out -> nhịp đổi chiều cho đỡ đều.
    """
    w, h = dims
    if idx % 2 == 0:
        zexpr = "min(zoom+0.0010,1.18)"
    else:
        zexpr = "if(eq(on,0),1.18,max(zoom-0.0010,1.0))"
    vf = (
        f"scale={w * 2}:{h * 2}:force_original_aspect_ratio=increase,"
        f"crop={w * 2}:{h * 2},"
        f"zoompan=z='{zexpr}':d=1:fps={FPS}:"
        f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={w}x{h},setsar=1,"
        f"eq=brightness={BRIGHTNESS_BOOST}:saturation=1.08"
    )
    subprocess.run(
        ["ffmpeg", "-y", "-stream_loop", "-1", "-i", str(src),
         "-t", f"{dur:.3f}", "-an", "-vf", vf,
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", str(FPS), str(out)],
        capture_output=True, check=True,
    )


def _hook_coldopen(voiceover, *, dims: tuple[int, int], landscape: bool,
                   work: Path, slug: str, used: set[str]) -> Path | None:
    """Cold-open ~vài giây: montage cảnh hành động (seg.hook) + title, đặt đầu video.

    Trả None nếu không segment nào đánh dấu hook hoặc thiếu B-roll keyword.
    Bám góp ý Studio: mở bằng chuyển động năng lượng cao trước khi vào kể chuyện.
    """
    out = work / f"{slug}_cold.mp4"
    # Resume: cold-open đã render xong hợp lệ ở lần chạy trước -> dùng lại luôn,
    # không tải B-roll/dựng lại (tránh tốn quota Pexels + thời gian vô ích).
    if out.exists() and _valid_clip(out):
        return out

    queries = [s.broll.strip() for s in voiceover.segments
               if s.hook and s.broll.strip()][:MAX_COLD_SHOTS]
    if not queries:
        return None

    beats: list[tuple[Path, float, int]] = []
    for j, q in enumerate(queries):
        variant = stock.fetch_broll_variants(q, 1, min_duration=2.0,
                                             landscape=landscape, exclude=used)
        beats.append((variant[0], COLD_BEAT_SEC, j))

    bg = work / f"{slug}_cold_bg.mp4"
    _build_background(beats, dims, bg)
    title_png = work / f"{slug}_cold_title.png"
    _coldopen_overlay(voiceover.title, dims).save(title_png)
    _silent_overlay_clip(bg, title_png, out, dims)
    return out


def _coldopen_overlay(title: str, dims: tuple[int, int]) -> Image.Image:
    """Veil + title lớn căn giữa cho cold-open."""
    w, h = dims
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, w, h], fill=VEIL)
    font = slide._font(104 if w > h else 116)
    lines = slide._wrap(draw, title, font, max_width=w - (320 if w > h else 200))
    line_h = font.getbbox("Ag")[3] + 26
    y = (h - line_h * len(lines)) / 2
    for line in lines:
        draw.text((w / 2, y + line_h / 2), line, font=font,
                  fill=slide.FG, anchor="mm")
        y += line_h
    return img


def _silent_overlay_clip(bg: Path, overlay_png: Path, out: Path,
                         dims: tuple[int, int]) -> None:
    """Clip cold-open câm (audio null) = nền động + overlay title, dài bằng nền."""
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(bg), "-loop", "1", "-i", str(overlay_png),
         "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
         "-filter_complex", "[0:v][1:v]overlay=0:0:shortest=1[v]",
         "-map", "[v]", "-map", "2:a",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
         "-shortest", str(out)],
        capture_output=True, check=True,
    )


def _static_overlay(seg, index: int, total: int,
                    dims: tuple[int, int]) -> Image.Image:
    """Overlay tĩnh: veil + terminal card (đoạn code) hoặc veil trơn."""
    w, h = dims
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, w, h], fill=VEIL)

    if seg.code and w <= h:
        cap_font = slide._font(78)
        cap_lines = slide._wrap(draw, seg.caption, cap_font, max_width=w - 140)
        cap_h = cap_font.getbbox("Ag")[3] + 18
        y = 360
        for line in cap_lines:
            draw.text((w / 2, y), line, font=cap_font,
                      fill=slide.DANGER if seg.danger else slide.FG, anchor="ma")
            y += cap_h
        slide._draw_terminal(img, draw, seg.code, top=y + 90, danger=seg.danger)
    return img


def _caption_layout(caption: str, dims: tuple[int, int]):
    """(font, line_h, lines, y0) — bố cục caption ở lower-third."""
    w, h = dims
    landscape = w > h
    img = Image.new("RGBA", (w, h))
    draw = ImageDraw.Draw(img)
    font = slide._font(84 if landscape else 96)
    lines = slide._wrap(draw, caption, font, max_width=w - (360 if landscape else 200))
    line_h = font.getbbox("Ag")[3] + 24
    total_h = line_h * len(lines)
    y0 = int(h * slide.CAPTION_Y) - total_h // 2
    return font, line_h, lines, y0


def _base_overlay(caption: str, dims: tuple[int, int],
                  badge: str | None = None) -> Image.Image:
    """Veil tối + badge + dải nền mờ (kích thước theo caption đầy đủ -> ổn định)."""
    w, h = dims
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, w, h], fill=VEIL)
    if badge:
        draw.text((w / 2, h * 0.12), badge,
                  font=slide._font(48 if w > h else 56),
                  fill=slide.ACCENT, anchor="mm")

    _, line_h, lines, y0 = _caption_layout(caption, dims)
    total_h = line_h * len(lines)
    pad = 36
    draw.rounded_rectangle(
        [80, y0 - pad, w - 80, y0 + total_h + pad],
        radius=28, fill=slide.CAPTION_BAND,
    )
    return img


def _text_overlay(text: str, full_caption: str, dims: tuple[int, int],
                  *, danger: bool = False) -> Image.Image:
    """Overlay trong suốt chỉ chứa chữ (đã tích luỹ), đặt theo bố cục caption đầy đủ."""
    w, h = dims
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    font, line_h, _, y0 = _caption_layout(full_caption, dims)
    lines = slide._wrap(draw, text, font, max_width=w - (360 if w > h else 200))
    y = y0
    for line in lines:
        draw.text((w / 2, y + line_h / 2), line, font=font,
                  fill=slide.DANGER if danger else slide.FG, anchor="mm")
        y += line_h
    return img


def _thumbnail(title: str, dims: tuple[int, int]) -> Image.Image:
    """Thumbnail: dọc dùng helper compose; ngang vẽ gradient + tiêu đề căn giữa."""
    w, h = dims
    if h >= w:
        return slide._caption_image(title, index=0, total=1, thumbnail=True, danger=True)

    img = Image.new("RGB", (w, h), slide.BG_TOP)
    px = img.load()
    top, bottom = slide.BG_TOP, slide.BG_BOTTOM
    for y in range(h):
        t = y / h
        row = tuple(int(top[c] + (bottom[c] - top[c]) * t) for c in range(3))
        for x in range(w):
            px[x, y] = row
    draw = ImageDraw.Draw(img)
    font = slide._font(110)
    lines = slide._wrap(draw, title, font, max_width=w - 240)
    line_h = font.getbbox("Ag")[3] + 30
    y = (h - line_h * len(lines)) / 2
    for line in lines:
        draw.text((w / 2, y + line_h / 2), line, font=font, fill=slide.DANGER, anchor="mm")
        y += line_h
    return img


def _broll_clip(bg: Path, overlay_png: Path, audio: Path, out: Path,
                dims: tuple[int, int]) -> None:
    """Nền B-roll (loop+crop W:H) + overlay PNG + audio, cắt theo độ dài audio."""
    w, h = dims
    subprocess.run(
        ["ffmpeg", "-y",
         "-stream_loop", "-1", "-i", str(bg),
         "-loop", "1", "-i", str(overlay_png),
         "-i", str(audio),
         "-filter_complex",
         f"[0:v]scale={w}:{h}:force_original_aspect_ratio=increase,"
         f"crop={w}:{h},setsar=1,fps=30[bg];[bg][1:v]overlay=0:0[v]",
         "-map", "[v]", "-map", "2:a",
         "-c:v", "libx264", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-b:a", "192k", "-shortest", str(out)],
        capture_output=True, check=True,
    )


def _broll_caption_clip(bg: Path, base_png: Path,
                        overlays: list[tuple[Path, float, float]],
                        audio: Path, out: Path, dims: tuple[int, int]) -> None:
    """B-roll + veil/band cố định + chữ hiện dần từng từ (enable theo thời gian)."""
    w, h = dims
    inputs = ["-stream_loop", "-1", "-i", str(bg),
              "-loop", "1", "-i", str(base_png)]
    for png, _, _ in overlays:
        inputs += ["-loop", "1", "-i", str(png)]
    audio_idx = 2 + len(overlays)
    inputs += ["-i", str(audio)]

    chain = [f"[0:v]scale={w}:{h}:force_original_aspect_ratio=increase,"
             f"crop={w}:{h},setsar=1,fps=30[bg]",
             "[bg][1:v]overlay=0:0[v0]"]
    prev = "v0"
    for k, (_, start, end) in enumerate(overlays):
        cur = f"v{k + 1}"
        chain.append(
            f"[{prev}][{k + 2}:v]overlay=0:0:"
            f"enable='between(t,{start:.3f},{end:.3f})'[{cur}]"
        )
        prev = cur

    subprocess.run(
        ["ffmpeg", "-y", *inputs, "-filter_complex", ";".join(chain),
         "-map", f"[{prev}]", "-map", f"{audio_idx}:a",
         "-c:v", "libx264", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-b:a", "192k", "-shortest", str(out)],
        capture_output=True, check=True,
    )


def _fallback_query(title: str) -> str:
    """Từ khoá B-roll mặc định khi segment không khai báo `broll`."""
    return "calm morning routine focus lifestyle"
