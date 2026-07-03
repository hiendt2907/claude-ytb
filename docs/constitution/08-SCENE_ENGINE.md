# 08 — SCENE ENGINE

## Purpose

Own the **narrative-layer** semantics of a Scene — setting, characters, mood,
lighting, duration, and the shots it contains — distinct from the
Storyboard's visual-layer Scene→Shot→Frame hierarchy (07-STORYBOARD). The
Scene Engine is where "what happens and why" lives; the Storyboard is "how it
looks."

## Scene Data Model

```python
from dataclasses import dataclass
from enum import Enum


class SceneType(str, Enum):
    TALKING_HEAD = "talking_head"
    B_ROLL = "b_roll"
    ANIMATION = "animation"
    STICKMAN = "stickman"
    CODE_WALKTHROUGH = "code_walkthrough"
    DATA_VIZ = "data_viz"


@dataclass(frozen=True)
class Scene:
    """Narrative-layer unit. One Scene maps 1:1 to one StoryboardScene
    (07-STORYBOARD) via shared `id`."""

    id: str
    scene_type: SceneType
    setting: str                  # e.g. "minimalist studio, dark backdrop"
    characters: tuple[str, ...] = ()   # KnowledgeGraph entity ids, () = none/narrator-only
    mood: str = "neutral"          # informs Visual Director palette + Voice Director prosody
    lighting: str = "soft, neutral"
    target_duration_sec: float = 0.0
    narration: str = ""             # ground-truth text for this scene (feeds Voice Engine)
    shot_ids: tuple[str, ...] = ()  # FK into Storyboard.scenes[*].shots
    emotional_beat: str = "neutral"  # "tension" | "release" | "curiosity" | "payoff" | "neutral"
```

`Scene.id` is the join key between the Scene Engine (narrative truth) and the
Storyboard (visual truth) — see 07-STORYBOARD's `StoryboardScene.scene_id`.
Neither model embeds the other; this separation is what lets Camera
Director iterate on shot composition without touching narrative content, and
lets Story Architect revise narrative without invalidating already-generated
visual assets that don't depend on the changed field.

## Scene Planning Algorithm (LLM Prompt → Structured Scene)

Narrative Planner (06-AGENTS) is the producer. The algorithm:

1. **Input assembly**: take one `Act` from `StoryStructure` plus its
   allocated duration share and the channel's niche voice constraints.
2. **Decomposition prompt**: ask the LLM to propose 2-6 scenes covering the
   act's purpose, each tagged with `scene_type`, `mood`, `emotional_beat`,
   and a duration estimate — constrained by a JSON schema matching the
   `Scene` dataclass (see 11-PROMPT_ENGINE §Structured output enforcement).
3. **Duration reconciliation**: sum proposed `target_duration_sec`; if the
   sum drifts from the act's allocation by more than 15%, re-prompt with the
   explicit delta (06-AGENTS Narrative Planner retry strategy) — never
   silently rescale every scene proportionally, since that destroys
   intentional pacing (a deliberately short punchy scene shouldn't be
   stretched).
4. **Type assignment validation**: cross-check `scene_type` against content —
   a scene whose narration describes a mechanism numerically/visually may be
   better as `data_viz` than `b_roll`; this check runs as a rule, not purely
   LLM self-report.
5. **Handoff**: validated `Scene` list passed to Storyboard Agent, which
   creates the corresponding `StoryboardScene` shells (07-STORYBOARD).

```python
class ScenePlanner(Protocol):
    async def plan(self, act: "Act", duration_budget_sec: float, ctx: "RunContext") -> "AgentResult[tuple[Scene, ...]]": ...
```

## Scene Types

| Type | Description | Typical generation path |
|---|---|---|
| `talking_head` | Narrator-presence framing (even when fully anonymous/voice-only, per channel's "giọng kể ẩn danh" convention) — usually a static or subtly animated background with text/caption focus | Image Engine static frame + Ken Burns, or none (caption-only card) |
| `b_roll` | Supporting visual footage illustrating the narration without literal correspondence | AI Video Engine (Wan2.2/CogVideoX) generated clip, see 13-VIDEO_ENGINE |
| `animation` | Motion graphics explaining an abstract mechanism | Animation Planner spec (06-AGENTS) rendered via declarative keyframe engine, not AI video |
| `stickman` | Simplified figure animation for behavior/process illustration | Same pipeline as `animation`, with a stickman asset template |
| `code_walkthrough` | Terminal/code card overlay (matches existing `Segment.code`/`danger` fields in `pkg/models.py`) | Static frame generation (syntax-highlighted card) + optional cursor/typing animation |
| `data_viz` | Charts, comparisons, statistics tied to `ResearchBrief` claims | Programmatic chart rendering (matplotlib/Pillow) seeded from sourced data — never LLM-hallucinated numbers |

`scene_type` determines which Engine the Asset Engine (09-ASSET_ENGINE)
routes generation requests to — this is the principal dispatch key.

## Scene Duration Constraints by Platform

| Platform/Format | Total video ceiling | Typical scene duration |
|---|---|---|
| Short (YouTube Shorts / Reels) | ≤ 60s | 2-6s per scene, high beat density |
| TikTok | ≤ 180s (3 min) | 3-8s per scene |
| Long-form (YouTube) | 10-30 min | 15-60s per scene, lower beat density, more room for `data_viz`/`code_walkthrough` |
| Podcast (audio-first) | unbounded, typically 20-60 min | Scene concept degrades to "segment" — no visual shot list required, only narration + optional static card |

These ceilings are enforced at the Narrative Planner stage (06-AGENTS) and
re-validated by Editor Agent at assembly time (`EditTimeline` duration check)
— two independent checkpoints, matching the project's general
fail-fast-at-boundaries convention (`config/settings.py` precedent).

## Scene Composition Rules

1. **First scene of a video carries the hook.** This generalizes the current
   `Segment.hook` boolean — instead of a flag that reorders segments
   post-hoc, the Scene Engine plans the hook scene as Scene 0 from the start,
   with `emotional_beat="curiosity"` and the channel's "paradox hook" framing
   applied at the narrative-planning stage, not the render stage.
2. **Mood must be consistent with `scene_type`.** A `data_viz` scene
   defaults to `mood="analytical"` unless explicitly overridden — Visual
   Director should not be asked to render a chart in a `mood="ominous"`
   palette without explicit narrative justification.
3. **`characters` references must resolve in `KnowledgeGraph`.** A Scene
   referencing a character/location not yet established in the knowledge
   graph is a Continuity Agent violation, not a silent default — this
   prevents the classic LLM failure of inventing a "recurring" character
   that was never actually introduced.
4. **Series bridge scenes are explicitly typed**, not inferred. The closing
   scene of a series episode that sets up the next episode is tagged via
   `emotional_beat="curiosity"` + a dedicated `is_series_bridge` convention
   (extend `Scene` with this flag when series support lands) so Editor Agent
   never trims it as filler.
5. **Maximum 1 `code_walkthrough` scene per 90s of runtime** (a content-
   density guard matching the channel's existing "mật độ ý" niche gate from
   `video-quality-rules.md` §0c) — too many terminal cards in a row reads as
   a tutorial, not a mechanism-explainer.

## Current State: `compose.py` / `compose_ai.py` Mapping

There is **no Scene Engine today** — `pkg/models.py`'s `Segment` is the only
unit, and `compose.py`/`compose_ai.py` derive all visual behavior procedurally
from segment fields rather than from any planned scene structure:

- `compose.py`: static gradient background per segment, caption + optional
  terminal card overlay (Pillow), no scene typing at all — every segment is
  effectively `talking_head`-with-code-card by default.
- `compose_ai.py`: same overlay logic, but background is Pexels B-roll
  fetched by `stock.fetch_broll(segment.broll)` — the `broll` field is a
  free-text English search keyword, not a generation prompt. Cut cadence is
  a fixed cadence constant (`BEAT_TARGET_SEC=6.0`, `HOOK_BEAT_SEC=2.5`)
  applied uniformly, not derived from any per-scene `emotional_beat` or
  duration plan.
- `Segment.hook` triggers a **post-hoc reordering** into a "cold-open" — the
  hook segments are pulled to the front of the render sequence by
  `compose_ai.py`'s cold-open logic (`MAX_COLD_SHOTS`, `COLD_BEAT_SEC`)
  rather than being planned as the first scene from the start.
- `Segment.danger` (red highlight) and `Segment.code` are the only two
  "scene type" signals that exist today, both narrowly serving the
  `code_walkthrough`-equivalent case.

## Migration Notes

1. **Additive first**: introduce `Scene`/`SceneType` in `pkg/models.py`
   alongside `Segment` — do not remove `Segment`. `Segment` remains the
   Voice Engine's narration/timing unit (it is referenced by `Scene.shot_ids`
   indirectly via the Storyboard linkage, not replaced).
2. **Converter bridge**: `segment_to_scene(segment: Segment, index: int) -> Scene`
   infers `scene_type` from existing signals (`code` non-empty →
   `code_walkthrough`; `broll` non-empty → `b_roll`; else `talking_head`) so
   `compose_ai.py` can keep running against synthesized `Scene` objects
   during transition without a rewrite.
3. **Replace cadence constants with planned duration**: once Narrative
   Planner exists, `Scene.target_duration_sec` (LLM-planned, beat-aware)
   replaces `BEAT_TARGET_SEC`/`HOOK_BEAT_SEC` as the cut-timing source for
   Editor Agent. The constants become fallback defaults only, used when a
   Scene lacks an explicit duration (degraded/offline mode).
4. **Hook becomes Scene 0 by construction**: retire the post-hoc cold-open
   reordering in `compose_ai.py` once Narrative Planner reliably places the
   hook scene first; keep the reordering code as a defensive fallback for
   any Scene list that arrives without a properly-ordered hook (e.g. legacy
   `Segment`-derived input via the converter bridge).
5. **`broll` keyword → generation prompt**: `b_roll` scenes stop using
   `stock.fetch_broll` as the default path once 13-VIDEO_ENGINE's AI
   generation + Pexels-fallback chain is live; the free-text keyword is
   replaced by Image Planner/Animation Planner-authored prompts attached to
   the Scene's shots.
6. **`data_viz` is net-new** — no current equivalent exists. First
   implementation can be a thin Pillow/matplotlib chart renderer fed
   directly by `ResearchBrief` sourced numbers, gated behind the same
   accuracy/sourcing compliance check QA Agent already enforces for text
   claims (`ComplianceCheck.accuracy`).
