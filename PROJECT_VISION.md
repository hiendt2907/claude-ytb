# PROJECT VISION

**Status: IMMUTABLE.** This document records decisions that define what this
project *is*. It is not a roadmap to be revised when convenient — it is the
constitution the roadmap must obey. Any change to a "Non-Negotiable Decision"
requires an explicit, written amendment in this file (with rationale and date),
never a silent drift through code.

---

## 1. Mission

`claude-ytb` is evolving from a YouTube-only automation pipeline into an
**AI Native Creative Operating System** — an engine that turns a topic into
finished, platform-ready content (video, audio, slides, text) through a
pipeline of swappable AI providers. It runs orchestration and rendering
primarily on a single MacBook Pro M4; under the 2026-08-24 amendment, its
default LLM and voice paths depend on xKiro cloud reachability. It remains
independent of third-party stock-media libraries by default.

The system's job is not "upload videos to YouTube." Its job is: **take a
creative intent, run it through a deterministic, checkpointed, resumable DAG
of AI-assisted production stages, and emit assets for any platform** —
YouTube today, Shorts/TikTok/Instagram/Podcast/Blog/Slides tomorrow — without
ever requiring the pipeline architecture itself to change.

## 2. Non-Negotiable Decisions

These decisions are fixed. Code, dependencies, and providers must be chosen
to honor them — never the reverse.

1. **Offline-first (amended 2026-08-24 for LLM + voice — see Amendment Log).**
   Render and publish-prep must remain runnable with zero internet
   connectivity except for the final publish step. LLM reasoning and
   text-to-speech are **excluded** from this requirement as of the
   2026-08-24 amendment: both are cloud-primary (xKiro) by design, so the
   MacBook itself only has to run workflow orchestration and the render
   pipeline, not inference. Any feature that hard-requires a cloud API for
   render/publish-prep is still a defect, not a feature.

2. **Cloud-primary inference for LLM + voice; local-first elsewhere (amended
   2026-08-26 — see Amendment Log).** Ideation uses only xKiro with
   Gemini 3.7 Flash; an xKiro failure stops generation and is never silently
   substituted with Codex or Claude. Text-to-speech defaults to xKiro. Image
   generation and video generation are unaffected by this amendment and keep
   local inference as the default (Flux/local diffusion).
   Any provider substitution must still be explicit via config, never a
   silent runtime branch outside the `Provider` port.

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

1. **Matches the approved capability policy.** xKiro is cloud-primary for
   LLM and TTS; visual generation and render remain local-first.
2. **Open weights / open source where local compute is the default** — avoids
   vendor lock and licensing risk for image/video/render paths.
3. **Swappable behind a `Provider` port** — no direct coupling in domain code.
4. **Has an explicit failure policy** appropriate to the capability;
   ideation is intentionally pinned to xKiro/Gemini 3.7 Flash and stops on
   failure rather than changing model/provider.

Current/target stack by capability:

| Capability | Local option | Cloud option |
|---|---|---|
| LLM reasoning (ideation, outline, research synthesis) | — (see Amendment 2026-08-26) | **xKiro / Gemini 3.7 Flash only** |
| Voice synthesis | F5-TTS (still available, opt-in) | **xKiro (default)**, Edge-TTS, ElevenLabs |
| Image generation | Flux (local diffusion) | — |
| Video generation | Local image-to-video / animation pipeline | — |
| B-roll / stock fallback (explicit opt-in only) | — | Pexels |
| Render/composition | Pillow + FFmpeg (always local) | — |
| Publish | — | YouTube Data API, Google Drive (network is inherent to publishing) |

## 5. Evolution Path

- **v1 (legacy):** YouTube-only pipeline. `script.json` artifact. Edge-TTS
  default, Pexels-backed `render.ai` path, monolithic `batch_cli.py`.
- **v2 (historical, 2026-07-06):** `Provider` ports for LLM/Voice/Image/
  Video/Publish/Render **done** (`providers/base.py` protocols +
  `providers/registry.py`, no if/elif branching). F5-TTS was then the default
  voice provider; the 2026-08-24 amendment supersedes that default with xKiro.
  Still outstanding: Pexels remains the default `render.ai`
  B-roll source (`settings.video_provider`/`broll_strategy = "pexels"`,
  confirmed live in `render/compose_ai.py`) — local diffusion has not
  replaced it as default yet. `script.json` → `project.json` migration:
  the domain model (`project/models.py`, `project/checkpoint.py`,
  `project/workflow.py`) is wired into the production orchestrator — see
  v3.
- **v3 (wired, 2026-07-23):** DAG executor is live in production. Each
  video's per-node state (`input`/`voiceover`/`audio_quality`/`render`/
  `render_quality`/`publish`) is driven by `pipeline.run_project` →
  `project/workflow.py::WorkflowGraph` (Kahn topo-sort) +
  `project/checkpoint.py::CheckpointManager` (atomic write,
  pending/running/done/failed), checkpointed per-project at
  `assets/projects/<slug>/project.json`. `python -m ytb_pipeline` (the
  subprocess `batch_cli.py`'s `run`/`retry` commands spawn) is the entry
  point into this DAG; stale nodes (missing output file, old dry-run
  publish) are reset automatically before resume
  (`pipeline._reset_stale_nodes`). `assets/auto_state.json` remains the
  **batch-level** queue (video ordering, `publish_at` scheduling) — that is
  a legitimate, separate concern from a single video's per-node DAG state
  and is not itself technical debt. `batch_cli.py` was 883 lines
  (over the 400-line limit) as of 2026-07-23; see the refactor tracked in
  this same change for its current shape.
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
  core pipeline). **Amended 2026-08-24 for LLM + TTS only** (see Amendment
  Log): those two stages now require xKiro (cloud SaaS) reachability by
  default; render/publish-prep remain constraint-compliant.
- Every external network call outside the publish stage must be explicit in
  provider/config design. The approved exception is the default-enabled xKiro
  LLM/TTS path (`allow_cloud_providers=true`); it is recorded in the Amendment
  Log rather than hidden behind a runtime branch.
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
- 2026-08-24 — Amends Decision #1 (Offline-first) and #2 (Local inference
  priority) for LLM reasoning and text-to-speech only. **Rationale:**
  offload the MacBook from running local LLM/TTS inference so it only runs
  workflow orchestration and the render pipeline — explicit operator
  request. **Change:** `settings.llm_provider` and `settings.tts_provider`
  default to `"xkiro"` (cloud, OpenAI-compatible aggregator). LLM ideation
  gets an automatic CLI fallback chain (xKiro → Codex CLI → Claude CLI) via
  `orchestrator/ideation_provider_cascade.py::CascadeScriptProvider`.
  `providers/llm/ollama_provider.py` and `providers/llm/mlx_provider.py` are
  **deleted** — no local LLM provider remains in the codebase.
  `providers/local_stack.py` (`OMNI_LOCAL` shortcut) is deleted as dead code
  (it hard-coded Ollama and was never called from the pipeline).
  `settings.allow_cloud_providers` defaults to `true` (previously `false`)
  so a fresh checkout doesn't silently revert `tts_provider` back to `f5` via
  `Settings.model_post_init`. **Unaffected:** image generation (Flux) and
  video generation remain local-first per Decision #2; render/publish-prep
  remain offline-capable per Decision #1. **Known risk (see
  docs/TOOL_UPGRADE_PLAN.md):** xKiro is a third-party aggregator with no
  prior track record known to the operator at amendment time; its model
  catalog (`GET /v1/models`) lists branded model names that 403 on the
  current free-tier key. The operator explicitly accepted this risk after
  review.
- 2026-08-26 — Amends the LLM ideation policy only. **Rationale:** the
  operator requires a single known model and must be able to trust the
  provenance and quality of every generated script. **Change:** ideation is
  pinned to xKiro model `google/gemini-3.7-flash` (Gemini 3.7 Flash); its
  model fallback list and the
  Codex CLI → Claude CLI fallback path are removed. An unavailable or failed
  xKiro request now stops the command with its original error. This does not
  alter xKiro TTS, visual generation, rendering, or publishing. **Verified
  access state:** the configured xKiro key returns HTTP 403 for this gateway
  model (and HTTP 403 for `GET /v1/models`), so ideation cannot run until the
  xKiro account grants access; this is an account entitlement, not a fallback
  condition.
