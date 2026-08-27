# 03 — ARCHITECTURE

## Purpose

This document specifies the layered, hexagonal structure of `claude-ytb`:
which code belongs in which layer, how dependencies are allowed to point,
where ports and adapters live, how data flows across the four production
stages, and where the system is designed to be extended. It is the
structural implementation of the principles in `02-PRINCIPLES.md` and the
non-negotiable decisions in `PROJECT_VISION.md`.

## Layered + Hexagonal Overview

```
                         ┌─────────────────────────────────────────┐
                         │            INTERFACE LAYER               │
                         │  CLI (batch_cli) · Telegram listener ·   │
                         │  (future) HTTP API / TUI                 │
                         └───────────────────┬───────────────────────┘
                                             │ invokes
                         ┌───────────────────▼───────────────────────┐
                         │           APPLICATION LAYER                │
                         │  Orchestrator · WorkflowGraph executor ·   │
                         │  Checkpoint manager · Provider resolver    │
                         └───┬──────────┬──────────┬──────────┬───────┘
                  uses ports │          │          │          │
        ┌──────────────────▼─┐ ┌──────▼─────┐ ┌──▼───────┐ ┌▼────────────┐
        │   LLMProvider port  │ │VoiceProvider│ │ImageProv. │ │PublishProv. │
        └──────────┬───────────┘ └─────┬──────┘ └────┬──────┘ └──────┬──────┘
                   │                    │              │               │
   ┌───────────────▼──┐   ┌────────────▼───┐  ┌───────▼────────┐ ┌────▼─────────┐
   │ INFRASTRUCTURE     │   │ INFRASTRUCTURE │  │ INFRASTRUCTURE │ │ INFRASTRUCTURE│
   │ xKiro adapter       │  │ xKiro adapter  │  │ Flux adapter   │ │ YouTube API   │
   │ Codex/Claude CLI    │  │ F5/Edge adapters│ │ Pexels adapter │ │ Drive adapter │
   └─────────────────────┘   └────────────────┘  └────────────────┘ └───────────────┘

                         ┌─────────────────────────────────────────┐
                         │              DOMAIN LAYER                 │
                         │  Frozen dataclasses: Project, Research,   │
                         │  Outline, Narrative, Scene, Shot, Asset,  │
                         │  Timeline, RenderJob, PublishJob, ...     │
                         │  Zero outward dependencies.               │
                         └─────────────────────────────────────────┘
```

Dependency rule: arrows of *knowledge* point inward only. Interface knows
about Application. Application knows about Domain and depends on Provider
ports (interfaces it defines). Infrastructure adapters know about Domain and
implement Provider ports — but Application and Domain never import
Infrastructure directly.

## Layer Definitions

### Domain Layer

Location: `src/ytb_pipeline/pkg/models.py` (current), to be expanded per
`04-DOMAIN.md`. Pure data: frozen dataclasses with no behavior beyond simple
derived properties and no imports of Pillow, FFmpeg, provider clients, or any
SDK. This layer encodes the non-negotiable platform independence from
`PROJECT_VISION.md` §2.7 — it must never contain a YouTube-specific field
bolted onto a generic concept.

### Application Layer

Location: `src/ytb_pipeline/orchestrator/` (current `batch_cli.py`, to be
decomposed per `01-VISION.md` v3). Owns:

- The `WorkflowGraph` executor — walks `WorkflowNode`s in dependency order.
- The checkpoint manager — persists/loads node outputs (`05-WORKFLOW.md`).
- The provider resolver — reads `config/settings.py` (Pydantic) and
  constructs the configured adapter for each `Provider` port, by name.
- Stage coordinators for ideation, voiceover, render, publish — each
  coordinates calls to its `Provider` port and produces/consumes Domain
  objects. These currently live partially in `ideation/`, `voiceover/`,
  `render/`, `publish/` — those packages are Application-layer coordinators
  plus their own Infrastructure adapters today; the target state (v2)
  separates the coordinator (Application) from the SDK-calling adapter
  (Infrastructure) within each.

This layer defines the `Provider` port interfaces themselves (e.g., an
abstract `LLMProvider.generate(prompt: str) -> str`), since ports are
*application* contracts that infrastructure must satisfy — this is the
Dependency Inversion half of hexagonal architecture.

### Infrastructure Layer

Location: concrete adapter modules — `voiceover/tts.py` (Edge-TTS),
`voiceover/f5_provider.py` (F5-TTS), `render/stock.py` (Pexels),
`render/compose.py` / `render/compose_ai.py` (Pillow/FFmpeg),
`publish/uploader.py` (YouTube Data API), `publish/drive.py` (Google Drive),
`claude_cli.py` (Claude API). Each adapter implements exactly one Provider
port and contains all SDK-specific code (auth, request/response shapes,
SDK-specific error handling). No other layer imports these modules directly
— only the provider resolver in the Application layer instantiates them, by
configured name.

### Interface Layer

Location: `orchestrator/batch_cli.py` (CLI entrypoint, to shrink to a thin
client per v3), `listener.py` (Telegram control surface), `notify/telegram.py`
(notifications out). This layer translates an external trigger (CLI args, a
Telegram command) into an Application-layer call (start/resume a `Project`
run) and translates Application-layer results back into human-facing output
(console text, Telegram messages). It contains no business logic — no
quality-gate decisions, no provider selection logic.

## Ports and Adapters (Hexagonal Detail)

| Port (interface, owned by Application) | Adapters (Infrastructure, implement the port) |
|---|---|
| `LLMProvider` | xKiro (cloud, default) · Codex CLI → Claude CLI (ideation fallback cascade) |
| `VoiceProvider` | xKiro (cloud, default) · F5-TTS (local opt-in) · Edge-TTS / ElevenLabs (configured alternatives) |
| `ImageProvider` | Flux local diffusion (default per v2) |
| `VideoProvider` | Local image-to-video / animation pipeline (default) · Pexels stock (`stock.py`, explicit opt-in fallback only, never default) |
| `RenderProvider` (composition strategy) | `compose.py` (slide/gradient strategy) · `compose_ai.py` (local Pexels-origin B-roll + beat-sync strategy) · `story.py` (profile-owned character illustrations + multi-voice timeline) |
| `PublishProvider` | YouTube Data API (`uploader.py`) · Google Drive backup (`drive.py`) · (planned) TikTok, Instagram, Podcast RSS, Blog CMS adapters |

### Content profile boundary (implemented 2026-08-25)

`profiles/<profile_id>/` is the unit of topic configuration. It owns editorial
prompts, format bounds, provider selection, voice cast, renderer timing, local
assets, and optional series continuity. The shared queue stores `profile_id` on
each item and `PipelineRunner.build_env()` resolves an isolated environment for
that subprocess before the normal DAG starts. There is no profile-specific DAG.

This is separate from `platform/profiles.py`: a content profile answers what
and how to tell; a platform profile answers where and under which publishing
constraints to deliver it. Adding a topic must be a data-directory operation,
not a branch in pipeline/domain code.

### Content profile — extended contract (added 2026-08-26/27, generalized 71-commit line)

A `profile.json` may declare, beyond the base fields above:

- **`format_prompts`** (`{"short": "<prompt name>", "long": "<prompt name>"}`)
  — lets a profile give the Short and the Long transcript a *different*
  structural prompt (e.g. `long-transcript-structure.md` vs
  `short-funnel-structure.md`) instead of one undifferentiated `editorial`
  prompt for both. Validated at load time: every name referenced must exist
  in `prompts`; only `short`/`long` are legal keys.
- **`editorial_review`** (`{"enabled", "rubric_prompt_name", "minimum_score",
  "max_rewrites"}`) — an **opt-in** LLM-judged quality gate, separate from
  the deterministic `qa_agent.py` heuristics (see
  `38-EDITORIAL_QUALITY_LAYERS.md` for the boundary between the two).
  Implemented in `agents/editorial_review_agent.py`: scores a script 0-10 on
  five fixed dimensions (`human_truth`, `spoken_naturalness`,
  `causal_coherence`, `role_fidelity`, `useful_restraint`), cached by
  `(profile_fingerprint, script content hash)` so an unchanged script is
  never re-reviewed. A profile that never declares this block triggers zero
  extra LLM calls — existing profiles are unaffected unless they opt in.
- **`content_rules.allow_short_generation`** (default `true`) — a series can
  stop producing *new* Shorts while keeping every already-rendered Short
  readable (`ContentProfile.supports_generation()` separates "can this
  format still be generated" from "can this format still be loaded").
- **`content_rules.story_primary_speaker_id` /
  `story_supporting_speaker_id`** — a `character_story` profile names its own
  two-cast role contract instead of the engine assuming any fixed speaker
  keys; empty (default) keeps the older, more permissive cast contract.
- **`content_rules.long_opening_mode`** (`channel_greeting` | `pain_first` |
  `story_context`) and **`short_ending_mode`** (`final_action` |
  `funnel_bridge`) — the opening/closing shape of a Long or Short is a
  per-profile editorial choice, not a hardcoded channel-wide convention.
- **`content_rules.require_next_episode_bridge`** — a serialized story can
  require its closing to name what continues into the next episode.

### Profile version snapshots

`profiles/<profile_id>/versions/<semver>/` holds an immutable copy of
`profile.json` (and any versioned prompt/bible files) taken at the moment the
active `version` field was bumped. `load_content_profile(profile_id,
version=...)` resolves a specific snapshot so an already-rendered or archived
script keeps working against the exact contract it was produced under, even
after the active profile has moved on. Every profile that bumps its version
is expected to keep a matching snapshot directory — this is a convention
enforced by consistent authoring, not (yet) a loader-level check.

Each port is a small, focused interface (Interface Segregation per
`02-PRINCIPLES.md`) — e.g. `VoiceProvider` exposes `synthesize(script:
VoiceScript) -> Asset` and a `capabilities()` descriptor (supports cloning?
supports SSML? max input length?), not the full surface of any one TTS SDK.

## Data Flow Across Stages

```
Topic
  │
  ▼
[IDEATION]  Research → KnowledgeBase → Outline → Narrative → Story/Script
  │  (LLMProvider port; xKiro default, then Codex CLI → Claude CLI on failure)
  ▼
[VOICEOVER] VoiceScript → synthesized Audio Asset + Subtitle/timing data
  │  (VoiceProvider port; xKiro default; local F5 remains explicit opt-in)
  ▼
[RENDER]    Scene/Shot/Frame plans → ImagePrompt/VideoPrompt → visual Assets
            → Timeline assembly → RenderJob → final video Asset
  │  (ImageProvider/VideoProvider/RenderProvider ports; local diffusion
  │   default, Pexels stock opt-in only)
  ▼
[PUBLISH]   Asset + metadata → PublishJob → platform upload + Drive backup
  │  (PublishProvider port; network call is inherent here)
  ▼
Published content + analytics feedback (future: feeds back into Memory/KB)
```

Every arrow above is also a checkpoint boundary — see `05-WORKFLOW.md` for
the exact node list and checkpoint contract. The `Project` object accumulates
state as it flows top to bottom; nothing downstream is recomputed from raw
inputs if its upstream checkpoint already exists.

## Timeline — story renderer (Phase 1 MVP, added 2026-08-27)

`src/ytb_pipeline/render/timeline.py` introduces the ordering the render
layer must follow for the `story` renderer (`render/story.py`):

```
Narration  = timing authority   (Segment.duration_sec, measured by TTS)
Timeline   = deterministic derived execution plan (render/timeline.py)
Renderer   = Timeline consumer  (render/story.py translates it into FFmpeg)
```

`Timeline` (and its `VideoClip`/`NarrationClip`/`Transition` parts) is plain
domain data — no shell strings, no FFmpeg filter graphs, no LLM prose, no
provider configuration — built once via `build_story_timeline(voiceover,
profile, ...)` before any FFmpeg call, and validated at construction time
(`Timeline.__post_init__`): clip counts must match 1-1 between the video and
narration tracks, `transitions` must cover every clip boundary exactly once,
overlap must be shorter than its neighbouring clips, and the video/narration
tracks' computed expected durations must agree within one frame. This is a
structural fix for the production 2026-08-26 incident (162 caption-card
crossfades applied as if they were 20 section boundaries, silently dropping
55s/14% of narration, see `docs/handoffs/2026-08-26-story-renderer-caption-
transition-fix-handoff.md`) — that specific shape of bug is now a
`TimelineError` raised before any `ffmpeg` process starts, not a discrepancy
discovered by probing the finished `.mp4`.

`Timeline` is a **derived artifact, not a competing source of truth**: it is
rebuilt deterministically from `Voiceover`/`Segment` + the profile's
`render` contract on every render, and persisted only as a debug/postmortem
JSON next to the render's own output (`assets/output/<slug>_timeline.json`,
alongside the existing `<slug>_thumb.jpg` convention) — never inside
`scripts/<slug>.json` or `assets/projects/<slug>/project.json`.

Scope note: v1 derives directly from the existing `Voiceover`/`Segment`
structure (one clip per script section — no `ScenePlan` yet, see
`docs/handoffs/2026-08-27-ai-content-factory-architecture-assessment.md`
§N/O for that later phase). Only `render/story.py` consumes it in this
phase; `compose.py`/`compose_ai.py` are unchanged.

## Extension Points

- **New AI provider for an existing capability**: implement the relevant
  `Provider` port in a new Infrastructure module; register it in
  `config/settings.py`'s provider name → adapter mapping. No Application or
  Domain code changes required.
- **New publish platform**: implement `PublishProvider` for that platform
  plus a render preset (aspect ratio, duration limits, caption style) in the
  render stage's preset table. No upstream stage changes required.
- **New domain object** (e.g., a new `SFX` or `Memory` subtype): add the
  frozen dataclass to the Domain layer per `04-DOMAIN.md`'s conventions;
  wire it into the relevant `WorkflowNode`'s input/output contract in
  `05-WORKFLOW.md`.
- **New quality gate**: add a `WorkflowNode` with a boolean pass/fail output
  inserted into the DAG before the node it gates (typically before
  Storyboard finalization or before Publish) — gates are first-class DAG
  nodes, not inline `if` statements inside another stage's code.
- **New interface surface** (HTTP API, TUI): add a new Interface-layer
  module that calls the same Application-layer orchestrator entrypoints
  `batch_cli.py` and `listener.py` already call — it must not duplicate
  orchestration logic.
