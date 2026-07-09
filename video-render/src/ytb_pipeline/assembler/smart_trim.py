"""Smart Trim MVP: pick short, usable segments inside source clips.

This is intentionally heuristic-only: no AI model, no object recognition. It
avoids obvious dead footage first, then gives the renderer concrete in/out
points instead of always taking each clip from the beginning.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, replace
from pathlib import Path

from ytb_pipeline.assembler.models import Assignment, Clip, ClipGroup, ClipSegment
from ytb_pipeline.assembler.profiles import AutoEditProfile
from ytb_pipeline.assembler.render_effects import ffprobe_duration
from ytb_pipeline.ffmpeg_bin import ffmpeg_cmd

_EDGE_GUARD_SEC = 0.5
_MIN_SEGMENT_SEC = 1.2
_WINDOW_STEP_SEC = 1.0
_DEFAULT_SEGMENT_SEC = 3.0
_ANALYSIS_CACHE: dict[tuple[str, int | None, int | None, float], "AnalyzedClip"] = {}


@dataclass(frozen=True)
class AnalyzedClip:
    clip: Clip
    duration: float
    segments: tuple[ClipSegment, ...]


def _cache_key(clip: Clip, segment_duration: float) -> tuple[str, int | None, int | None, float]:
    try:
        stat = clip.path.stat()
        return (str(clip.path), stat.st_size, stat.st_mtime_ns, segment_duration)
    except OSError:
        return (str(clip.path), None, None, segment_duration)


def _detect_ranges(path: Path, filter_name: str, start_pattern: str, end_pattern: str) -> tuple[tuple[float, float], ...]:
    try:
        result = subprocess.run(
            [
                ffmpeg_cmd(),
                "-v",
                "warning",
                "-i",
                str(path),
                "-vf",
                filter_name,
                "-an",
                "-f",
                "null",
                "-",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
    except (subprocess.CalledProcessError, OSError):
        return ()

    starts = [float(match) for match in re.findall(start_pattern, result.stderr)]
    ends = [float(match) for match in re.findall(end_pattern, result.stderr)]
    return tuple((start, ends[index] if index < len(ends) else start) for index, start in enumerate(starts))


def _dead_ranges(path: Path) -> tuple[tuple[float, float], ...]:
    freeze = _detect_ranges(
        path,
        "freezedetect=n=-60dB:d=0.8",
        r"freeze_start:\s*([0-9.]+)",
        r"freeze_end:\s*([0-9.]+)",
    )
    black = _detect_ranges(
        path,
        "blackdetect=d=0.4:pix_th=0.10",
        r"black_start:\s*([0-9.]+)",
        r"black_end:\s*([0-9.]+)",
    )
    return (*freeze, *black)


def _overlap_seconds(start: float, end: float, ranges: tuple[tuple[float, float], ...]) -> float:
    total = 0.0
    for range_start, range_end in ranges:
        total += max(0.0, min(end, range_end) - max(start, range_start))
    return total


def _duration_for_analysis(clip: Clip, fallback: float) -> float:
    if clip.duration_sec is not None:
        return clip.duration_sec
    try:
        return ffprobe_duration(clip.path)
    except (subprocess.CalledProcessError, OSError, ValueError):
        return fallback


def _candidate_windows(duration: float, segment_duration: float) -> tuple[tuple[float, float], ...]:
    if duration <= _MIN_SEGMENT_SEC:
        return ((0.0, max(duration, _MIN_SEGMENT_SEC)),)

    usable_start = min(_EDGE_GUARD_SEC, duration * 0.15)
    usable_end = max(usable_start + _MIN_SEGMENT_SEC, duration - min(_EDGE_GUARD_SEC, duration * 0.15))
    window = min(segment_duration, usable_end - usable_start)
    if window <= _MIN_SEGMENT_SEC:
        return ((usable_start, usable_end),)

    starts: list[float] = []
    current = usable_start
    last_start = usable_end - window
    while current <= last_start + 0.001:
        starts.append(round(current, 3))
        current += _WINDOW_STEP_SEC
    if starts[-1] < last_start:
        starts.append(round(last_start, 3))
    return tuple((start, round(start + window, 3)) for start in starts)


def _clean_range_windows(
    duration: float,
    segment_duration: float,
    dead_ranges: tuple[tuple[float, float], ...],
) -> tuple[tuple[float, float], ...]:
    if not dead_ranges:
        return ()

    guard = min(_EDGE_GUARD_SEC, duration * 0.15)
    cursor = guard
    usable_end = max(cursor, duration - guard)
    windows: list[tuple[float, float]] = []
    for start, end in sorted(dead_ranges):
        clean_start = cursor
        clean_end = min(start, usable_end)
        if clean_end - clean_start >= _MIN_SEGMENT_SEC:
            windows.append((round(clean_start, 3), round(min(clean_start + segment_duration, clean_end), 3)))
        cursor = max(cursor, end)
    if usable_end - cursor >= _MIN_SEGMENT_SEC:
        windows.append((round(cursor, 3), round(min(cursor + segment_duration, usable_end), 3)))
    return tuple(windows)


def _score_window(start: float, end: float, duration: float, dead_ranges: tuple[tuple[float, float], ...]) -> float:
    window_duration = max(_MIN_SEGMENT_SEC, end - start)
    dead_ratio = _overlap_seconds(start, end, dead_ranges) / window_duration
    center = (start + end) / 2
    center_bias = 1.0 - abs((center / max(duration, 0.001)) - 0.5)
    edge_penalty = 0.15 if start <= 0.05 or end >= duration - 0.05 else 0.0
    return max(0.0, 0.65 + center_bias * 0.25 - dead_ratio * 1.2 - edge_penalty)


def analyze_clip(clip: Clip, segment_duration: float = _DEFAULT_SEGMENT_SEC) -> AnalyzedClip:
    segment_duration = max(_MIN_SEGMENT_SEC, segment_duration)
    key = _cache_key(clip, segment_duration)
    cached = _ANALYSIS_CACHE.get(key)
    if cached is not None:
        return cached

    duration = _duration_for_analysis(clip, fallback=segment_duration)
    dead = _dead_ranges(clip.path)
    candidate_ranges = (
        *_candidate_windows(duration, segment_duration),
        *_clean_range_windows(duration, segment_duration, dead),
    )
    candidates = [
        ClipSegment(
            clip=clip,
            start_sec=start,
            end_sec=end,
            score=_score_window(start, end, duration, dead),
        )
        for start, end in candidate_ranges
    ]
    clean_candidates = [
        segment
        for segment in candidates
        if _overlap_seconds(segment.start_sec, segment.end_sec, dead) <= 0.001
    ]
    if clean_candidates:
        candidates = clean_candidates
    candidates.sort(key=lambda segment: segment.score, reverse=True)
    analyzed = AnalyzedClip(clip=clip, duration=duration, segments=tuple(candidates))
    _ANALYSIS_CACHE[key] = analyzed
    return analyzed


def _segment_duration_for_profile(profile: AutoEditProfile) -> float:
    if profile.name == "tiktok_shop_fast":
        return 2.4
    if profile.name in {"product_review_smooth", "beauty_skincare", "voiceover_catalog"}:
        return 4.0
    if profile.name in {"fashion_tryon", "food_demo"}:
        return 3.0
    return _DEFAULT_SEGMENT_SEC


def _segments_overlap(left: ClipSegment, right: ClipSegment) -> bool:
    return left.start_sec < right.end_sec and right.start_sec < left.end_sec


def _select_non_overlapping_segments(
    candidates: tuple[ClipSegment, ...],
    remaining_duration: float,
) -> tuple[ClipSegment, ...]:
    selected: list[ClipSegment] = []
    remaining = remaining_duration
    for candidate in candidates:
        if remaining <= 0.25:
            break
        if any(_segments_overlap(candidate, existing) for existing in selected):
            continue
        segment = candidate
        if segment.duration_sec > remaining and remaining >= _MIN_SEGMENT_SEC:
            segment = replace(segment, end_sec=segment.start_sec + remaining)
        if segment.duration_sec < _MIN_SEGMENT_SEC:
            continue
        selected.append(segment)
        remaining -= segment.duration_sec
    return tuple(sorted(selected, key=lambda segment: segment.start_sec))


def _select_segments_for_group(
    group: ClipGroup,
    target_duration: float,
    profile: AutoEditProfile,
) -> tuple[ClipSegment, ...]:
    if not group.clips:
        return ()

    desired = max(_MIN_SEGMENT_SEC, target_duration)
    selected: list[ClipSegment] = []
    total = 0.0
    for clip in group.clips:
        analyzed = analyze_clip(clip, _segment_duration_for_profile(profile))
        if not analyzed.segments:
            continue
        remaining = desired - total
        if remaining <= 0.25:
            break
        clip_segments = _select_non_overlapping_segments(analyzed.segments, remaining)
        selected.extend(clip_segments)
        total += sum(segment.duration_sec for segment in clip_segments)

    return tuple(selected)


def enrich_assignment_with_smart_trim(
    assignment: Assignment,
    scene_durations: tuple[float, ...],
    profile: AutoEditProfile,
) -> tuple[Assignment, tuple[float, ...]]:
    enriched_groups: list[ClipGroup] = []
    enriched_durations: list[float] = []
    for group, target_duration in zip(assignment.groups, scene_durations, strict=True):
        segments = _select_segments_for_group(group, target_duration, profile)
        if segments:
            enriched_groups.append(replace(group, segments=segments))
            enriched_durations.append(sum(segment.duration_sec for segment in segments))
        else:
            enriched_groups.append(group)
            enriched_durations.append(target_duration)
    return replace(assignment, groups=tuple(enriched_groups)), tuple(enriched_durations)
