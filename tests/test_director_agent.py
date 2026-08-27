import pytest

from ytb_pipeline.agents.director_agent import validate_directed_shots
from ytb_pipeline.render.scene_plan import normalize_directed_shots
from ytb_pipeline.render.scene_planning import prepare_scene_plan


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
