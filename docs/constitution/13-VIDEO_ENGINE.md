# 13 — VIDEO ENGINE

## Purpose

Generate every moving-image clip the pipeline needs — b-roll, animation
renders, transitions, stickman motion, screen recordings — locally-first on
the M4, with AI video generation as the new default and Pexels stock
demoted to an explicit fallback rather than the only option it is today.

## Provider Interface

```python
from typing import Protocol
from dataclasses import dataclass


@dataclass(frozen=True)
class VideoGenRequest:
    prompt: str                          # motion/scene description
    source_image_path: str | None = None  # image-to-video seed frame, if applicable
    duration_sec: float = 4.0
    fps: int = 24
    width: int = 1024
    height: int = 576
    seed: int | None = None
    motion_strength: float = 0.5          # 0=near-static, 1=high motion


@dataclass(frozen=True)
class VideoGenResult:
    video_path: str
    provider: str
    model: str
    duration_sec: float
    fps: int
    cost_usd: float
    latency_ms: int


class VideoProvider(Protocol):
    name: str
    is_local: bool

    async def generate(self, request: VideoGenRequest) -> VideoGenResult: ...
    async def health_check(self) -> bool: ...
```

## Supported Providers

| Provider | Type | Notes |
|---|---|---|
| **Wan2.2** | local | Primary provider. Strong image-to-video and text-to-video on Apple Silicon via MPS; preferred for b-roll and stickman/animation motion where a still keyframe (from Image Engine) seeds the clip. |
| **CogVideoX** | local | Secondary local provider — useful for longer or more complex camera-movement requests Wan2.2 handles less reliably; selection between the two is a per-request heuristic (duration, motion complexity), not a fixed preference. |
| **RunwayML** | cloud | Cloud fallback for shots needing capability beyond current local model quality (e.g. complex multi-subject motion); explicitly opt-in given cost. |
| **Pika** | cloud | Secondary cloud fallback / comparison provider. |

Default chain for routine b-roll: `[wan2.2_local, cogvideox_local, pexels_fallback]`
— note Pexels sits in the chain as an explicit, typed fallback step (see
below), not a separate code path bypassing the Video Engine entirely as it
is today.

## Video Types

| Type | Typical source | Notes |
|---|---|---|
| `b_roll` | text-to-video or image-to-video from Image Engine keyframe | Scene Engine's `b_roll` scene type (08-SCENE_ENGINE) |
| `animation` | Animation Planner's declarative keyframe spec, rendered by a deterministic motion engine, NOT an AI video model | See note below — kept separate from AI-generated clips |
| `stickman` | Same declarative path as `animation`, stickman-specific asset template | |
| `transition` | Procedural (FFmpeg xfade/whoosh), not AI-generated | Owned by Editor Agent's `EditTimeline`, executed at assembly time |
| `screen_recording` | Captured input (not generated) — e.g. an actual terminal session recording for `code_walkthrough` scenes | Stored/cached like any other asset, but has no `VideoGenRequest` — it's an ingestion path, not a generation path |

**Important distinction**: `animation`/`stickman` types are explicitly
*not* routed through `VideoProvider` — they are rendered by a deterministic,
declarative motion engine (interpreting `AnimationSpec` keyframes,
06-AGENTS) precisely because AI video generation cannot guarantee the exact
keyframe positions a mechanism-explainer animation requires. Treating them
as a separate, non-AI path is intentional, not a migration gap.

## Generation Pipeline

```
Storyboard Shot (scene_type=b_roll)
        │
        ▼
Image Planner produces a seed keyframe (Image Engine, 12) ── optional,
        │                                                     for image-to-video
        ▼
Animation/Camera context (motion_strength from Camera Director's
        │                  `movement` field, e.g. push_in -> higher strength)
        ▼
VideoGenRequest built, wrapped in AssetSpec (09-ASSET_ENGINE)
        │
        ▼
AssetRegistry.get() — cache check
        │ MISS
        ▼
VideoProvider.generate()
        │
        ▼
Quality gate (validate, below)
        │ PASS                          │ FAIL
        ▼                                ▼
cache + return                    bounded retry (seed bump, max 2)
                                          │ exhausted
                                          ▼
                                  fallback chain: next local provider →
                                  Pexels stock → static image + Ken Burns
```

## Duration Constraints

| Format | Max segment duration |
|---|---|
| Short (≤60s total) | ≤ 6s per generated segment |
| TikTok (≤180s total) | ≤ 6s per generated segment |
| Long-form (10-30 min) | ≤ 15s per generated segment |

These ceilings exist because current-generation local video models degrade
in coherence past short durations — segments are generated short and
concatenated by the Editor Agent's `EditTimeline` rather than requesting one
long generation, matching FFmpeg's existing strength at this project (concat
+ transition compositing) over any model's strength at long-duration
coherence.

## Quality Gate

Run inside the Asset Engine's `validate` step before caching:

1. **Motion blur / incoherence detection** — frame-to-frame optical-flow
   sanity check; videos with discontinuous or degenerate motion (a common
   local-model failure mode) are rejected.
2. **Artifact detection** — flicker/morphing-artifact heuristic (frame
   difference variance outlier detection) catches the visually obvious
   failure cases before they reach a human reviewer.
3. **FPS consistency** — verify the output file's actual frame rate matches
   `VideoGenRequest.fps`; some providers silently interpolate or drop frames,
   which would otherwise desync against the planned `Shot.duration_sec`.

Failures trigger the same bounded-retry-then-fallback chain as image
generation (12-IMAGE_ENGINE), parameterized per provider's typical failure
rate (Wan2.2 retries before falling to CogVideoX, not straight to Pexels).

## Fallback Strategy

```
AI video generation (Wan2.2 → CogVideoX)
        │ exhausted (both fail validation or are unavailable)
        ▼
Pexels stock fetch (render/stock.py::fetch_broll equivalent) — keyword-matched,
        │                                                       NOT prompt-matched;
        │                                                       degrades shot specificity
        │ no usable result / API unavailable
        ▼
Static image (from Image Engine, or the existing gradient fallback) + Ken Burns
        movement (07-STORYBOARD camera vocabulary's `ken_burns` value) — guaranteed
        to always succeed, the terminal fallback that can never itself fail
```

This three-tier fallback is the direct generalization of the project's
existing two-tier reality (`compose.py`'s gradient as the only universal
fallback, `compose_ai.py`'s Pexels as the only "real visual" option) — AI
generation is inserted as the new top tier, Pexels demoted to tier 2, and
the static+Ken-Burns path retained as the unconditional last resort exactly
as `compose.py` already behaves today.

## FFmpeg Integration

FFmpeg remains the assembly/transcode layer regardless of which tier
produced a clip — the Video Engine's job ends at producing validated clip
files; Editor Agent's `EditTimeline` (06-AGENTS) drives:

- **Transcode**: normalize every clip (regardless of source provider) to a
  consistent codec/resolution/fps before concat, since Wan2.2/CogVideoX/
  Pexels/static-Ken-Burns outputs will not natively share encoding
  parameters.
- **Concat**: assemble validated segments per the planned `Shot` order.
- **Overlay**: composite caption/terminal-card/veil layers (existing
  `compose_ai.py` overlay logic) on top of whichever background tier was
  used — overlay compositing is provider-agnostic by construction.
- **Transitions**: apply whoosh/crossfade/hard-cut per Editor Agent's
  transition-type assignment (07-STORYBOARD migration notes), reusing the
  existing `render/transitions.py` module's primitives rather than
  reimplementing them.

PyAV is the recommended path for any frame-level programmatic manipulation
(e.g. quality-gate optical-flow analysis) where shelling out to the `ffmpeg`
CLI per-frame would be too slow or awkward; FFmpeg-the-binary remains the
right tool for whole-file transcode/concat/overlay operations, matching the
project's existing FFmpeg dependency (`brew install ffmpeg`, per
`CLAUDE.md`).

## Current State

`render/compose_ai.py` is the entire current "video generation" capability,
and it generates nothing — it fetches existing stock footage from Pexels via
`render/stock.py::fetch_broll(segment.broll)`, keyed by a free-text English
keyword on `Segment`, with **no caching** (a re-run with the same keyword
re-fetches from Pexels every time — see 09-ASSET_ENGINE Current State). Cut
cadence is procedural (`BEAT_TARGET_SEC=6.0`, `HOOK_BEAT_SEC=2.5`,
`MAX_VARIANTS=4` round-robin shot selection), not derived from any planned
shot list. If no Pexels API key is configured, the module fails fast rather
than falling back — there is currently no fallback chain at all, only a
single path that either works or raises.

`render/compose.py` (the non-AI variant) is the unconditional gradient+Ken-
Burns-equivalent-via-static-background fallback that already exists and
should be preserved as the new pipeline's tier-3 fallback essentially
unchanged.

`render/transitions.py` already implements the whoosh/crossfade primitives
the Editor Agent's `EditTimeline` will reuse.

## Migration: Replace Pexels Default with AI Generation

1. **Insert AI generation above Pexels, don't replace it outright.** Stand
   up `Wan2.2Provider`/`CogVideoXProvider`, wire them as tier 1/2 ahead of
   the existing `fetch_broll` call (now tier 3) behind a feature flag
   (`VIDEO_ENGINE_ENABLED`) — `compose_ai.py` keeps working exactly as today
   when the flag is off or local generation is unavailable.
2. **Add the cache layer immediately**, independent of the AI-generation
   work — wrapping the existing Pexels fetch in `AssetSpec`/`AssetRegistry`
   (09-ASSET_ENGINE) is a low-risk, immediate win (stop re-fetching
   identical keywords) that should land before or alongside the AI provider
   work, not after.
3. **Replace `BEAT_TARGET_SEC`/`HOOK_BEAT_SEC` constants with planned
   `Shot.duration_sec`** once Storyboard/Camera Director exist
   (07-STORYBOARD) — duration constraints in this document (≤6s Short, ≤15s
   long-form) become validation ceilings Camera Director must respect when
   planning, not values discovered by a fixed cadence formula at render time.
4. **Promote the fallback chain to a first-class, always-on code path** —
   today's "no Pexels key → hard fail" becomes "no Pexels key → skip
   straight to static+Ken-Burns," removing the current single point of
   failure.
5. **Quality-gate before cache-write from day one** of the AI provider
   work — unlike the image engine where Pillow overlays had no quality
   concern, AI video generation's failure modes (motion artifacts) are
   common enough on current-generation local models that shipping without
   the gate would visibly degrade output quality versus the existing
   Pexels-only baseline.
