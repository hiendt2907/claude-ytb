# PROJECT VISION

**Status: IMMUTABLE.** This document records decisions that define what this
project *is*. It is not a roadmap to be revised when convenient — it is the
constitution the roadmap must obey. Any change to a "Non-Negotiable Decision"
requires an explicit, written amendment in this file (with rationale and date),
never a silent drift through code.

---

## 1. Mission

`claude-ytb` is evolving from a YouTube-only automation pipeline into an
**AI Native Creative Operating System** — a local-first engine that turns a
topic into finished, platform-ready content (video, audio, slides, text)
through a pipeline of swappable AI providers, running primarily on a single
MacBook Pro M4 with no dependency on cloud uptime, cloud billing, or
third-party stock-media libraries.

The system's job is not "upload videos to YouTube." Its job is: **take a
creative intent, run it through a deterministic, checkpointed, resumable DAG
of AI-assisted production stages, and emit assets for any platform** —
YouTube today, Shorts/TikTok/Instagram/Podcast/Blog/Slides tomorrow — without
ever requiring the pipeline architecture itself to change.

## 2. Non-Negotiable Decisions

These decisions are fixed. Code, dependencies, and providers must be chosen
to honor them — never the reverse.

1. **Offline-first.** The full pipeline (ideation → voiceover → render →
   publish-prep) must be runnable with zero internet connectivity except for
   the final publish step. Any feature that hard-requires a cloud API for a
   non-publish stage is a defect, not a feature.

2. **Local inference priority.** For every AI capability — LLM reasoning,
   text-to-speech, image generation, video generation — the *default*
   provider must be a model running locally (Ollama/Qwen3 for text, F5-TTS
   for voice, Flux/local diffusion for images). Cloud providers (Claude API,
   ElevenLabs, Pexels, etc.) are **opt-in fallbacks**, selected explicitly by
   config, never silently substituted as the default path.

3. **No stock video as default.** Pexels (or any third-party stock-footage
   API) must never be the default B-roll source. AI-generated visuals
   (image-to-video, diffusion-rendered scenes, animated stickman/storyboard
   frames) are the default `render.ai` path. Stock footage may exist as one
   strategy among several, selected explicitly, never as the fallback when
   AI generation is "too slow" or "too hard."

4. **Plugin providers for every external capability.** LLM, Image
   generation, Video generation, and Voice synthesis are each defined by a
   `Provider` interface (port) with one or more adapters. Adding a new
   provider must never require touching domain logic, pipeline stages, or
   other providers' code. A provider is a plugin: discoverable, replaceable,
   independently testable.

5. **`script.json` → `project.json` evolution.** The artifact that anchors a
   piece of content evolves from a flat script document into a structured
   `project.json` that captures the full DAG state: research, outline,
   narrative, scenes, shots, prompts, assets, render jobs, and checkpoints.
   This is a planned schema migration, not a parallel format — `project.json`
   is the canonical successor to `script.json`.

6. **DAG + checkpoint + resume.** The pipeline is modeled as a directed
   acyclic graph of named nodes (Topic → Research → ... → Publisher). Every
   node's output is checkpointed to disk before the next node runs. A failed
   or interrupted run must be resumable from the last successful checkpoint
   without recomputation of upstream nodes. This is mandatory for every
   pipeline stage, not an optimization added later.

7. **Platform independence.** The domain model (Project, Narrative, Scene,
   Asset, Timeline, etc.) must carry no platform-specific assumptions.
   Publishing is a final adapter stage (`Publisher` provider) per target
   platform. Adding TikTok or Podcast support must mean writing a new
   `Publisher` adapter and platform-specific render preset — never modifying
   ideation, voiceover, or core render logic.

## 3. Platform Targets

| Platform | Status | Notes |
|---|---|---|
| YouTube (long-form) | Active | Current production target |
| YouTube Shorts | Active | Shares pipeline, different render preset (9:16, ≤60s) |
| TikTok | Planned | New `Publisher` adapter only |
| Instagram Reels | Planned | New `Publisher` adapter only |
| Podcast (audio-only) | Planned | Skips render-video, ships voiceover + music mix |
| Blog / article | Planned | Skips voiceover/render, ships narrative as text |
| Slides / carousel | Planned | Render stage emits static frames, no video encode |

## 4. Technology Stack Priorities

Priority order when choosing or evaluating a dependency, highest first:

1. **Runs fully local on Apple Silicon (M4)** — no network call required.
2. **Open weights / open source** — avoids vendor lock and licensing risk.
3. **Swappable behind a `Provider` port** — no direct coupling in domain code.
4. **Cloud equivalent exists as an opt-in adapter** — for cases where local
   quality/speed is insufficient (e.g., highest-fidelity voice clone,
   batch image generation beyond local GPU/NPU throughput).

Current/target stack by capability:

| Capability | Local (default) | Cloud (opt-in) |
|---|---|---|
| LLM reasoning (ideation, outline, research synthesis) | Ollama + Qwen3 | Claude API |
| Voice synthesis | F5-TTS (Vietnamese fine-tuned voice clone) | Edge-TTS, ElevenLabs |
| Image generation | Flux (local diffusion) | — |
| Video generation | Local image-to-video / animation pipeline | — |
| B-roll / stock fallback (explicit opt-in only) | — | Pexels |
| Render/composition | Pillow + FFmpeg (always local) | — |
| Publish | — | YouTube Data API, Google Drive (network is inherent to publishing) |

## 5. Evolution Path

- **v1 (legacy):** YouTube-only pipeline. `script.json` artifact. Edge-TTS
  default, Pexels-backed `render.ai` path, monolithic `batch_cli.py`.
- **v2 (in progress, 2026-07-06):** `Provider` ports for LLM/Voice/Image/
  Video/Publish/Render **done** (`providers/base.py` protocols +
  `providers/registry.py`, no if/elif branching). F5-TTS is now the default
  voice provider. Still outstanding: Pexels remains the default `render.ai`
  B-roll source (`settings.video_provider`/`broll_strategy = "pexels"`,
  confirmed live in `render/compose_ai.py`) — local diffusion has not
  replaced it as default yet. `script.json` → `project.json` migration:
  the new domain model exists (`project/models.py`,
  `project/checkpoint.py`, `project/workflow.py`) but is not wired into the
  production orchestrator yet (see v3).
- **v3 (partially built, not wired):** DAG executor exists —
  `project/workflow.py::WorkflowGraph` (Kahn topo-sort) +
  `project/checkpoint.py::CheckpointManager` (atomic write, per-node
  pending/running/done/failed). `batch_cli.py` has been decomposed (1330 →
  382 lines) but still runs the old linear `assets/auto_state.json` state
  machine — it does not yet call into `WorkflowGraph`/`CheckpointManager`.
  Next step for v3 completion: wire `batch_cli.py` (or its successor) to the
  DAG executor instead of maintaining two parallel state systems.
- **v4:** Multi-platform `Publisher` adapters (Shorts, TikTok, Instagram,
  Podcast). Plugin discovery/registration mechanism for third-party
  providers.
- **v5:** Creative OS surface — project.json becomes a portable, inspectable,
  diff-able creative artifact; Memory/Checkpoint subsystem enables long-running
  multi-session creative projects (series, recurring characters, persistent
  knowledge base) independent of any single platform.

## 6. Constraints

- Must run end-to-end on a single MacBook Pro M4 (no required external
  compute, no required GPU server, no required SaaS subscription for the
  core pipeline).
- Every external network call outside the publish stage must be guarded by
  an explicit config flag — never a hidden default.
- Domain objects (`models.py` / `pkg/models.py`) remain **frozen
  dataclasses** — immutability is structural, not a style preference.
- No pipeline stage may directly import a concrete provider SDK
  (`google-api-python-client`, `elevenlabs`, `pexels`, etc.) — only the
  `Provider` port interface. Concrete SDKs live exclusively in adapter
  modules.
- Backward compatibility: `script.json` artifacts already produced under v1
  must remain loadable (via a migration adapter) when `project.json` becomes
  canonical.

---

*Amendments to Section 2 require a dated changelog entry below. No other
section overrides Section 2.*

### Amendment Log

- 2026-06-29 — Initial ratification of all seven Non-Negotiable Decisions.
