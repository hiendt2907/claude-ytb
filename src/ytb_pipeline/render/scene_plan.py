"""Deterministic ScenePlan domain model for the story renderer.

    Voiceover + Segment  -->  build_story_scene_plan()  -->  ScenePlan
        -->  build_story_timeline_from_scene_plan()  -->  Timeline  -->  renderer

The authoritative hierarchy this module sits in:

    Script      answers WHAT is being said.
    Narration   answers HOW LONG the spoken content actually lasts
                (`Segment.duration_sec`, already measured by TTS).
    ScenePlan   answers WHAT should visually represent each narration-aligned
                time region (this module).
    Timeline    answers WHEN every renderable element appears (`timeline.py`).
    Renderer    answers HOW those Timeline elements become media (`story.py`).

`ScenePlan` is NOT a second Timeline: a scene's `narration_start_sec`/
`narration_end_sec` window is the segment's own raw narration span only (no
`inter_segment_gap_sec`, no `transition_overlap_sec` — those are Timeline/
renderer transition arithmetic, never ScenePlan's to own). It carries plain
semantic/visual planning data — no FFmpeg filter graphs, no ComfyUI/provider
configuration, no shell strings, no LLM prose, no generated asset paths as
required state. ScenePlan describes requested visuals; it does not generate
them.

Phase 2 v1 scope: this module only makes explicit a decision the story
renderer already made implicitly before this model existed — one scene per
script segment, exactly one shot per scene, covering the whole scene window.
It intentionally does not change production shot count, image count, or
pacing. The schema allows more shots per scene later (a future Director
phase); this phase must not exercise that just to prove the abstraction.

`ScenePlan.__post_init__` enforces the same class of invariant `Timeline`
does for transitions (see `docs/handoffs/2026-08-26-story-renderer-caption-
transition-fix-handoff.md`): the number of scenes must equal the number of
narrative segments, never the number of presentation elements (caption
cards) inside them. A caption card is a `render/story.py`-only visual detail;
it never becomes a Scene, a Shot, or a scene boundary here.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..content_profiles import ContentProfile
    from ..pkg.models import Voiceover


class ScenePlanError(ValueError):
    """A ScenePlan (or one of its scenes/shots) violates its own contract."""


@dataclass(frozen=True)
class Shot:
    """One requested visual unit inside a Scene's narration window.

    `relative_start_sec` is relative to the owning Scene's own window, not to
    the overall narration timeline — Timeline is the one that places scenes
    (and therefore shots) on the absolute timeline.
    """

    shot_id: str
    relative_start_sec: float
    duration_sec: float
    visual_kind: str
    visual_intent: str
    visual_asset: str
    scene_characters: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.shot_id.strip():
            raise ScenePlanError("Shot.shot_id không được rỗng.")
        if self.relative_start_sec < 0:
            raise ScenePlanError(f"Shot[{self.shot_id}].relative_start_sec phải >= 0.")
        if self.duration_sec <= 0:
            raise ScenePlanError(f"Shot[{self.shot_id}].duration_sec phải > 0.")


@dataclass(frozen=True)
class Scene:
    """One narrative/visual scene, aligned to exactly one Script segment."""

    scene_id: str
    source_segment_index: int
    narration_start_sec: float
    narration_end_sec: float
    purpose: str
    visual_intent: str
    characters: tuple[str, ...]
    shots: tuple[Shot, ...]

    def __post_init__(self) -> None:
        if not self.scene_id.strip():
            raise ScenePlanError("Scene.scene_id không được rỗng.")
        if self.source_segment_index < 0:
            raise ScenePlanError(f"Scene[{self.scene_id}].source_segment_index phải >= 0.")
        if self.narration_start_sec < 0:
            raise ScenePlanError(f"Scene[{self.scene_id}].narration_start_sec phải >= 0.")
        if self.narration_end_sec <= self.narration_start_sec:
            raise ScenePlanError(
                f"Scene[{self.scene_id}].narration_end_sec phải > narration_start_sec."
            )
        if not self.shots:
            raise ScenePlanError(f"Scene[{self.scene_id}] cần ít nhất một shot.")
        window = self.narration_end_sec - self.narration_start_sec
        shots_total = sum(shot.duration_sec for shot in self.shots)
        if abs(shots_total - window) > 1e-6:
            raise ScenePlanError(
                f"Scene[{self.scene_id}]: tổng duration_sec của shots "
                f"({shots_total:.3f}s) phải khớp đúng narration window ({window:.3f}s)."
            )


@dataclass(frozen=True)
class ScenePlan:
    """Deterministic, validated semantic/visual plan for one story render."""

    scenes: tuple[Scene, ...]
    source_fingerprint: str = ""

    def __post_init__(self) -> None:
        if not self.scenes:
            raise ScenePlanError("ScenePlan cần ít nhất một scene.")
        seen_ids: set[str] = set()
        for scene in self.scenes:
            if scene.scene_id in seen_ids:
                raise ScenePlanError(f"scene_id trùng lặp: {scene.scene_id!r}.")
            seen_ids.add(scene.scene_id)
        expected_indices = list(range(len(self.scenes)))
        actual_indices = [scene.source_segment_index for scene in self.scenes]
        if actual_indices != expected_indices:
            raise ScenePlanError(
                "ScenePlan.scenes phải phủ đúng mỗi segment đúng một lần, theo thứ "
                f"tự ({expected_indices!r}), nhận được {actual_indices!r}. Đây là bất "
                "biến chống lớp lỗi 'presentation card bị coi là ranh giới scene' — số "
                "scene phải khớp số segment ngữ nghĩa thật, không phải số caption card."
            )
        for index in range(1, len(self.scenes)):
            previous = self.scenes[index - 1]
            current = self.scenes[index]
            if current.narration_start_sec < previous.narration_end_sec:
                raise ScenePlanError(
                    "ScenePlan.scenes phải đơn điệu tăng và không chồng lấn theo "
                    f"narration window (scene {index} bắt đầu trước khi scene "
                    f"{index - 1} kết thúc)."
                )

    def to_json_dict(self) -> dict:
        def scene_dict(scene: Scene) -> dict:
            data = {k: v for k, v in asdict(scene).items() if k != "shots"}
            data["shots"] = [asdict(shot) for shot in scene.shots]
            return data

        return {
            "source_fingerprint": self.source_fingerprint,
            "scenes": [scene_dict(scene) for scene in self.scenes],
        }

    def write_json(self, path: Path) -> None:
        """Persist as a derived, rebuildable artifact — never a source of truth.

        Written to `assets/projects/<slug>/scene_plan.json`: that directory
        already exists as the per-project state root (`project.json`), and
        ScenePlan is project-specific rather than a reusable global cache. If
        the file is absent (legacy project, or simply deleted), it is always
        deterministically rebuildable from `Script` + `Voiceover` + profile —
        this write is a debug/postmortem convenience, not a dependency.
        """
        path.write_text(
            json.dumps(self.to_json_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )

    @classmethod
    def from_json_dict(cls, data: dict) -> "ScenePlan":
        def shot_from_dict(shot: dict) -> Shot:
            fields = dict(shot)
            fields["scene_characters"] = tuple(fields["scene_characters"])
            return Shot(**fields)

        def scene_from_dict(scene: dict) -> Scene:
            fields = {k: v for k, v in scene.items() if k != "shots"}
            fields["characters"] = tuple(fields["characters"])
            shots = tuple(shot_from_dict(shot) for shot in scene["shots"])
            return Scene(**fields, shots=shots)

        return cls(
            source_fingerprint=data.get("source_fingerprint", ""),
            scenes=tuple(scene_from_dict(scene) for scene in data["scenes"]),
        )

    @classmethod
    def read_json(cls, path: Path) -> "ScenePlan":
        return cls.from_json_dict(json.loads(path.read_text(encoding="utf-8")))


def _scene_id(index: int) -> str:
    return f"scene-{index:03d}"


def _shot_id(scene_id: str, shot_index: int) -> str:
    return f"{scene_id}-shot-{shot_index:02d}"


def _source_fingerprint(profile: "ContentProfile", segments) -> str:
    """Hash of every input that materially affects PLANNING (not timeline
    transition arithmetic — `render/timeline.py` fingerprints that
    separately). Changing a segment's semantic visual fields or its measured
    narration duration must change this; profile render gap/overlap must
    not, because ScenePlan never reads them.
    """
    digest = hashlib.sha256()
    digest.update(f"{profile.profile_id}\x1f{profile.version}".encode("utf-8"))
    for index, segment in enumerate(segments):
        digest.update(
            "\x1f".join((
                str(index),
                str(segment.duration_sec),
                segment.purpose,
                segment.visual_intent,
                segment.video_type,
                segment.visual_asset,
                ",".join(segment.scene_characters),
            )).encode("utf-8")
        )
    return digest.hexdigest()


def build_story_scene_plan(voiceover: "Voiceover", profile: "ContentProfile") -> ScenePlan:
    """The ScenePlanBuilder boundary: `Voiceover` + `Segment` -> validated `ScenePlan`.

    Deterministic and pure — no LLM, no FFmpeg, no I/O, no provider calls (no
    DirectorAgent in this phase). Reuses existing `Segment` semantic fields
    (`purpose`, `visual_intent`, `scene_characters`, `visual_asset`,
    `video_type`) rather than duplicating a parallel master-script schema.

    v1 expresses the EXISTING renderer decision explicitly: one scene per
    segment, exactly one shot per scene, covering the whole scene window —
    not a new pacing/shot-count decision.
    """
    segments = voiceover.segments
    if not segments:
        raise ScenePlanError("build_story_scene_plan cần ít nhất một segment.")

    scenes: list[Scene] = []
    cursor = 0.0
    for index, segment in enumerate(segments):
        scene_id = _scene_id(index)
        start = cursor
        end = cursor + segment.duration_sec
        shot = Shot(
            shot_id=_shot_id(scene_id, 0),
            relative_start_sec=0.0,
            duration_sec=segment.duration_sec,
            visual_kind=segment.video_type,
            visual_intent=segment.visual_intent,
            visual_asset=segment.visual_asset,
            scene_characters=segment.scene_characters,
        )
        scenes.append(
            Scene(
                scene_id=scene_id,
                source_segment_index=index,
                narration_start_sec=start,
                narration_end_sec=end,
                purpose=segment.purpose,
                visual_intent=segment.visual_intent,
                characters=segment.scene_characters,
                shots=(shot,),
            )
        )
        cursor = end

    return ScenePlan(
        scenes=tuple(scenes),
        source_fingerprint=_source_fingerprint(profile, segments),
    )
