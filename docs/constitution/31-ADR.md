# 31 — ARCHITECTURE DECISION RECORDS

## Purpose

This document records the *why* behind decisions already encoded as fact in
`02-PRINCIPLES.md`, `03-ARCHITECTURE.md`, `04-DOMAIN.md`, and the engine
documents. Those documents state the decision; this document preserves the
context, trade-off analysis, and rejected alternatives so a future
contributor (including future us) does not silently re-litigate or
accidentally reverse a decision without realizing what it cost to reach.

Format: each ADR is immutable once `Accepted`. A changed decision is recorded
as a *new* ADR that supersedes the old one — the old ADR's `Status` updates
to `Superseded`, with a pointer. ADRs are never edited to pretend a decision
was always the current one.

---

## ADR-001: Frozen dataclasses over Pydantic models for domain objects

**Status:** Accepted
**Date:** 2026-06-29

**Context:** The Domain layer (`04-DOMAIN.md`) needed a representation for
`Project`, `Scene`, `Asset`, and ~25 other objects that is cheap to
construct, safe to pass across the DAG executor's node boundaries, and
incapable of silent in-place mutation once a `WorkflowNode` has consumed it.
Pydantic was the obvious incumbent choice — it is already a transitive
dependency via FastAPI-adjacent tooling familiarity, and offers built-in
JSON schema generation and validation.

**Decision:** Domain objects are `@dataclass(frozen=True)`, not Pydantic
`BaseModel`. Validation that Pydantic would give for free is pushed to the
boundary — the Application layer validates inputs *before* constructing the
frozen dataclass, per `02-PRINCIPLES.md`'s "validate at the edge, trust the
core" rule.

**Consequences:**
- Easier: domain objects have zero runtime dependency surface — no Pydantic
  version coupling, no metaclass magic, `mypy --strict` checks them exactly
  like any stdlib dataclass. Object identity and equality are structural and
  predictable. `frozen=True` makes the immutability principle
  (`PROJECT_VISION.md` §6) a language-enforced invariant, not a convention
  someone can forget.
- Harder: no automatic `.json()`/`.parse_obj()` — `project.json`
  serialization (`23-MEMORY_SYSTEM.md`, `25-CHECKPOINT_SYSTEM.md`) requires
  hand-written `asdict()`-based encoders/decoders per object, and nested
  `Optional`/`tuple` fields need explicit decode logic. Field-level
  validation (e.g., "`pacing_wpm` must be positive") is not declarative; it
  lives in small constructor-adjacent factory functions instead of being
  colocated with the field declaration.

**Alternatives considered:**
- *Pydantic `BaseModel` with `frozen=True` config* — rejected because
  Pydantic's mutation guard is a runtime config flag, not a structural
  property; a future contributor flipping that flag silently reintroduces
  mutability with no `mypy` signal. Also rejected to keep the Domain layer's
  zero-outward-dependency rule (`03-ARCHITECTURE.md`) literal, not
  aspirational — Domain code that imports Pydantic is one dependency away
  from importing an HTTP-serialization concern into a layer that must never
  know what HTTP is.
- *attrs with `frozen=True`* — viable, marginally less stdlib-native than
  `dataclasses`, no compelling advantage given the project already has zero
  attrs usage; rejected on YAGNI grounds.
- *Plain mutable classes with discipline* — rejected outright; "don't mutate
  it" as a code-review convention is exactly the failure mode immutability
  is meant to eliminate per `02-PRINCIPLES.md`.

---

## ADR-002: Claude CLI subprocess vs direct Anthropic SDK

**Status:** Accepted (current state); superseded at v2 milestone (planned)
**Date:** 2026-06-29

**Context:** `claude_cli.py` currently shells out to the `claude` CLI binary
as a subprocess to obtain LLM completions when the cloud-opt-in `LLMProvider`
path is used (Ollama/Qwen3 is the local default per `03-ARCHITECTURE.md`).
This was the fastest path to a working cloud fallback during early
development — no API key plumbing, no SDK dependency, reuses the
developer's already-authenticated `claude` CLI session.

**Decision:** Keep subprocess invocation as the *current* `LLMProvider`
cloud adapter. Plan, but do not yet implement, a direct `anthropic` Python
SDK adapter as a second cloud `LLMProvider` implementation at the v2
milestone (`01-VISION.md`).

**Consequences:**
- Easier (now): zero new dependency, zero key-management code, works
  immediately in any environment where the CLI is already authenticated —
  appropriate for a solo-creator local tool in early development.
- Harder (now): subprocess calls are slow (process spawn overhead per call),
  fragile (CLI output format is not a stable contract — a CLI version bump
  can silently change stdout shape and break the adapter), and impossible to
  stream tokens through, which blocks any future "live progress" UX
  (`34-EVENT_BUS.md` §3 `ProgressEvent` granularity is capped at "subprocess
  finished," not per-token).
- Easier (after v2 SDK adapter): explicit API key config (already a pattern
  the project uses for `publish/uploader.py` OAuth), streaming responses,
  typed error handling (rate limit vs auth vs server error distinguished by
  exception type, not stderr string-matching), and a stable contract
  pinned by SDK semver instead of a CLI's incidental stdout format.

**Alternatives considered:**
- *Direct SDK now, skip subprocess entirely* — rejected for v1 because it
  adds key-management surface (`27-CODING_STANDARD.md` secret-handling
  rules) before the cloud LLM path was even proven necessary; the local
  Ollama/Qwen3 path is the default and the cloud path exists only as an
  escape hatch for harder reasoning tasks the local model handles poorly.
  Premature SDK integration would have been speculative generality (YAGNI).
- *HTTP calls to Anthropic's REST API directly, no SDK* — rejected; the SDK
  exists specifically to avoid hand-rolling retry/backoff/streaming/error
  taxonomy that the SDK already gets right.

---

## ADR-003: Edge-TTS as default voice vs F5-TTS local

**Status:** Accepted (current state); superseded at v2 milestone (planned, see `01-VISION.md`)
**Date:** 2026-06-29

**Context:** `voiceover/tts.py` (Edge-TTS) is the current default
`VoiceProvider`; `voiceover/f5_provider.py` (F5-TTS, local) exists as an
opt-in alternative. This appears to contradict the offline-first manifesto
(`PROJECT_VISION.md` §1) at first read — Edge-TTS is a Microsoft cloud
service, not a local model.

**Decision:** Edge-TTS remains the default for v1 specifically because it
requires zero local model weights, zero GPU/NPU scheduling, and produces
consistently high-quality Vietnamese prosody today, which F5-TTS's local
Vietnamese voice cloning quality has not yet matched in informal testing
during early development. The default flips to F5-TTS at the v2 milestone
(`01-VISION.md` "Provider Abstraction + Local-First Defaults") once F5-TTS
Vietnamese voice quality is validated against a fixed quality bar.

**Consequences:**
- Easier (now): no model download, no local inference latency, immediately
  usable on a fresh machine, predictable voice quality for the niches this
  project currently targets (Vietnamese self-development/explainer content).
- Harder (now): every voiceover call is a network call — this is the one
  acknowledged exception to "100% offline" in `01-VISION.md`'s success
  metrics table ("100% except final publish call" is aspirationally
  inaccurate today; Edge-TTS is a second exception until the v2 flip).
  Voice cloning (a `Character.voice_id` reusable across projects per
  `04-DOMAIN.md`) is not available via Edge-TTS's stock voices, blocking the
  full Character-reuse vision until F5-TTS becomes default.
- Easier (after v2 flip): true offline voiceover, custom voice cloning per
  `Character`, no per-call network dependency or latency variance.

**Alternatives considered:**
- *F5-TTS default now, accept lower quality* — rejected; shipping
  noticeably worse Vietnamese narration to validate an architectural
  principle (offline-first) before the model is ready would trade content
  quality for ideological purity, contradicting the "Content quality" success
  metric in `01-VISION.md` which is not subordinate to the offline metric.
- *ElevenLabs as default* — rejected as default (remains an opt-in adapter
  only); highest quality but explicitly cloud, paid-per-call, and the
  furthest possible choice from local-first, reserved for cases where a
  creator explicitly wants premium voice cloning and accepts the cost/privacy
  trade-off.

---

## ADR-004: Pexels B-roll as current default vs AI-generated video

**Status:** Accepted (current state); superseded at v2 milestone (planned)
**Date:** 2026-06-29

**Context:** `render/stock.py` (Pexels) is currently the default visual
source `render.ai` falls back to. Local image-to-video generation (Flux for
stills, a local animation/video step per `13-VIDEO_ENGINE.md`) exists in the
target architecture but is not yet the default, because Apple Silicon M4
local diffusion/video generation throughput is not yet fast enough to
produce a full Short's worth of unique visuals within an acceptable
iteration loop for early development.

**Decision:** Pexels stock footage remains the v1 default `VideoProvider`
fallback. Local diffusion (Flux for images, a local animate/video pipeline)
becomes default at v2, with Pexels demoted to an explicitly-opted-in
fallback strategy (`01-VISION.md`) — not removed, since stock footage
remains useful for B-roll genres (news-style explainer cutaways) where fully
custom AI visuals add no value over well-tagged stock.

**Consequences:**
- Easier (now): fast iteration, no GPU/NPU contention with the LLM and TTS
  models running concurrently on the same M4, immediately usable visual
  variety via Pexels' tag search.
- Harder (now): visual style is not under full creative control — Pexels
  clips are licensed stock, not original IP backing the channel's visual
  brand; this directly conflicts with the v5 "Creative OS" vision of fully
  authored `Character`/`Location` visual identity reused across episodes
  (`04-DOMAIN.md` `Character.visual_style_prompt` cannot meaningfully apply
  to a stock clip).
- Easier (after v2 flip): full visual brand consistency, `Character`/
  `Location` style prompts actually drive every frame, true offline render
  path (closing the one remaining gap in `01-VISION.md`'s offline success
  metric on the render side).

**Alternatives considered:**
- *Force local diffusion now regardless of throughput* — rejected; would
  make a single Short's render time impractical for daily iteration on the
  target M4 hardware, harming the "fast, cheap, always-available feedback
  loop" goal in `01-VISION.md` more than the stock-footage compromise harms
  it.
- *Cloud video generation (Runway, Pika) as the non-Pexels alternative* —
  rejected outright as a *default*; available only as a future opt-in cloud
  `VideoProvider` adapter, consistent with the cost/privacy stance in
  ADR-010.

---

## ADR-005: Markdown ledger vs SQLite for audit trail

**Status:** Accepted (current state); migration path defined
**Date:** 2026-06-29

**Context:** The system needs a durable record of what happened to a
`Project` — which nodes ran, which AI calls were made, what a human approved
or rejected via Telegram. The simplest possible implementation is an
append-only `ledger.md` file per project, human-readable in any text editor
or `git diff`.

**Decision:** `ledger.md` (append-only Markdown) is the v1 audit trail.
SQLite (`assets/traces.db` per `36-AI_GOVERNANCE.md`) is introduced
alongside it once `AITrace` records need to be *queried* (e.g., "which model
generated the script for episode 42") rather than merely read top-to-bottom.
The ledger is not deleted when SQLite arrives — it remains the
human-skimmable summary; SQLite becomes the queryable detail store.

**Consequences:**
- Easier (now): zero schema, zero migration tooling, trivially diffable in
  git, readable without any tool besides a text editor — appropriate when
  the only consumer of the audit trail is a human skimming what a single
  project did.
- Harder (now): no query capability. "Show me every project where the
  Image Provider fell back to Pexels" requires grepping every `ledger.md`
  across every project directory — `O(n)` file scans, not an indexed query.
  No structured joins between a ledger entry and the `Asset`/`Checkpoint`
  records it refers to.
- Easier (after SQLite introduction): indexed queries across all projects,
  joins to `Asset`/`AITrace` records, the governance queries in
  `36-AI_GOVERNANCE.md` §2 become possible.

**Alternatives considered:**
- *SQLite from day one* — rejected for v1; introducing a database schema
  before there is more than one project to query across is premature
  infrastructure for a single-creator tool still validating its core
  pipeline (YAGNI, `02-PRINCIPLES.md`).
- *JSON Lines log file instead of Markdown* — considered as a middle
  ground; rejected because it loses the "human can open this and read it
  directly" property that Markdown gives for free, and the structured-query
  need is better served by going straight to SQLite rather than a halfway
  format that is neither readable nor queryable.

---

## ADR-006: Sequential batch processing vs parallel

**Status:** Accepted (current state); scaling roadmap defined
**Date:** 2026-06-29

**Context:** `batch_cli.py` processes a batch of `Project`s strictly
sequentially — one full pipeline run completes (or fails) before the next
begins. The hardware target is a single MacBook Pro M4; the local LLM
(Ollama/Qwen3), local TTS (F5-TTS), and local image/video diffusion models
all compete for the same GPU/NPU and unified memory pool.

**Decision:** Keep batch processing strictly sequential across `Project`s
for v1–v3. Parallelism is scoped *within* a single project's DAG (concurrent
independent branches, per `05-WORKFLOW.md`'s `VoicePrompt` vs
`ScenePlanning→VideoPrompt` branches) — never across multiple projects'
heavy model invocations simultaneously.

**Consequences:**
- Easier: no resource-contention bugs between two projects' concurrent local
  model calls thrashing the same unified memory pool; predictable, bounded
  memory/thermal footprint; checkpoint/resume semantics per
  `05-WORKFLOW.md`/`25-CHECKPOINT_SYSTEM.md` stay simple because only one
  project's DAG executor is ever live.
- Harder: a batch of N projects takes roughly N times one project's
  wall-clock time; there is no throughput benefit from idle CPU while one
  project is GPU-bound on image generation, even though that idle CPU could
  in principle be doing another project's LLM-bound research stage.

**Alternatives considered:**
- *Full parallel batch processing now* — rejected; on a single M4 the local
  model adapters are not designed for concurrent invocation safety
  (`10-LLM_ENGINE.md`, `12-IMAGE_ENGINE.md` assume one in-flight request),
  and the realistic ceiling is thermal/memory-bound regardless, so the
  complexity cost of adapter-level concurrency control would buy little.
- *Process-pool parallelism across projects, gated to "non-GPU stages only"
  (e.g., run Research for project 2 while project 1 renders)* — the
  legitimate future scaling path; deferred to a post-v3 milestone once the
  DAG executor (v3) exists and node-level resource tagging (`provider_port`
  on `WorkflowNode`, per `04-DOMAIN.md`) can express "this node is
  GPU-exclusive" vs "this node is CPU/network-bound and safe to interleave."

---

## ADR-007: Telegram as human-in-loop interface vs web UI

**Status:** Accepted
**Date:** 2026-06-29

**Context:** Several pipeline stages require human approval (script
approval before render, publish confirmation per the quality-gate pattern in
`05-WORKFLOW.md`). The target user is a solo creator (`01-VISION.md`) who is
not necessarily sitting at the machine running the pipeline when an approval
gate is reached — a multi-hour render can finish at any time.

**Decision:** Telegram (`listener.py`, `notify/telegram.py`) is the
human-in-the-loop interface for v1–v4. No web UI is built before the v5
"Creative OS Surface" milestone.

**Consequences:**
- Easier: push notifications work from any device the creator already
  carries, zero new infrastructure (no server, no auth system, no hosting
  decision for a UI that would need to be reachable from outside the
  MacBook); approval is a button tap, not a context switch into opening a
  browser tab and navigating to a dashboard.
- Harder: no rich visual review surface — approving a script is reviewing
  text in a chat bubble, not a formatted document; approving a render means
  trusting a thumbnail/short clip Telegram can embed, not a full scrubber;
  inherently single-user-at-a-time interaction model, which is fine for the
  current solo-creator target but would not scale to a small team reviewing
  the same project concurrently.
- Bounded scope: Telegram remains a *notification and approval* surface, not
  an authoring surface — editing an outline or shot list happens by editing
  `project.json`/config directly today, not through a chat command grammar
  that would need to express arbitrary structured edits.

**Alternatives considered:**
- *Local web UI (e.g., a small FastAPI + HTMX dashboard) now* — rejected for
  v1–v4; building and maintaining a UI surface before the underlying domain
  model (`04-DOMAIN.md`) and DAG executor (`05-WORKFLOW.md`) have stabilized
  would mean redesigning the UI every time the domain model changes shape —
  premature surface-building. `01-VISION.md` v5 explicitly scopes a
  GUI/IDE-style surface as a "plausible v5+ extension, not a current
  commitment."
- *Email-based approval* — rejected; lacks Telegram's structured
  inline-button affordance for approve/reject, would require parsing
  free-text replies for what is fundamentally a binary/small-enum decision.
- *Slack* — functionally similar to Telegram; rejected only because Telegram
  has a simpler bot API for a single-developer integration and the creator's
  existing personal workflow already centers on Telegram per the target-user
  profile.

---

## ADR-008: Provider Pattern over hard-coded if/else

**Status:** Accepted
**Date:** 2026-06-29

**Context:** `batch_cli.py` (1330 lines) currently contains direct,
hard-coded branching logic for which TTS engine, which image source, and
which render strategy to use per run — provider selection is interleaved
with orchestration logic rather than being a clean seam. This is the
specific monolith smell `01-VISION.md`'s "Maintainability" success metric
names directly ("zero `batch_cli.py`-class monoliths" as the target state).

**Decision:** Formalize the Provider Pattern (`21-PROVIDER_SYSTEM.md`):
every swappable capability (LLM, Voice, Image, Video, Render, Publish) is an
abstract port defined in the Application layer, with named adapter
implementations in Infrastructure, resolved by a config-driven provider
resolver (`03-ARCHITECTURE.md`). `batch_cli.py`'s direct branching is
decomposed into this resolver plus per-stage coordinators as part of the v2
milestone.

**Consequences:**
- Easier: adding a new provider for an existing capability (e.g., a new
  cloud TTS adapter) requires exactly one new Infrastructure module plus one
  config registry entry — zero changes to orchestration code, per the
  "Provider swap cost" success metric in `01-VISION.md`. Testing a stage in
  isolation means injecting a fake/stub adapter behind the port, not
  mocking deep into `batch_cli.py`'s control flow.
- Harder: one extra layer of indirection to trace through when debugging —
  "which adapter actually ran" requires checking the resolved config, not
  just reading the call site. Slightly more boilerplate per capability (a
  port interface plus at least one adapter) versus a single inline
  `if provider == "edge_tts":` branch.

**Alternatives considered:**
- *Strategy objects passed as constructor args, no named registry* —
  considered; rejected because it pushes provider *selection* logic back
  into whatever code constructs the coordinator, which is exactly the smell
  being removed from `batch_cli.py` — the named, config-driven registry
  keeps selection declarative and centralized in `config/settings.py`.
- *Plugin-only approach, no built-in providers* — rejected; current
  providers (Ollama, Edge-TTS, F5-TTS, Pexels, Flux) are core to the
  product, not third-party extensions; the Plugin System (`22-PLUGIN_SYSTEM.md`)
  is for genuinely optional/experimental providers layered on top of this
  pattern, not a replacement for it.

---

## ADR-009: DAG + checkpoint vs linear pipeline

**Status:** Accepted; not yet implemented (v3 milestone)
**Date:** 2026-06-29

**Context:** The current `pipeline.py` runs four stages
(ideation → voiceover → render → publish) strictly linearly, with no
formal per-substage checkpoint contract — resume logic is scattered and
stage-local (per `25-CHECKPOINT_SYSTEM.md`'s "NOT IMPLEMENTED" status note).
A failure in render after a successful multi-minute voiceover synthesis
currently risks recomputing work that already succeeded.

**Decision:** Replace the implicit four-stage linear pipeline with an
explicit `WorkflowGraph` of `WorkflowNode`s (`04-DOMAIN.md`,
`05-WORKFLOW.md`), each independently checkpointed
(`25-CHECKPOINT_SYSTEM.md`), at the v3 milestone.

**Consequences:**
- Easier: resume is a structural guarantee, not a per-module convention
  (the exact problem `25-CHECKPOINT_SYSTEM.md` was written to solve); two
  independent branches (voice synthesis vs visual generation) can run
  concurrently since the DAG makes their independence explicit instead of
  implicit in stage-call ordering; adding a new quality gate is "insert a
  DAG node," not "find the right `if` statement to wedge a check into."
- Harder: the DAG executor itself is new infrastructure that must be built
  and tested before any of these benefits materialize — `04-DOMAIN.md`'s
  `WorkflowNode`/`WorkflowGraph`/`Checkpoint` dataclasses exist today as
  *target* domain model, not yet wired to an executor; until v3 ships, this
  decision is "decided," not "delivered."

**Alternatives considered:**
- *Keep the four-stage linear pipeline, add ad-hoc resume flags per stage* —
  rejected; this is the status quo and is exactly what produces the
  "scattered, stage-local resume checks" `25-CHECKPOINT_SYSTEM.md` describes
  as the problem, not a solution.
- *Adopt a general-purpose workflow engine (Airflow, Prefect, Temporal)* —
  rejected; these are server/daemon-oriented orchestration systems built for
  distributed, multi-tenant, long-lived deployments — categorically the
  wrong weight class for a single-process, single-user, local-first tool.
  Adopting one would invert the project's own offline-first/local-first
  thesis by requiring a scheduler service and typically a database backend
  the project does not otherwise need (see ADR-005, ADR-012 for the same
  "don't import distributed-systems infrastructure for a solo local tool"
  reasoning).

---

## ADR-010: Local-first AI vs cloud-first

**Status:** Accepted
**Date:** 2026-06-29

**Context:** This is the foundational decision `PROJECT_VISION.md` already
states as non-negotiable; this ADR exists to preserve the reasoning, not to
re-decide it.

**Decision:** Default execution path for every AI capability (LLM, TTS,
image, video) runs on local compute the creator already owns. Cloud
providers exist only as explicit, opt-in fallbacks for capabilities where
local quality is not yet sufficient (see ADR-003, ADR-004) or for stages
where a network call is inherent to the task itself (Publish — there is no
local alternative to uploading to YouTube).

**Consequences:**
- Easier: zero marginal cost per generation once hardware is owned — the
  creator can iterate on a script or a shot composition dozens of times in
  an evening with no metered API bill accumulating; no creative IP (scripts,
  research, character designs) leaves the machine by default, which matters
  for a creator who may be developing original characters/IP they don't want
  in a third-party training pipeline; works on a flight, works with no
  internet, works during an ISP outage.
- Harder: bounded by the M4's actual compute ceiling — local models are
  smaller and sometimes lower-quality than the largest cloud models (this is
  exactly why ADR-002's cloud LLM escape hatch and ADR-003/004's current
  cloud-leaning defaults exist); the creator bears the hardware cost
  upfront rather than amortizing it as a per-use API fee; local model
  updates (new Qwen3 checkpoint, new F5-TTS voices) are a manual pull, not
  an automatic provider-side upgrade.

**Alternatives considered:**
- *Cloud-first by default, local-as-fallback* — rejected outright; this is
  the inverse of the entire product thesis. A cloud-first creative tool for
  a cost- and privacy-sensitive solo creator (`01-VISION.md` target user) is
  a different, already-crowded product category; the explicit bet here is
  that "your own MacBook Pro M4 is enough compute, and owning it beats
  renting it" for this user.
- *Hybrid with no stated default, "pick per call"* — rejected for being
  directionless; every provider port needs a stated default so a fresh
  install behaves predictably without per-capability configuration before
  first use.

---

## ADR-011: project.json vs script.json

**Status:** Accepted; migration in progress (v2 milestone)
**Date:** 2026-06-29

**Context:** The current artifact produced by a pipeline run is
`script.json`, shaped around the existing `VideoIdea → Script → Voiceover →
RenderedVideo → PublishResult` inheritance chain in
`src/ytb_pipeline/pkg/models.py` — a YouTube-specific, single-inheritance,
linear-pipeline-shaped artifact (`04-DOMAIN.md`'s "Migration Note").

**Decision:** `project.json`, anchored on the flatter, composition-based
`Project` domain model (`04-DOMAIN.md`), supersedes `script.json` as the
durable artifact. `project.json` embeds checkpoints
(`25-CHECKPOINT_SYSTEM.md`), is platform-agnostic
(`target_platforms: tuple[str, ...]` rather than an implicit YouTube
assumption), and is designed from the start to be the "portable, diffable,
mergeable creative artifact" `01-VISION.md` names as the v5 end state.

**Consequences:**
- Easier: one artifact represents the full creative + execution state of a
  project, inspectable and `git diff`-able; adding a new target platform is
  adding a string to `target_platforms`, not restructuring the artifact;
  the artifact survives the v3 DAG-executor migration unchanged in shape
  (checkpoints are already a first-class embedded map, per
  `25-CHECKPOINT_SYSTEM.md` §3).
- Harder: a compatibility loader (`04-DOMAIN.md` migration step 2) must be
  maintained until no code path produces `script.json` artifacts anymore —
  during the transition, the codebase must correctly read both shapes,
  which is real but temporary complexity.

**Alternatives considered:**
- *Extend `script.json` in place (add fields) rather than introduce a new
  artifact name* — rejected; `script.json`'s name itself encodes the
  YouTube-script-centric assumption this migration is meant to remove, and
  silently growing it would mean the artifact's name lies about its scope
  indefinitely. A renamed, restructured artifact makes the v1→v2 boundary
  legible in the codebase and in any tooling that inspects project
  directories.

---

## ADR-012: No Event Bus

**Status:** Accepted
**Date:** 2026-06-29

**Context:** Stage-to-stage and node-to-node communication needs some
mechanism for progress signaling (UI/Telegram updates), audit logging, and
decoupling. An event bus (in-process pub/sub, or a durable broker like Redis
Streams/Kafka) is the conventional answer in distributed or
plugin-heavy systems.

**Decision:** No event bus is introduced. See `34-EVENT_BUS.md` for the
full analysis; this ADR records the decision pointer. Stage/node
communication uses direct function calls (single-process DAG executor) plus
a lightweight `ProgressCallback` protocol (`34-EVENT_BUS.md` §3) for the
two concrete observers that exist today (Telegram notifier, ledger writer).

**Consequences:**
- Easier: no broker to run, configure, or keep alive on a solo creator's
  laptop; no event schema versioning concern beyond the small
  `ProgressEvent` dataclass; stack traces from a failing callback are direct
  and synchronous, not scattered across an async event-delivery boundary.
- Harder: adding a third observer (beyond Telegram + ledger) means adding
  another direct call site rather than a new subscriber registration — fine
  at 2 observers, would become unwieldy well before 5+.

**Alternatives considered:** see `34-EVENT_BUS.md` §2 in full; summarized
here as: in-process pub/sub (rejected — adds indirection with zero
multi-process benefit since everything is one process today), Redis Streams
(rejected — durable broker is ops overhead with no current multi-process or
multi-user consumer), asyncio.Queue-based internal bus (deferred — the
documented future path once a second process genuinely needs to consume
events, not a current need).

---

## ADR-013: `_cli()` lazy import pattern for test-compatible module splitting

**Status:** Accepted
**Date:** 2026-06-29

**Context:** Phase 0 of `29-MIGRATION_PLAN.md` required splitting the
1330-line `batch_cli.py` into smaller, focused modules without changing any
of the 212 existing tests' assertions. Those tests rely heavily on
`monkeypatch.setattr(batch_cli, "SOME_NAME", fake_value)` to stub paths
(`AUTO_STATE_PATH`, `WARN_LOG_PATH`, `PID_PATH`, `ROOT`), the `telegram`
client, and helper functions (`update_ledger`, `emit_warning`) for the
duration of a test. `monkeypatch.setattr` mutates the **module object's**
namespace — `batch_cli.__dict__["SOME_NAME"]` — not any particular
function's closure. A naive split (move a function to a new file, `from
ytb_pipeline.orchestrator.batch_cli import SOME_NAME` at the top of that new
file) captures the value of `SOME_NAME` *once*, at import time, into the new
module's own namespace. After that, the test's `monkeypatch.setattr(
batch_cli, "SOME_NAME", fake)` patches `batch_cli`'s namespace, but the moved
function is still reading its own module's stale copy — the patch silently
has no effect, and the test either fails or, worse, passes against the
wrong (production) value without the test author noticing.

**Decision:** Each new module that needs to read a patchable name from
`batch_cli` defines a small lazy accessor at module scope:

```python
def _cli():
    from ytb_pipeline.orchestrator import batch_cli
    return batch_cli
```

All access to patchable state goes through `_cli().NAME` (e.g.,
`_cli().AUTO_STATE_PATH`, `_cli().telegram.send_message(...)`) instead of a
top-level `from batch_cli import NAME`. Because the import inside `_cli()`
runs at *call time*, not module-load time, and Python caches modules in
`sys.modules` (so every call to `_cli()` returns the exact same `batch_cli`
module object), every read goes through the one namespace
`monkeypatch.setattr(batch_cli, ...)` actually patches. This applies in
`queue_manager.py`, `pipeline_runner.py`, `doctor.py`, and
`ideation_cmd.py` — the four new modules that read CLI-level mutable state.

**Consequences:**
- Easier: all 212 existing tests pass with zero test-file edits — the split
  is purely a code-organization change from the test suite's point of view.
  No new mocking infrastructure, no test rewrite, no risk of silently
  testing against stale values.
- Harder: every patchable read is one extra level of indirection
  (`_cli().NAME` instead of a bare `NAME`) — a future reader unfamiliar with
  this pattern may not immediately understand why a plain top-level import
  wasn't used. The helper function itself is boilerplate repeated per module
  (acceptable here at 4 occurrences; would warrant extraction to a shared
  utility if it grew further). This is acknowledged as transitional: once
  Phase 1's Provider Registry and dependency-injection-friendly constructors
  exist, the patchable globals this pattern works around should be passed
  as explicit parameters instead, removing the need for `_cli()` entirely.

**Alternatives considered:**
- *Re-export everything from `batch_cli.py` after the split (`from
  .queue_manager import *`) and keep tests patching only `batch_cli`'s
  re-exported names* — rejected; this only fixes patches *of the
  re-exported name itself*, not reads happening inside the moved function's
  own module, which is exactly the bug this ADR fixes. The closure problem
  is unchanged.
- *Rewrite all 212 tests to patch each new module directly
  (`monkeypatch.setattr(queue_manager, "AUTO_STATE_PATH", fake)`)* —
  rejected for Phase 0 specifically; `29-MIGRATION_PLAN.md`'s acceptance
  criterion requires test *assertions* to be unchanged, and patch-target
  changes are a test-behavior change, not a pure file move. This remains
  the long-term correct fix and is deferred to Phase 1, once the Provider
  Registry gives these globals a real injection seam instead of a
  module-level constant to patch.
- *Pass all patchable state as explicit function parameters now* — the
  architecturally cleanest option, rejected for Phase 0 only because it
  would require changing every call site's signature and therefore every
  test's call site too — again a test-behavior change, not a pure split.
  This is the intended end state once Phase 1's dependency-injection-style
  constructors land.

---

## ADR-014: Adapter pattern for provider wrapping (don't rewrite, wrap)

**Status:** Accepted
**Date:** 2026-06-29

**Context:** Phase 1 of `29-MIGRATION_PLAN.md` required introducing
`VoiceProvider`, `RenderProvider`, and `PublishProvider` Protocols with
concrete adapters resolved via a `ProviderRegistry`. The existing
implementations this work had to migrate — `voiceover/tts.py` (Edge-TTS +
F5-TTS), `render/compose.py`, `render/compose_ai.py`, `publish/uploader.py`,
`publish/drive.py` — are working, already-tested code with real production
mileage (212 passing tests as of Phase 0). Rewriting any of them from
scratch to "properly" implement the new Protocol from the ground up risked
reintroducing bugs the existing implementations had already worked through
(API quirks, retry edge cases, credential refresh timing).

**Decision:** Each new provider module under `providers/{voice,render,
publish}/` is a thin adapter that implements the relevant Protocol by
delegating to the existing implementation — `voice/edge_provider.py` and
`voice/f5_provider.py` call into the existing `voiceover/tts.py` logic
rather than reimplementing TTS synthesis; `render/slide_provider.py` and
`render/ai_provider.py` delegate to `compose.py`/`compose_ai.py`;
`publish/youtube_provider.py` and `publish/drive_provider.py` delegate to
`uploader.py`/`drive.py`. A full rewrite of the underlying implementations
(e.g., removing `tts.py`'s internal `if settings.tts_provider == "f5"`
branch entirely) is explicitly deferred as a separate future task, not
bundled into Phase 1.

**Consequences:**
- Easier: zero regression risk — the code paths that actually call Edge-TTS,
  F5-TTS, Pexels/Flux compose logic, and the YouTube/Drive APIs are
  unchanged; only the call boundary above them changed shape. All 222 tests
  (212 existing + 10 new adapter tests) pass with no behavior change to the
  underlying providers. Phase 1 shipped without needing to re-validate TTS
  audio quality, render output, or OAuth flows from scratch.
- Harder: slight duplication — the Protocol method signature and the legacy
  function signature both exist, with the adapter as a translation layer
  between them; `voiceover/tts.py` still has its internal `f5` branch,
  invisible to callers but still present in that one file (tracked as a
  known gap in `29-MIGRATION_PLAN.md` Phase 1). A future contributor reading
  only the adapter may need to follow one more hop to find the actual
  synthesis/render/upload logic.

**Alternatives considered:**
- *Rewrite `tts.py`/`compose.py`/`compose_ai.py`/`uploader.py`/`drive.py`
  fully against the new Protocol now, deleting the legacy call shape* —
  rejected for Phase 1; this conflates "introduce a swappable seam" with
  "re-architect every implementation behind it," doubling the risk surface
  of a single phase and contradicting the Phase 0/Phase 1 sequencing
  rationale that each phase has one clear acceptance criterion. The rewrite
  remains worth doing — it is simply a distinct, separately-scoped task with
  its own acceptance criterion, not a silent scope expansion of Phase 1.
- *Leave the legacy if/else branching as the public interface, add
  Protocols only as documentation/type-hints with no real adapter
  indirection* — rejected; this would satisfy a `mypy` check while leaving
  `pipeline.py` and other call sites still coupled to the legacy function
  signatures, failing the actual Phase 1 acceptance criterion (zero
  hardcoded provider branching in pipeline code).

---

## ADR-015: Kahn's algorithm for DAG topo sort (no networkx dependency)

**Status:** Accepted
**Date:** 2026-06-29

**Context:** Phase 2 of `29-MIGRATION_PLAN.md` required `WorkflowGraph`
(`src/ytb_pipeline/project/workflow.py`) to execute `WorkflowNode`s in an
order that respects their declared dependencies — a topological sort over a
DAG. `networkx` is the conventional off-the-shelf answer for graph
algorithms in Python and was the first option considered, since it ships a
battle-tested `topological_sort()` along with cycle detection.

**Decision:** Implement Kahn's algorithm directly in `workflow.py` (~20
lines: compute in-degree per node, repeatedly pop zero-in-degree nodes into a
queue, decrement neighbors' in-degree, raise `WorkflowError` if nodes remain
after the queue empties — which signals a cycle) instead of adding
`networkx` as a dependency.

**Consequences:**
- Easier: zero new dependency for a single-project tool that already keeps
  its dependency surface deliberately small (per ADR-010's local-first,
  low-footprint stance); the algorithm is small enough to read end-to-end in
  one sitting and to unit-test directly against `tests/test_project.py`
  fixtures (linear chains, diamond dependencies, intentional cycles) without
  needing to learn `networkx`'s API surface; a typical video project's DAG
  is small (≤30 nodes — ideation/voiceover/render/publish plus a handful of
  per-segment sub-nodes), well within the regime where Kahn's algorithm's
  `O(V + E)` cost is irrelevant and a heavier library buys nothing.
- Harder: no free cycle-visualization or advanced graph queries (shortest
  path, subgraph extraction) that `networkx` would provide if the DAG ever
  grows complex enough to need them; if `WorkflowGraph` later needs richer
  graph algorithms (e.g., critical-path analysis for render time estimates),
  `networkx` remains an option to revisit, not permanently foreclosed.

**Alternatives considered:**
- *`networkx`* — rejected for Phase 2; a full graph library is
  disproportionate weight for "topologically order ≤30 nodes and detect
  cycles," and adds a dependency whose vastly larger API surface (centrality
  measures, graph drawing, multiple graph types) is unused. Revisit only if
  a concrete future need (e.g., critical-path scheduling) actually requires
  it.
- *Depth-first-search-based topological sort* — functionally equivalent to
  Kahn's algorithm for this use case; Kahn's was preferred because its
  iterative queue-based structure maps directly onto `execute()`'s existing
  "process the next ready node" loop, whereas a DFS-based sort would compute
  the full order up front and then require a separate pass to interleave
  with `CheckpointManager` status checks.

---

## ADR-016: Sync `ImageProvider.generate()` vs async

**Status:** Accepted
**Date:** 2026-06-29

**Context:** Phase 3 of `29-MIGRATION_PLAN.md` introduced the `ImageProvider`
Protocol (`providers/base.py`) alongside `PillowImageProvider` (CPU-bound
gradient drawing) and `FluxImageProvider` (HTTP calls to a local ComfyUI
instance). The existing `VoiceProvider.synthesise()` (`providers/base.py`,
Phase 1) is `async def`, because TTS synthesis is I/O-bound (Edge-TTS is a
network call; F5-TTS local inference still benefits from not blocking the
event loop during model invocation). The natural question when adding a
second AI-capability Protocol was whether `ImageProvider.generate()` should
follow the same `async def` shape for consistency.

**Decision:** `ImageProvider.generate()` is a synchronous method, not
`async def`. `PillowImageProvider.generate()` is plain CPU-bound Pillow
drawing; `FluxImageProvider.generate()` makes one or two simple,
short-lived HTTP calls to a local ComfyUI instance via stdlib
`urllib.request` (mirroring `is_available()`'s existing sync ping pattern)
rather than an async HTTP client.

**Consequences:**
- Easier: no need to drag an async HTTP client (`aiohttp`/`httpx`) into the
  image-provider adapters just to match `VoiceProvider`'s shape; a simple
  file-in/file-out, request/response operation does not need coroutine
  machinery to be correct or readable; `PillowImageProvider` in particular
  has zero I/O to await — wrapping it in `async def` would have meant either
  a no-op `async` function (misleading: looks like it yields control, never
  does) or an unnecessary `run_in_executor` call for work that's already
  fast and synchronous.
- Harder: if a caller running inside an async event loop (e.g., the DAG
  executor's node coordinator, `project/workflow.py`) invokes
  `FluxImageProvider.generate()` directly, the synchronous ComfyUI HTTP
  call blocks that loop for its duration — acceptable today because no
  caller currently invokes `ImageProvider.generate()` from inside a running
  event loop, but a future caller that does must explicitly wrap the call
  in `asyncio.get_event_loop().run_in_executor(None, provider.generate,
  ...)` rather than `await`-ing it directly. This is a known, deliberate
  asymmetry with `VoiceProvider` — not an oversight.

**Alternatives considered:**
- *`async def generate()` matching `VoiceProvider.synthesise()` for
  Protocol-shape consistency* — rejected; consistency-for-its-own-sake
  across two Protocols with genuinely different I/O profiles (TTS is
  inherently network-bound at every implementation; image generation today
  is either pure-CPU or a single simple HTTP round trip) would have added
  async ceremony — `await`, event-loop plumbing in tests, `pytest-asyncio`
  markers on `tests/test_image_provider.py` — with no corresponding benefit,
  since neither current adapter does concurrent/overlapping I/O that async
  would help schedule.
- *Sync now, async later via a breaking Protocol change* — considered as the
  fallback if a future adapter (e.g., a cloud image API needing concurrent
  multi-request batching) needs it; rejected as the *current* decision only
  because YAGNI — Pillow and the Flux/ComfyUI stub do not need it today, and
  introducing the breaking change is cheaper to do once a real async-needing
  adapter exists than to speculatively build for it now.

---

## ADR-017: MetadataAdapter as pure function class (no LLM for metadata optimization)

**Status:** Accepted
**Date:** 2026-06-29

**Context:** Phase 4 of `29-MIGRATION_PLAN.md` needed to translate a
`Project`'s narrative/metadata fields into platform-appropriate publish
metadata — YouTube Shorts tags (`#Shorts` appended), TikTok bare hashtags,
podcast episode metadata, blog frontmatter. SEO-optimized titles/
descriptions/hashtag selection is a task an LLM could plausibly do better
than rule-based logic — picking the most search-relevant hashtags for a
given script, or rewriting a title for platform-specific algorithmic
ranking, is exactly the kind of judgment call an LLM is good at and a fixed
rule set is not.

**Decision:** `src/ytb_pipeline/platform/metadata.py`'s `MetadataAdapter` is
a pure, rule-based function class — no LLM call inside `adapt()`. Per-
platform behavior (hashtag style, truncation length, caption caps) is
expressed as plain conditional logic keyed on `Platform`, consuming the
`Project`'s existing narrative/metadata fields as-is. Any future LLM-driven
SEO optimization (better title rewrites, hashtag relevance ranking,
platform-specific hook rewording) is explicitly delegated to the planned
`SEOAgent` (`29-MIGRATION_PLAN.md` Phase 5, Agent System), which would run
*before* `MetadataAdapter` in the pipeline and produce the improved
narrative fields `MetadataAdapter` then formats — not inside the adapter
itself.

**Consequences:**
- Easier: `MetadataAdapter.adapt()` is deterministic, free (no API/inference
  cost), instant (no network/inference latency), and trivially unit-testable
  with fixed input/output assertions — `tests/test_platform.py`'s 18 tests
  assert exact hashtag/truncation output per platform with zero flakiness
  risk from nondeterministic LLM output. Adding a new platform's formatting
  rule is a pure-function code change with no prompt-engineering surface.
- Harder: metadata quality is capped by what fixed rules can express —
  `MetadataAdapter` cannot judge whether a given hashtag is actually
  trending or relevant, cannot rewrite a title for stronger hook framing,
  and cannot adapt phrasing per platform's algorithmic preferences beyond
  what's encoded as a static rule. That quality ceiling is accepted for
  Phase 4 and intentionally deferred to `SEOAgent` rather than smuggled into
  this adapter, keeping the seam between "deterministic formatting" and
  "LLM-judged optimization" explicit per `02-PRINCIPLES.md`.

**Alternatives considered:**
- *LLM call inside `MetadataAdapter.adapt()` now* — rejected for Phase 4;
  this would couple a deterministic formatting concern to an LLM-provider
  dependency (cost, latency, nondeterminism, a new failure mode requiring
  fallback handling) before the Agent System (Phase 5) that's meant to own
  LLM-driven content judgment even exists. It would also make
  `tests/test_platform.py` either slow/flaky (real LLM calls) or require a
  fake-LLM test harness for what should be a pure-function unit test suite.
- *Hybrid: rule-based by default, optional LLM enhancement behind a flag* —
  considered as a middle ground; rejected for Phase 4 specifically because
  it would require deciding `SEOAgent`'s prompt/interface shape now, ahead
  of Phase 5's actual Agent Protocol design — premature interface
  commitment. The clean Phase 4/5 boundary (formatting now, an `SEOAgent`
  later that feeds *into* this formatter) is simpler to reason about and
  matches the project's phase-sequencing discipline (`29-MIGRATION_PLAN.md`
  Cross-Phase Constraints).

---

## ADR-018: Agents never raise — always return `AgentResult(FAILED)`

**Status:** Accepted
**Date:** 2026-06-29

**Context:** Phase 5 of `29-MIGRATION_PLAN.md` introduced 5 `Agent`
implementations (`ResearchAgent`, `StoryArchitectAgent`,
`VoiceDirectorAgent`, `SEOAgent`, `QAAgent`) that are called from within
pipeline code — eventually the DAG executor (`project/workflow.py`,
Phase 2) and, today, `ideation_cmd.py`/equivalent call sites. Each agent
wraps a genuinely failure-prone operation: `ResearchAgent` hits an external
YouTube API that can be misconfigured (missing key) or rate-limited;
`StoryArchitectAgent` shells out to the `claude` CLI, which can be absent
from `PATH` or exit non-zero; `SEOAgent`/`QAAgent`/`VoiceDirectorAgent` are
rule-based but still operate on caller-supplied data that may not match
the shape they expect. A single uncaught exception from any one agent, if
allowed to propagate, aborts the entire pipeline run — including whatever
other agents or DAG nodes were scheduled to run after it, and any
partially-completed work in the same `Project`.

**Decision:** Every `Agent` implementation catches all exceptions
internally, at the boundary of its public entrypoint, and returns
`AgentResult(status=AgentStatus.FAILED, error=str(e))` instead of letting
the exception propagate. No agent's public method ever raises for an
operational failure (missing API key, CLI binary not found, malformed
input). The `Agent` Protocol's contract is: calling an agent always returns
an `AgentResult` — success or failure is communicated through
`result.status`, never through `try`/`except` around the call site.

**Consequences:**
- Easier: callers (today's pipeline glue code; eventually the DAG executor)
  have exactly one pattern to check after invoking any agent —
  `if result.status is AgentStatus.FAILED: ...` — regardless of which
  agent it is or what internally went wrong. One agent's failure (e.g.,
  `ResearchAgent` failing because the YouTube API key is unset) cannot
  silently abort a sibling agent's already-scheduled work or crash the
  whole batch run. Testing each agent's failure path
  (`tests/test_agents.py`) is a plain return-value assertion, not an
  `pytest.raises()` exception-matching test per failure mode.
- Harder: every agent implementation carries its own internal
  `try`/`except Exception` block around its real logic, which is
  boilerplate repeated 5 times (acceptable at this count; would warrant a
  shared decorator/base-class `run()` wrapper if more agents are added in
  Phase 6+). Catching `Exception` broadly inside each agent risks masking a
  genuine programming bug (e.g., a `TypeError` from a code defect) as if it
  were an expected operational failure — mitigated by `result.error`
  always carrying the original exception's `str()`, so the detail is not
  lost, only redirected from a traceback to a structured field a caller (or
  the ledger writer / Telegram notifier) can log and surface.

**Alternatives considered:**
- *Let agents raise; callers wrap every call site in `try`/`except`* —
  rejected; this pushes the same boilerplate to every call site instead of
  once per agent, and risks an inconsistent catch granularity across call
  sites (one call site catches `Exception`, another only catches a specific
  type and lets others propagate) — exactly the inconsistency a single
  `AgentResult` return contract is meant to eliminate.
- *Agents raise a custom `AgentError` hierarchy (e.g., `ResearchAgentError`,
  `StoryArchitectAgentError`), callers catch the common base class* —
  considered; rejected because it still requires `try`/`except` at every
  call site (just narrower), and does not improve on `AgentResult` for the
  current need — there is no case today where a caller needs to
  distinguish *which* agent's exception type fired versus just checking
  `result.status` and reading `result.error` for detail. This remains an
  option to revisit only if a future caller needs typed-error branching
  agents currently have no use case for.
- *Only catch exceptions in agents that call external/networked
  resources (`ResearchAgent`, `StoryArchitectAgent`), leave the pure
  rule-based agents (`VoiceDirectorAgent`, `SEOAgent`, `QAAgent`)
  unguarded* — rejected for interface consistency; a caller iterating over
  `agent_registry` to run a sequence of agents should not need to know
  which specific agents are "the ones that might raise" — the uniform
  `AgentResult` contract across all 5 agents is the entire point of the
  `Agent` Protocol existing as a single abstraction in the first place.

**Alternatives considered:**
- *LLM call inside `MetadataAdapter.adapt()` now* — rejected for Phase 4;
  this would couple a deterministic formatting concern to an LLM-provider
  dependency (cost, latency, nondeterminism, a new failure mode requiring
  fallback handling) before the Agent System (Phase 5) that's meant to own
  LLM-driven content judgment even exists. It would also make
  `tests/test_platform.py` either slow/flaky (real LLM calls) or require a
  fake-LLM test harness for what should be a pure-function unit test suite.
- *Hybrid: rule-based by default, optional LLM enhancement behind a flag* —
  considered as a middle ground; rejected for Phase 4 specifically because
  it would require deciding `SEOAgent`'s prompt/interface shape now, ahead
  of Phase 5's actual Agent Protocol design — premature interface
  commitment. The clean Phase 4/5 boundary (formatting now, an `SEOAgent`
  later that feeds *into* this formatter) is simpler to reason about and
  matches the project's phase-sequencing discipline (`29-MIGRATION_PLAN.md`
  Cross-Phase Constraints).
