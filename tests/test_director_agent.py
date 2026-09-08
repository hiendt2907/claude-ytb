import pytest
from types import SimpleNamespace

from ytb_pipeline.agents.director_agent import validate_directed_shots
from ytb_pipeline.render.scene_plan import normalize_directed_shots
from ytb_pipeline.render.scene_planning import prepare_scene_plan


class _Director:
    def __init__(self, shots): self.shots, self.calls = shots, 0
    async def plan_scene(self, **_kwargs):
        self.calls += 1
        return validate_directed_shots(self.shots, allowed_characters=("minh",), max_shots=4)


def _profile(mode="director"):
    return SimpleNamespace(profile_id="test", version="1", scene_planning=SimpleNamespace(
        mode=mode, max_shots_per_scene=4, min_shot_sec=1.0,
    ))


def _voiceover(intent="cafe"):
    segment = SimpleNamespace(duration_sec=6.0, purpose="core", visual_intent=intent,
        video_type="image_motion", visual_asset="", scene_characters=("minh",), narration="words")
    return SimpleNamespace(segments=(segment,))


@pytest.mark.asyncio
async def test_director_plan_persists_and_reuses_without_second_call(tmp_path):
    director = _Director([
        {"visual_intent": "wide cafe", "characters": ["minh"], "duration_weight": 1},
        {"visual_intent": "close reaction", "characters": ["minh"], "duration_weight": 1},
    ])
    first = await prepare_scene_plan(_voiceover(), _profile(), project_dir=tmp_path, director=director)
    second = await prepare_scene_plan(_voiceover(), _profile(), project_dir=tmp_path, director=director)
    assert (tmp_path / "scene_plan.json").is_file()
    assert len(first.scenes[0].shots) == 2
    assert second == first and director.calls == 1


@pytest.mark.asyncio
async def test_planning_input_change_invalidates_persisted_director_plan(tmp_path):
    director = _Director([{"visual_intent": "wide cafe", "characters": ["minh"], "duration_weight": 1}])
    await prepare_scene_plan(_voiceover(), _profile(), project_dir=tmp_path, director=director)
    await prepare_scene_plan(_voiceover("office"), _profile(), project_dir=tmp_path, director=director)
    assert director.calls == 2


def test_director_output_is_bounded_and_normalized_without_timing_drift():
    directed = validate_directed_shots([
        {"visual_intent": "wide café", "characters": ["minh"], "duration_weight": 1},
        {"visual_intent": "close reaction", "characters": ["minh"], "duration_weight": 2},
    ], allowed_characters=("minh",), max_shots=3)
    shots = normalize_directed_shots("scene-000", 6.0, directed, min_shot_sec=1.0)
    assert len(shots) == 2 and sum(shot.duration_sec for shot in shots) == pytest.approx(6.0)
    assert shots[0].visual_intent != shots[1].visual_intent


def test_director_rejects_unknown_character_and_excess_shots():
    with pytest.raises(ValueError):
        validate_directed_shots([{"visual_intent":"x", "characters":["other"], "duration_weight":1}], allowed_characters=("minh",), max_shots=2)
    with pytest.raises(ValueError):
        validate_directed_shots([], allowed_characters=(), max_shots=2)


def test_semantic_ids_survive_unrelated_insertion():
    a = validate_directed_shots([{"visual_intent":"A", "characters":[], "duration_weight":1}, {"visual_intent":"B", "characters":[], "duration_weight":1}], allowed_characters=(), max_shots=4)
    b = validate_directed_shots([{"visual_intent":"A", "characters":[], "duration_weight":1}, {"visual_intent":"X", "characters":[], "duration_weight":1}, {"visual_intent":"B", "characters":[], "duration_weight":1}], allowed_characters=(), max_shots=4)
    assert normalize_directed_shots("scene", 6, a, min_shot_sec=1)[1].shot_id == normalize_directed_shots("scene", 6, b, min_shot_sec=1)[2].shot_id
