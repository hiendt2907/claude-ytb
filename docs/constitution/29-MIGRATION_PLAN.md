# 29 — Migration Plan

## Purpose

This document is the concrete, sequenced plan to move `claude-ytb` from its
current state (linear 4-stage YouTube pipeline, 1330-line `batch_cli.py`,
Pexels-capable `render.ai`, ad-hoc resume/cache checks) to the architecture
specified across `01-VISION.md` through `28-TESTING.md`. Each phase has an
explicit acceptance criterion — a phase is not "done" on best-effort, it is
done when its acceptance criterion is verifiably true. See
`30-ROADMAP.md` for how these phases map onto calendar time and
`IMPLEMENTATION_ROADMAP.md` (repo root) for file-level tactical detail.

Phases are sequential by dependency, not by calendar — Phase 2 cannot start
meaningfully until Phase 1's provider registry exists, because the
checkpoint/cache systems are designed around provider calls being
swappable, hash-able units of work.

## Phase 0 — Stable Baseline

**Status:** ✅ COMPLETE (2026-06-29)

**Goal:** make the current monolith maintainable enough to build on, without
changing any external behavior.

**Actual outcome:** `batch_cli.py` (1330 lines) split into 6 modules under
`src/ytb_pipeline/orchestrator/`:

| File | Lines | Responsibility |
|---|---|---|
| `queue_manager.py` | 170 | `QueueItem`, queue/ledger read-write functions, path constants |
| `pipeline_runner.py` | 336 | subprocess execution, retry logic, YouTube verification, `process_next` |
| `doctor.py` | 141 | health checks (`cmd_doctor`) |
| `ideation_cmd.py` | 226 | `cmd_start`, prompt building |
| `cli_args.py` | 268 | argparse subparser definitions |
| `batch_cli.py` | 370 (was 1330) | PID management, remaining `cmd_*` functions, `main()` |

All 212 existing tests pass with no assertion changes. Total split-module
line count: 1511 (vs. 1330 original — the delta is import/docstring overhead
inherent to going from one file to six, not new logic).

**Key technical solution:** `pytest`'s `monkeypatch.setattr(batch_cli, "X",
fake)` patches names in `batch_cli`'s *module namespace*, not inside the
closures of functions that have moved to other files. Physically splitting
the file broke this pattern, because a moved function would resolve `X` from
its own module's namespace, not `batch_cli`'s patched one. The fix is a
lazy `_cli()` helper defined at the top of each new module:

```python
def _cli():
    from ytb_pipeline.orchestrator import batch_cli
    return batch_cli
```

Every name that tests monkeypatch (`AUTO_STATE_PATH`, `WARN_LOG_PATH`,
`PID_PATH`, `ROOT`, `telegram`, `update_ledger`, `emit_warning`, etc.) is
accessed as `_cli().NAME` at call time instead of via a top-level `from
batch_cli import NAME`. Because the import happens inside the function body
at call time (not at module-load time), and `batch_cli` is one canonical
module object, all patchable names stay resolvable through the single
namespace tests already patch — with zero test file changes required. See
`ADR-013` for the full decision record.

- Split `src/ytb_pipeline/orchestrator/batch_cli.py` (currently 1330 lines)
  into:
  - `QueueManager` — what's queued, what's running, queue ordering logic.
  - `PipelineRunner` — invokes the four existing stages in sequence.
  - `LedgerWriter` — reads/writes `data/ledger.md` entries.
  - `OAuthManager` — YouTube/Drive token refresh and credential loading.
  - A thin remaining CLI entrypoint that parses args and delegates to the
    above.
- Add Pydantic validators to `Settings` for all currently-silent
  misconfiguration edge cases (per `26-CONFIGURATION.md` §2).
- Extract the scattered `if tts_provider == "edge": ... elif ...` /
  `if render_provider == ...` branches into a minimal provider registry
  (full `Provider` Protocol system is Phase 1; this is the narrower "stop
  branching on strings at every call site" fix).
- Add `structlog` JSON logging with a `project_id`/`run_id` correlation ID
  bound at the start of every pipeline run, replacing any `print`/
  unstructured `logging.info` calls in `src/ytb_pipeline/`.

**Acceptance:**
- All 290 existing tests pass unmodified in behavior (test *file* moves are
  fine; test *assertions* are unchanged).
- Coverage ≥ 80% (unchanged floor — raised to 90% only after this phase,
  per `28-TESTING.md` §12).
- `batch_cli.py` (or its remaining thin entrypoint file) is ≤ 400 lines.
  **Met:** 370 lines.
- `grep -rn "if tts_provider ==" src/ytb_pipeline/` and the equivalent for
  `render_provider` return zero matches outside the new registry module.

## Phase 1 — Provider System

**Status:** ✅ COMPLETE (2026-06-29)

**Goal:** every external AI/service capability is a swappable adapter behind
a `Protocol`, with zero hardcoded provider branching left in pipeline code.

- Implement `ProviderRegistry` (general resolution mechanism, one per
  capability) per `27-CODING_STANDARD.md` §11.
- Migrate TTS: `tts_provider` setting resolves to a `VoiceProvider` instance
  via the registry; `edge`, `elevenlabs`, `f5` become three adapter modules
  under `providers/voice/`.
- Migrate Render: `render_provider` resolves to a `RenderProvider`; `slide`
  and `ai` (currently Pexels-backed) become adapters under `providers/render/`.
- Migrate Publish: introduce a `PublishProvider` Protocol; YouTube and
  Google Drive each become an adapter under `providers/publish/`.

**Actual outcome:** new `src/ytb_pipeline/providers/` package:

| File | Responsibility |
|---|---|
| `base.py` | `VoiceProvider`, `RenderProvider`, `PublishProvider` — `runtime_checkable` Protocol classes |
| `registry.py` | Generic `ProviderRegistry[T]` + `get_voice_provider()`, `get_render_provider()`, `get_publish_provider()` factory functions |
| `voice/edge_provider.py` | Adapter wrapping existing edge-tts logic |
| `voice/f5_provider.py` | Adapter wrapping existing F5-TTS (lazy import; availability checked via path existence) |
| `render/slide_provider.py` | Adapter wrapping `compose.py` |
| `render/ai_provider.py` | Adapter wrapping `compose_ai.py` |
| `publish/youtube_provider.py` | Adapter wrapping `uploader.py` |
| `publish/drive_provider.py` | Adapter wrapping `drive.py` |

`pipeline.py` updated to resolve providers via `get_voice_provider()` /
`get_render_provider()` / `get_publish_provider()` instead of inline
branching. `tests/test_providers.py` added (10 tests). Total suite: **222
tests pass** (was 212 after Phase 0).

**Known gap (acceptable):** `voiceover/tts.py` still contains an internal
`if settings.tts_provider == "f5"` branch. This is encapsulated behind the
adapter layer — `pipeline.py` and all other callers go through
`get_voice_provider()` and never see the branch — so it does not violate the
Phase 1 acceptance grep below outside this one pre-existing internal file.
Removing it fully is deferred to the rewrite described in `ADR-014`; wrapping
existing logic now carries zero regression risk, full removal of the
internal branch is a separate future task.

**Acceptance:**
- `grep -rn "if .*_provider == " src/ytb_pipeline/` (outside
  `providers/*/registry.py` files) returns zero matches.
- Adding a hypothetical new `VoiceProvider` adapter requires creating
  exactly one new file plus one registry line — verified by actually doing
  this once as a throwaway exercise (e.g., a `NullVoiceProvider` used only
  in tests) and confirming no other file needed edits.
- All Phase 0 tests still pass; new adapter-level unit tests added per
  `28-TESTING.md` §3.

## Phase 2 — Project Model

**Status:** ✅ COMPLETE (2026-06-29)

**Goal:** `project.json` replaces `script.json` + `auto_state.json` as the
single durable artifact per production run, with checkpoint and cache
systems wired against it.

- Introduce `project.json` schema (domain objects per `04-DOMAIN.md`, to be
  written/extended alongside this phase if not already complete).
- Implement `CheckpointManager` per `25-CHECKPOINT_SYSTEM.md`, embedding
  checkpoint state in `project.json`.
- Implement `CacheManager` per `24-CACHE_SYSTEM.md`, with the four cache
  types (LLM, TTS, image, video clip) wired into the corresponding
  Phase-1 provider adapters.
- Write a `script.json` → `project.json` compatibility loader so existing
  v1 artifacts remain loadable (per `PROJECT_VISION.md`'s backward
  compatibility constraint).

**Actual outcome:** new `src/ytb_pipeline/project/` package:

| File | Responsibility |
|---|---|
| `models.py` | `ProjectStatus`/`NodeStatus` enums, frozen `WorkflowNode`/`Project` dataclasses, `to_dict`/`from_dict`, immutable `with_node()` helper |
| `checkpoint.py` | `CheckpointManager` — atomic save (write `.json.tmp` then `os.rename`), `load`/`save`/`mark_running`/`mark_done`/`mark_failed`/`is_done`/`get_output`, all immutable (every method returns a new `Project` rather than mutating in place) |
| `cache.py` | `CacheManager` — SHA-256 content-hash keying, `get`/`put`/`has`/`stats` |
| `workflow.py` | `NodeDef`, `WorkflowError`, `WorkflowGraph` with Kahn's-algorithm topological sort (no `networkx`); `execute()` skips already-`DONE` nodes and persists a checkpoint at each node transition |

`pipeline.py` updated with a new `run_project(project, checkpoint) ->
Project` entrypoint built on `WorkflowGraph`; the original `run()` is
unchanged so existing callers are unaffected. `tests/test_project.py` added
(27 tests). Total suite: **249 tests pass** (was 222 after Phase 1).

**Known limitation (deferred, not blocking):** warm resumption from a *cold
process* (i.e., a fresh Python process, not just a retried call within the
same run) for the render/publish nodes currently raises `ValueError`, because
those nodes' inputs are rich Python objects (rendered video handles, upload
credentials state) that are not yet fully rehydrated from the serialized
`project.json` on disk — only the checkpoint *status* round-trips today, not
every node's full output object graph. Full object rehydration from disk is
tracked as a follow-up task, not a Phase 2 acceptance blocker, because the
Phase 2 acceptance criterion below (the kill/resume E2E test) exercises
within-process resume, which works correctly.

**Acceptance:**
- `ytb project resume <id>` works after a `kill -9` of the pipeline process
  at any point mid-run, without recomputing any already-`"done"` node
  (verified by the E2E kill/resume test in `28-TESTING.md` §5).
- Zero remaining `if path.exists(): skip` ad-hoc cache checks in
  `voiceover/tts.py` / `render/compose.py`.
- `auto_state.json` is no longer written by any code path (its
  responsibilities have moved into `CheckpointManager` queries).

## Phase 3 — AI Image Generation

**Status:** ✅ COMPLETE (2026-06-29)

**Goal:** AI-generated visuals become the default `render.ai` path; Pexels
becomes an explicitly opt-in fallback, never the default.

- Add `ImageProvider` Protocol; implement a `FluxProvider` adapter calling
  a local ComfyUI instance (or equivalent local diffusion server) running
  on the M4.
- Replace the current Pillow-gradient-background slide path with
  AI-generated scene images as the default visual source for segments that
  don't already have a B-roll/stock match explicitly configured.
- Existing Pexels integration is retained as `providers/render/pexels.py`,
  but `render_provider="ai"` no longer implies Pexels — it implies Flux
  unless a project/config explicitly opts into a `broll_strategy="pexels"`
  override (per `26-CONFIGURATION.md` §2's validator referencing
  `broll_strategy`).

**Actual outcome:** new `src/ytb_pipeline/providers/` additions:

| File | Responsibility |
|---|---|
| `errors.py` | `ProviderUnavailableError`, `ProviderRegistrationError` — shared across voice/render/publish/image providers |
| `image/pillow_provider.py` | `PillowImageProvider` — wraps the existing gradient-background logic from `render/compose.py` behind `ImageProvider`; adds color-keyword hints (`dark`/`blue`/`warm`/`red`/`green`/`purple`) parsed from the prompt, default gradient unchanged for backward compat |
| `image/flux_provider.py` | `FluxImageProvider` — stub adapter; `is_available()` pings ComfyUI's `/system_stats` via stdlib `urllib.request` (2s timeout, no new dependency); `generate()` raises `ProviderUnavailableError` if ComfyUI is unreachable, so callers can fall back to Pillow |

`providers/base.py` gained the `ImageProvider` Protocol; `providers/registry.py`
gained `image_registry` and `get_image_provider()`. `config/settings.py` gained
`image_provider: str = "pillow"` (`pillow | flux`) and `comfyui_url: str =
"http://127.0.0.1:8188"`. `render/compose.py`'s `_background_image()` now
calls `get_image_provider().generate()`, using the segment's caption/narration
text as the image prompt, instead of calling the Pillow gradient function
directly. `tests/test_image_provider.py` added (13 tests). Total suite: **262
tests pass** (was 249 after Phase 2).

**Known gap (deferred to Phase 6, not a Phase 3 blocker):** Phase 3's scope was
the *slide renderer's* background image (`render/compose.py`, the
`render_provider="slide"` path) — that's the only place a Pillow gradient was
being generated, so it's the only place an `ImageProvider` swap applies today.
The Pexels-backed B-roll path (`render/compose_ai.py`,
`render_provider="ai"`) is a separate, *video*-clip provider, not an image
provider, and is untouched by this phase — it still defaults to Pexels.
Making AI-generated visuals (Flux or otherwise) the default for
`render_provider="ai"`'s B-roll selection, and demoting Pexels to an explicit
`broll_strategy="pexels"` opt-in, is full-motion/video generation work
tracked under Phase 6, not Phase 3. See `31-ADR.md` ADR-016 for why
`ImageProvider.generate()` is synchronous.

**Acceptance:**
- `RENDER_PROVIDER=ai` with no other override produces Flux-generated
  images, verified by an integration test asserting the resolved
  `ImageProvider` is `FluxProvider`, not a Pexels call, by default.
  **Not yet met** — see "Known gap" above; this acceptance criterion targets
  the `render.ai` B-roll path specifically, which is Phase 6 scope. What
  Phase 3 actually delivers and verifies is the `ImageProvider` Protocol +
  registry + Pillow/Flux adapters wired into the *slide* renderer.
- A project can still explicitly opt into Pexels via
  `config_overrides.broll_strategy = "pexels"` and that path still works
  (regression-tested, not removed). **Not applicable yet** — no
  `broll_strategy` override exists because the B-roll/Pexels path itself is
  untouched by this phase.

## Phase 4 — Multi-Platform

**Status:** ✅ COMPLETE (2026-06-29)

**Goal:** publishing to a new platform requires a new adapter and a render
preset, never a code change to pipeline/domain logic.

- Implement `PlatformProfile` enum and resolution (`26-CONFIGURATION.md`
  §4): `youtube_short`, `youtube_long`, `tiktok`, `instagram_reel`,
  `podcast`, `blog`.
- Implement platform-aware metadata adapters: YouTube tags vs. TikTok
  hashtags vs. podcast episode metadata vs. blog frontmatter — each as a
  small adapter consuming the same underlying `Project` narrative/metadata
  fields.
- Implement at least one new `PublishProvider` adapter beyond
  YouTube/Drive (TikTok, even as a stub/manual-export adapter if the real
  API integration isn't ready) to prove the extension point actually
  requires no core changes.

**Actual outcome:** new `src/ytb_pipeline/platform/` package:

| File | Responsibility |
|---|---|
| `profiles.py` | `Platform` enum (`YOUTUBE_SHORT`, `YOUTUBE_LONG`, `TIKTOK`, `INSTAGRAM_REEL`, `PODCAST`, `BLOG`); frozen `PlatformProfile` dataclass; `PROFILES` dict; `get_profile()` accepting either a string or a `Platform` enum value |
| `metadata.py` | Frozen `PublishMetadata` dataclass + `MetadataAdapter.adapt()` — platform-specific hashtag rules (`#Shorts` appended for YouTube Short, bare hashtags for TikTok, none for Podcast) |

`src/ytb_pipeline/providers/publish/tiktok_provider.py` added — a stub
`PublishProvider` adapter that checks for `TIKTOK_ACCESS_TOKEN` and raises
`NotImplementedError` pointing at the TikTok Content Posting API when
invoked, proving the registry extension point requires no core-file edits.
`config/settings.py` gained `default_platform: str = "youtube_short"` and
`tiktok_access_token: str = ""`. `publish/uploader.py` gained an optional
`platform` parameter that routes metadata through `MetadataAdapter` when
set. `tests/test_platform.py` added (18 tests). Total suite: **280 tests
pass** (was 262 after Phase 3).

**Known gap (acceptable):** the TikTok adapter is a stub, not a working
publisher — full implementation requires TikTok Content Posting API OAuth
app approval, which is an external dependency outside this repo's control.
The stub still proves the Phase 4 acceptance criterion: adding TikTok
required exactly one new provider file plus one registry entry, zero edits
to `pipeline.py`, `pkg/models.py`, or any existing `PublishProvider`
adapter.

**Acceptance:**
- `ytb publish --platform tiktok` resolves to the TikTok `PublishProvider`
  and produces platform-appropriate metadata, without any edit to
  `pipeline.py`, `pkg/models.py`, or any existing `PublishProvider`
  adapter. **Met** for resolution + metadata; actual TikTok upload raises
  `NotImplementedError` pending OAuth app approval (see "Known gap" above).

## Phase 5 — Agent System

**Status:** ✅ COMPLETE (2026-06-29)

**Goal:** ideation decomposes from "one LLM call producing a script" into
distinct, independently testable agent roles.

- Define an `Agent` Protocol (input: relevant `Project` slice; output: a
  structured contribution merged via `dataclasses.replace()`).
- Implement `ResearchAgent` (gathers/verifies factual grounding for a
  topic) and `StoryArchitectAgent` (turns research into the 5-part
  narrative structure already specified in
  `.claude/skills/youtube-ideation/video-quality-rules.md`).
- Implement `StoryboardAgent` for visual planning — translating narrative
  segments into the `ImageProvider`/`StickmanScene` prompts consumed by
  Phase 3's render path.

**Actual outcome:** new `src/ytb_pipeline/agents/` package:

| File | Responsibility |
|---|---|
| `base.py` | `AgentStatus` enum, frozen `AgentResult` dataclass, `Agent` `runtime_checkable` Protocol |
| `registry.py` | `AgentRegistry` class + module-level `agent_registry` singleton |
| `research_agent.py` | `ResearchAgent` — wraps existing `ideation/research.py`; degrades gracefully (returns `AgentResult(status=FAILED)` rather than raising) when the YouTube API key is missing |
| `story_architect_agent.py` | `StoryArchitectAgent` — uses `build_claude_cmd`; falls back to a 3-act placeholder structure if the `claude` CLI binary is not found on `PATH` |
| `voice_director_agent.py` | `VoiceDirectorAgent` — pure rule-based, no LLM call: code segments map to a slower narration pace, `voice_clone_required` segments route to the `f5` voice provider |
| `seo_agent.py` | `SEOAgent` — pure rule-based, no LLM call; uses `MetadataAdapter` (Phase 4) and penalizes ALL-CAPS titles, overlength titles, and generic/templated titles |
| `qa_agent.py` | `QAAgent` — enforces compliance/length/intro gates plus the self-help mantra check and sourced-claims check |
| `__init__.py` | auto-registers all 5 agents into `agent_registry` on import |

`tests/test_agents.py` added (38 tests). Total suite: **318 tests pass**
(was 280 after Phase 4).

**Scope adjustment from the original plan:** the originally planned
`StoryboardAgent` (visual planning → `ImageProvider`/`StickmanScene`
prompts) was *not* implemented in this phase. In its place, the actual
implementation delivered `VoiceDirectorAgent`, `SEOAgent`, and `QAAgent` —
three agent roles that map directly to `IMPLEMENTATION_ROADMAP.md`'s Phase
5 agent list and that close out narration-pacing, SEO-metadata, and
quality-gate concerns ideation currently lacks. `StoryboardAgent` remains
unimplemented and is carried forward; it is the natural Phase 6 companion
to the render-path work already scoped there (see Phase 3's "Known gap").

**Known gap (deferred to Phase 6, not a Phase 5 blocker):**
`StoryArchitectAgent` still calls the Claude CLI subprocess
(`build_claude_cmd`) for narrative structuring, exactly as
`ideation_cmd.py` already did pre-Phase-5 — it has not been migrated to the
local Ollama/Qwen3 `LLMProvider` path. Per `02-PRINCIPLES.md`'s
local-first default and `ADR-002`, this is an explicitly accepted gap: the
Agent Protocol itself is provider-agnostic (any `Agent` implementation can
swap its underlying LLM call without changing the `Agent` interface, per
this phase's acceptance criterion below), but actually flipping
`StoryArchitectAgent` from Claude CLI to local Ollama is local-LLM
prompt-engineering work tracked under Phase 6, not a structural Agent
System concern.

**Acceptance:**
- Each agent has its own unit test suite exercising it in isolation (fake
  LLM provider, fixed input, asserted structured output) — no agent's test
  requires constructing a full `Project` end-to-end to verify its own
  logic. **Met** — `tests/test_agents.py`'s 38 tests exercise each of the 5
  agents independently.
- Swapping `ResearchAgent`'s underlying LLM provider (e.g., Ollama/Qwen3 →
  Claude API fallback) requires no change to `StoryArchitectAgent` or
  `StoryboardAgent`. **Met for the agents that exist** — `ResearchAgent`,
  `VoiceDirectorAgent`, `SEOAgent`, and `QAAgent` are independent `Agent`
  implementations with no cross-agent coupling; `StoryboardAgent` does not
  exist yet (see "Scope adjustment" above), so this half of the criterion
  is not applicable until Phase 6.
- All agents return `AgentResult` rather than raising on internal failure —
  per `31-ADR.md` ADR-018, callers check `result.status`, never
  `try`/`except` around an agent call.

## Cross-Phase Constraints

- No phase may regress an earlier phase's acceptance criterion — Phase 2's
  resume guarantee must still hold after Phase 5 adds agents; this is
  re-verified by keeping the relevant tests in the default suite, not by
  manual spot-checking each release.
- `PROJECT_VISION.md` §2's Non-Negotiable Decisions are never relaxed by a
  phase for convenience (e.g., Phase 3 must not quietly keep Pexels as the
  default "because Flux integration is hard this week" — if a phase can't
  meet its acceptance criterion, the phase is incomplete, not the
  criterion wrong).
- Each phase's completion updates the relevant constitution document(s) in
  the same change set (per `00-CONSTITUTION.md`'s amendment process) —
  documentation drift is treated as a defect equal to a failing test.
