# 30 — Roadmap

## Purpose

This document maps `29-MIGRATION_PLAN.md`'s phases onto product-level
versions and approximate calendar targets. It is the answer to "where are
we going and by when," at a granularity suitable for prioritization
decisions — not the file-level tactical detail, which lives in
`IMPLEMENTATION_ROADMAP.md` (repo root).

## Version Milestones

### v1.0 (current) — YouTube Automation

Linear 4-stage pipeline (ideation → voiceover → render → publish).
`script.json` artifact. Edge-TTS default voice. `render.ai` defaults to
Pexels B-roll. Orchestration concentrated in
`src/ytb_pipeline/orchestrator/batch_cli.py` (1330 lines). 290 tests, 80%
coverage.

### v1.1 (Q3 2026) — Refactor

Maps to `29-MIGRATION_PLAN.md` Phase 0. Split `batch_cli.py` into
`QueueManager`/`PipelineRunner`/`LedgerWriter`/`OAuthManager`. Provider
registry (minimal form). `structlog` JSON logging with correlation IDs.
Pydantic validators on `Settings`.

### v1.2 (Q3 2026) — Project Model

Maps to Migration Plan Phase 1 + Phase 2. Full `ProviderRegistry` with
`Protocol` interfaces for Voice/Render/Publish. `project.json` introduced
alongside a `script.json` compatibility loader. `CheckpointManager` and
`CacheManager` live; DAG checkpoint/resume working for the existing linear
stages treated as coarse-grained nodes.

### v2.0 (Q4 2026) — AI Image Generation

Maps to Migration Plan Phase 3. `FluxProvider` (local ComfyUI) becomes the
default `render.ai` image source. Pillow-gradient slide backgrounds
replaced by AI-generated scene images. Pexels demoted to an explicit,
non-default opt-in strategy — satisfying `PROJECT_VISION.md`'s "no stock
video as default" non-negotiable decision in practice, not just in policy.

### v2.1 (Q4 2026) — Stickman Engine

Implements `15-STICKMAN_ENGINE.md` (currently spec-only, not implemented):
LLM-authored `StickmanScene` pose/action sequences, SVG → PNG frame
rendering, timed against voiceover segment duration, handed to the Render
Engine as a clip source alongside Flux-generated images and any
explicitly-opted-in stock footage.

### v3.0 (Q1 2027) — Multi-Platform

Maps to Migration Plan Phase 4. `PlatformProfile` enum
(`youtube_short`/`youtube_long`/`tiktok`/`instagram_reel`/`podcast`/`blog`).
Platform-aware metadata adapters. At least one new `PublishProvider`
beyond YouTube/Drive shipped (TikTok).

### v3.1 (Q1 2027) — Agent System

Maps to Migration Plan Phase 5. Ideation decomposes into `ResearchAgent` +
`StoryArchitectAgent` + `StoryboardAgent`, each independently testable and
independently swappable on underlying LLM provider.

### v4.0 (Q2 2027) — Full Local Stack

Ollama/Qwen3 becomes the default ideation/research LLM, replacing the
`claude -p` subprocess invocation as the default path (Claude API/CLI
remains available as an explicit opt-in fallback, consistent with
`PROJECT_VISION.md`'s local-inference-priority decision, not removed
outright). F5-TTS is the default voice provider (Edge-TTS demoted to
fallback). Flux is the default image provider (already true from v2.0).
Wan2.2 (or the best available local image-to-video/animation model at the
time) becomes the default B-roll/video-generation source, closing the loop
on "no stock video as default" for motion content as well as stills.

### v5.0 (2027+) — AI Native Studio

`project.json` is a fully portable, diffable, mergeable creative artifact.
`Memory` (`23-MEMORY_SYSTEM.md`) and `Checkpoint` (`25-CHECKPOINT_SYSTEM.md`)
subsystems support long-running, multi-session creative work: recurring
`Character`/`Location` reuse across projects, a persistent per-channel
`KnowledgeBase`, and the ability to branch/fork a project's DAG state for
A/B creative exploration. This is the point at which "a pipeline that makes
videos" has fully become "an operating system for AI-assisted creative
production," per `01-VISION.md`'s framing.

## Sequencing Notes

- Versions are listed in dependency order, not strict calendar
  independence — v2.0 cannot ship meaningfully ahead of v1.2 because AI
  image generation needs the cache system (to avoid re-generating identical
  images every run) and the provider registry (to be swappable) that v1.2
  establishes.
- Calendar quarters are targets, not commitments with externally imposed
  deadlines — this is a single-operator project; a quarter slipping does
  not cascade into contractual risk, but the **dependency order between
  versions** must not be skipped (e.g., shipping "Multi-Platform" before
  "Project Model" would mean building platform-specific publish adapters
  against a domain model still mid-migration, which is straightforwardly
  more expensive than doing it in order).
- Any version that would require relaxing a `PROJECT_VISION.md`
  Non-Negotiable Decision to ship on schedule must slip the schedule, not
  the decision (see `29-MIGRATION_PLAN.md`'s Cross-Phase Constraints).
