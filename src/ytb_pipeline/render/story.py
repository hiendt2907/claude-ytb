"""Local character-story renderer driven entirely by profile assets.

The shared pipeline still owns sequencing, checkpoints, QA, and publishing.
This module only implements the RenderProvider port for profiles whose visual
language is a cast of recurring characters rather than stock B-roll.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import textwrap
from dataclasses import replace
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

import hashlib

from ..config.settings import settings
from ..content_profiles import ContentProfile, load_content_profile
from ..pkg.models import RenderedVideo, Segment, Voiceover
from ..voiceover.tts import _slugify
from .timeline import build_story_timeline

STORY_FPS = 30

# Kích thước sinh ảnh — kích thước SDXL native đã kiểm chứng cho nhận dạng ổn
# định, KHÔNG phải kích thước render cuối (1920x1080/1080x1920). _story_frame
# đã fit/crop bất kỳ ảnh nguồn nào vào khung cuối, nên không cần khớp.

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
    profile = load_content_profile(
        voiceover.content_profile_id, version=voiceover.content_profile_version or None,
    )
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

    # Timeline is the authoritative, validated execution plan derived from
    # narration (Segment.duration_sec, already measured by TTS) — built and
    # checked BEFORE any ffmpeg call, not reconstructed inline while encoding.
    # See render/timeline.py for the invariants this construction enforces.
    timeline = build_story_timeline(
        voiceover, profile, fps=STORY_FPS, width=dims[0], height=dims[1],
    )
    timeline.write_json(output_dir / f"{slug}_timeline.json")

    with tempfile.TemporaryDirectory(prefix=f"{slug}-story-", dir=output_dir) as raw_work:
        work = Path(raw_work)
        # Caption cards are a VIDEO-ONLY presentation detail inside a section,
        # never a scene transition and never a reason to touch the section's
        # audio. Slicing the original TTS audio into one re-encoded piece per
        # card (the previous design) let each slice's AAC re-encode round
        # independently from the (also independently rounding) video track,
        # so the two streams drifted apart by different amounts — a real
        # Long ended with a video stream 1.1s shorter than its audio stream.
        # The fix: build each section's video track from frame-EXACT card
        # clips (no drift possible, see `_frame_counts`), mux the section's
        # REAL, UNSLICED audio file onto it exactly once, and let
        # `_compose_clips` crossfade the video timeline and cross-fade the
        # audio timeline as two independently measured tracks.
        section_clips: list[Path] = []
        video_durations: list[float] = []
        audio_durations: list[float] = []
        first_frame: Path | None = None
        for index, segment in enumerate(voiceover.segments):
            if segment.audio_path is None or not Path(segment.audio_path).is_file():
                raise FileNotFoundError("Story segment thiếu audio_path thật.")
            # Read from the already-validated Timeline instead of
            # recomputing the index-boundary condition here.
            gap = (
                timeline.transitions[index].gap_sec
                if index < len(timeline.transitions) else 0.0
            )
            # Một section Long dài ~450 ký tự: chia thành nhiều thẻ caption thay
            # vì để một tấm chữ đứng yên suốt cả section.
            cards = _segment_cards(segment, profile, dims)
            # Resolve MỘT lần cho cả section: mọi thẻ caption của cùng section
            # dùng chung một tấm nền, và asset cố định/generate+cache đều đắt
            # hơn việc gọi lại nhiều lần trong vòng lặp thẻ.
            image_path = resolve_scene_image(segment, profile, dims)
            frame_counts = _frame_counts([length for (_, _, length) in cards], fps=30)
            if frame_counts:
                frame_counts[-1] += round(gap * 30)
            card_clips: list[Path] = []
            for card_index, ((text, _seek, _length), frames) in enumerate(zip(cards, frame_counts)):
                frame = work / f"frame-{index:03d}-{card_index:02d}.jpg"
                _story_frame(segment, profile, dims, image_path, caption=text).save(frame, quality=92)
                if first_frame is None:
                    first_frame = frame
                clip = work / f"clip-{index:03d}-{card_index:02d}.mp4"
                _render_video_card(ffmpeg, frame, clip, frames=frames)
                card_clips.append(clip)
            if len(card_clips) == 1:
                section_video = card_clips[0]
            else:
                section_video = work / f"section-{index:03d}-video.mp4"
                _concat_clips(ffmpeg, card_clips, section_video, work)
            section_audio = work / f"section-{index:03d}-audio.m4a"
            _mux_section_audio(ffmpeg, Path(segment.audio_path), section_audio, gap=gap)
            section_clip = work / f"section-{index:03d}.mp4"
            _mux_video_audio(ffmpeg, section_video, section_audio, section_clip)
            # The video track is frame-exact by construction, but the AAC
            # encode of the section's real audio can still land a fraction of
            # a codec frame away from that same nominal length. Left alone,
            # that per-section fraction is consistently signed (AAC frames are
            # ~21-23ms; padding/encoding tends to round the SAME direction
            # every time) and compounds across many section joins — a real
            # 20-section Long drifted 261ms this way even though no single
            # section was ever more than ~15ms off. Reconciling within each
            # section keeps the bias from ever accumulating.
            section_clip = _reconcile_section_streams(ffmpeg, section_clip, work, tag=f"{index:03d}")
            section_clips.append(section_clip)
            video_durations.append(_video_duration(section_clip))
            audio_durations.append(_audio_duration(section_clip))
        # Structural guard, right before the final composite encode: the
        # number of REAL section clips built must match the Timeline's own
        # plan exactly. This is the same class of check `Timeline.__post_init__`
        # already enforces on `transitions` vs. clip count — repeated here
        # against what the render loop actually produced, so a future
        # regression in the loop above (e.g. one clip per caption CARD
        # again, not per section) fails loudly here instead of silently
        # cross-fading the wrong number of boundaries.
        if len(section_clips) != len(timeline.video_clips):
            raise ValueError(
                f"Story renderer dựng {len(section_clips)} section clip nhưng "
                f"Timeline khai {len(timeline.video_clips)} — không được compose."
            )
        _compose_clips(
            ffmpeg,
            section_clips,
            video_path,
            work,
            video_durations=video_durations,
            audio_durations=audio_durations,
            overlap=profile.render.transition_overlap_sec,
        )
        # Each section's own video/audio streams matched within one frame
        # (see `_reconcile_section_streams` above), but `xfade`/`acrossfade`
        # snap their offsets to their own codec's frame grid at EVERY
        # transition — a real 20-section Long had 19 crossfades and still
        # drifted 261ms even though no individual section was ever more than
        # 16ms off, because the video (30fps) and audio (AAC ~21-23ms frames)
        # grids round independently at every join. Reconciling once more on
        # the fully composed output closes whatever the transition chain
        # itself introduced.
        reconciled = _reconcile_section_streams(ffmpeg, video_path, work, tag="final")
        if reconciled != video_path:
            shutil.move(str(reconciled), str(video_path))
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



# Bảng màu thoại: danh tính người nói được truyền bằng MÀU, không bằng một nhãn
# viết hoa kiểu kịch bản phim. Narrator giữ trắng ngà; các nhân vật lấy màu theo
# thứ tự khai trong voice_cast nên thêm nhân vật là việc của profile, không phải
# của renderer.
_NARRATOR_COLOUR = (247, 244, 236)
_CAST_COLOURS = (
    (137, 214, 232),   # xanh băng
    (240, 196, 132),   # hổ phách
    (176, 222, 168),   # xanh lá nhạt
    (232, 168, 190),   # hồng phấn
)
_SENTENCE_END = re.compile(r"(?<=[.!?…])\s+")


def speaker_colour(profile: ContentProfile, speaker_id: str) -> tuple[int, int, int]:
    """Màu chữ của một người nói; người lạ dùng màu narrator."""
    narrator_id = profile.editorial_contract.narration_speaker_id
    normalised = (speaker_id or narrator_id).strip().lower()
    cast = [name for name in profile.voice_cast if name != narrator_id]
    if normalised in cast:
        return _CAST_COLOURS[cast.index(normalised) % len(_CAST_COLOURS)]
    return _NARRATOR_COLOUR


def caption_lines(narration: str, *, max_chars: int) -> list[str]:
    """Chia lời đọc thành các thẻ caption, mỗi thẻ là một câu đọc được hết.

    Một section của Long dài ~450 ký tự — không thể là MỘT tấm chữ đứng yên
    suốt hai mươi lăm giây. Cắt theo câu, câu nào dài quá thì xuống dòng tiếp,
    không bao giờ bỏ chữ.
    """
    text = " ".join((narration or "").split())
    if not text:
        return []
    lines: list[str] = []
    for sentence in _SENTENCE_END.split(text):
        sentence = sentence.strip()
        if not sentence:
            continue
        if len(sentence) <= max_chars:
            lines.append(sentence)
            continue
        lines.extend(textwrap.wrap(sentence, width=max_chars, break_long_words=False))
    return [line for line in lines if line]


def line_durations(lines: list[str], *, total_sec: float) -> list[float]:
    """Chia thời lượng đo được của segment cho từng thẻ theo số ký tự.

    Xấp xỉ, không phải căn theo từng từ: tốc độ đọc trong một segment gần như
    không đổi, và mọi thẻ cộng lại LUÔN đúng bằng audio thật nên hình không bao
    giờ trôi khỏi tiếng.
    """
    if not lines or total_sec <= 0:
        return []
    weights = [max(1, len(line)) for line in lines]
    total_weight = sum(weights)
    durations = [total_sec * weight / total_weight for weight in weights]
    # Bù sai số dồn vào thẻ cuối để tổng khớp tuyệt đối.
    durations[-1] = total_sec - sum(durations[:-1])
    return durations


def _merge_short_lines(lines: list[str], *, total_sec: float, min_sec: float) -> list[str]:
    """Merge a caption line whose proportional slice of `total_sec` would be
    at/under `min_sec` into a neighbour.

    `textwrap.wrap` inside `caption_lines` can leave a trailing chunk of a
    long sentence just a few characters long (e.g. "đó?"). `line_durations`
    weights purely by character count, so that chunk's share of the audio can
    fall under the profile's own `transition_overlap_sec` — a real Long
    render crashed in `_compose_clips` ('Story transition_overlap_sec phải
    ngắn hơn mọi segment clip.') on exactly this. A per-card floor derived
    from the profile's own overlap, rather than a fixed literal, keeps this
    correct at any `transition_overlap_sec` a profile declares.
    """
    if min_sec <= 0 or len(lines) <= 1:
        return lines
    merged = list(lines)
    while len(merged) > 1:
        durations = line_durations(merged, total_sec=total_sec)
        short_index = next((i for i, d in enumerate(durations) if d <= min_sec), None)
        if short_index is None:
            break
        target = short_index - 1 if short_index > 0 else short_index + 1
        first, second = sorted((short_index, target))
        merged[first] = f"{merged[first]} {merged[second]}".strip()
        del merged[second]
    return merged


def _asset_path(profile: ContentProfile, relative: str) -> Path:
    return profile.visual_asset_path(relative)


_SDXL_GENERATION_DIMS = {LANDSCAPE: (1344, 768), PORTRAIT: (832, 1216)}


def _generation_cache_key(
    segment: Segment, profile: ContentProfile, dims: tuple[int, int]
) -> str:
    """Nội dung nào làm ảnh khác đi phải làm hash khác đi — không hơn không kém.

    profile_fingerprint đã bao gồm ảnh neo nhận dạng + duo reference, nên đổi
    ảnh neo tự động invalidate cache mà không cần liệt kê lại ở đây.
    """
    vg = profile.visual_generation
    payload = "\x1f".join((
        profile.profile_id, profile.version,
        f"{dims[0]}x{dims[1]}",
        ",".join(sorted(segment.scene_characters)),
        segment.visual_intent.strip(),
        vg.style_prompt, vg.negative_prompt,
        str(vg.steps), str(vg.cfg), str(vg.solo_weight), str(vg.duo_weight), str(vg.duo_denoise),
    ))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def resolve_scene_image(
    segment: Segment, profile: ContentProfile, dims: tuple[int, int],
    *, cache_dir: Path | None = None, provider=None,
) -> Path:
    """Ảnh cho MỘT section: asset cố định nếu có, không thì auto-generate + cache.

    Fail-closed theo chủ đích: nếu ComfyUI không phản hồi, lỗi của provider
    (`ProviderUnavailableError`) được để nguyên bay lên — KHÔNG âm thầm rơi về
    asset khác. Cache là write-through: file chỉ xuất hiện sau khi provider
    trả về THÀNH CÔNG, nên một lần fail không để lại file rỗng/hỏng.
    """
    if segment.visual_asset:
        return _asset_path(profile, segment.visual_asset)

    vg = profile.visual_generation
    if vg is None or not vg.enabled:
        raise ValueError(
            f"Section thiếu visual_asset và profile '{profile.profile_id}' "
            "không bật visual_generation — không có ảnh nào để dùng."
        )

    cache_dir = cache_dir or (settings.assets_dir / "generated_visuals" / profile.profile_id)
    cache_dir = Path(cache_dir)
    key = _generation_cache_key(segment, profile, dims)
    cached = cache_dir / f"{key}.png"
    if cached.is_file():
        return cached

    if provider is None:
        from ..providers.registry import get_story_image_provider
        provider = get_story_image_provider()

    gen_width, gen_height = _SDXL_GENERATION_DIMS[dims]
    seed = int(key[:16], 16) % (2**32)
    provider.generate_scene(
        profile,
        characters_present=tuple(segment.scene_characters),
        prompt=segment.visual_intent.strip(),
        width=gen_width, height=gen_height, seed=seed,
        output_path=cached,
    )
    return cached


_CAPTION_MAX_CHARS = {PORTRAIT: 30, LANDSCAPE: 52}
_MIN_CARD_SEC = 1 / 30


def _segment_cards(
    segment: Segment, profile: ContentProfile, dims: tuple[int, int]
) -> list[tuple[str, float, float]]:
    """(text, seek, length) cho từng thẻ caption của một segment.

    Không bật caption, hoặc lời đọc rỗng: một thẻ duy nhất không chữ, dài đúng
    bằng audio — hình vẫn giữ nguyên hành vi cũ.
    """
    if not profile.render.show_captions:
        return [("", 0.0, segment.duration_sec)]
    lines = caption_lines(segment.narration, max_chars=_CAPTION_MAX_CHARS[dims])
    if not lines:
        return [("", 0.0, segment.duration_sec)]
    lines = _merge_short_lines(
        lines,
        total_sec=segment.duration_sec,
        # Even hard-cut profiles need enough time to show every card for one
        # real output frame.  Without this floor, overlap=0 bypassed merging
        # and could create more cards than the frame timeline can represent.
        min_sec=max(profile.render.transition_overlap_sec, _MIN_CARD_SEC),
    )
    lengths = line_durations(lines, total_sec=segment.duration_sec)
    cards: list[tuple[str, float, float]] = []
    seek = 0.0
    for line, length in zip(lines, lengths):
        cards.append((line, seek, length))
        seek += length
    return cards


def _story_frame(
    segment: Segment, profile: ContentProfile, dims: tuple[int, int], image_path: Path,
    *, caption: str = "",
) -> Image.Image:
    source = Image.open(image_path).convert("RGB")
    background = ImageOps.fit(source, dims, method=Image.Resampling.LANCZOS)
    background = background.filter(ImageFilter.GaussianBlur(radius=22))
    background = Image.blend(background, Image.new("RGB", dims, "#111218"), 0.30)
    # Vùng dành cho hình: từ mép trên tới nơi caption bắt đầu. Căn GIỮA vùng đó
    # thay vì dán sát mép trên — một keyframe ngang đặt trong khung dọc từng để
    # lại một mảng mờ trống chiếm gần nửa khung phía dưới.
    top_margin = int(dims[1] * 0.04)
    stage_bottom = int(dims[1] * (0.80 if dims == PORTRAIT else 0.84))
    foreground = ImageOps.contain(
        source,
        (int(dims[0] * 0.94), stage_bottom - top_margin),
        method=Image.Resampling.LANCZOS,
    )
    x = (dims[0] - foreground.width) // 2
    y = top_margin + (stage_bottom - top_margin - foreground.height) // 2
    background.paste(foreground, (x, y))

    text = caption.strip()
    if profile.render.show_captions and text:
        _draw_caption(background, text, speaker_colour(profile, segment.speaker_id), dims)
    return background


def _draw_caption(
    image: Image.Image, text: str, colour: tuple[int, int, int], dims: tuple[int, int]
) -> None:
    """Vẽ đúng câu đang được đọc, căn giữa, viền đậm thay vì tấm nền lớn.

    Bản cũ vẽ `Segment.caption` (mô tả HÌNH) dưới một nhãn NARRATOR viết hoa,
    trên một tấm nền chiếm một phần tư khung: người xem đọc một ghi chú kịch bản
    không liên quan gì đến câu đang nghe. Danh tính người nói giờ nằm ở màu chữ.
    """
    draw = ImageDraw.Draw(image, "RGBA")
    portrait = dims == PORTRAIT
    font = _font(56 if portrait else 46, bold=True)
    wrapped = textwrap.wrap(text, width=_CAPTION_MAX_CHARS[dims], break_long_words=False)
    box = draw.multiline_textbbox((0, 0), "\n".join(wrapped), font=font, spacing=14)
    height = box[3] - box[1]
    baseline = int(dims[1] * (0.86 if portrait else 0.88))
    top = baseline - height

    # Scrim mỏng ôm sát chữ, đủ để chữ sáng đọc được trên nền sáng.
    pad = 26
    draw.rounded_rectangle(
        (int(dims[0] * 0.06), top - pad, int(dims[0] * 0.94), baseline + pad),
        radius=20, fill=(10, 12, 18, 128),
    )
    draw.multiline_text(
        (dims[0] // 2, top), "\n".join(wrapped), font=font, fill=(*colour, 255),
        spacing=14, align="center", anchor="ma",
        stroke_width=3, stroke_fill=(8, 10, 16, 220),
    )


def _frame_counts(lengths: list[float], *, fps: int) -> list[int]:
    """Per-card frame counts with one frame per card and an exact total.

    Rounding each length to the nearest frame independently lets error
    accumulate across many cards (a real 12-card section drifted +76ms this
    way). Cumulative rounding preserves each boundary when every card earns
    at least one frame. For a sub-frame card, allocate the rounded total with
    a one-frame floor instead; this retains the exact section total without
    silently lengthening its visual timeline.
    """
    if fps <= 0:
        raise ValueError("Story renderer cần FPS dương.")
    if any(length <= 0 for length in lengths):
        raise ValueError("Mỗi caption card phải có thời lượng dương.")

    counts: list[int] = []
    cumulative_seconds = 0.0
    previous_frames = 0
    for length in lengths:
        cumulative_seconds += length
        total_frames = round(cumulative_seconds * fps)
        counts.append(total_frames - previous_frames)
        previous_frames = total_frames
    if all(count >= 1 for count in counts):
        return counts

    total_frames = round(sum(lengths) * fps)
    if total_frames < len(lengths):
        raise ValueError(
            "Không đủ frame để hiển thị mỗi caption card; hãy gộp caption ngắn."
        )

    # Start with the indispensable one frame per card, then assign the
    # remaining frames to the card furthest below its ideal frame budget.
    # This only handles the sub-frame edge; ordinary sections retain their
    # cumulative-rounding boundaries above.
    counts = [1] * len(lengths)
    ideal_frames = [length * fps for length in lengths]
    for _ in range(total_frames - len(counts)):
        chosen = max(
            range(len(counts)),
            key=lambda index: (ideal_frames[index] - counts[index], -index),
        )
        counts[chosen] += 1
    return counts


def _stream_duration(path: Path, stream: str) -> float:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise RuntimeError("Story renderer cần ffprobe trong PATH.")
    output = subprocess.run([
        ffprobe, "-v", "error", "-select_streams", stream,
        "-show_entries", "stream=duration", "-of", "csv=p=0", str(path),
    ], check=True, capture_output=True, text=True).stdout
    return float(output.strip())


def _video_duration(path: Path) -> float:
    return _stream_duration(path, "v:0")


def _audio_duration(path: Path) -> float:
    return _stream_duration(path, "a:0")


def _probe_duration(path: Path) -> float:
    """Real container duration — used by callers that don't care which track."""
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise RuntimeError("Story renderer cần ffprobe trong PATH.")
    output = subprocess.run([
        ffprobe, "-v", "error", "-show_entries", "format=duration",
        "-of", "csv=p=0", str(path),
    ], check=True, capture_output=True, text=True).stdout
    return float(output.strip())


def _render_video_card(ffmpeg: str, frame: Path, output: Path, *, frames: int) -> None:
    """Encode exactly `frames` video frames from a static image — no audio.

    Caption-card timing is purely a visual concern. Giving this clip an
    audio track at all (even a slice of the section's real audio) reintroduces
    the per-card AAC re-encode rounding that used to desync the video and
    audio timelines; a video-only clip with an explicit frame count can never
    drift, because `-frames:v` is exact, not a `-t` cutoff that rounds.
    """
    subprocess.run([
        ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
        "-loop", "1", "-framerate", "30", "-i", str(frame),
        "-frames:v", str(frames), "-r", "30",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(output),
    ], check=True)


def _mux_section_audio(ffmpeg: str, audio_path: Path, output: Path, *, gap: float) -> None:
    """Transcode a section's REAL, UNSLICED audio file exactly once.

    Never re-encoded per caption card: one AAC encode per section instead of
    one per card means at most one small, bounded rounding error per
    section, not one per card compounding across the whole section.
    """
    command = [ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-i", str(audio_path)]
    if gap > 0:
        command.extend(("-af", f"apad=pad_dur={gap:.3f}"))
    command.extend(("-c:a", "aac", "-b:a", "192k", str(output)))
    subprocess.run(command, check=True)


def _mux_video_audio(ffmpeg: str, video_path: Path, audio_path: Path, output: Path) -> None:
    """Combine an already-encoded video-only track and audio-only track.

    Both inputs are already the target codec (h264/aac) — `-c copy` on both
    is a lossless remux, not a re-encode, so it introduces no new rounding.
    """
    subprocess.run([
        ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(video_path), "-i", str(audio_path),
        "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "copy", "-c:a", "copy",
        "-movflags", "+faststart", str(output),
    ], check=True)


_ONE_FRAME_SEC = 1 / 30


def _reconcile_section_streams(ffmpeg: str, clip: Path, work: Path, *, tag: str) -> Path:
    """Align a section's video/audio stream lengths to within one frame.

    The video track is frame-exact; the AAC encode of the section's real
    audio can still land a fraction of a codec frame away from that same
    nominal length, and that fraction is consistently signed rather than
    random — it compounded to 261ms of drift across a real 20-section Long
    even though no single section was ever more than ~15ms off. Never trims
    either stream: if audio outlasts video, the video's LAST FRAME is held
    (not cut) for the difference; if video outlasts audio, audio is padded
    with silence (never shortened).
    """
    video_dur = _video_duration(clip)
    audio_dur = _audio_duration(clip)
    residual = audio_dur - video_dur
    if abs(residual) <= _ONE_FRAME_SEC:
        return clip
    fixed = work / f"section-{tag}-reconciled.mp4"
    if residual > 0:
        subprocess.run([
            ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(clip),
            "-vf", f"tpad=stop_mode=clone:stop_duration={residual:.3f}",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-pix_fmt", "yuv420p", "-c:a", "copy",
            "-movflags", "+faststart", str(fixed),
        ], check=True)
    else:
        subprocess.run([
            ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(clip),
            "-af", f"apad=pad_dur={-residual:.3f}",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart", str(fixed),
        ], check=True)
    return fixed


def _compose_clips(
    ffmpeg: str,
    clips: list[Path],
    output: Path,
    work: Path,
    *,
    video_durations: list[float],
    audio_durations: list[float],
    overlap: float,
) -> None:
    """Crossfade section clips using TWO independent timelines.

    A section clip's video and audio streams are built independently (see
    `render_story_video`) and can end at very slightly different real
    lengths. Sharing one `durations` list for both the video `xfade` offset
    and the audio `acrossfade` offset (the previous design) forced one
    timeline's rounding onto the other's transitions. Each stream now gets
    its own measured duration list and its own cumulative offset.
    """
    if len(clips) == 1 or overlap <= 0:
        _concat_clips(ffmpeg, clips, output, work)
        return
    if overlap >= min(min(video_durations), min(audio_durations)):
        raise ValueError("Story transition_overlap_sec phải ngắn hơn mọi segment clip.")

    command = [ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-y"]
    for clip in clips:
        command.extend(("-i", str(clip)))
    filters: list[str] = []
    for index in range(len(clips)):
        # A section clip that is itself a `-c copy` concat of several caption
        # cards can carry a distorted container-level average frame rate
        # (e.g. 583680/19471 instead of 30/1) even though every source card
        # was encoded at a clean 30fps — `xfade` refuses to blend two inputs
        # whose reported frame rates disagree. `fps=30` normalises the actual
        # frame timing inside the filter graph regardless of what the
        # container metadata says, matching the `-framerate 30` every card
        # was rendered at in `_render_video_card`.
        filters.append(f"[{index}:v]fps=30,settb=AVTB,setpts=PTS-STARTPTS[v{index}]")
        filters.append(f"[{index}:a]aresample=async=1:first_pts=0[a{index}]")
    video_label = "v0"
    audio_label = "a0"
    video_cumulative = video_durations[0]
    audio_cumulative = audio_durations[0]
    for index in range(1, len(clips)):
        next_video = f"vx{index}"
        next_audio = f"ax{index}"
        video_offset = video_cumulative - overlap
        audio_offset = audio_cumulative - overlap
        filters.append(
            f"[{video_label}][v{index}]xfade=transition=fade:duration={overlap:.3f}:offset={video_offset:.3f}[{next_video}]"
        )
        filters.append(
            f"[{audio_label}][a{index}]acrossfade=d={overlap:.3f}:c1=tri:c2=tri[{next_audio}]"
        )
        video_label = next_video
        audio_label = next_audio
        video_cumulative += video_durations[index] - overlap
        audio_cumulative += audio_durations[index] - overlap
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
