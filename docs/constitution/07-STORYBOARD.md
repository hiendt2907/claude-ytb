# 07 — STORYBOARD

## Purpose

Define the Storyboard as the single source of truth for "what is on screen
and when" — the artifact that sits between narrative planning (06-AGENTS:
Narrative Planner) and asset generation (12-IMAGE_ENGINE, 13-VIDEO_ENGINE).
Every visual decision in the system traces back to a node in this hierarchy.

## What a Storyboard Is

A Storyboard is a **frozen, content-addressable data structure** — not a
process. It is produced once per video by the Storyboard Agent (with
contributions from Visual Director and Camera Director), then consumed
read-only by every downstream engine. Like the rest of the pipeline, it obeys
the immutable-dataclass + `replace()` enrichment convention already
established in `pkg/models.py`: each pass (Visual Director's style pass,
Camera Director's movement pass, Image Planner's prompt pass) returns an
enriched copy, never a mutation.

## Scene → Shot → Frame Hierarchy

```
Storyboard
└── Scene[]              (08-SCENE_ENGINE owns Scene semantics)
    └── Shot[]            (a continuous camera take within a scene)
        └── Frame[]        (a single generated image — 1 per still frame;
                             N per shot if motion/video is generated from
                             a sequence of keyframes)
```

```python
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Frame:
    """One generated image. The atomic unit Image Engine produces."""

    frame_id: str                 # content-hash, see 09-ASSET_ENGINE
    description: str              # human/LLM-readable visual description
    prompt: str = ""               # filled by Image Planner (12-IMAGE_ENGINE)
    negative_prompt: str = ""
    seed: int | None = None        # deterministic seed for consistency
    resolution_profile: str = "frame"  # "thumbnail" | "bg_portrait" | "frame"
    asset_path: Path | None = None  # filled post-generation


@dataclass(frozen=True)
class Shot:
    """A continuous camera take. Camera Director populates movement fields."""

    shot_id: str
    purpose: str                  # "establish" | "reaction" | "detail" | "transition"
    shot_type: str = ""            # see Camera movement vocabulary below
    movement: str = ""
    angle: str = ""
    duration_sec: float = 0.0
    frames: tuple[Frame, ...] = ()
    continuity_refs: tuple[str, ...] = ()  # character/location ids to track


@dataclass(frozen=True)
class StoryboardScene:
    """Visual-layer view of a Scene (08-SCENE_ENGINE owns the narrative-layer
    Scene model; this is the Storyboard's reference to it)."""

    scene_id: str                 # matches Scene.id in 08-SCENE_ENGINE
    shots: tuple[Shot, ...] = ()
    style_overrides: dict[str, str] = None  # rare: scene-specific style deltas


@dataclass(frozen=True)
class Storyboard:
    """The full visual plan for one video. Immutable; enriched via replace()."""

    video_id: str
    scenes: tuple[StoryboardScene, ...] = ()
    style_guide_id: str = ""        # FK to VisualStyleGuide (06-AGENTS)
    version: int = 1                 # bumped on each enrichment pass
```

`frame_id` and `asset_path` follow the content-hash addressing scheme defined
in 09-ASSET_ENGINE — a Frame with an identical `(prompt, seed,
resolution_profile)` tuple resolves to the same cached asset across videos and
across re-runs, which is what makes checkpoint/resume safe and cheap.

## Storyboard Generation Pipeline (LLM-driven)

```
ScenePlan (06-AGENTS: Narrative Planner output)
        │
        ▼
Storyboard Agent  ── draft Scene→Shot breakdown, shot purpose only
        │
        ▼
Visual Director   ── attaches/confirms style_guide_id (once per video/series)
        │
        ▼
Camera Director   ── fills shot_type / movement / angle per shot
        │
        ▼
Image Planner     ── fills Frame.prompt / negative_prompt / seed
        │
        ▼
Continuity Agent   ── validates character/location consistency pre-generation
        │
        ▼
[ frozen Storyboard handed to Asset Engine for generation ]
```

Each stage is a `replace()` over the previous `Storyboard`, bumping
`version`. The DAG checkpoints after each stage (see 02-DAG, project-level
checkpoint/resume contract) so a failure in Image Planner does not require
re-running Storyboard Agent or Camera Director.

## Visual Continuity Rules

1. **One `VisualStyleGuide` per video** (and, for series, one per series
   unless an episode explicitly forks the style). `style_guide_id` is set
   once by Visual Director and never overridden by downstream stages except
   via `style_overrides` on a specific `StoryboardScene`, which must be
   explicitly justified (e.g. a dream-sequence scene with a different palette).
2. **Recurring entities use a fixed reference description + seed lineage.**
   Any character/location appearing in more than one `Shot.continuity_refs`
   must reuse the same base descriptive tokens in every `Frame.prompt`, and
   should prefer seed derivation (e.g. `base_seed + shot_index`) over fully
   random seeds when the provider supports seed-consistency techniques
   (IP-Adapter / ControlNet reference, LoRA character embedding).
3. **Continuity Agent runs twice**: once on the text-level Storyboard (catch
   inconsistent descriptions before spending compute on generation), once on
   generated Frame assets (embedding similarity against the canonical
   reference image) — see 06-AGENTS Continuity Agent.
4. **No silent re-description.** If Image Planner must adapt a description to
   fit a provider's prompt grammar, the semantic subject must remain
   unchanged; only style/composition phrasing may be adapted.

## Camera Movement Vocabulary

A closed vocabulary keeps Camera Director's output machine-checkable instead
of free-text guesswork.

| Field | Allowed values |
|---|---|
| `shot_type` | `wide`, `medium`, `close_up`, `extreme_close_up`, `over_the_shoulder`, `pov`, `insert` |
| `movement` | `static`, `pan_left`, `pan_right`, `tilt_up`, `tilt_down`, `push_in`, `pull_out`, `dolly`, `handheld`, `ken_burns` |
| `angle` | `eye_level`, `low_angle`, `high_angle`, `birds_eye`, `dutch_tilt` |

Rules:
- `ken_burns` is reserved for the static-image fallback path (13-VIDEO_ENGINE
  §Fallback strategy) — Camera Director should not assign it to a shot that
  will have genuine AI-video motion.
- Monotony guard: the same `(shot_type, movement)` pair must not repeat for
  more than 3 consecutive shots within a scene (06-AGENTS Camera Director
  failure mode).
- Emotional-beat mapping is a **soft default**, overridable per scene:
  tension → `close_up`/`push_in`; release/payoff → `wide`/`pull_out` or
  `static`.

## Export Formats

| Format | Use case | Notes |
|---|---|---|
| **JSON** | Canonical machine format — the `Storyboard` dataclass serialized via `dataclasses.asdict()` | Source of truth; checkpointed at every DAG stage |
| **Image grid (contact sheet)** | Human review (Telegram approval gate, matching existing `ideation/approval.py` pattern) | One thumbnail per Frame, laid out Scene-major / Shot-minor, generated via Pillow once frames exist |
| **PDF** | Optional client-facing / archival deliverable | Generated from the image grid + per-shot metadata (duration, camera, narration excerpt); not required for the render pipeline itself |

JSON is the only format the pipeline depends on programmatically; image grid
and PDF are presentation layers generated on demand from the same JSON.

## Migration from Current `script.json` Segments

The current model (`pkg/models.py`) is **flat**: a `Script` has a tuple of
`Segment` (caption + narration + optional broll keyword), with no Scene/Shot/
Frame distinction — `compose_ai.py` derives "beats" (cuts every ~6s,
2.5s in the hook) procedurally from segment duration rather than from any
planned shot structure, and fetches B-roll from Pexels per `Segment.broll`.

Mapping:

| Current (`pkg/models.py` / `compose_ai.py`) | Target (Storyboard) |
|---|---|
| `Segment` | Roughly one `StoryboardScene` with 1+ `Shot` — a `Segment` today conflates scene-level narrative content with shot-level visual content; the migration splits it |
| `Segment.broll` (English keyword for Pexels search) | `Frame.prompt` (full generation prompt for Flux/SDXL) — keyword search replaced by direct prompt construction |
| `Segment.hook` (bool, routes to cold-open) | `StoryboardScene` ordering — hook segments become the first scenes, no longer a special-cased reordering flag |
| `Segment.transition` (bool, triggers whoosh+xfade) | `Shot`-to-`Shot` transition metadata, owned by Editor Agent's `EditTimeline` (06-AGENTS), referencing Storyboard shot boundaries |
| `BEAT_TARGET_SEC` / `HOOK_BEAT_SEC` procedural cut cadence in `compose_ai.py` | `Shot.duration_sec`, planned explicitly by Camera Director rather than derived from a fixed cadence constant |
| No camera vocabulary today (only veil/caption overlay compositing) | `Shot.shot_type` / `movement` / `angle`, explicit per shot |
| No continuity tracking today | `Shot.continuity_refs` + Continuity Agent |

Migration sequencing:
1. Introduce `Frame`/`Shot`/`StoryboardScene`/`Storyboard` as new dataclasses
   in `pkg/models.py` (additive, no breaking change to `Segment`-based flow).
2. Add a converter `segment_to_storyboard_scene(segment: Segment) -> StoryboardScene`
   that synthesizes a single-shot scene from each existing `Segment`, so the
   current Pexels-based `compose_ai.py` path keeps working unmodified during
   transition.
3. Once Storyboard Agent + Camera Director exist (06-AGENTS), retire the
   converter and have Narrative Planner emit real multi-shot scenes directly;
   `compose_ai.py`'s procedural beat cadence is then replaced by
   Editor Agent's `EditTimeline`, assembled from the Storyboard rather than
   recomputed from segment duration.
4. `Segment` is not deleted — it remains the Voice Engine's unit of narration
   text and timing (14-VOICE_ENGINE), since narration pacing is a property of
   text/audio, not of the visual Storyboard. The two structures are linked by
   a shared `scene_id`/segment index, not collapsed into one model.
