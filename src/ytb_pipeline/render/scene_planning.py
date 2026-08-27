"""Persistent pre-visual ScenePlan boundary for opt-in Director mode."""
from __future__ import annotations

import hashlib
from dataclasses import replace

from .scene_plan import ScenePlan, build_story_scene_plan, normalize_directed_shots


def _planning_identity(baseline: ScenePlan, profile, director) -> tuple[str, dict[str, str]]:
    """Only semantic planning inputs participate; render/media state does not."""
    mode = profile.scene_planning.mode
    ruleset = getattr(director, "ruleset_version", "legacy-v1") if mode == "director" else "legacy-v1"
    provider = getattr(director, "provider_identity", "configured-provider") if mode == "director" else "none"
    provenance = {
        "planner_mode": mode, "planner_contract_version": "scene-plan-v2",
        "director_ruleset_version": ruleset, "provider": provider,
        "profile_id": profile.profile_id, "profile_version": profile.version,
        "base_source_fingerprint": baseline.source_fingerprint,
    }
    encoded = "\x1f".join(f"{key}={value}" for key, value in sorted(provenance.items()))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest(), provenance


async def prepare_scene_plan(voiceover, profile, *, project_dir, director=None) -> ScenePlan:
    baseline = build_story_scene_plan(voiceover, profile)
    if profile.scene_planning.mode == "director" and director is None:
        from ..agents.director_agent import DirectorAgent
        director = DirectorAgent()
    fingerprint, provenance = _planning_identity(baseline, profile, director)
    path = project_dir / "scene_plan.json"
    if path.is_file():
        persisted = ScenePlan.read_json(path)
        if persisted.source_fingerprint == fingerprint:
            return persisted
    if profile.scene_planning.mode == "legacy_single_shot":
        plan = baseline
    else:
        scenes = []
        for scene in baseline.scenes:
            segment = voiceover.segments[scene.source_segment_index]
            directed = await director.plan_scene(narration=segment.narration, visual_intent=scene.visual_intent, characters=scene.characters, max_shots=profile.scene_planning.max_shots_per_scene)
            shots = normalize_directed_shots(scene.scene_id, scene.narration_end_sec - scene.narration_start_sec, directed, min_shot_sec=profile.scene_planning.min_shot_sec)
            scenes.append(replace(scene, shots=shots))
        plan = ScenePlan(tuple(scenes), source_fingerprint=fingerprint, planner_provenance=provenance)
    if profile.scene_planning.mode == "legacy_single_shot":
        plan = replace(baseline, source_fingerprint=fingerprint, planner_provenance=provenance)
    project_dir.mkdir(parents=True, exist_ok=True)
    plan.write_json(path)
    return plan
