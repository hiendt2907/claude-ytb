# 15 — Stickman Engine

> Status: **NOT IMPLEMENTED.** This document specifies the target design for
> the stickman animation engine described in `PROJECT_VISION.md` §2.3
> ("animated stickman/storyboard frames" as part of the AI-generated visuals
> default path). No code in `src/ytb_pipeline/` currently implements this.

## 1. Purpose

Educational and explainer content frequently needs a cheap, fast,
style-consistent way to visualize an abstract concept, a process, or a
cause-effect relationship without the cost of full diffusion-rendered video.
Stick-figure ("stickman") animation fills that gap:

- Near-zero marginal generation cost (vector shapes, not pixels)
- Deterministic, reproducible across re-renders (no diffusion seed drift)
- Reads instantly as "explainer," which sets correct viewer expectations
- Cheap to keep on-model with simple LLM-authored pose/action sequences

Stickman is a **render strategy**, selected per-segment or per-video like any
other provider (see `21-PROVIDER_SYSTEM.md`), not a replacement for B-roll or
diffusion image rendering. It is the right tool when the segment's narration
describes a process, comparison, or mechanism rather than a concrete visual
subject.

## 2. Responsibilities

- Translate a narration segment into a structured `StickmanScene`
  (characters, poses, actions, camera) via LLM prompting.
- Maintain a finite, well-defined **pose library** and **expression library**
  so the LLM is constrained to a renderable vocabulary (no open-ended SVG
  generation from free text — that is unreliable and slow).
- Render each `StickmanScene` to an SVG → PNG frame sequence.
- Time the frame sequence against the segment's voiceover duration (already
  known from the voiceover stage — see `pkg/models.py::Segment.duration_sec`).
- Hand off the frame sequence to the Render Engine (`19-RENDER_ENGINE.md`) for
  FFmpeg assembly, exactly like any other video clip source.

## 3. Data Model

```python
"""src/ytb_pipeline/stickman/models.py (planned)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class PoseName(str, Enum):
    STANDING = "standing"
    POINTING = "pointing"
    THINKING = "thinking"
    FALLING = "falling"
    RUNNING = "running"
    GESTURING = "gesturing"
    SITTING = "sitting"
    WALKING = "walking"


class ExpressionName(str, Enum):
    HAPPY = "happy"
    CONFUSED = "confused"
    SURPRISED = "surprised"
    NEUTRAL = "neutral"
    WORRIED = "worried"


@dataclass(frozen=True)
class Pose:
    """One named pose: a fixed skeleton joint-angle set, looked up from the
    pose library by name. Never freeform — the LLM picks a `PoseName`, the
    renderer resolves it to coordinates."""

    name: PoseName
    expression: ExpressionName = ExpressionName.NEUTRAL
    hold_ms: int = 800  # how long this pose is held before the next action


@dataclass(frozen=True)
class Character:
    """A stickman actor in a scene. `role` lets the LLM refer to characters
    semantically ("the user", "the server") instead of inventing names,
    which keeps multi-character scenes consistent across segments."""

    character_id: str
    role: str               # e.g. "user", "server", "attacker", "narrator"
    color: str = "#1a1a1a"  # stroke color, distinguishes characters on screen
    x: float = 0.5          # normalized stage position [0, 1]


@dataclass(frozen=True)
class Action:
    """A transition from one pose to another for a single character,
    anchored to a point in the segment's timeline."""

    character_id: str
    pose: Pose
    start_ms: int           # offset from segment start
    duration_ms: int        # transition duration (tween length)


@dataclass(frozen=True)
class CameraShot:
    """Camera framing for a stickman scene. Stickman scenes are 2D, so
    "camera" means viewport crop + zoom, not 3D perspective."""

    zoom: float = 1.0        # 1.0 = full stage; >1.0 = zoomed in
    focus_x: float = 0.5     # normalized focus point
    focus_y: float = 0.5
    pan_to: tuple[float, float] | None = None  # optional pan target


@dataclass(frozen=True)
class StickmanScene:
    """The fully-resolved scene for one narration segment: ready to render
    to a frame sequence. Produced by the LLM prompt step, validated against
    the pose/expression enums before rendering."""

    scene_id: str
    segment_index: int
    characters: tuple[Character, ...]
    actions: tuple[Action, ...] = ()
    camera: CameraShot = field(default_factory=CameraShot)
    duration_ms: int = 0      # must equal the bound segment's duration_ms
    background: str = "#fafafa"


@dataclass(frozen=True)
class StickmanFrameSequence:
    """Output of rendering: a directory of PNG frames ready for FFmpeg."""

    scene_id: str
    frames_dir: Path
    fps: int
    frame_count: int
```

## 4. Animation Pipeline

```
narration segment (Segment.narration, Segment.duration_sec)
        │
        ▼
[1] Stickman Prompt Builder
    — builds an LLM prompt constrained to PoseName/ExpressionName enums
    — includes segment narration, prior scene's character roster (continuity)
        │
        ▼
[2] LLM Call (Ollama/Qwen3, local-first per provider system)
    — returns JSON matching StickmanScene schema (strict; reject + retry on
      schema violation, never best-effort parse of free text)
        │
        ▼
[3] Scene Validator
    — every Action.pose.name must be in PoseName
    — sum of Action timings must fit within Scene.duration_ms
    — character_id references must resolve
        │
        ▼
[4] SVG Renderer
    — resolves each Pose to a skeleton (joint coordinates) from the pose
      library, interpolates between poses for in-between frames
        │
        ▼
[5] SVG → PNG Frame Export
    — rasterize at target fps (e.g. 30fps) using a headless SVG renderer
        │
        ▼
[6] FFmpeg Assembly (Render Engine)
    — frames → video clip, handed to Timeline as a Clip with this segment's
      voiceover audio attached
```

## 5. Pose Library

The pose library is a fixed, versioned set of skeletons. Each pose is a
named joint-angle configuration (shoulders, elbows, hips, knees), not
free-form SVG path data, so poses interpolate cleanly and stay visually
consistent across the whole library.

| Pose | Use case |
|---|---|
| `standing` | Default neutral, narration anchor |
| `pointing` | Drawing attention to an on-screen element/diagram |
| `thinking` | Reflection, "consider this..." beats |
| `falling` | Failure, crash, "this breaks" beats |
| `running` | Urgency, speed, deadline pressure |
| `gesturing` | General emphasis, explaining with hands |
| `sitting` | Passive/waiting states |
| `walking` | Transition between scene beats, process steps |

```python
"""src/ytb_pipeline/stickman/pose_library.py (planned)."""

POSE_LIBRARY: dict[PoseName, "Skeleton"] = {
    PoseName.STANDING: Skeleton(
        head=(0.5, 0.1), shoulders=(0.5, 0.25), hips=(0.5, 0.55),
        left_arm=((0.4, 0.3), (0.35, 0.45)),
        right_arm=((0.6, 0.3), (0.65, 0.45)),
        left_leg=((0.45, 0.55), (0.45, 0.9)),
        right_leg=((0.55, 0.55), (0.55, 0.9)),
    ),
    # ... one entry per PoseName, hand-authored once, never LLM-generated.
}
```

## 6. Expression Library

Expressions modify only the face region of a pose (a small set of SVG path
overrides for eyes/mouth) and compose orthogonally with any pose.

| Expression | Visual cue |
|---|---|
| `happy` | Upward eye arcs, smiling mouth |
| `confused` | Asymmetric eyebrow tilt, squiggle mouth |
| `surprised` | Wide circular eyes, open mouth |
| `neutral` | Flat eyes, flat mouth (default) |
| `worried` | Downward eyebrow tilt, flat tense mouth |

## 7. Camera Positioning

Since stickman scenes are 2D vector stages, "camera" is implemented as a
viewport transform over the stage, not a 3D camera:

- `zoom = 1.0, focus = (0.5, 0.5)` — default full-stage shot, used for
  multi-character interaction scenes.
- `zoom > 1.0` — push in on one character for emphasis (e.g. on a `pointing`
  action paired with an `emphasis` chip in the segment).
- `pan_to` — slow pan between two focus points across the scene duration,
  used for process/sequence narration ("first this happens, then this").

Camera changes are authored by the LLM in the same JSON payload as poses —
they are part of `StickmanScene`, not a separate pass.

## 8. F5-TTS Sync

Stickman actions are timed against the **already-rendered** voiceover audio,
never the reverse — the voiceover stage runs first in the pipeline DAG and
produces an authoritative `Segment.duration_sec` (see `pkg/models.py`). The
stickman prompt builder receives this duration and instructs the LLM to keep
`Action.start_ms + Action.duration_ms` sums within it.

For finer-grained alignment (e.g. snapping a `pointing` action to the exact
word being emphasized), the Subtitle Engine's Whisper word-timestamps
(`18-SUBTITLE_ENGINE.md`) can optionally be consulted — if word-level timing
exists for the segment, the prompt builder includes word offsets so the LLM
can anchor actions to specific words rather than only segment boundaries.
This is an enhancement, not a requirement: scene-level timing alone is
sufficient for v1.

## 9. Rendering: SVG → PNG → FFmpeg

```python
"""src/ytb_pipeline/stickman/renderer.py (planned)."""

def render_scene(scene: StickmanScene, *, fps: int = 30) -> StickmanFrameSequence:
    """Interpolate poses across the scene timeline, rasterize each frame to
    PNG. Frame count = duration_ms / 1000 * fps, rounded up.

    Uses a headless SVG rasterizer (e.g. resvg or CairoSVG) — no browser
    dependency, keeps the pipeline offline-first per PROJECT_VISION.md §2.1.
    """
    frames_dir = OUTPUT_DIR / "_stickman" / scene.scene_id
    frames_dir.mkdir(parents=True, exist_ok=True)
    frame_count = math.ceil(scene.duration_ms / 1000 * fps)
    for i in range(frame_count):
        t_ms = int(i * 1000 / fps)
        svg = _compose_frame_svg(scene, t_ms)
        _rasterize_svg_to_png(svg, frames_dir / f"frame_{i:05d}.png")
    return StickmanFrameSequence(
        scene_id=scene.scene_id, frames_dir=frames_dir,
        fps=fps, frame_count=frame_count,
    )
```

FFmpeg then assembles the frame sequence into a clip exactly like any other
visual source (`ffmpeg -framerate {fps} -i frame_%05d.png -i {audio} ...`),
consistent with the existing `transitions.py` concat approach.

## 10. Current State

**NOT IMPLEMENTED.** No `src/ytb_pipeline/stickman/` package exists. There is
no `StickmanProvider`, no pose/expression library, no SVG rasterization
dependency declared in `requirements.txt`. This document is the target
design to build against.

## 11. Implementation Roadmap

1. **Pose/expression library** — hand-author the `Skeleton` data for all 8
   poses + 5 expressions as static Python data (no generation needed; this
   is the one piece that must NOT be LLM-authored, for visual consistency).
2. **`StickmanScene` schema + validator** — dataclasses above + strict JSON
   schema validation on LLM output (reject and retry on violation).
3. **SVG composer** — pure-Python skeleton → SVG string, with linear
   interpolation between poses for in-between frames.
4. **Rasterizer integration** — wire `resvg` or `CairoSVG` (must run fully
   offline on macOS M4, no cloud rendering).
5. **`StickmanProvider`** implementing the render-strategy `Provider`
   protocol (`21-PROVIDER_SYSTEM.md`) so `render_provider` can be set to
   `"stickman"` alongside existing `"slide"` / `"ai"`.
6. **Render Engine integration** — `StickmanFrameSequence` → `Clip` adapter
   in the Timeline model (`19-RENDER_ENGINE.md`).
7. **Per-segment strategy selection** — extend `Segment` (or its
   `project.json` successor) with an optional `visual_strategy` field so a
   single video can mix stickman segments with B-roll/diffusion segments.
</content>
