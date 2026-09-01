from pathlib import Path
from types import SimpleNamespace

import pytest

from ytb_pipeline.render.subtitle import (
    SubtitleCue, SubtitleTrack, build_subtitle_track, write_subtitle_artifacts,
)
from ytb_pipeline.render.timeline import NarrationClip, Timeline, Transition, VideoClip


def _timeline() -> Timeline:
    clips = tuple(VideoClip(i, i, float(i * 2), 2.0) for i in range(2))
    narration = tuple(NarrationClip(i, i, float(i * 2), 2.0, Path(f"{i}.wav")) for i in range(2))
    return Timeline(30, 1920, 1080, clips, narration, (Transition(0),), 4.0)


def test_subtitles_are_deterministic_and_follow_narration_timing():
    voiceover = SimpleNamespace(segments=(SimpleNamespace(narration="Xin chào\nViệt Nam"), SimpleNamespace(narration="Cảm ơn <bạn>")))
    track = build_subtitle_track(voiceover, _timeline(), language="vi")
    assert track.cues == (
        SubtitleCue(0.0, 2.0, "Xin chào\nViệt Nam"),
        SubtitleCue(2.0, 4.0, "Cảm ơn <bạn>"),
    )
    assert track.to_srt().startswith("1\n00:00:00,000 --> 00:00:02,000")
    assert track.to_vtt().startswith("WEBVTT\n\n")


def test_subtitle_serializers_preserve_unicode_and_write_both_artifacts(tmp_path: Path):
    track = SubtitleTrack("vi", (SubtitleCue(0.0, 1.25, "Đúng & rõ"),))
    srt, vtt = write_subtitle_artifacts(track, tmp_path / "video")
    assert srt.read_text(encoding="utf-8").endswith("Đúng & rõ\n")
    assert "00:00:00.000 --> 00:00:01.250" in vtt.read_text(encoding="utf-8")


def test_subtitle_contract_rejects_invalid_cues():
    with pytest.raises(ValueError):
        SubtitleCue(1.0, 1.0, "x")
    with pytest.raises(ValueError):
        SubtitleTrack("vi", (SubtitleCue(1.0, 2.0, "later"), SubtitleCue(0.0, 1.0, "earlier")))


def test_build_subtitle_track_corrects_cue_timing_for_crossfade_overlap():
    """`NarrationClip.start_sec` is a NOMINAL, pre-crossfade planning
    position (`cursor += duration + gap`, see
    `build_story_timeline_from_scene_plan`) — it never subtracts `overlap`.
    The REAL composed video, however, crossfades adjacent sections and trims
    `overlap_sec` of real time at every transition (`_compose_clips`'s own
    `audio_cumulative += ... - overlap` in `story.py`); nothing else in the
    codebase ever reads `narration_clips[i].start_sec` (grep confirms
    `_compose_clips` recomputes its own positions independently from
    measured per-clip durations), so `build_subtitle_track` was the only
    consumer of the nominal, uncorrected value — meaning every real subtitle
    cue after the first was timestamped `overlap_sec` later than the speech
    actually falls in the composited video, drifting further at every
    segment boundary. Verified against real production data: a real,
    published 22-segment episode (profile `ban-so-6`, `inter_segment_gap_sec
    == transition_overlap_sec == 0.4`) drifted the final cue 8.4s (21
    transitions x 0.4s) past the video's own true runtime.

    This fixture uses the same gap == overlap == 0.4 contract every shipped
    `ban-so-6` profile version uses: real playback positions collapse back
    to exactly 0/2/4s (no net gap), while the nominal, uncorrected cursor
    would place them at 0/2.4/4.8s.
    """
    voiceover = SimpleNamespace(
        segments=tuple(SimpleNamespace(narration=f"Cau {i}") for i in range(3))
    )
    gap = overlap = 0.4
    nominal_starts = [i * (2.0 + gap) for i in range(3)]
    narration = tuple(
        NarrationClip(i, i, nominal_starts[i], 2.0, Path(f"{i}.wav")) for i in range(3)
    )
    video = tuple(VideoClip(i, i, nominal_starts[i], 2.0) for i in range(3))
    transitions = (
        Transition(after_clip_index=0, overlap_sec=overlap, gap_sec=gap),
        Transition(after_clip_index=1, overlap_sec=overlap, gap_sec=gap),
    )
    timeline = Timeline(30, 1920, 1080, video, narration, transitions, expected_duration_sec=6.0)

    track = build_subtitle_track(voiceover, timeline)

    assert track.cues == (
        SubtitleCue(0.0, 2.0, "Cau 0"),
        SubtitleCue(2.0, 4.0, "Cau 1"),
        SubtitleCue(4.0, 6.0, "Cau 2"),
    )


# Real measured segment durations from `chin-ban-nhap-mot-nut-gui`, a real
# published 22-segment `ban-so-6` episode (assets/projects/chin-ban-nhap-
# mot-nut-gui/project.json, node "render", output_data.segments).
_REAL_EPISODE_DURATIONS_SEC = (
    26.812608, 7.75, 13.106961, 5.087098, 12.082086, 17.014875, 11.725941,
    18.984354, 14.796508, 16.061293, 5.991361, 14.499025, 7.977324,
    13.563129, 15.598707, 9.801587, 12.893333, 14.980567, 8.749751,
    9.866553, 15.245488, 27.411451000000024,
)


def test_build_subtitle_track_tolerates_float_noise_from_overlap_correction():
    """The crossfade-overlap correction above subtracts a running total of
    `overlap_sec` from each nominal `start_sec` — when `gap == overlap`
    (every shipped `ban-so-6` profile version), the corrected boundary
    between two cues is mathematically exactly the previous cue's end, but
    22 real floating-point subtractions accumulate ~1e-14s of noise, which
    can land a corrected start_sec a few ULPs BEFORE the previous cue's end.
    `SubtitleTrack.__post_init__` has no tolerance (`current.start_sec <
    previous.end_sec` is an exact comparison), so this genuinely reproduces
    against this real episode's real 22 measured durations
    (`_REAL_EPISODE_DURATIONS_SEC`) — not a synthetic edge case.
    """
    gap = overlap = 0.4
    cursor = 0.0
    narration = []
    video = []
    transitions = []
    for i, duration in enumerate(_REAL_EPISODE_DURATIONS_SEC):
        narration.append(NarrationClip(i, i, cursor, duration, Path(f"{i}.mp3")))
        video.append(VideoClip(i, i, cursor, duration))
        if i < len(_REAL_EPISODE_DURATIONS_SEC) - 1:
            transitions.append(Transition(after_clip_index=i, overlap_sec=overlap, gap_sec=gap))
        cursor += duration + gap
    expected_duration = sum(_REAL_EPISODE_DURATIONS_SEC)  # gap == overlap cancels exactly
    timeline = Timeline(
        30, 1920, 1080, tuple(video), tuple(narration), tuple(transitions), expected_duration,
    )
    voiceover = SimpleNamespace(
        segments=[SimpleNamespace(narration=f"seg{i}") for i in range(len(_REAL_EPISODE_DURATIONS_SEC))]
    )

    track = build_subtitle_track(voiceover, timeline)

    assert len(track.cues) == len(_REAL_EPISODE_DURATIONS_SEC)
    assert track.cues[0].start_sec == pytest.approx(0.0, abs=1e-9)
    assert track.cues[-1].end_sec == pytest.approx(expected_duration, abs=1e-6)
    for previous, current in zip(track.cues, track.cues[1:]):
        assert current.start_sec >= previous.end_sec


def test_srt_separates_consecutive_cues_with_a_blank_line():
    """SRT requires a blank line between entries so parsers know where one
    cue's text ends and the next cue's index digit begins.

    `to_vtt()` already joins its bodies with "\n\n"; `to_srt()` joined cue
    blocks with a single "\n", so two-or-more-cue tracks produced a cue's
    text immediately followed by the next cue's bare index digit on the very
    next line — malformed by the SRT spec (verified against real production
    narration from `chin-ban-nhap-mot-nut-gui`, a real 22-segment episode:
    ffmpeg's own lenient demuxer tolerated it, but a strict/standard SRT
    parser is not guaranteed to split cues correctly without the blank
    line).
    """
    track = SubtitleTrack(
        "vi",
        (SubtitleCue(0.0, 2.0, "Cau mot"), SubtitleCue(2.0, 4.0, "Cau hai")),
    )
    srt = track.to_srt()
    assert srt == (
        "1\n00:00:00,000 --> 00:00:02,000\nCau mot\n\n"
        "2\n00:00:02,000 --> 00:00:04,000\nCau hai\n"
    )
