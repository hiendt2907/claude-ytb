# 12 — IMAGE ENGINE

## Purpose

Generate every still-image asset the pipeline needs — thumbnails,
backgrounds, overlays, character/location reference art — locally-first on
the MacBook Pro M4, replacing the current Pillow-gradient-only background
path with real AI image generation while keeping a uniform provider
interface so Flux today doesn't lock out SDXL, Midjourney, or DALL-E
tomorrow.

## Provider Interface

```python
from typing import Protocol
from dataclasses import dataclass


@dataclass(frozen=True)
class ImageGenRequest:
    prompt: str
    negative_prompt: str = ""
    width: int = 1024
    height: int = 1024
    seed: int | None = None
    steps: int = 25
    guidance_scale: float = 7.0
    reference_image_path: str | None = None   # for IP-Adapter/character consistency
    lora: str | None = None                     # named LoRA, if provider supports it


@dataclass(frozen=True)
class ImageGenResult:
    image_path: str
    provider: str
    model: str
    seed_used: int
    cost_usd: float
    latency_ms: int


class ImageProvider(Protocol):
    name: str
    is_local: bool

    async def generate(self, request: ImageGenRequest) -> ImageGenResult: ...
    async def health_check(self) -> bool: ...
```

Agents (06-AGENTS: Image Planner, Thumbnail Agent) never call a concrete
provider — they build an `ImageGenRequest` and submit it through the Asset
Engine (09-ASSET_ENGINE), which checks the content-hash cache before
dispatching to whichever `ImageProvider` the selection strategy resolves.

## Supported Providers

| Provider | Type | Notes |
|---|---|---|
| **Flux** (via ComfyUI) | local | Primary provider on M4. Best quality/speed tradeoff for Apple Silicon via MPS; run through a ComfyUI workflow graph (see below) rather than a bare diffusers call, for composability with upscale/control nodes. |
| **SDXL** | local | Secondary local provider — faster, lower VRAM footprint; useful fallback when Flux's workflow is unavailable or for high-volume low-stakes assets (e.g. background filler frames). |
| **Midjourney** | cloud | Opt-in only, for cases needing a specific stylistic look Flux/SDXL don't reproduce well; no API access pattern is officially supported by Midjourney, so this adapter is a manual-export-import bridge, not a live API call — flagged `is_local=False`, `health_check()` always conservative. |
| **DALL-E** (OpenAI) | cloud | Cloud fallback with a real API; used when local generation is unavailable and Midjourney's manual workflow is impractical for the run's latency needs. |

Default chain: `[flux_comfyui, sdxl_local, dalle_cloud]` — Midjourney is
excluded from automatic chains (opt-in per-asset only) given its non-API
nature.

## Image Types

| Type | Resolution profile | Notes |
|---|---|---|
| `thumbnail` | 1920×1080 | High-contrast, designed for small-size legibility (06-AGENTS Thumbnail Agent) |
| `background` | platform-dependent (`bg_portrait` 1080×1920 for Shorts, `bg_landscape` 1920×1080 for long-form) | Scene-setting imagery behind caption/overlay layers |
| `overlay` | matches target composite resolution | Caption cards, terminal cards — may still be Pillow-rendered procedurally rather than AI-generated; routed through the same Asset Engine cache regardless |
| `stickman` | `frame` 1024×1024 per keyframe | Source frames for Animation Planner's declarative motion, not full AI-video |
| `character` | `frame` 1024×1024, square for reference consistency | Canonical reference portrait per `KnowledgeGraph` character entity, generated once and reused via `reference_image_path` |
| `location` | `frame` 1024×1024 or `bg_*` depending on use | Canonical reference per `KnowledgeGraph` location entity |

## Prompt Construction

Image Planner (06-AGENTS) assembles the final prompt from three layers, in
this fixed order, so style never silently overrides subject:

1. **Subject** — the shot/frame's concrete visual description (from
   Storyboard, 07-STORYBOARD).
2. **Style guide tokens** — palette, lighting, composition rules from
   `VisualStyleGuide` (Visual Director, 06-AGENTS).
3. **Camera language** — shot type/movement/angle translated to visual
   vocabulary (e.g. `close_up` → "tight framing, shallow depth of field").

```
{subject}, {style_tokens}, {camera_language}
```

**Negative prompts** carry a project-wide baseline (extending and never
fully overriding) plus per-request additions:

```
baseline_negative = "blurry, low quality, watermark, text artifacts, deformed hands, extra limbs"
```

Image Planner appends to, never replaces, this baseline — a request that
needs "no text overlay" adds it as an additional negative term rather than
constructing a negative prompt from scratch, keeping quality-floor
guarantees consistent across every generated image.

## Resolution Profiles

| Profile | Dimensions | Aspect | Use |
|---|---|---|---|
| `thumbnail` | 1920×1080 | 16:9 | YouTube thumbnail |
| `bg_portrait` | 1080×1920 | 9:16 | Shorts/TikTok background |
| `bg_landscape` | 1920×1080 | 16:9 | Long-form background |
| `frame` | 1024×1024 | 1:1 | Default square working resolution — character/location refs, stickman keyframes |

Profiles are a named lookup table (`RESOLUTION_PROFILES: dict[str, tuple[int, int]]`)
consumed by `ImagePlanner`, never hardcoded width/height literals scattered
through agent code — adding a platform (e.g. Instagram's 4:5) is a one-line
table addition.

## Quality Gate

Run automatically inside the Asset Engine's `validate` step
(09-ASSET_ENGINE) before an image is cached:

1. **Blur detection** — Laplacian-variance check (OpenCV); below-threshold
   images are rejected and regenerated, not silently accepted.
2. **NSFW check** — a local lightweight classifier (CLIP-based safety
   classifier running on MPS) gates every generated image before it can
   enter the cache, independent of the provider's own safety filtering
   (defense in depth, never trust a single layer).
3. **Consistency check** — for images tagged with `continuity_refs`
   (07-STORYBOARD), embedding similarity (CLIP/DINO) against the canonical
   reference image must clear a similarity threshold; below threshold routes
   to Continuity Agent (06-AGENTS) as a flagged violation rather than a hard
   reject, since some drift may be an acceptable stylistic choice a human
   should confirm.

A failed blur/NSFW check triggers up to 2 regenerations with a bumped seed
before falling back to the next provider in the chain (mirroring 10-LLM_ENGINE's
retry/fallback shape, applied to image generation).

## Content-Hash Caching

Every `ImageGenRequest` is wrapped in an `AssetSpec` (09-ASSET_ENGINE) before
dispatch — `asset_type="image"`, `provider` set to whichever `ImageProvider`
handles it, `prompt`/`negative_prompt`/`seed`/`params` (width, height, steps,
guidance_scale, lora) all included in the hash. **The same prompt is never
regenerated twice** for the same provider/params combination — this is the
single highest-leverage cost/latency optimization available given how
repetitive style-guide-driven prompts are across a series (the same
character reference, the same background style, reused across many
episodes).

## ComfyUI Integration

Flux generation runs through a ComfyUI workflow graph rather than a bare
model call, so upscale, IP-Adapter (character consistency), and ControlNet
(composition guidance) nodes compose without bespoke per-feature Python code:

```python
@dataclass(frozen=True)
class ComfyUIWorkflow:
    workflow_json_path: str        # template stored in assets/template/
    node_mapping: dict[str, str]    # logical name -> ComfyUI node id, e.g.
                                      # {"prompt": "6", "negative_prompt": "7",
                                      #  "seed": "3", "width": "5", "height": "5"}


class ComfyUIProvider:
    """ImageProvider implementation backed by a running local ComfyUI server."""

    name = "flux_comfyui"
    is_local = True

    def __init__(self, workflow: ComfyUIWorkflow, base_url: str = "http://127.0.0.1:8188"):
        ...

    async def generate(self, request: ImageGenRequest) -> ImageGenResult:
        # 1. load workflow_json_path
        # 2. substitute request fields into the nodes per node_mapping
        # 3. POST to ComfyUI's /prompt endpoint, poll /history for completion
        # 4. download the output image, return ImageGenResult
        ...
```

Workflow JSON files are version-pinned `template`-type assets
(09-ASSET_ENGINE) — a workflow change (e.g. adding an upscale node) is a new
template file, not an in-place edit, so historical runs referencing the old
workflow remain reproducible.

## Current State

There is **no AI image generation today**. `render/compose.py` draws
gradient backgrounds procedurally with Pillow (`ImageDraw`), and
`render/compose_ai.py` substitutes a Pexels-fetched B-roll video frame
instead of a gradient — neither path generates a novel image from a prompt.
Caption cards, terminal cards, and the danger-highlight red tint are all
Pillow-drawn overlays composited at render time, not cached or
content-addressed.

## Migration Path

1. **Stand up `ComfyUIProvider` against a local Flux checkpoint first** —
   validate the M4/MPS performance characteristics (latency, memory
   headroom alongside Ollama running concurrently) before any agent code
   depends on it.
2. **Replace `compose_ai.py`'s gradient/Pexels background with a generated
   `background` image** behind a feature flag (`IMAGE_ENGINE_ENABLED`),
   so the existing Pexels path remains the safe fallback during the
   transition rather than being deleted outright.
3. **Migrate overlay drawing (caption/terminal cards) last, if at all** —
   these are simple, fast, deterministic Pillow draws that don't benefit
   meaningfully from AI generation; they are good candidates to stay
   procedural indefinitely, just wrapped in the Asset Engine's cache for
   consistency of addressing (not for quality reasons).
4. **Introduce `character`/`location` reference generation once
   `KnowledgeGraph` (06-AGENTS Research Agent / Continuity Agent) exists** —
   this is a net-new capability with no current equivalent; it should not be
   retrofitted onto the existing flat `Segment` model, only onto the Scene
   Engine's `characters` field (08-SCENE_ENGINE) once that lands.
5. **Wire the quality gate (blur/NSFW/consistency) before any generated
   image reaches `compose_ai.py`'s compositor** — this is a hard
   prerequisite, not an optional enhancement, given the channel publishes
   publicly and the project's existing advertiser-friendly/COPPA compliance
   discipline (`ComplianceCheck` in `pkg/models.py`) must extend to visual
   content, not just text.
