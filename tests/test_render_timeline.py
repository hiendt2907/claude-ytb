"""Deterministic Timeline domain model — fast unit tests, no ffmpeg/TTS/network.

`Timeline` is the validated execution plan between `Voiceover`/`Segment` and
the story renderer's FFmpeg calls. These tests exercise the domain model in
isolation: construction, invariants, and the historical-class regression
that made `docs/handoffs/2026-08-26-story-renderer-caption-transition-fix-
handoff.md` necessary (162 caption-card transitions instead of 19 real
section transitions, silently dropping 55s of narration).
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from ytb_pipeline.render.timeline import (
    NarrationClip,
    Timeline,
    TimelineError,
    Transition,
    VideoClip,
    build_story_timeline,
)


def _segment(duration_sec: float, *, audio_path: str = "a.wav") -> SimpleNamespace:
    return SimpleNamespace(audio_path=Path(audio_path), duration_sec=duration_sec)


def _voiceover(*durations: float) -> SimpleNamespace:
    return SimpleNamespace(
        segments=tuple(_segment(d, audio_path=f"seg-{i}.wav") for i, d in enumerate(durations))
    )


def _profile(*, gap: float = 0.0, overlap: float = 0.0) -> SimpleNamespace:
    return SimpleNamespace(
        profile_id="fixture", version="1.0.0",
        render=SimpleNamespace(inter_segment_gap_sec=gap, transition_overlap_sec=overlap),
    )


# 1. Normal story timeline ----------------------------------------------------

def test_normal_story_timeline_matches_expected_story_duration_sec():
    from ytb_pipeline.render.story import expected_story_duration_sec

    profile = _profile(gap=0.2, overlap=0.1)
    voiceover = _voiceover(3.0, 4.0, 2.5)

    timeline = build_story_timeline(voiceover, profile, fps=30, width=1920, height=1080)

    assert len(timeline.video_clips) == 3
    assert len(timeline.narration_clips) == 3
    assert len(timeline.transitions) == 2
    assert timeline.expected_duration_sec == pytest.approx(
        expected_story_duration_sec(profile, [3.0, 4.0, 2.5])
    )


# 2. Single segment ------------------------------------------------------------

def test_single_segment_has_no_transitions():
    profile = _profile(gap=0.3, overlap=0.2)
    voiceover = _voiceover(5.0)

    timeline = build_story_timeline(voiceover, profile, fps=30, width=1080, height=1920)

    assert len(timeline.video_clips) == 1
    assert timeline.transitions == ()
    assert timeline.expected_duration_sec == pytest.approx(5.0)


# 3. Many segments --------------------------------------------------------------

def test_many_segments_produce_exactly_one_transition_per_boundary():
    profile = _profile(gap=0.1, overlap=0.1)
    voiceover = _voiceover(*([2.0] * 20))

    timeline = build_story_timeline(voiceover, profile, fps=30, width=1920, height=1080)

    assert len(timeline.video_clips) == 20
    assert len(timeline.transitions) == 19
    assert sorted(t.after_clip_index for t in timeline.transitions) == list(range(19))


# 4. Transition overlap calculation ---------------------------------------------

def test_overlap_only_shortens_expected_duration():
    profile = _profile(gap=0.0, overlap=0.4)
    voiceover = _voiceover(10.0, 10.0, 10.0)

    timeline = build_story_timeline(voiceover, profile, fps=30, width=1920, height=1080)

    assert timeline.expected_duration_sec == pytest.approx(30.0 - 2 * 0.4)


# 5. Optional intentional gap calculation ---------------------------------------

def test_gap_only_lengthens_expected_duration():
    profile = _profile(gap=0.5, overlap=0.0)
    voiceover = _voiceover(10.0, 10.0, 10.0)

    timeline = build_story_timeline(voiceover, profile, fps=30, width=1920, height=1080)

    assert timeline.expected_duration_sec == pytest.approx(30.0 + 2 * 0.5)


# 6. Invalid negative duration ----------------------------------------------------

def test_zero_or_negative_clip_duration_is_rejected():
    with pytest.raises(TimelineError):
        VideoClip(index=0, segment_index=0, start_sec=0.0, duration_sec=0.0)
    with pytest.raises(TimelineError):
        NarrationClip(
            index=0, segment_index=0, start_sec=0.0, duration_sec=-1.0,
            audio_path=Path("a.wav"),
        )


# 7. Invalid transition reference --------------------------------------------------

def test_transition_referencing_an_out_of_range_boundary_is_rejected():
    video_clips = (
        VideoClip(index=0, segment_index=0, start_sec=0.0, duration_sec=2.0),
        VideoClip(index=1, segment_index=1, start_sec=2.0, duration_sec=2.0),
    )
    narration_clips = (
        NarrationClip(index=0, segment_index=0, start_sec=0.0, duration_sec=2.0, audio_path=Path("a.wav")),
        NarrationClip(index=1, segment_index=1, start_sec=2.0, duration_sec=2.0, audio_path=Path("b.wav")),
    )
    with pytest.raises(TimelineError):
        Timeline(
            fps=30, width=1920, height=1080,
            video_clips=video_clips, narration_clips=narration_clips,
            # boundary 5 does not exist for a 2-clip timeline (only boundary 0 does)
            transitions=(Transition(after_clip_index=5),),
            expected_duration_sec=4.0,
        )


# 8. Duration-drift regression: the 2026-08-26 incident class --------------------

def test_excessive_cumulative_transitions_cannot_silently_shorten_the_output():
    """The historical bug: 20 real sections, but 162 caption cards were each
    treated as a transition boundary (161 crossfades instead of 19),
    silently dropping ~55s of narration. Reproduced at the domain level
    (not with real assets): build a correct 3-clip timeline, then try to
    smuggle in one extra transition per clip pair, as a caption-card
    crossfade scheme would. Construction must fail before any FFmpeg call.
    """
    video_clips = tuple(
        VideoClip(index=i, segment_index=i, start_sec=float(i * 4), duration_sec=4.0)
        for i in range(3)
    )
    narration_clips = tuple(
        NarrationClip(
            index=i, segment_index=i, start_sec=float(i * 4), duration_sec=4.0,
            audio_path=Path(f"seg-{i}.wav"),
        )
        for i in range(3)
    )
    # Correct: exactly 2 transitions for 3 clips.
    Timeline(
        fps=30, width=1920, height=1080,
        video_clips=video_clips, narration_clips=narration_clips,
        transitions=(
            Transition(after_clip_index=0, overlap_sec=0.4),
            Transition(after_clip_index=1, overlap_sec=0.4),
        ),
        expected_duration_sec=12.0 - 2 * 0.4,
    )
    # Corrupted: an extra, duplicate transition at boundary 0 — the shape a
    # per-caption-card crossfade scheme would produce (more transitions than
    # real section boundaries). Must be rejected, not silently accepted with
    # a shortened composited output.
    with pytest.raises(TimelineError):
        Timeline(
            fps=30, width=1920, height=1080,
            video_clips=video_clips, narration_clips=narration_clips,
            transitions=(
                Transition(after_clip_index=0, overlap_sec=0.4),
                Transition(after_clip_index=0, overlap_sec=0.4),
                Transition(after_clip_index=1, overlap_sec=0.4),
            ),
            expected_duration_sec=12.0 - 3 * 0.4,
        )


def test_video_and_narration_track_drift_beyond_one_frame_is_rejected():
    """A future bug that builds the video track from a different length list
    than the narration track (e.g. per-card instead of per-section) must
    fail here, not surface as a silently-shortened .mp4."""
    narration_clips = (
        NarrationClip(index=0, segment_index=0, start_sec=0.0, duration_sec=2.0, audio_path=Path("a.wav")),
    )
    mismatched_video_clips = (
        VideoClip(index=0, segment_index=0, start_sec=0.0, duration_sec=2.0),
        VideoClip(index=1, segment_index=0, start_sec=2.0, duration_sec=2.0),
    )
    with pytest.raises(TimelineError):
        Timeline(
            fps=30, width=1920, height=1080,
            video_clips=mismatched_video_clips, narration_clips=narration_clips,
            transitions=(Transition(after_clip_index=0),),
            expected_duration_sec=4.0,
        )


# 9. Deterministic rebuild --------------------------------------------------------

def test_building_the_same_inputs_twice_is_deterministic():
    profile = _profile(gap=0.2, overlap=0.1)
    voiceover = _voiceover(3.0, 4.0, 2.5)

    first = build_story_timeline(voiceover, profile, fps=30, width=1920, height=1080)
    second = build_story_timeline(voiceover, profile, fps=30, width=1920, height=1080)

    assert first == second
    assert first.source_fingerprint == second.source_fingerprint


# Missing audio / empty segments --------------------------------------------------

def test_build_story_timeline_requires_segments_with_audio():
    profile = _profile()
    with pytest.raises(TimelineError):
        build_story_timeline(_voiceover(), profile, fps=30, width=1920, height=1080)

    voiceover = SimpleNamespace(segments=(SimpleNamespace(audio_path=None, duration_sec=1.0),))
    with pytest.raises(TimelineError):
        build_story_timeline(voiceover, profile, fps=30, width=1920, height=1080)


# Persistence ----------------------------------------------------------------------

def test_timeline_round_trips_through_json(tmp_path):
    profile = _profile(gap=0.2, overlap=0.1)
    voiceover = _voiceover(3.0, 4.0, 2.5)
    timeline = build_story_timeline(voiceover, profile, fps=30, width=1920, height=1080)

    path = tmp_path / "timeline.json"
    timeline.write_json(path)
    restored = Timeline.read_json(path)

    assert restored == timeline
