# 01 — VISION

## Purpose

This document expands `PROJECT_VISION.md`'s mission statement into a full
picture of what "AI Native Creative Operating System" means in practice: who
it serves, what platforms it targets, how success is measured, and the
concrete milestones that take the system from its current YouTube-only state
to that end state. Where `PROJECT_VISION.md` states *what must never change*,
this document describes *what the system becomes* — the roadmap inside the
fence the vision document builds.

## What "AI Native Creative Operating System" Means

Today, `claude-ytb` is a pipeline: topic in, YouTube video out. An AI Native
Creative OS is a different shape of system — it is an **environment** in
which:

- A creative intent (a topic, a series concept, a recurring character) is a
  durable, inspectable object (`Project`), not a transient CLI argument.
- Every production decision — research findings, narrative structure, shot
  composition, voice direction, visual style — is captured as structured,
  versioned data (`project.json`), not buried in prompt strings or
  regenerated from scratch on every run.
- AI models are **orchestrated tools** the system calls at well-defined DAG
  nodes, not an opaque black box that owns the whole pipeline. A human (or a
  supervising agent) can inspect, override, or re-run any single node without
  re-running the whole pipeline.
- Output is platform-agnostic until the final `Publisher` stage — the same
  `Project` can yield a YouTube long-form video, a vertical Short, a podcast
  episode, and a blog post, because the upstream domain model never assumed
  a platform.
- The system runs primarily on local compute the creator already owns (a
  MacBook Pro M4), because creative iteration requires fast, cheap,
  always-available feedback loops — not metered API calls that throttle
  experimentation.

This is the difference between "a script that calls some AI APIs" and "an
operating system for AI-assisted creative production." The former optimizes
for shipping one video. The latter optimizes for the creator's ability to
direct, inspect, resume, and reuse creative work indefinitely.

## Target User

The primary user is a **solo or small-team content creator** who:

- Produces recurring content (a channel, a series) rather than one-off videos,
  and therefore benefits from reusable Characters, Locations, voice models,
  and narrative templates across projects.
- Wants creative control — the ability to inspect and edit an outline, a
  shot list, or a voice script before it becomes a final render — rather than
  a fully opaque "type a topic, get a video" black box.
- Is cost- and privacy-sensitive: prefers to own the compute and avoid
  recurring API billing or sending creative IP to third-party cloud services
  by default.
- Is comfortable with a CLI/config-driven workflow today, with no requirement
  for a GUI in early versions (a GUI/IDE-style surface is a plausible v5+
  extension, not a current commitment).

## Target Platforms

See `PROJECT_VISION.md` §3 for the authoritative table. In vision terms: the
system targets any platform that consumes **video, audio, or structured
text** — the four production stages (ideation, voiceover, render, publish)
are general enough to serve YouTube, Shorts, TikTok, Instagram, Podcast feeds,
blogs, and slide decks, differentiated only by render preset and `Publisher`
adapter.

## Success Metrics

| Dimension | Metric | Target |
|---|---|---|
| Offline capability | % of pipeline runnable with no network | 100% except final publish call |
| Local inference coverage | % of AI calls served by local models by default | 100% (LLM, TTS, image, video) |
| Provider swap cost | Engineering effort to add a new provider for an existing capability | New adapter file only; zero changes to domain/pipeline code |
| Resume reliability | % of interrupted runs that resume from last checkpoint without recomputation | 100% |
| Platform extensibility | Engineering effort to add a new publish target | New `Publisher` adapter + render preset only |
| Content quality | Automated quality gate pass rate before publish | No publish without passing defined quality gates (length, pacing, niche relevance) |
| Maintainability | `batch_cli.py`-class monoliths in the codebase | Zero — orchestration logic lives in composable modules, CLI is a thin entrypoint |
| Test coverage | Coverage on pipeline/domain code | ≥ 80%, currently tracked via the existing 290-case pytest suite |

## Evolution Milestones

### v1 — Current State (YouTube Pipeline)
Linear four-stage pipeline (ideation → voiceover → render → publish).
`script.json` artifact. Edge-TTS default voice, optional F5-TTS. `render.ai`
defaults to Pexels B-roll. Orchestration concentrated in `batch_cli.py`.

### v2 — Provider Abstraction + Local-First Defaults
Introduce `Provider` ports for LLM, Voice, Image, Video (see
`03-ARCHITECTURE.md`). Flip defaults: F5-TTS becomes default voice provider,
local diffusion (Flux) becomes default image/video source, Pexels demoted to
an explicitly-opted-in fallback strategy. Begin `script.json` → `project.json`
schema migration with a compatibility loader for existing v1 artifacts.

### v3 — DAG Executor + Checkpoint/Resume
Replace the implicit linear pipeline with an explicit `WorkflowGraph` of
`WorkflowNode`s, each independently checkpointed (see `05-WORKFLOW.md`).
Decompose `batch_cli.py` into an orchestrator service plus a thin CLI client.
Add structured logging (correlation IDs per `Project` run) across all stages.

### v4 — Multi-Platform Publishing + Plugin Discovery
Add `Publisher` adapters for Shorts, TikTok, Instagram, Podcast, Blog, and
Slides. Introduce a plugin registration mechanism so third-party or
experimental providers can be added without modifying core package code.

### v5 — Creative OS Surface
`project.json` becomes a fully portable, diffable, mergeable creative
artifact. `Memory` and `Checkpoint` subsystems support long-running,
multi-session creative work: recurring `Character`/`Location` reuse across
projects, persistent `KnowledgeBase` per channel or niche, and the ability to
branch/fork a project's DAG state for A/B creative exploration.
