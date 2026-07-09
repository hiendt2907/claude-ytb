"""Unit tests for Smart Trim segment selection."""

from __future__ import annotations

import subprocess
from pathlib import Path

from ytb_pipeline.assembler.models import Assignment, Clip, ClipGroup
from ytb_pipeline.assembler.profiles import resolve_profile
from ytb_pipeline.assembler.smart_trim import (
    analyze_clip,
    enrich_assignment_with_smart_trim,
)


class _RunResult:
    def __init__(self, stdout: str = "", stderr: str = "") -> None:
        self.stdout = stdout
        self.stderr = stderr


def _clip(path: Path, scene_index: int = 0) -> Clip:
    return Clip(path=path, scene_index=scene_index, sub_index=(scene_index + 1, 1))


def test_analyze_clip_creates_ranked_segments_and_avoids_dead_edges(
    monkeypatch, tmp_path: Path
) -> None:
    clip = _clip(tmp_path / "1.1.mp4")

    def fake_run(cmd, capture_output, text, check):  # noqa: ANN001
        if cmd[0] == "ffprobe":
            return _RunResult(stdout="12.0\n")
        return _RunResult(stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    analyzed = analyze_clip(clip, segment_duration=4.0)

    assert analyzed.clip == clip
    assert analyzed.duration == 12.0
    assert analyzed.segments
    assert analyzed.segments[0].start_sec >= 0.5
    assert analyzed.segments[0].end_sec <= 11.5
    assert analyzed.segments[0].score >= analyzed.segments[-1].score


def test_analyze_clip_penalizes_freeze_and_black_windows(monkeypatch, tmp_path: Path) -> None:
    clip = _clip(tmp_path / "1.1.mp4")

    def fake_run(cmd, capture_output, text, check):  # noqa: ANN001
        if cmd[0] == "ffprobe":
            return _RunResult(stdout="12.0\n")
        if any("freezedetect" in part for part in cmd):
            return _RunResult(
                stderr="[freezedetect] freeze_start: 4.0\n"
                "[freezedetect] freeze_duration: 2.0\n"
                "[freezedetect] freeze_end: 6.0\n"
            )
        if any("blackdetect" in part for part in cmd):
            return _RunResult(stderr="[blackdetect] black_start: 8.0 black_end: 10.0\n")
        return _RunResult(stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    analyzed = analyze_clip(clip, segment_duration=4.0)

    best = analyzed.segments[0]
    assert not (best.start_sec < 6.0 and best.end_sec > 4.0)
    assert not (best.start_sec < 10.0 and best.end_sec > 8.0)


def test_enrich_assignment_selects_segments_instead_of_whole_clips(
    monkeypatch, tmp_path: Path
) -> None:
    clip_a = _clip(tmp_path / "1.1.mp4")
    clip_b = Clip(path=tmp_path / "1.2.mp4", scene_index=0, sub_index=(1, 2))
    assignment = Assignment(
        output_index=0,
        groups=(ClipGroup(scene_index=0, clips=(clip_a, clip_b)),),
    )

    def fake_run(cmd, capture_output, text, check):  # noqa: ANN001
        if cmd[0] == "ffprobe":
            return _RunResult(stdout="10.0\n")
        return _RunResult(stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    enriched, durations = enrich_assignment_with_smart_trim(
        assignment,
        scene_durations=(20.0,),
        profile=resolve_profile("tiktok_shop_fast"),
    )

    assert durations[0] < 20.0
    assert enriched.groups[0].segments
    for segment in enriched.groups[0].segments:
        assert segment.end_sec > segment.start_sec
        assert segment.end_sec - segment.start_sec <= 4.0


def test_enrich_assignment_can_select_multiple_non_overlapping_segments_from_one_clip(
    monkeypatch, tmp_path: Path
) -> None:
    clip = _clip(tmp_path / "1.1.mp4")
    assignment = Assignment(
        output_index=0,
        groups=(ClipGroup(scene_index=0, clips=(clip,)),),
    )

    def fake_run(cmd, capture_output, text, check):  # noqa: ANN001
        if cmd[0] == "ffprobe":
            return _RunResult(stdout="14.0\n")
        return _RunResult(stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    enriched, durations = enrich_assignment_with_smart_trim(
        assignment,
        scene_durations=(9.0,),
        profile=resolve_profile("product_review_smooth"),
    )

    segments = enriched.groups[0].segments
    assert len(segments) >= 2
    assert sum(segment.duration_sec for segment in segments) == durations[0]
    assert durations[0] > 4.0
    ordered = sorted(segments, key=lambda segment: segment.start_sec)
    for previous, current in zip(ordered, ordered[1:], strict=False):
        assert previous.end_sec <= current.start_sec
