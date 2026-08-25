"""Local character-story renderer driven entirely by profile assets.

The shared pipeline still owns sequencing, checkpoints, QA, and publishing.
This module only implements the RenderProvider port for profiles whose visual
language is a cast of recurring characters rather than stock B-roll.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import textwrap
from dataclasses import replace
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from ..config.settings import settings
from ..content_profiles import ContentProfile, load_content_profile
from ..pkg.models import RenderedVideo, Segment, Voiceover
from ..voiceover.tts import _slugify

PORTRAIT = (1080, 1920)
LANDSCAPE = (1920, 1080)
_FONT_PATHS = (
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/Library/Fonts/Arial.ttf",
)


def render_story_video(voiceover: Voiceover, output_dir: Path) -> RenderedVideo:
    """Compose real per-segment audio over local profile illustrations."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("Story renderer cần ffmpeg trong PATH.")
    profile = load_content_profile(voiceover.content_profile_id)
    if profile.providers.render != "story":
        raise ValueError(
            f"Profile '{profile.profile_id}' không chọn story renderer."
        )
    if voiceover.content_profile_version != profile.version:
        raise ValueError(
            f"Script dùng profile version {voiceover.content_profile_version!r}, "
            f"renderer đang có {profile.version!r}."
        )
    if not voiceover.segments:
        raise ValueError("Story renderer cần ít nhất một segment.")

    output_dir.mkdir(parents=True, exist_ok=True)
    dims = LANDSCAPE if settings.orientation == "landscape" else PORTRAIT
    slug = _slugify(voiceover.project_id or voiceover.title) or "story"
    video_path = output_dir / f"{slug}.mp4"
    thumbnail_path = output_dir / f"{slug}_thumb.jpg"

    with tempfile.TemporaryDirectory(prefix=f"{slug}-story-", dir=output_dir) as raw_work:
        work = Path(raw_work)
        clips: list[Path] = []
        first_frame: Path | None = None
        for index, segment in enumerate(voiceover.segments):
            frame = work / f"frame-{index:03d}.jpg"
            _story_frame(segment, profile, dims).save(frame, quality=92)
            if first_frame is None:
                first_frame = frame
            clip = work / f"clip-{index:03d}.mp4"
            gap = (
                profile.render.inter_segment_gap_sec
                if index < len(voiceover.segments) - 1 else 0.0
            )
            _render_clip(ffmpeg, frame, segment, clip, gap=gap)
            clips.append(clip)
        _compose_clips(
            ffmpeg,
            clips,
            video_path,
            work,
            durations=[
                segment.duration_sec
                + (profile.render.inter_segment_gap_sec if i < len(clips) - 1 else 0.0)
                for i, segment in enumerate(voiceover.segments)
            ],
            overlap=profile.render.transition_overlap_sec,
        )
        if first_frame is None:
            raise ValueError("Story renderer không sinh được frame đầu.")
        _thumbnail(first_frame, voiceover.title, dims).save(
            thumbnail_path, quality=92
        )

    return replace(
        RenderedVideo(**vars(voiceover)),
        video_path=video_path,
        thumbnail_path=thumbnail_path,
    )


def expected_story_duration_sec(
    profile: ContentProfile, audio_durations: list[float]
) -> float:
    """Expected viewer timeline from the same profile timing contract."""
    if not audio_durations:
        return 0.0
    joins = len(audio_durations) - 1
    return (
        sum(audio_durations)
        + joins * profile.render.inter_segment_gap_sec
        - joins * profile.render.transition_overlap_sec
    )


def _asset_path(profile: ContentProfile, relative: str) -> Path:
    return profile.visual_asset_path(relative)


def _story_frame(
    segment: Segment, profile: ContentProfile, dims: tuple[int, int]
) -> Image.Image:
    source = Image.open(_asset_path(profile, segment.visual_asset)).convert("RGB")
    background = ImageOps.fit(source, dims, method=Image.Resampling.LANCZOS)
    background = background.filter(ImageFilter.GaussianBlur(radius=22))
    background = Image.blend(background, Image.new("RGB", dims, "#111218"), 0.30)
    foreground = ImageOps.contain(
        source,
        (int(dims[0] * 0.94), int(dims[1] * (0.72 if dims == PORTRAIT else 0.88))),
        method=Image.Resampling.LANCZOS,
    )
    x = (dims[0] - foreground.width) // 2
    y = int(dims[1] * 0.04)
    background.paste(foreground, (x, y))

    if profile.render.show_captions:
        draw = ImageDraw.Draw(background, "RGBA")
        band_top = int(dims[1] * (0.75 if dims == PORTRAIT else 0.72))
        draw.rounded_rectangle(
            (int(dims[0] * 0.055), band_top, int(dims[0] * 0.945), int(dims[1] * 0.95)),
            radius=32,
            fill=(8, 10, 16, 218),
        )
        label_font = _font(38 if dims == PORTRAIT else 32, bold=True)
        body_font = _font(48 if dims == PORTRAIT else 38)
        speaker = (segment.speaker_id or "narrator").upper()
        draw.text(
            (int(dims[0] * 0.09), band_top + 28), speaker,
            font=label_font, fill=(232, 179, 108, 255),
        )
        caption = segment.caption.strip() or segment.narration.strip()
        wrapped = "\n".join(textwrap.wrap(caption, width=34 if dims == PORTRAIT else 58)[:3])
        draw.multiline_text(
            (int(dims[0] * 0.09), band_top + 86), wrapped,
            font=body_font, fill=(250, 248, 242, 255), spacing=12,
        )
    return background


def _render_clip(
    ffmpeg: str, frame: Path, segment: Segment, output: Path, *, gap: float
) -> None:
    if segment.audio_path is None or not Path(segment.audio_path).is_file():
        raise FileNotFoundError("Story segment thiếu audio_path thật.")
    if segment.duration_sec <= 0:
        raise ValueError("Story segment cần duration_sec đo từ audio.")
    duration = segment.duration_sec + gap
    command = [
        ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
        "-loop", "1", "-framerate", "30", "-i", str(frame),
        "-i", str(segment.audio_path),
    ]
    if gap > 0:
        command.extend(("-af", f"apad=pad_dur={gap:.3f}"))
    command.extend((
        "-t", f"{duration:.3f}", "-c:v", "libx264", "-preset", "veryfast",
        "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart", str(output),
    ))
    subprocess.run(command, check=True)


def _compose_clips(
    ffmpeg: str,
    clips: list[Path],
    output: Path,
    work: Path,
    *,
    durations: list[float],
    overlap: float,
) -> None:
    if len(clips) == 1 or overlap <= 0:
        _concat_clips(ffmpeg, clips, output, work)
        return
    if overlap >= min(durations):
        raise ValueError("Story transition_overlap_sec phải ngắn hơn mọi segment clip.")

    command = [ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-y"]
    for clip in clips:
        command.extend(("-i", str(clip)))
    filters: list[str] = []
    for index in range(len(clips)):
        filters.append(f"[{index}:v]settb=AVTB,setpts=PTS-STARTPTS[v{index}]")
        filters.append(f"[{index}:a]aresample=async=1:first_pts=0[a{index}]")
    video_label = "v0"
    audio_label = "a0"
    cumulative = durations[0]
    for index in range(1, len(clips)):
        next_video = f"vx{index}"
        next_audio = f"ax{index}"
        offset = cumulative - overlap
        filters.append(
            f"[{video_label}][v{index}]xfade=transition=fade:duration={overlap:.3f}:offset={offset:.3f}[{next_video}]"
        )
        filters.append(
            f"[{audio_label}][a{index}]acrossfade=d={overlap:.3f}:c1=tri:c2=tri[{next_audio}]"
        )
        video_label = next_video
        audio_label = next_audio
        cumulative += durations[index] - overlap
    command.extend((
        "-filter_complex", ";".join(filters),
        "-map", f"[{video_label}]", "-map", f"[{audio_label}]",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart", str(output),
    ))
    subprocess.run(command, check=True)


def _concat_clips(ffmpeg: str, clips: list[Path], output: Path, work: Path) -> None:
    manifest = work / "clips.ffconcat"
    lines = ["ffconcat version 1.0"]
    for clip in clips:
        escaped = str(clip.resolve()).replace("'", "'\\''")
        lines.append(f"file '{escaped}'")
    manifest.write_text("\n".join(lines) + "\n", encoding="utf-8")
    subprocess.run([
        ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "concat", "-safe", "0", "-i", str(manifest),
        "-c", "copy", "-movflags", "+faststart", str(output),
    ], check=True)


def _thumbnail(frame: Path, title: str, dims: tuple[int, int]) -> Image.Image:
    image = Image.open(frame).convert("RGB")
    draw = ImageDraw.Draw(image, "RGBA")
    top = int(dims[1] * 0.08)
    draw.rounded_rectangle(
        (int(dims[0] * 0.06), top, int(dims[0] * 0.94), top + int(dims[1] * 0.18)),
        radius=34, fill=(8, 10, 16, 220),
    )
    text = "\n".join(textwrap.wrap(title, width=24)[:2])
    draw.multiline_text(
        (dims[0] // 2, top + int(dims[1] * 0.09)), text,
        font=_font(70 if dims == PORTRAIT else 56, bold=True),
        fill=(255, 248, 232, 255), anchor="mm", align="center", spacing=10,
    )
    return image


def _font(size: int, *, bold: bool = False):
    paths = list(_FONT_PATHS)
    if bold:
        paths = [paths[1], paths[0], paths[2]]
    for path in paths:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()
