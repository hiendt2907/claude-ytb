"""Render 1 output video từ Assignment bằng ffmpeg."""

from __future__ import annotations

import subprocess
import random
from pathlib import Path

from ytb_pipeline.assembler.models import Assignment, Clip, ClipGroup, ClipSegment
from ytb_pipeline.assembler.profiles import AutoEditProfile, resolve_profile
from ytb_pipeline.assembler.render_effects import (
    X264_ENCODE_ARGS,
    effective_xfade_duration,
    fade_out_filter,
    ffprobe_duration,
    ken_burns_filter,
    normalize_video_filter,
    resolve_aspect_ratio,
    scale_filter,
)
from ytb_pipeline.ffmpeg_bin import ffmpeg_cmd


def _render_items(group: ClipGroup) -> tuple[Clip | ClipSegment, ...]:
    return group.segments if group.segments else group.clips


def _item_path(item: Clip | ClipSegment) -> Path:
    return item.clip.path if isinstance(item, ClipSegment) else item.path


def _item_duration(item: Clip | ClipSegment) -> float:
    return item.duration_sec if isinstance(item, ClipSegment) else ffprobe_duration(item.path)


def _item_input_args(item: Clip | ClipSegment) -> list[str]:
    if isinstance(item, ClipSegment):
        return [
            "-ss",
            str(round(item.start_sec, 3)),
            "-t",
            str(round(item.duration_sec, 3)),
            "-i",
            str(item.clip.path),
        ]
    return ["-i", str(item.path)]


def _concat_clips(
    group: ClipGroup,
    out_path: Path,
    target_size: tuple[int, int],
    fit_mode: str,
    edit_profile: AutoEditProfile,
    enable_ken_burns: bool = True,
    transition_seed: int = 0,
) -> Path:
    """Scale, normalize CFR 30fps và nối clip theo đúng thứ tự sub_index."""
    width, height = target_size
    inputs: list[str] = []
    parts: list[str] = []
    durations: list[float] = []
    items = _render_items(group)
    for i, item in enumerate(items):
        inputs += _item_input_args(item)
        durations.append(_item_duration(item))
        filter_chain = scale_filter(width, height, fit_mode)
        if enable_ken_burns:
            tuning = edit_profile.tuning
            motion_filter = ken_burns_filter(
                width,
                height,
                tuning.motion_scale,
                tuning.pan_strength_x,
                tuning.pan_strength_y,
                tuning.pan_speed_x,
                tuning.pan_speed_y,
            )
            filter_chain += f",{motion_filter}"
        filter_chain += f",{normalize_video_filter()}"
        parts.append(f"[{i}:v:0]{filter_chain}[v{i}]")

    running_duration = durations[0]
    current_label = "[v0]"
    if len(items) == 1:
        parts.append(f"{current_label}{normalize_video_filter()}[v]")
    else:
        for i in range(1, len(items)):
            t = effective_xfade_duration(
                running_duration, durations[i], edit_profile.tuning.clip_transition_duration
            )
            offset = running_duration - t
            out_label = f"[cx{i}]"
            transition_style = _transition_style_for_profile(edit_profile, i, seed=transition_seed)
            parts.append(
                f"{current_label}[v{i}]xfade=transition={transition_style}:"
                f"duration={t}:offset={offset}{out_label}"
            )
            current_label = out_label
            running_duration = running_duration + durations[i] - t
        parts.append(f"{current_label}{normalize_video_filter()}[v]")
    concat_filter = ";".join(parts)

    cmd = [
        ffmpeg_cmd(),
        "-y",
        *inputs,
        "-filter_complex",
        concat_filter,
        "-map",
        "[v]",
        "-an",
        *X264_ENCODE_ARGS,
        str(out_path),
    ]
    subprocess.run(cmd, capture_output=True, text=True, check=True)
    return out_path


def _loop_and_trim(in_path: Path, target_duration: float, out_path: Path) -> Path:
    """Loop nếu ngắn hơn và trim khớp target_duration bằng re-encode CFR."""
    cmd = [
        ffmpeg_cmd(),
        "-y",
        "-stream_loop",
        "-1",
        "-i",
        str(in_path),
        "-t",
        str(target_duration),
        "-vf",
        normalize_video_filter(),
        "-an",
        *X264_ENCODE_ARGS,
        str(out_path),
    ]
    subprocess.run(cmd, capture_output=True, text=True, check=True)
    return out_path


_DEFAULT_TRANSITION_DURATION = 0.75
# "dissolve" mượt hơn "fade" phẳng và không phụ thuộc hướng.
_XFADE_TRANSITION_STYLE = "dissolve"


def _transition_style_for_profile(
    edit_profile: AutoEditProfile, transition_index: int, seed: int = 0
) -> str:
    """Chọn transition xfade theo profile, deterministic để output dễ lặp lại."""
    animations = set(edit_profile.animation_names)
    rng = random.Random(f"{edit_profile.name}:{seed}:{transition_index}")
    candidates = [_XFADE_TRANSITION_STYLE]
    if "zoom_blur_cut" in animations and transition_index % 3 == 1:
        candidates.extend(("zoomin", "fadefast"))
    if "swipe_soft" in animations and transition_index % 2 == 1:
        candidates.extend(("smoothleft", "smoothright"))
    if "blur_dissolve" in animations and transition_index % 2 == 1:
        candidates.extend(("fade", "dissolve"))
    if "match_cut" in animations and transition_index % 3 == 2:
        candidates.extend(("fadefast", "fade"))
    return rng.choice(candidates)


def _pairwise_transition_duration(
    durations: tuple[float, ...], index: int, transition_duration: float
) -> float:
    """Clamp transition duration xuống tối đa 40% độ dài mỗi cảnh liền kề, tránh
    xfade offset âm hoặc "ăn" gần hết 1 cảnh ngắn."""
    return effective_xfade_duration(durations[index - 1], durations[index], transition_duration)


def _build_xfade_filter(
    durations: tuple[float, ...],
    transition_duration: float,
    edit_profile: AutoEditProfile,
    transition_seed: int = 0,
) -> tuple[str, str]:
    """Build filter_complex để crossfade video-only bằng xfade."""
    parts: list[str] = [
        f"[{i}:v:0]{normalize_video_filter()}[v{i}]" for i in range(len(durations))
    ]
    running_duration = durations[0]
    current_label = "[v0]"
    for i in range(1, len(durations)):
        t = _pairwise_transition_duration(durations, i, transition_duration)
        offset = running_duration - t
        out_label = f"[x{i}]"
        transition_style = _transition_style_for_profile(edit_profile, i, seed=transition_seed)
        parts.append(
            f"{current_label}[v{i}]xfade=transition={transition_style}:"
            f"duration={t}:offset={offset}{out_label}"
        )
        current_label = out_label
        running_duration = running_duration + durations[i] - t
    parts.append(
        f"{current_label}{normalize_video_filter()},"
        f"{fade_out_filter(running_duration, edit_profile.tuning.end_fade_duration)}[v]"
    )
    return ";".join(parts), "[v]"


def _concat_with_transitions(
    segment_paths: list[Path],
    durations: tuple[float, ...],
    out_path: Path,
    edit_profile: AutoEditProfile,
    transition_duration: float,
    transition_seed: int = 0,
) -> Path:
    """Nối scene segment bằng xfade video-only thay vì hard-cut."""
    if len(segment_paths) == 1:
        cmd = [
            ffmpeg_cmd(),
            "-y",
            "-i",
            str(segment_paths[0]),
            "-vf",
            normalize_video_filter(),
            "-an",
            *X264_ENCODE_ARGS,
            str(out_path),
        ]
        subprocess.run(cmd, capture_output=True, text=True, check=True)
        return out_path

    filter_complex, final_label = _build_xfade_filter(
        durations, transition_duration, edit_profile, transition_seed
    )
    inputs: list[str] = []
    for p in segment_paths:
        inputs += ["-i", str(p)]

    cmd = [
        ffmpeg_cmd(),
        "-y",
        *inputs,
        "-filter_complex",
        filter_complex,
        "-map",
        final_label,
        "-an",
        *X264_ENCODE_ARGS,
        str(out_path),
    ]
    subprocess.run(cmd, capture_output=True, text=True, check=True)
    return out_path
    return out_path


def _render_scene_segment(
    group: ClipGroup,
    target_duration: float,
    out_path: Path,
    target_size: tuple[int, int],
    fit_mode: str,
    edit_profile: AutoEditProfile,
    enable_ken_burns: bool = True,
    transition_seed: int = 0,
) -> Path:
    """Nối clip trong 1 nhóm rồi trim/loop khớp target_duration."""
    if not group.clips:
        raise ValueError(f"Cảnh {group.scene_index} không có clip nào để render")

    raw_path = out_path.with_name(f"{out_path.stem}_raw{out_path.suffix}")
    _concat_clips(
        group,
        raw_path,
        target_size,
        fit_mode,
        edit_profile,
        enable_ken_burns,
        transition_seed + group.scene_index,
    )
    raw_duration = ffprobe_duration(raw_path)
    overlap_budget = max(0, len(_render_items(group)) - 1) * edit_profile.tuning.clip_transition_duration
    if raw_duration < target_duration and target_duration - raw_duration <= overlap_budget + 0.2:
        target_duration = raw_duration
    return _loop_and_trim(raw_path, target_duration, out_path)


# Lề watermark tính theo % kích thước video, tránh dính sát mép khung hình.
_WATERMARK_MARGIN_FRACTION = 0.04

_WATERMARK_OVERLAY_XY: dict[str, str] = {
    "top-left": f"x=W*{_WATERMARK_MARGIN_FRACTION}:y=H*{_WATERMARK_MARGIN_FRACTION}",
    "top-right": f"x=W-w-W*{_WATERMARK_MARGIN_FRACTION}:y=H*{_WATERMARK_MARGIN_FRACTION}",
    "bottom-left": f"x=W*{_WATERMARK_MARGIN_FRACTION}:y=H-h-H*{_WATERMARK_MARGIN_FRACTION}",
    "bottom-right": f"x=W-w-W*{_WATERMARK_MARGIN_FRACTION}:y=H-h-H*{_WATERMARK_MARGIN_FRACTION}",
}


def _escape_ffmpeg_filter_path(path: Path) -> str:
    """Escape path để dùng an toàn bên trong 1 giá trị filter ffmpeg (VD subtitles=filename='...')."""
    return str(path).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


def _ensure_subtitles_filter_available() -> None:
    """Filter `subtitles` cần ffmpeg build kèm libass. Kiểm tra trước, báo lỗi
    rõ ràng thay vì để lỗi parse filter cryptic từ ffmpeg khi thiếu."""
    result = subprocess.run(
        [ffmpeg_cmd(), "-hide_banner", "-filters"], capture_output=True, text=True, check=True
    )
    if "subtitles" not in result.stdout:
        raise RuntimeError(
            "ffmpeg hiện tại không hỗ trợ filter 'subtitles' (thiếu libass lúc build). "
            "Cài lại ffmpeg có libass, VD trên macOS: `brew reinstall ffmpeg` (bản Homebrew "
            "chính thức có kèm libass) hoặc build ffmpeg với --enable-libass."
        )


def _mux_with_overlays(
    concat_path: Path,
    voice_track: Path,
    out_path: Path,
    target_size: tuple[int, int],
    subtitle_path: Path | None,
    watermark_path: Path | None,
    watermark_position: str,
    watermark_scale: float,
) -> Path:
    """Mux voice + overlay trong 1 lệnh ffmpeg."""
    inputs = ["-i", str(concat_path), "-i", str(voice_track)]
    parts: list[str] = []
    current = "[0:v:0]"

    if subtitle_path is not None:
        _ensure_subtitles_filter_available()
        escaped = _escape_ffmpeg_filter_path(subtitle_path)
        parts.append(f"{current}subtitles='{escaped}'[s1]")
        current = "[s1]"

    if watermark_path is not None:
        if watermark_position not in _WATERMARK_OVERLAY_XY:
            raise ValueError(
                f"watermark_position không hợp lệ: {watermark_position!r} "
                f"(dùng {list(_WATERMARK_OVERLAY_XY)})"
            )
        target_width, _ = target_size
        wm_width = max(1, round(target_width * watermark_scale))
        overlay_xy = _WATERMARK_OVERLAY_XY[watermark_position]
        watermark_input_index = 2
        inputs += ["-i", str(watermark_path)]
        parts.append(f"[{watermark_input_index}:v]scale={wm_width}:-1[wm]")
        parts.append(f"{current}[wm]overlay={overlay_xy}[s2]")
        current = "[s2]"

    # Đổi tên video label cuối cùng thành [v], rồi pad voice để voice ngắn
    # không cắt mất phần video đã render trong chế độ clip_length.
    parts[-1] = parts[-1][: -len(current)] + "[v]"
    parts.append("[1:a:0]apad[a]")
    filter_complex = ";".join(parts)

    cmd = [
        ffmpeg_cmd(),
        "-y",
        *inputs,
        "-filter_complex",
        filter_complex,
        "-map",
        "[v]",
        "-map",
        "[a]",
        "-c:a",
        "aac",
        "-shortest",
        str(out_path),
    ]
    subprocess.run(cmd, capture_output=True, text=True, check=True)
    return out_path


def _apply_video_overlays(
    in_path: Path,
    out_path: Path,
    target_size: tuple[int, int],
    subtitle_path: Path | None,
    watermark_path: Path | None,
    watermark_position: str,
    watermark_scale: float,
) -> Path:
    """Áp overlay lên video-only, dùng cho pipeline review/cắt trước khi mux voice."""
    if subtitle_path is None and watermark_path is None:
        return in_path

    inputs = ["-i", str(in_path)]
    parts: list[str] = []
    current = "[0:v:0]"

    if subtitle_path is not None:
        _ensure_subtitles_filter_available()
        escaped = _escape_ffmpeg_filter_path(subtitle_path)
        parts.append(f"{current}subtitles='{escaped}'[s1]")
        current = "[s1]"

    if watermark_path is not None:
        if watermark_position not in _WATERMARK_OVERLAY_XY:
            raise ValueError(
                f"watermark_position không hợp lệ: {watermark_position!r} "
                f"(dùng {list(_WATERMARK_OVERLAY_XY)})"
            )
        target_width, _ = target_size
        wm_width = max(1, round(target_width * watermark_scale))
        overlay_xy = _WATERMARK_OVERLAY_XY[watermark_position]
        watermark_input_index = 1
        inputs += ["-i", str(watermark_path)]
        parts.append(f"[{watermark_input_index}:v]scale={wm_width}:-1[wm]")
        parts.append(f"{current}[wm]overlay={overlay_xy}[s2]")
        current = "[s2]"

    parts[-1] = parts[-1][: -len(current)] + "[v]"
    cmd = [
        ffmpeg_cmd(),
        "-y",
        *inputs,
        "-filter_complex",
        ";".join(parts),
        "-map",
        "[v]",
        "-an",
        *X264_ENCODE_ARGS,
        str(out_path),
    ]
    subprocess.run(cmd, capture_output=True, text=True, check=True)
    return out_path


def render_output(
    assignment: Assignment,
    scene_durations: tuple[float, ...],
    voice_track: Path,
    out_path: Path,
    tmp_dir: Path,
    aspect_ratio: str = "16:9",
    fit_mode: str = "pad",
    watermark_path: Path | None = None,
    watermark_position: str = "bottom-right",
    watermark_scale: float = 0.15,
    subtitle_path: Path | None = None,
    transition_duration: float | None = None,
    enable_ken_burns: bool = True,
    edit_profile: AutoEditProfile | None = None,
    transition_seed: int | None = None,
) -> Path:
    """Render 1 output hoàn chỉnh với xfade dissolve và Ken Burns tuỳ chọn."""
    if len(scene_durations) != len(assignment.groups):
        raise ValueError("scene_durations phải có cùng độ dài với assignment.groups")

    edit_profile = edit_profile if edit_profile is not None else resolve_profile(None)
    transition_duration = (
        transition_duration
        if transition_duration is not None
        else edit_profile.tuning.scene_transition_duration
    )
    target_size = resolve_aspect_ratio(aspect_ratio)
    transition_seed = assignment.output_index if transition_seed is None else transition_seed
    tmp_dir.mkdir(parents=True, exist_ok=True)
    segment_paths = [
        _render_scene_segment(
            group,
            duration,
            tmp_dir / f"scene_{group.scene_index:03d}.mp4",
            target_size,
            fit_mode,
            edit_profile,
            enable_ken_burns,
            transition_seed,
        )
        for group, duration in zip(assignment.groups, scene_durations, strict=True)
    ]

    out_path.parent.mkdir(parents=True, exist_ok=True)

    concat_path = tmp_dir / "concat_video.mp4"
    _concat_with_transitions(
        segment_paths, scene_durations, concat_path, edit_profile, transition_duration, transition_seed
    )

    if watermark_path is not None or subtitle_path is not None:
        return _mux_with_overlays(
            concat_path, voice_track, out_path, target_size,
            subtitle_path, watermark_path, watermark_position, watermark_scale,
        )

    cmd = [
        ffmpeg_cmd(),
        "-y",
        "-i",
        str(concat_path),
        "-i",
        str(voice_track),
        "-filter_complex",
        "[1:a:0]apad[a]",
        "-map",
        "0:v:0",
        "-map",
        "[a]",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-shortest",
        str(out_path),
    ]
    subprocess.run(cmd, capture_output=True, text=True, check=True)
    return out_path


def render_video_only(
    assignment: Assignment,
    scene_durations: tuple[float, ...],
    out_path: Path,
    tmp_dir: Path,
    aspect_ratio: str = "16:9",
    fit_mode: str = "pad",
    watermark_path: Path | None = None,
    watermark_position: str = "bottom-right",
    watermark_scale: float = 0.15,
    subtitle_path: Path | None = None,
    transition_duration: float | None = None,
    enable_ken_burns: bool = True,
    edit_profile: AutoEditProfile | None = None,
    transition_seed: int | None = None,
) -> Path:
    """Render video-only để user review/cắt trước khi mux voice."""
    if len(scene_durations) != len(assignment.groups):
        raise ValueError("scene_durations phải có cùng độ dài với assignment.groups")

    edit_profile = edit_profile if edit_profile is not None else resolve_profile(None)
    transition_duration = (
        transition_duration
        if transition_duration is not None
        else edit_profile.tuning.scene_transition_duration
    )
    target_size = resolve_aspect_ratio(aspect_ratio)
    transition_seed = assignment.output_index if transition_seed is None else transition_seed
    tmp_dir.mkdir(parents=True, exist_ok=True)
    segment_paths = [
        _render_scene_segment(
            group,
            duration,
            tmp_dir / f"scene_{group.scene_index:03d}.mp4",
            target_size,
            fit_mode,
            edit_profile,
            enable_ken_burns,
            transition_seed,
        )
        for group, duration in zip(assignment.groups, scene_durations, strict=True)
    ]

    out_path.parent.mkdir(parents=True, exist_ok=True)
    rendered_path = _concat_with_transitions(
        segment_paths, scene_durations, out_path, edit_profile, transition_duration, transition_seed
    )
    if watermark_path is None and subtitle_path is None:
        return rendered_path
    overlay_path = out_path.with_name(f"{out_path.stem}_overlay{out_path.suffix}")
    _apply_video_overlays(
        rendered_path,
        overlay_path,
        target_size,
        subtitle_path,
        watermark_path,
        watermark_position,
        watermark_scale,
    )
    overlay_path.replace(out_path)
    return out_path
