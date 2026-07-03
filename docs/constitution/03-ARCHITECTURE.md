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
   │ Ollama/Qwen3 adapter│  │ F5-TTS adapter │  │ Flux adapter   │ │ YouTube API   │
   │ Claude API adapter  │  │ Edge-TTS adapter│ │ Pexels adapter │ │ Drive adapter │
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
derived properties and no imports of Pillow, FFmpeg, Ollama clients, or any
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
| `LLMProvider` | Ollama/Qwen3 (local, default) · Claude API (`claude_cli.py`, cloud, opt-in) |
| `VoiceProvider` | F5-TTS (`f5_provider.py`, local, default per v2) · Edge-TTS (`tts.py`, cloud-free but online) · ElevenLabs (cloud, opt-in) |
| `ImageProvider` | Flux local diffusion (default per v2) |
| `VideoProvider` | Local image-to-video / animation pipeline (default) · Pexels stock (`stock.py`, explicit opt-in fallback only, never default) |
| `RenderProvider` (composition strategy) | `compose.py` (slide/gradient strategy) · `compose_ai.py` (AI B-roll + beat-sync strategy) |
| `PublishProvider` | YouTube Data API (`uploader.py`) · Google Drive backup (`drive.py`) · (planned) TikTok, Instagram, Podcast RSS, Blog CMS adapters |

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
  │  (LLMProvider port; local Qwen3 default, Claude API opt-in)
  ▼
[VOICEOVER] VoiceScript → synthesized Audio Asset + Subtitle/timing data
  │  (VoiceProvider port; F5-TTS default, Edge-TTS/ElevenLabs opt-in)
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
