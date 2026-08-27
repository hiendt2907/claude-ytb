"""Persistent pre-visual ScenePlan boundary for opt-in Director mode."""
from __future__ import annotations

from .scene_plan import ScenePlan, build_story_scene_plan, normalize_directed_shots


async def prepare_scene_plan(voiceover, profile, *, project_dir, director=None) -> ScenePlan:
    baseline = build_story_scene_plan(voiceover, profile)
    path = project_dir / "scene_plan.json"
    if path.is_file():
        persisted = ScenePlan.read_json(path)
        if persisted.source_fingerprint == baseline.source_fingerprint:
            return persisted
    if profile.scene_planning.mode == "legacy_single_shot":
        plan = baseline
    else:
        if director is None:
            from ..agents.director_agent import DirectorAgent
            director = DirectorAgent()
        scenes = []
        for scene in baseline.scenes:
            segment = voiceover.segments[scene.source_segment_index]
            directed = await director.plan_scene(narration=segment.narration, visual_intent=scene.visual_intent, characters=scene.characters, max_shots=profile.scene_planning.max_shots_per_scene)
            shots = normalize_directed_shots(scene.scene_id, scene.narration_end_sec - scene.narration_start_sec, directed, min_shot_sec=profile.scene_planning.min_shot_sec)
            scenes.append(type(scene)(**{**scene.__dict__, "shots": shots}))
        plan = ScenePlan(tuple(scenes), source_fingerprint=baseline.source_fingerprint)
    project_dir.mkdir(parents=True, exist_ok=True)
    plan.write_json(path)
    return plan
