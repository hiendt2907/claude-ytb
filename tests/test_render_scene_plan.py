"""Deterministic ScenePlan domain model — fast unit tests, no ffmpeg/TTS/network.

`ScenePlan` sits between `Voiceover`/`Segment` and `Timeline` (see
`render/scene_plan.py`'s module docstring for the full hierarchy). These
tests exercise the domain model in isolation and prove the same class of
historical regression Timeline already guards against — a presentation
detail (caption card) must never inflate the scene count above the real
number of narrative segments.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from ytb_pipeline.render.scene_plan import (
    Scene,
    ScenePlan,
    ScenePlanError,
    Shot,
    build_story_scene_plan,
)
from ytb_pipeline.render.timeline import (
    Timeline,
    build_story_timeline,
    build_story_timeline_from_scene_plan,
)


def _segment(
    duration_sec: float,
    *,
    audio_path: str = "a.wav",
    purpose: str = "core_answer",
    visual_intent: str = "nhân vật đứng trong quán cà phê",
    video_type: str = "image_motion",
    visual_asset: str = "",
    scene_characters: tuple[str, ...] = (),
) -> SimpleNamespace:
    return SimpleNamespace(
        audio_path=Path(audio_path),
        duration_sec=duration_sec,
        purpose=purpose,
        visual_intent=visual_intent,
        video_type=video_type,
        visual_asset=visual_asset,
        scene_characters=scene_characters,
    )


def _voiceover(*segments: SimpleNamespace) -> SimpleNamespace:
    return SimpleNamespace(segments=tuple(segments))


def _profile(*, gap: float = 0.0, overlap: float = 0.0) -> SimpleNamespace:
    return SimpleNamespace(
        profile_id="fixture", version="1.0.0",
        render=SimpleNamespace(inter_segment_gap_sec=gap, transition_overlap_sec=overlap),
    )


# 1. one segment -> one Scene ---------------------------------------------------

def test_one_segment_produces_one_scene():
    voiceover = _voiceover(_segment(5.0))
    plan = build_story_scene_plan(voiceover, _profile())

    assert len(plan.scenes) == 1
    assert plan.scenes[0].source_segment_index == 0
    assert plan.scenes[0].narration_start_sec == pytest.approx(0.0)
    assert plan.scenes[0].narration_end_sec == pytest.approx(5.0)


# 2. multiple segments -> deterministic ordered scenes ---------------------------

def test_multiple_segments_produce_ordered_scenes():
    voiceover = _voiceover(_segment(3.0), _segment(4.0), _segment(2.5))
    plan = build_story_scene_plan(voiceover, _profile())

    assert [scene.source_segment_index for scene in plan.scenes] == [0, 1, 2]
    assert [scene.scene_id for scene in plan.scenes] == ["scene-000", "scene-001", "scene-002"]


# 3. narration start/end alignment -----------------------------------------------

def test_narration_windows_are_contiguous_and_gap_free():
    voiceover = _voiceover(_segment(3.0), _segment(4.0), _segment(2.5))
    plan = build_story_scene_plan(voiceover, _profile(gap=0.5, overlap=0.2))

    # ScenePlan windows never include gap/overlap — that is Timeline's job.
    assert plan.scenes[0].narration_start_sec == pytest.approx(0.0)
    assert plan.scenes[0].narration_end_sec == pytest.approx(3.0)
    assert plan.scenes[1].narration_start_sec == pytest.approx(3.0)
    assert plan.scenes[1].narration_end_sec == pytest.approx(7.0)
    assert plan.scenes[2].narration_start_sec == pytest.approx(7.0)
    assert plan.scenes[2].narration_end_sec == pytest.approx(9.5)


# 4. deterministic scene IDs ------------------------------------------------------

def test_scene_ids_are_deterministic_not_random():
    voiceover = _voiceover(_segment(3.0), _segment(4.0))
    first = build_story_scene_plan(voiceover, _profile())
    second = build_story_scene_plan(voiceover, _profile())

    assert [s.scene_id for s in first.scenes] == [s.scene_id for s in second.scenes]
    assert first == second


# 5. deterministic shot IDs --------------------------------------------------------

def test_shot_ids_are_deterministic_and_scoped_to_their_scene():
    voiceover = _voiceover(_segment(3.0), _segment(4.0))
    plan = build_story_scene_plan(voiceover, _profile())

    assert plan.scenes[0].shots[0].shot_id == "scene-000-shot-00"
    assert plan.scenes[1].shots[0].shot_id == "scene-001-shot-00"


# 6. source fingerprint stability ---------------------------------------------------

def test_fingerprint_is_stable_for_identical_inputs():
    voiceover = _voiceover(_segment(3.0), _segment(4.0))
    first = build_story_scene_plan(voiceover, _profile())
    second = build_story_scene_plan(voiceover, _profile())

    assert first.source_fingerprint == second.source_fingerprint


# 7. fingerprint changes with script semantic input ----------------------------------

def test_fingerprint_changes_when_visual_intent_changes():
    baseline = build_story_scene_plan(_voiceover(_segment(3.0)), _profile())
    changed = build_story_scene_plan(
        _voiceover(_segment(3.0, visual_intent="một cảnh hoàn toàn khác")), _profile()
    )

    assert baseline.source_fingerprint != changed.source_fingerprint


# 8. fingerprint changes with narration timing ----------------------------------------

def test_fingerprint_changes_when_narration_duration_changes():
    baseline = build_story_scene_plan(_voiceover(_segment(3.0)), _profile())
    changed = build_story_scene_plan(_voiceover(_segment(3.6)), _profile())

    assert baseline.source_fingerprint != changed.source_fingerprint


# 9. character propagation -------------------------------------------------------------

def test_scene_characters_propagate_from_segment():
    voiceover = _voiceover(_segment(3.0, scene_characters=("an", "minh")))
    plan = build_story_scene_plan(voiceover, _profile())

    assert plan.scenes[0].characters == ("an", "minh")
    assert plan.scenes[0].shots[0].scene_characters == ("an", "minh")


# 10. visual_intent propagation ----------------------------------------------------------

def test_visual_intent_propagates_to_scene_and_shot():
    voiceover = _voiceover(_segment(3.0, visual_intent="cận cảnh tách cà phê bốc khói"))
    plan = build_story_scene_plan(voiceover, _profile())

    assert plan.scenes[0].visual_intent == "cận cảnh tách cà phê bốc khói"
    assert plan.scenes[0].shots[0].visual_intent == "cận cảnh tách cà phê bốc khói"


# 11. no caption-card inflation of Scene count -------------------------------------------

def test_scene_count_never_depends_on_caption_card_count():
    """ScenePlan has no notion of caption cards at all — its scene count is
    always exactly the segment count, regardless of how long/short the
    narration text is (which is what would drive caption card count in
    render/story.py). This is the ScenePlan-level analogue of the 2026-08-26
    Timeline regression test."""
    long_narration_segment = _segment(25.0)  # would split into many caption cards
    short_narration_segment = _segment(1.0)
    voiceover = _voiceover(long_narration_segment, short_narration_segment)
    plan = build_story_scene_plan(voiceover, _profile())

    assert len(plan.scenes) == 2


# 12. ScenePlan -> Timeline compatibility ------------------------------------------------

def test_scene_plan_produces_the_same_timeline_as_the_legacy_builder():
    voiceover = _voiceover(_segment(3.0), _segment(4.0), _segment(2.5))
    profile = _profile(gap=0.2, overlap=0.1)

    via_legacy = build_story_timeline(voiceover, profile, fps=30, width=1920, height=1080)

    scene_plan = build_story_scene_plan(voiceover, profile)
    via_scene_plan = build_story_timeline_from_scene_plan(
        scene_plan, voiceover, profile, fps=30, width=1920, height=1080,
    )

    assert via_legacy == via_scene_plan


def test_mismatched_scene_plan_and_voiceover_length_is_rejected():
    from ytb_pipeline.render.timeline import TimelineError

    voiceover = _voiceover(_segment(3.0), _segment(4.0))
    profile = _profile()
    scene_plan = build_story_scene_plan(_voiceover(_segment(3.0)), profile)

    with pytest.raises(TimelineError):
        build_story_timeline_from_scene_plan(
            scene_plan, voiceover, profile, fps=30, width=1920, height=1080,
        )


# 13. ScenePlan JSON round-trip -----------------------------------------------------------

def test_scene_plan_round_trips_through_json(tmp_path):
    voiceover = _voiceover(_segment(3.0), _segment(4.0))
    plan = build_story_scene_plan(voiceover, _profile())

    path = tmp_path / "scene_plan.json"
    plan.write_json(path)
    restored = ScenePlan.read_json(path)

    assert restored == plan


# 14. legacy project without scene_plan.json can rebuild successfully ---------------------

def test_scene_plan_is_always_rebuildable_without_reading_any_file():
    """A 'legacy project' here just means: nothing was ever read from disk.
    build_story_scene_plan never depends on a persisted file existing — it is
    pure over Voiceover + profile, so rebuilding is always possible."""
    voiceover = _voiceover(_segment(3.0), _segment(4.0))
    profile = _profile()

    rebuilt_once = build_story_scene_plan(voiceover, profile)
    rebuilt_twice = build_story_scene_plan(voiceover, profile)

    assert rebuilt_once == rebuilt_twice


# Invariant / error-path coverage -----------------------------------------------------------

def test_scene_plan_requires_segments():
    with pytest.raises(ScenePlanError):
        build_story_scene_plan(_voiceover(), _profile())


def test_scene_with_no_shots_is_rejected():
    with pytest.raises(ScenePlanError):
        Scene(
            scene_id="scene-000", source_segment_index=0,
            narration_start_sec=0.0, narration_end_sec=1.0,
            purpose="core_answer", visual_intent="x", characters=(), shots=(),
        )


def test_shot_durations_must_sum_to_the_scene_window():
    with pytest.raises(ScenePlanError):
        Scene(
            scene_id="scene-000", source_segment_index=0,
            narration_start_sec=0.0, narration_end_sec=5.0,
            purpose="core_answer", visual_intent="x", characters=(),
            shots=(
                Shot(
                    shot_id="scene-000-shot-00", relative_start_sec=0.0,
                    duration_sec=2.0,  # does not match the 5.0s window
                    visual_kind="image_motion", visual_intent="x",
                    visual_asset="", scene_characters=(),
                ),
            ),
        )


def test_scene_plan_rejects_a_duplicate_or_out_of_order_segment_index():
    with pytest.raises(ScenePlanError):
        ScenePlan(
            scenes=(
                Scene(
                    scene_id="scene-000", source_segment_index=0,
                    narration_start_sec=0.0, narration_end_sec=1.0,
                    purpose="core_answer", visual_intent="x", characters=(),
                    shots=(Shot("scene-000-shot-00", 0.0, 1.0, "image_motion", "x", "", ()),),
                ),
                Scene(
                    scene_id="scene-001", source_segment_index=0,  # duplicate index
                    narration_start_sec=1.0, narration_end_sec=2.0,
                    purpose="core_answer", visual_intent="x", characters=(),
                    shots=(Shot("scene-001-shot-00", 0.0, 1.0, "image_motion", "x", "", ()),),
                ),
            )
        )
