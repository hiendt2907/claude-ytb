# PROJECT VISION

**Status: IMMUTABLE.** This document records decisions that define what this
project *is*. It is not a roadmap to be revised when convenient — it is the
constitution the roadmap must obey. Any change to a "Non-Negotiable Decision"
requires an explicit, written amendment in this file (with rationale and date),
never a silent drift through code.

> **AMENDMENT (2026-07-07) — Mission narrowed to render-only tool.**
> Sections 1–5 below describe the original "AI Native Creative OS" mission
> (ideation → voiceover → render → publish, full YouTube automation). That
> mission is **superseded**. As of 2026-07-07 the project's mission is the
> narrower one stated in the Amendment Log at the bottom of this file. Ideation,
> voiceover/TTS, and publish concerns described below are **out of scope**
> going forward — kept here only as historical/reference context for anyone
> reading old code paths (`ideation/`, `voiceover/`, `publish/`). Do not use
> the text below to justify new work in those directories; see the Amendment
> Log for the current mission.
>
> **AMENDMENT (2026-07-09) — Mission re-expanded: this project is now the
> render core of an end-to-end content pipeline (script → voice → Pexels →
> render → publish), NOT render-only anymore.** The 2026-07-07 "out of
> scope: ideation/voiceover/publish" line above is **superseded again**. See
> the 2026-07-09 Amendment Log entry at the bottom for full rationale — in
> short: rather than duplicating ideation/Pexels/publish logic in a second
> project, the existing `claude-ytb` logic was ported (rate-of-reuse, not
> rewrite) into a new `content/` package that wraps this project's
> `assembler/*` render engine, which is kept 100% unchanged.

---

## 1. Mission (superseded — see Amendment 2026-07-07 above)

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
- 2026-07-07 — **Mission narrowed: render-only tool for KOL/KOC/affiliate
  video production.** Rationale: the "AI Native Creative OS" mission
  (ideation/voiceover/publish, full YouTube automation) is no longer the
  goal; the user redefined the project's purpose to a local video assembler
  — a CapCut replacement, not a content-ideation/publishing pipeline.
  Sections 1–5 above (Mission, Non-Negotiable Decisions 1–3 and 5–7,
  Platform Targets, Tech Stack, Evolution Path) are **superseded** except
  where explicitly reaffirmed below.

  **New Mission:** Given a set of **scene folders** (one folder per scene in
  the final video, each folder holding multiple candidate raw source video
  clips for that scene) and **one voiceover track** for the whole video
  (single voice, selected by the user, applies to one affiliate-product
  video end-to-end), render **N finished output videos** (N chosen by the
  user, e.g. 5/10/15) by combinatorially assembling one clip per scene per
  output, synced to the fixed voice track. Primary use case: KOL/KOC/
  affiliate creators who need many distinct video variants from the same
  shoot without manually editing each one in CapCut.

  **What remains true from the original decisions:** Provider Pattern for
  swappable capabilities (Decision 4) is still a reasonable architectural
  default if/when providers are reintroduced, but is not mandatory scope —
  this project has no LLM/TTS/publish provider by mission definition.
  Immutable domain objects (`frozen dataclass`) and no-hardcoded-path
  conventions from `CLAUDE.md` Coding Standards still apply.

  **Explicitly out of scope now:** ideation (topic/script generation),
  voiceover synthesis (TTS) — voice files are a user-supplied input, not
  generated by this project — and publish/upload to any platform. This
  project's job ends at "finished rendered video file(s) on disk."

  **Not yet decided (flag before implementing):** exact selection strategy
  for "1 clip per scene per output" (random without repeat across the N
  outputs? weighted? user-curated shortlist per scene?), output naming/
  directory convention, and whether audio-duration-per-scene must be
  derived from voice-track silence/segment detection or supplied explicitly
  by the user per scene. See `docs/handoffs/` or ask the user before coding
  against an assumption here.

- 2026-07-09 — **Mission re-expanded: render core of an end-to-end content
  pipeline, not a render-only tool anymore.** Rationale: the user wants one
  continuous UI flow — Claude writes the script, edge-tts reads it, Pexels
  auto-fetches matching B-roll per script segment, this project's existing
  assembler renders it (unchanged), and the result publishes straight to
  YouTube with a scheduled `publish_at` — instead of operating this project
  and `claude-ytb` as two separate, overlapping tools (both would otherwise
  need their own ideation/Pexels/publish logic).

  This repo (`claude-ytb/video-render/`) is a **copy** of the original
  `~/Documents/video-render` project, made 2026-07-09 at the user's explicit
  request ("copy video-render về đây để làm, vì nó là core, cấm thao tác
  trên đó"). The Documents copy is the reference source and must not be
  edited going forward; all new work happens on this copy.

  **What changed:** a new `content/` package (`script_gen.py`,
  `voiceover.py`, `pexels_fetch.py`, `publish.py`, `youtube_auth.py`,
  `jobs.py`) was added, plus `webui/content_routes.py` wiring them into the
  existing `webui/jobs.py` render job machinery. **What did NOT change:**
  `assembler/*` (scanning, assignment, cutting, duration, render, profiles,
  smart_trim) — the N-variant candidate-per-scene selection algorithm from
  the 2026-07-07 amendment is fully preserved; Pexels now auto-populates
  scene folders with multiple candidates per scene instead of the user
  manually curating them, but the algorithm operating on those folders is
  untouched.

  **Reused, not reinvented:** script generation prompt/CLI-call pattern,
  edge-tts synthesis (parallelized, x2 rate), Pexels stock-fetch logic, and
  YouTube OAuth/upload/`publish_at` scheduling were all ported (simplified,
  re-scoped) from `claude-ytb`'s existing `orchestrator/`, `voiceover/`,
  `render/stock.py`, and `publish/` modules rather than rewritten from
  scratch. YouTube OAuth credentials/token are the SAME ones `claude-ytb`
  uses (copied into `video-render/secrets/`, gitignored) — same channel, by
  explicit user decision, not a fresh OAuth app.

  **Still explicitly out of scope:** multi-platform publish beyond YouTube;
  AI-generated (non-stock) B-roll — Pexels stock footage remains the source,
  matching `claude-ytb`'s own known technical debt on this point (see
  `claude-ytb/CLAUDE.md` invariant #3).

- 2026-07-09 (amendment 2) — **Auto topic-discovery + QA gate + ledger
  dedup, ported selectively from claude-ytb's ideation system after a full
  audit.** Rationale: the user asked "did you wire in Claude auto-searching
  for a topic" — it hadn't been (topic was always user-typed). Before
  coding, a thorough audit of `claude-ytb`'s `ideation_cmd.py`,
  `ideation/generator.py`, `ideation/research.py`, `ideation/series.py`,
  `ideation/approval.py`, and all `agents/*.py` (incl. `qa_agent.py`) was
  done and reported back; the user then picked exactly 3 of 4 offered scopes
  to port: (1) trending topic auto-search, (2) a QA quality gate, (3) ledger-
  style dedup against prior topics. Telegram approval gate and the 30-day
  series scheduler were explicitly NOT requested and were not ported.

  **What was ported (simplified/re-scoped, not copy-pasted verbatim):**
  `content/research.py` (YouTube mostPopular + autocomplete — the only real
  "auto topic search" mechanism that exists anywhere in claude-ytb; there is
  no competitor analysis or general web search), `content/ledger.py` (just
  `slugify` + dedup from `ideation/series.py`, with the 30-day scheduling
  machinery deliberately dropped as unneeded here), `content/qa.py` (a
  narrow subset of `agents/qa_agent.py`'s rule-based checks — length,
  self-help-mantra blocklist, stage-direction leak, weak visual_keywords,
  ledger dedup, unsourced-claim warning — rescoped to this project's
  Short-only, compliance-free `Script` schema; hook-strength/entertainment-
  retention/compliance checks from the original were NOT ported, they don't
  apply to this simpler schema).

  **Important finding surfaced during the audit, worth remembering:** in
  `claude-ytb` itself, `qa_agent.py`'s "3-gate ngách" (self-help ban / idea
  density / sourced claims) is only PARTIALLY code-enforced — idea-density-
  per-chapter has no code check at all, and sourced-claims is a warning, not
  a block. The same limitation carries over here: `content/qa.py`'s
  sourced-claims check is a warning too, not a hard gate. This is a known,
  accepted gap, not an oversight.

  **New pipeline behavior:** every script — whether typed by hand, generated
  from a user topic, or auto-discovered — now passes through
  `content/jobs.py::_ensure_qa_passed` before voice/pexels/render begin.
  Failing QA triggers up to 3 automatic repair round-trips to Claude
  (`script_gen.repair_script`) before the job is marked failed. A passing
  script is appended to `data/content_ledger.json` (gitignored local state,
  mirroring how claude-ytb treats `data/ledger.md`) so future auto-discovery
  and dedup checks see it.
