# Implementation Roadmap

> Tactical, file-level companion to `docs/constitution/29-MIGRATION_PLAN.md`
> (architectural phases/acceptance) and `docs/constitution/30-ROADMAP.md`
> (version/calendar milestones). This document answers "which files, in
> what order, with what tests, with what risk" for each phase. Week numbers
> are planning estimates for a single operator, not external commitments.

## Phase 0 — Foundation (Week 1-2)

### Objectives
Make the codebase safe to build on top of: split the orchestration
monolith, close config validation gaps, add structured logging, and
de-duplicate retry logic — with zero behavior change.

### Modules
- `src/ytb_pipeline/orchestrator/queue_manager.py` (new)
- `src/ytb_pipeline/orchestrator/pipeline_runner.py` (new)
- `src/ytb_pipeline/orchestrator/ledger_writer.py` (new)
- `src/ytb_pipeline/orchestrator/oauth_manager.py` (new)
- `src/ytb_pipeline/orchestrator/batch_cli.py` (modify — shrink to thin CLI entrypoint)
- `src/ytb_pipeline/config/settings.py` (modify — add validators)
- `src/ytb_pipeline/pkg/logging.py` (new — structlog setup + correlation ID binding)
- `src/ytb_pipeline/pkg/retry.py` (new — extracted shared retry/backoff helper)

### Files
- `src/ytb_pipeline/orchestrator/batch_cli.py` (currently 1330 lines)
- `src/ytb_pipeline/config/settings.py` (currently 78 lines)
- `data/ledger.md` (read/write target of `LedgerWriter`)
- `auto_state.json` (read/write target of `QueueManager`, until Phase 2 retires it)
- `tests/test_batch_cli.py` (modify — split into per-module test files)

### Acceptance Criteria
- `batch_cli.py` ≤ 400 lines.
- `wc -l` on each new orchestrator module ≤ 400 lines.
- `grep -rn "if tts_provider ==" src/ytb_pipeline/` and equivalent for
  `render_provider` return zero matches outside the to-be-built registry
  stub.
- All 290 existing tests pass; coverage stays ≥ 80%.
- `Settings()` raises `ValidationError` (not a downstream runtime crash)
  for every currently-silent misconfiguration listed in
  `docs/constitution/26-CONFIGURATION.md` §2.
- Every `print()`/unstructured `logging.info` call in
  `src/ytb_pipeline/` is replaced with a `structlog` call carrying a
  dot-namespaced event name.

### Risks
- Splitting `batch_cli.py` risks silently changing CLI argument parsing
  order/precedence if arg-parsing logic is entangled with orchestration
  logic. Mitigate by writing characterization tests (pin current CLI
  output for a fixed set of invocations) *before* the split, not after.
- Retrofitting validators onto `Settings` could break a currently-working
  but technically-invalid `.env` some developer machine relies on.
  Mitigate by running validators against the actual `.env.example` and any
  real `.env` in CI/dev before merging.

### Tests
- Unit tests for `QueueManager`, `LedgerWriter`, `OAuthManager` extracted
  pure functions (queue ordering, ledger entry formatting, token refresh
  decision logic) — written test-first against the *target* module shape,
  not retrofitted.
- Characterization tests for `batch_cli.py`'s current CLI behavior, written
  before the split, kept passing after.
- New tests asserting each `Settings` validator rejects its specific
  invalid case.

### Dependencies
None — this is the entry phase.

---

## Phase 1 — Provider System (Week 3-4)

### Objectives
Replace string-branching provider selection with a `Protocol`-based
registry for Voice, Render, and Publish capabilities.

### Modules
- `src/ytb_pipeline/providers/__init__.py` (new)
- `src/ytb_pipeline/providers/voice/protocol.py` (new — `VoiceProvider` Protocol)
- `src/ytb_pipeline/providers/voice/edge.py` (new — wraps existing Edge-TTS code)
- `src/ytb_pipeline/providers/voice/elevenlabs.py` (new — wraps existing ElevenLabs code)
- `src/ytb_pipeline/providers/voice/f5.py` (new — wraps existing F5-TTS code)
- `src/ytb_pipeline/providers/voice/registry.py` (new — `resolve_voice_provider(settings)`)
- `src/ytb_pipeline/providers/render/protocol.py` (new — `RenderProvider` Protocol)
- `src/ytb_pipeline/providers/render/slide.py`, `pexels.py` (new — wrap existing code)
- `src/ytb_pipeline/providers/render/registry.py` (new)
- `src/ytb_pipeline/providers/publish/protocol.py` (new — `PublishProvider` Protocol)
- `src/ytb_pipeline/providers/publish/youtube.py`, `drive.py` (new — wrap existing code)
- `src/ytb_pipeline/providers/publish/registry.py` (new)
- `src/ytb_pipeline/voiceover/tts.py` (modify — call registry instead of inline branching)
- `src/ytb_pipeline/render/compose.py` (modify — call registry)
- `src/ytb_pipeline/publish/uploader.py` (modify — call registry)

### Files
Same as Modules above; existing logic in `tts.py`/`compose.py`/`uploader.py`
moves into the corresponding `providers/*/*.py` adapter, with the original
file shrinking to orchestration-only code that calls the registry.

### Acceptance Criteria
- `grep -rn "if .*_provider == " src/ytb_pipeline/` outside
  `providers/*/registry.py` returns zero matches.
- A throwaway `NullVoiceProvider` adapter (used only in a test) can be added
  with exactly one new file + one registry line, verified by actually doing
  it once and confirming no other file required edits.
- All Phase 0 tests pass; new per-adapter unit tests added.

### Tests
- Unit test per adapter: given fixed input, fake underlying SDK call,
  assert adapter returns expected shape.
- Unit test for each registry's resolution function: given each valid
  `Settings` value, assert the correct adapter class is returned.
- Regression test: a pipeline run with `tts_provider="edge"` (or any
  existing default) produces byte-identical output to pre-Phase-1 behavior
  for a fixed fixture input.

### Dependencies
Phase 0 (provider registry stub must exist; structured logging should
already be in place so new adapters log consistently from day one).

---

## Phase 2 — Project Model (Week 5-6)

### Objectives
Introduce `project.json` as the canonical artifact; implement
`CheckpointManager` and `CacheManager`; retire `auto_state.json`.

### Modules
- `src/ytb_pipeline/pkg/project.py` (new — `Project` domain object + `project.json` (de)serialization)
- `src/ytb_pipeline/pkg/checkpoint.py` (new — `CheckpointManager`, per `docs/constitution/25-CHECKPOINT_SYSTEM.md`)
- `src/ytb_pipeline/pkg/cache.py` (new — `CacheManager`, per `docs/constitution/24-CACHE_SYSTEM.md`)
- `src/ytb_pipeline/pkg/workflow.py` (new — minimal `WorkflowGraph`/`WorkflowNode` for the still-linear 4 stages, treated as coarse nodes)
- `src/ytb_pipeline/pkg/compat.py` (new — `script.json` → `project.json` loader)
- `src/ytb_pipeline/orchestrator/pipeline_runner.py` (modify — drive execution via `WorkflowGraph` + `CheckpointManager` instead of a flat function call chain)
- `src/ytb_pipeline/voiceover/tts.py`, `render/compose.py` (modify — replace `if path.exists(): skip` with `CacheManager.get()/put()`)

### Files
- `data/cache_registry.db` (new SQLite file, created at runtime)
- `assets/cache/{llm,tts,image,video_clip}/` (new directory tree, created at runtime)
- `project.json` (new artifact shape, one per project under e.g. `data/projects/<id>/project.json`)
- `auto_state.json` (deprecated — last file to delete once `QueueManager` queries `CheckpointManager` instead)

### Acceptance Criteria
- `ytb project resume <id>` works correctly after a `kill -9` mid-run:
  verified by an integration test that kills the process at a specific
  checkpointed node and asserts the rerun does not recompute any node
  already `"done"` (call-count spy on fixture providers stays at 0 for
  already-done nodes).
- Zero remaining `if path.exists(): skip` patterns in
  `voiceover/tts.py`/`render/compose.py`.
- `auto_state.json` is no longer written by any code path.
- `script.json` artifacts from before this phase still load successfully
  via `compat.py`.

### Risks
- `project.json` schema choices made early are expensive to change later
  (every checkpoint/cache reference embeds assumptions about node IDs).
  Mitigate by keeping `node_id` a stable string namespace
  (`{stage}.{substage}`) decided up front per
  `docs/constitution/25-CHECKPOINT_SYSTEM.md` §2, not a positional index.
- SQLite concurrent access from the listener daemon (potentially multiple
  commands dispatched close together) could contend on `cache_registry.db`.
  Mitigate with WAL mode (`PRAGMA journal_mode=WAL`) and short-lived
  connections per operation, not one long-held connection.

### Tests
- Unit tests for `CacheManager.get/put` key derivation (deterministic
  across dict key ordering, per `docs/constitution/24-CACHE_SYSTEM.md` §2).
- Unit tests for `CheckpointManager` state transitions
  (`pending→running→done`, `failed` retry counting, `max_attempts`
  exhaustion).
- Integration test: real SQLite read/write against a temp `.db` file for
  both registries.
- E2E kill/resume test (the acceptance criterion above, formalized as a
  `@pytest.mark.e2e` test).

### Dependencies
Phase 1 (cache wiring needs provider adapters to wrap; checkpoint wiring
needs the registry's resolved instances to know what "a node" actually
calls).

---

## Phase 3 — AI Image Generation (Week 7-8)

### Objectives
Make AI-generated visuals the default `render.ai` path; demote Pexels to
explicit opt-in.

### Modules
- `src/ytb_pipeline/providers/image/protocol.py` (new — `ImageProvider` Protocol)
- `src/ytb_pipeline/providers/image/flux.py` (new — calls local ComfyUI HTTP API)
- `src/ytb_pipeline/providers/image/registry.py` (new)
- `src/ytb_pipeline/render/compose.py` (modify — default scene-image generation via `ImageProvider` instead of Pillow gradient backgrounds)
- `src/ytb_pipeline/render/thumbnail.py` (new or modify — Flux-based thumbnail generation)
- `src/ytb_pipeline/config/settings.py` (modify — add `broll_strategy: str = "ai"` field with `pexels` as an explicit non-default value, validated per `docs/constitution/26-CONFIGURATION.md` §2)

### Files
- `src/ytb_pipeline/render/compose.py`
- `src/ytb_pipeline/providers/image/*.py`
- `assets/cache/image/` (consumed via Phase 2's `CacheManager`)

### Acceptance Criteria
- `RENDER_PROVIDER=ai` with no other override resolves to `FluxProvider`,
  not Pexels, by default — verified by an integration test asserting the
  resolved `ImageProvider` class.
- A project can still explicitly set `config_overrides.broll_strategy =
  "pexels"` and that path still works, regression-tested.
- Thumbnail generation uses Flux output, not a Pillow-only composite, when
  `render_provider="ai"`.

### Risks
- Local ComfyUI/Flux inference latency on M4 could be high enough to make
  iterative ideation painful. Mitigate with aggressive cache warming
  (`docs/constitution/24-CACHE_SYSTEM.md` §7) for repeated/similar prompts
  and a configurable quality/speed tradeoff (fewer diffusion steps for
  draft renders, full steps for final render).
- ComfyUI server availability (not running, wrong port) must fail fast at
  `validate_environment()` (Phase 0/`26-CONFIGURATION.md` §7), not mid-render.

### Tests
- Unit test for `FluxProvider` against a fake local HTTP server (no real
  GPU inference in unit tests).
- Integration test (marked `slow` or `integration`) that does call a real
  local ComfyUI instance if available in the dev environment, to catch
  real integration drift — excluded from default CI run.
- Regression test confirming the Pexels path still functions when
  explicitly selected.

### Dependencies
Phase 2 (image generation must be cached — without `CacheManager`, every
ideation iteration would re-pay Flux's generation cost for unchanged
prompts).

---

## Phase 4 — Multi-Platform (Week 9-10)

### Objectives
Add platform profiles and at least one new `PublishProvider` beyond
YouTube/Drive, proving the extension point requires no core changes.

### Modules
- `src/ytb_pipeline/config/platform_profile.py` (new — `PlatformProfile` enum + resolution)
- `src/ytb_pipeline/publish/metadata_adapters.py` (new — YouTube tags vs. TikTok hashtags vs. podcast/blog metadata)
- `src/ytb_pipeline/providers/publish/tiktok.py` (new — stub or real adapter)
- `src/ytb_pipeline/orchestrator/batch_cli.py` (modify — add `--platform` CLI flag wiring)

### Files
- `src/ytb_pipeline/config/platform_profile.py`
- `src/ytb_pipeline/publish/metadata_adapters.py`
- `src/ytb_pipeline/providers/publish/tiktok.py`

### Acceptance Criteria
- `ytb publish --platform tiktok` resolves the TikTok `PublishProvider`
  and produces platform-appropriate metadata, with zero edits to
  `pipeline.py`, `pkg/models.py`, or any existing `PublishProvider`
  adapter (verified by `git diff` scope review on the PR that adds this).

### Risks
- TikTok's real API access/approval process may not be available in time;
  mitigate by shipping a stub adapter that produces correctly-formatted
  metadata + a manual-export file, deferring real API wiring to a later
  release without blocking the architectural proof point.

### Tests
- Unit tests per metadata adapter (given a `Project`, assert correct
  platform-specific metadata shape).
- Unit test for `PlatformProfile` resolution (given a profile, assert
  correct `orientation`/caption-default/publisher bundle).

### Dependencies
Phase 1 (needs the `PublishProvider` Protocol/registry already in place).

---

## Phase 5 — Agent System (Week 11-14)

### Objectives
Decompose ideation into distinct, independently testable agent roles.

### Modules
- `src/ytb_pipeline/agents/protocol.py` (new — `Agent` Protocol)
- `src/ytb_pipeline/agents/research_agent.py` (new)
- `src/ytb_pipeline/agents/story_architect_agent.py` (new)
- `src/ytb_pipeline/agents/voice_director_agent.py` (new)
- `src/ytb_pipeline/agents/seo_agent.py` (new)
- `src/ytb_pipeline/agents/qa_agent.py` (new)
- `src/ytb_pipeline/ideation/generator.py` (modify — orchestrate the above agents instead of a single LLM call)

### Files
- `src/ytb_pipeline/agents/*.py`
- `src/ytb_pipeline/ideation/generator.py`

### Acceptance Criteria
- Each agent has its own unit test suite exercising it in isolation (fake
  LLM provider, fixed input, asserted structured output) — none requires
  constructing a full `Project` end-to-end.
- Swapping `ResearchAgent`'s underlying LLM provider (Ollama/Qwen3 ↔
  Claude API fallback) requires no change to `StoryArchitectAgent` or
  `StoryboardAgent`/`VoiceDirectorAgent`.

### Risks
- Splitting one LLM call into five agent calls multiplies latency/cost per
  ideation pass. Mitigate by running independent agents concurrently
  (`asyncio.gather`) where there's no data dependency, and by caching each
  agent's LLM call via Phase 2's `CacheManager` (type `"llm"`).
- Agent output quality regression vs. the current single-call approach is
  a real risk for a content-quality-sensitive channel. Mitigate with a
  side-by-side quality comparison on a fixed set of past topics before
  cutting over the default ideation path.

### Tests
- Unit test per agent: fake LLM provider returns a fixed structured
  response, assert agent's output parsing/validation is correct.
- Integration test: full agent chain (Research → StoryArchitect →
  Storyboard) against fixture LLM responses, assert the merged `Project`
  state is internally consistent (no contradicting fields).

### Dependencies
Phase 2 (agents write into `project.json`'s working memory /
`docs/constitution/23-MEMORY_SYSTEM.md` structures) and Phase 1 (agents
call the LLM through the provider registry, not directly).

---

## Phase 6 — Full Local Stack (Week 15-18)

### Objectives
Flip every remaining default from cloud/subprocess to local inference.

### Modules
- `src/ytb_pipeline/providers/llm/ollama.py` (new — `OllamaProvider`, replaces `claude -p` subprocess as default)
- `src/ytb_pipeline/providers/llm/registry.py` (modify — default to `OllamaProvider`, Claude CLI becomes opt-in fallback adapter)
- `src/ytb_pipeline/providers/voice/registry.py` (modify — default `tts_provider` flips to `"f5"`)
- `src/ytb_pipeline/providers/video/wan22.py` (new — `Wan2_2Provider` for B-roll/video generation)
- `src/ytb_pipeline/providers/video/registry.py` (new)

### Files
- `src/ytb_pipeline/providers/llm/*.py`
- `src/ytb_pipeline/providers/video/*.py`
- `src/ytb_pipeline/config/settings.py` (modify — default field values flipped per `docs/constitution/26-CONFIGURATION.md`)

### Acceptance Criteria
- A fresh `.env` with no explicit provider overrides runs the entire
  pipeline (ideation→voiceover→render, excluding the inherently-networked
  publish step) using only local models — verified by the E2E network
  guard test (`docs/constitution/28-TESTING.md` §5) passing with zero
  provider overrides set.
- `claude_bin`/`claude -p` subprocess invocation is no longer on the
  default ideation path (still available as an explicit fallback adapter,
  not deleted).

### Risks
- Local LLM (Qwen3 via Ollama) ideation quality may not match Claude's
  current output quality, directly risking content quality on a
  production channel. Mitigate with a quality-gated rollout: run local LLM
  in shadow mode (generate but don't use for real episodes) for N episodes,
  compare against the existing quality gates
  (`.claude/skills/youtube-ideation/video-quality-rules.md`) before
  flipping the real default.
- Wan2.2 (or whatever the best local video-gen model is at this point in
  2027) is a fast-moving target; treat the specific model choice as a
  config value, not a hardcoded assumption, so swapping it later is a
  one-adapter change per the Provider Pattern.

### Tests
- Unit tests for `OllamaProvider`/`Wan2_2Provider` against fake local HTTP
  endpoints.
- A `slow`-marked integration test that runs real local inference once,
  manually triggered, to catch real model/version drift.
- Quality-gate regression test comparing local-LLM ideation output against
  the existing niche/series gates (0c/0d) on a fixed fixture topic set.

### Dependencies
Phase 1 (LLM/Voice/Video registries must already exist to flip their
defaults) and Phase 5 (agents should already be calling providers through
the registry, not a hardcoded `claude -p` call, before this phase changes
what the registry resolves to by default).

---

## Final Release: v2.0 AI Native Studio (Week 19-20)

### Objectives
Prove the full system end-to-end with zero cloud dependencies (except the
inherently-networked publish call) and benchmark real M4 throughput.

### Modules
None new — this phase is verification, benchmarking, and documentation
closure, not new feature code.

### Files
- `docs/constitution/*.md` (modify — close out any remaining "NOT
  IMPLEMENTED" status markers that are now actually implemented)
- `CONSTITUTION_CHECKLIST.md` (modify — flip all ❌/⚠️ entries that are now
  ✅ DONE, based on real verification, not aspirational marking)
- `CLAUDE_NEW.md` → merge into `CLAUDE.md` (only after this phase's
  acceptance criteria are met)

### Acceptance Criteria
- A single E2E test runs the full pipeline (ideation → voiceover → render
  → publish-prep, `dry_run=true`) with every provider resolved to its
  local default and asserts: zero non-localhost network calls (network
  guard fixture), full `project.json` produced with every node `"done"`.
- Performance benchmark recorded: wall-clock time per pipeline stage on
  the target MacBook Pro M4, for a fixed fixture topic, committed to
  `docs/benchmarks/m4_throughput.md` (or equivalent) as a dated baseline
  for future regression comparison.
- `CONSTITUTION_CHECKLIST.md` re-run honestly against the now-current
  codebase; any remaining ❌/⚠️ items are explicitly carried forward into a
  v2.1+ roadmap entry, not silently dropped.

### Risks
- "Zero cloud dependencies" is an absolute claim that's easy to violate by
  accident (one forgotten fallback default still pointing at a cloud
  adapter). Mitigate by making the network-guard E2E test the actual gate
  for this release, not a manual checklist item — if the test doesn't fail
  the build, the claim isn't verified.

### Tests
- The full-local E2E test described in Acceptance Criteria.
- A regression suite run across all prior phases' test suites to confirm
  nothing introduced during Phase 6 silently broke an earlier phase's
  guarantee (resume reliability, cache hit correctness, provider
  swappability).

### Dependencies
All prior phases (0 through 6).
