# 02 — PRINCIPLES

## Purpose

This document defines the principles that govern every design and code
decision in `claude-ytb` — independent of which specific module is being
touched. `03-ARCHITECTURE.md` describes the resulting structure; this
document explains *why* that structure is the right one, and gives a
decision framework for the recurring question that comes up in nearly every
change: local model or cloud API?

## Engineering Principles

### SOLID

- **Single Responsibility.** Each pipeline stage module (`ideation/`,
  `voiceover/`, `render/`, `publish/`) owns exactly one production concern.
  `orchestrator/batch_cli.py` violates this today (it mixes CLI parsing,
  orchestration, and stage invocation in ~1330 lines) — this is a known
  defect to resolve per the v3 milestone in `01-VISION.md`, not a pattern to
  replicate.
- **Open/Closed.** Adding a new TTS engine, image generator, or publish
  target must never require editing existing provider code — only adding a
  new adapter that implements the relevant `Provider` port.
- **Liskov Substitution.** Any adapter implementing a `Provider` port
  (`LLMProvider`, `VoiceProvider`, `ImageProvider`, `VideoProvider`,
  `PublishProvider`) must be substitutable for any other adapter of that
  port without the calling pipeline stage changing behout up to documented
  capability differences (e.g., a `VoiceProvider` that doesn't support voice
  cloning must declare that capability, not silently no-op).
- **Interface Segregation.** Provider ports expose the minimal method set a
  pipeline stage actually needs (e.g., `synthesize(text, voice) -> Audio`),
  not a kitchen-sink interface mirroring one specific SDK's full surface.
- **Dependency Inversion.** Pipeline/domain code depends on `Provider`
  abstract interfaces defined in the application layer. Concrete SDKs
  (Edge-TTS, F5-TTS, YouTube Data API, Pexels) are injected as adapters at
  the infrastructure boundary. No domain or pipeline module imports a
  concrete SDK directly.

### Clean Architecture

Dependencies point inward only: Interface → Application → Domain. The domain
layer (frozen dataclasses in `04-DOMAIN.md`) has zero dependencies on
anything outside itself — no Pillow, no FFmpeg, no Google API client, no
Ollama client. See `03-ARCHITECTURE.md` for the full layer diagram.

### DRY

Shared cross-stage logic (config loading, checkpoint serialization, provider
resolution, structured logging) lives in a shared kernel
(`src/ytb_pipeline/pkg/`), not duplicated per stage. The existing
`pkg/models.py` for frozen dataclasses is the precedent to extend, not a
one-off.

### YAGNI

Provider ports are added when a second real implementation exists or is
imminently planned (e.g., add the `VoiceProvider` port now because both
Edge-TTS and F5-TTS already exist) — not speculatively for capabilities with
no second implementation in sight. Plugin discovery infrastructure (v4) is
deferred until multiple platform `Publisher`s actually exist, per the
milestone sequencing in `01-VISION.md`.

## AI-Native Principles

### LLM as Orchestrator Input, Never as Hidden Control Flow

LLM calls produce **data** (an outline, a script, a research summary) that
flows into the next deterministic DAG node. An LLM call must never itself
decide *which* pipeline node runs next, retry logic, or checkpoint behavior —
that control flow is explicit code in the orchestrator (`05-WORKFLOW.md`),
auditable without re-running a model.

### Human-in-the-Loop at Quality Gates

Per `ideation/approval.py`'s existing precedent, certain DAG nodes (notably
after Outline/Narrative generation and before Publish) support an explicit
approval checkpoint. This is a first-class workflow concept (see
`05-WORKFLOW.md` checkpoint types), not an ad hoc CLI prompt — human approval
state must be checkpointed and resumable exactly like any other node output.

### Fail-Fast on Quality, Not on Infrastructure Flakiness

Distinguish two failure classes:

1. **Content quality failure** (script too short, niche mismatch, banned
   topic) — fail fast, do not retry with the same inputs, surface to the
   human/approval gate.
2. **Infrastructure failure** (local model server unreachable, transient
   FFmpeg crash, network blip on publish) — retry with backoff per the node's
   declared retry strategy (`05-WORKFLOW.md`), then checkpoint the failure
   state for resume rather than crashing the whole run.

### Checkpoints Are Not Optional

Every DAG node must checkpoint its output before the pipeline proceeds. This
is not a performance optimization — it is the mechanism that makes long,
expensive, partially-cloud-dependent pipelines safe to interrupt, debug, and
resume without burning compute or API budget twice.

## Content Principles

### Quality Gates Before Publish

No `Project` reaches the `Publisher` stage without passing defined quality
gates: minimum/maximum length, pacing checks (existing
`test_length_gate.py`, `test_intro_gate.py` precedent), and niche/topic
relevance scoring. Quality gates are pipeline nodes with their own
pass/fail/retry semantics, not implicit checks buried inside render code.

### Niche Enforcement

A `Project` is associated with a niche/channel identity from the
`KnowledgeBase`/`Research` stage onward. Ideation prompts, voice style, and
visual style are constrained by that niche — generic, niche-agnostic output
is treated as a quality-gate failure, not an acceptable fallback when a
model "doesn't have anything better."

### No Generic AI Output

Scripts, narration, and visuals must reflect the specific `Research` and
`KnowledgeBase` gathered for that `Project`. A narrative or image prompt that
could be produced identically regardless of input topic indicates the
ideation/visual-planning stage is not actually conditioning on upstream DAG
state — this is a defect to fix at the prompt-construction layer, not a
property to tolerate.

## Decision Framework: Local vs. Cloud AI

Apply in this order when choosing or configuring a provider for any
capability:

1. **Is there a local model that meets the quality bar for this capability
   today?** If yes, it is the default. (Per `PROJECT_VISION.md` §2.2, this
   is non-negotiable — the question is "is the bar met," not "is cloud
   better.")
2. **Does the task have a hard latency or throughput requirement the local
   M4 cannot meet** (e.g., batch-generating hundreds of images faster than
   local diffusion can produce them)? If yes, a cloud adapter may be
   selected **explicitly**, by config, for that run — never silently
   substituted as a new default.
3. **Is the capability inherently networked** (publishing to YouTube,
   pulling trending-topic research from a live API)? Then a cloud call is
   expected and not subject to the local-first rule — but it must still be
   isolated behind a `Provider`/`Publisher` port so it remains swappable and
   testable with a fake/mock adapter.
4. **Never let cost or developer convenience alone justify defaulting to
   cloud.** "Cloud is easier to set up" is not a valid reason to violate
   §2.2 of `PROJECT_VISION.md` — if local setup friction is the real
   blocker, fix the setup tooling (`make setup-f5` is the existing
   precedent), not the default provider.
