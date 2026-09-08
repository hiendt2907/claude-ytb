"""Explicit, persisted Long-to-Short visual reuse lineage.

This module links semantic shots; it never looks for similar files or videos.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class ReuseSource:
    parent_project_id: str
    parent_scene_id: str
    parent_shot_id: str
    policy_version: str = "phase8-v1"


@dataclass(frozen=True)
class DerivativeLineage:
    parent_project_id: str
    shot_sources: dict[str, ReuseSource] = field(default_factory=dict)
    contract_version: str = "derivative-lineage-v1"

    def source_for(self, shot_id: str) -> ReuseSource | None:
        return self.shot_sources.get(shot_id)

    def write_json(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"parent_project_id": self.parent_project_id, "contract_version": self.contract_version,
            "shot_sources": {key: asdict(value) for key, value in self.shot_sources.items()}}, ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def read_json(cls, path: Path) -> "DerivativeLineage":
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(str(data["parent_project_id"]), {key: ReuseSource(**value) for key, value in data.get("shot_sources", {}).items()}, str(data.get("contract_version", "derivative-lineage-v1")))


def derive_lineage(voiceover, child_plan, *, projects_dir: Path) -> DerivativeLineage | None:
    """Build only explicit exact semantic links from Short strategy evidence.

    A source section is already editorially persisted in ``ContentStrategy``.
    We may select a parent Shot only when its semantic request exactly matches
    the child Shot; there is deliberately no ordinal or fuzzy fallback.
    """
    strategy = getattr(voiceover, "strategy", None)
    parent_id = getattr(strategy, "source_long_slug", "") if strategy else ""
    source_index = getattr(strategy, "source_section_index", None) if strategy else None
    if not parent_id or source_index is None:
        return None
    plan_path = projects_dir / parent_id / "scene_plan.json"
    if not plan_path.is_file():
        return DerivativeLineage(parent_id)
    from .scene_plan import ScenePlan
    parent = ScenePlan.read_json(plan_path)
    parent_scene = next((scene for scene in parent.scenes if scene.source_segment_index == source_index), None)
    if parent_scene is None:
        return DerivativeLineage(parent_id)
    sources: dict[str, ReuseSource] = {}
    for child_scene in child_plan.scenes:
        for child_shot in child_scene.shots:
            match = next((shot for shot in parent_scene.shots if shot.visual_intent.strip() == child_shot.visual_intent.strip() and shot.scene_characters == child_shot.scene_characters), None)
            if match is not None:
                sources[child_shot.shot_id] = ReuseSource(parent_id, parent_scene.scene_id, match.shot_id)
    return DerivativeLineage(parent_id, sources)
