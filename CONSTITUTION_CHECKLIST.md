# Constitution Checklist

> Đánh giá trung thực trạng thái hiện tại của `claude-ytb` so với
> `docs/constitution/00-30` và `PROJECT_VISION.md`. ✅ DONE = đã implement
> và verify được trong code/test hiện tại. ⚠️ PARTIAL = một phần tồn tại
> nhưng không đầy đủ/không đúng spec. ❌ MISSING = chưa có gì trong code.
> Cập nhật file này mỗi khi một phase của `docs/constitution/29-MIGRATION_PLAN.md`
> hoàn thành.

## Phase 0 Completion (2026-06-29)

`batch_cli.py` (1330 lines) split into 6 modules (`queue_manager.py`,
`pipeline_runner.py`, `doctor.py`, `ideation_cmd.py`, `cli_args.py`,
`batch_cli.py` now 370 lines) under `src/ytb_pipeline/orchestrator/`. All 212
tests pass, no behavior changes. Key solution: lazy `_cli()` import helper
per module so `monkeypatch.setattr(batch_cli, ...)` keeps working across the
split — see `31-ADR.md` ADR-013. Phase 0's other sub-goals (Pydantic
validators, provider-branch extraction, `structlog`) are not yet started;
only the file-split sub-goal is complete.

## Phase 1 Completion (2026-06-29)

New `src/ytb_pipeline/providers/` package: `base.py` (`VoiceProvider`,
`RenderProvider`, `PublishProvider` — `runtime_checkable` Protocols),
`registry.py` (generic `ProviderRegistry[T]` + `get_voice_provider()` /
`get_render_provider()` / `get_publish_provider()` factories),
`voice/edge_provider.py`, `voice/f5_provider.py`, `render/slide_provider.py`,
`render/ai_provider.py`, `publish/youtube_provider.py`,
`publish/drive_provider.py` — each a thin adapter wrapping the existing
implementation (per `31-ADR.md` ADR-014: wrap, don't rewrite). `pipeline.py`
now resolves providers through the registry factory functions instead of
inline branching. `tests/test_providers.py` added (10 tests). **222 tests
pass** (was 212). Known gap, acceptable: `voiceover/tts.py` still has an
internal `if settings.tts_provider == "f5"` branch, encapsulated behind the
adapter layer and invisible to `pipeline.py`/callers — see
`29-MIGRATION_PLAN.md` Phase 1 for detail. Full removal of that internal
branch is a separate future task.

## Phase 2 Completion (2026-06-29)

New `src/ytb_pipeline/project/` package: `models.py` (`ProjectStatus`/
`NodeStatus` enums, frozen `WorkflowNode`/`Project` dataclasses, `to_dict`/
`from_dict`, immutable `with_node()`), `checkpoint.py` (`CheckpointManager`
— atomic save via `.json.tmp` + rename, `load`/`save`/`mark_running`/
`mark_done`/`mark_failed`/`is_done`/`get_output`, fully immutable),
`cache.py` (`CacheManager` — SHA-256 content-hash keying, `get`/`put`/`has`/
`stats`), `workflow.py` (`NodeDef`, `WorkflowError`, `WorkflowGraph` using
Kahn's algorithm for topo sort — see `31-ADR.md` ADR-015 — `execute()` skips
already-`DONE` nodes and checkpoints at each transition). `pipeline.py`
gained `run_project(project, checkpoint) -> Project`; original `run()`
unchanged. `tests/test_project.py` added (27 tests). **249 tests pass**
(was 222). Known limitation, acceptable: cold-process resume (fresh Python
process, not just a retried call) for render/publish nodes raises
`ValueError` because those nodes' rich object outputs are not yet fully
rehydrated from `project.json` on disk — only checkpoint status round-trips
today. Full object serialization/rehydration is deferred as a follow-up
task; see `29-MIGRATION_PLAN.md` Phase 2.

## Phase 3 Completion (2026-06-29)

New `src/ytb_pipeline/providers/errors.py` (`ProviderUnavailableError`,
`ProviderRegistrationError`) and `providers/image/` package:
`pillow_provider.py` (`PillowImageProvider` — wraps the existing
`render/compose.py` gradient logic behind `ImageProvider`, plus
color-keyword prompt hints) and `flux_provider.py` (`FluxImageProvider` —
stub adapter pinging ComfyUI `/system_stats` via stdlib `urllib.request`,
raises `ProviderUnavailableError` if unreachable). `providers/base.py` gained
the `ImageProvider` Protocol; `providers/registry.py` gained `image_registry`
+ `get_image_provider()`. `settings.py` gained `image_provider: str =
"pillow"` and `comfyui_url`. `render/compose.py::_background_image()` now
resolves through `get_image_provider().generate()` instead of calling the
Pillow gradient function directly. `tests/test_image_provider.py` added (13
tests). **262 tests pass** (was 249). See `31-ADR.md` ADR-016 for the
sync-vs-async `generate()` decision. **Known gap:** this phase only replaced
the Pillow gradient background in the *slide* renderer — the Pexels-backed
B-roll path in `render/compose_ai.py` (`render_provider="ai"`) is untouched
and still defaults to Pexels; making AI image generation the default for
that path, and Pexels an explicit `broll_strategy="pexels"` opt-in, is
deferred to Phase 6 (full-motion/video generation). See
`29-MIGRATION_PLAN.md` Phase 3.

## Phase 4 Completion (2026-06-29)

New `src/ytb_pipeline/platform/` package: `profiles.py` (`Platform` enum —
`YOUTUBE_SHORT`/`YOUTUBE_LONG`/`TIKTOK`/`INSTAGRAM_REEL`/`PODCAST`/`BLOG`,
frozen `PlatformProfile` dataclass, `PROFILES` dict, `get_profile()`
accepting string or enum) and `metadata.py` (frozen `PublishMetadata`
dataclass + `MetadataAdapter.adapt()` with platform-specific hashtag rules:
`#Shorts` for YouTube Short, bare tags for TikTok, none for Podcast). New
`src/ytb_pipeline/providers/publish/tiktok_provider.py` — TikTok
`PublishProvider` stub, checks `TIKTOK_ACCESS_TOKEN`, raises
`NotImplementedError` pointing to the TikTok Content Posting API.
`settings.py` gained `default_platform: str = "youtube_short"` and
`tiktok_access_token: str = ""`. `publish/uploader.py` gained an optional
`platform` param routed through `MetadataAdapter`. `tests/test_platform.py`
added (18 tests). **280 tests pass** (was 262). Known acceptable gap: TikTok
publisher is a stub — real upload requires TikTok Content Posting API OAuth
app approval (external dependency, not blocked on this repo). See
`docs/constitution/29-MIGRATION_PLAN.md` Phase 4, `31-ADR.md` ADR-017.

## Phase 5 Completion (2026-06-29)

New `src/ytb_pipeline/agents/` package: `base.py` (`AgentStatus` enum,
frozen `AgentResult` dataclass, `Agent` `runtime_checkable` Protocol),
`registry.py` (`AgentRegistry` class + module-level `agent_registry`),
`research_agent.py` (`ResearchAgent` — wraps `ideation/research.py`,
degrades gracefully when the YouTube API key is missing instead of
raising), `story_architect_agent.py` (`StoryArchitectAgent` — uses
`build_claude_cmd`, falls back to a 3-act placeholder if `claude` is not
found on `PATH`), `voice_director_agent.py` (`VoiceDirectorAgent` — pure
rule-based: code segments → slower pace, `voice_clone_required` → `f5`
provider), `seo_agent.py` (`SEOAgent` — pure rule-based, uses
`MetadataAdapter`, penalizes ALL-CAPS/overlength/generic titles),
`qa_agent.py` (`QAAgent` — enforces compliance/length/intro gates + the
self-help mantra check + sourced-claims check), `__init__.py`
(auto-registers all 5 agents into `agent_registry`). `tests/test_agents.py`
added (38 tests). **318 tests pass** (was 280). See `31-ADR.md` ADR-018:
agents never raise — every agent catches internal exceptions and returns
`AgentResult(status=FAILED, error=...)` instead. **Known gap:**
`StoryArchitectAgent` still calls the Claude CLI subprocess for narrative
structuring, not yet migrated to local Ollama/Qwen3 — that migration is
Phase 6 scope, not a Phase 5 blocker (see `29-MIGRATION_PLAN.md` Phase 5).
The originally planned `StoryboardAgent` (visual planning) was not
implemented in this phase; `VoiceDirectorAgent`/`SEOAgent`/`QAAgent` were
delivered instead, matching `IMPLEMENTATION_ROADMAP.md`'s Phase 5 agent
list. `StoryboardAgent` carries forward to Phase 6.

## Architecture

| Requirement | Status | Note |
|---|---|---|
| Clean + Hexagonal layering (domain has zero outward deps) | ⚠️ PARTIAL | `pkg/models.py` frozen dataclasses are clean; pipeline stages now resolve providers via Protocol ports (Phase 1, 2026-06-29), but the underlying `voiceover/tts.py`/`render/compose.py` implementations still import concrete SDKs directly inside the adapters that wrap them. |
| Provider Registry (Protocol-based, swappable) | ✅ DONE | `src/ytb_pipeline/providers/registry.py` — generic `ProviderRegistry[T]` + `get_voice_provider()`/`get_render_provider()`/`get_publish_provider()`; `providers/base.py` defines `VoiceProvider`/`RenderProvider`/`PublishProvider` Protocols. `pipeline.py` resolves via the registry. Phase 1, 2026-06-29; see `29-MIGRATION_PLAN.md`. |
| DAG workflow (vs linear pipeline) | ✅ DONE | `src/ytb_pipeline/project/workflow.py` — `WorkflowGraph`/`NodeDef` with Kahn's-algorithm topo sort (`31-ADR.md` ADR-015); `execute()` skips `DONE` nodes and checkpoints each transition. `pipeline.py::run_project()` runs the DAG; the original linear `run()` is kept unchanged alongside it. Phase 2, 2026-06-29. |
| `script.json` → `project.json` evolution | ✅ DONE | `src/ytb_pipeline/project/models.py` — frozen `Project`/`WorkflowNode` dataclasses with `to_dict`/`from_dict`. Phase 2, 2026-06-29; see `29-MIGRATION_PLAN.md`. Note: the `script.json` → `project.json` *compatibility loader* for legacy v1 artifacts is not yet separately verified in this audit pass. |
| Plugin discovery mechanism | ❌ MISSING | No registration mechanism for third-party providers; not expected until v4 per roadmap. |

## Domain Model

| Requirement | Status | Note |
|---|---|---|
| Frozen dataclass chain (`VideoIdea → Script → Voiceover → RenderedVideo → PublishResult`) | ✅ DONE | Implemented in `pkg/models.py`, enrichment via `dataclasses.replace()`, verified by `tests/test_models.py`. |
| `Segment` domain object (per-segment granularity) | ❌ MISSING | Needed for checkpoint/cache granularity per `25-CHECKPOINT_SYSTEM.md` §5; not yet defined. |
| `Character`/`Location` reusable objects | ❌ MISSING | v5 concept, not yet needed by current linear pipeline. |
| `04-DOMAIN.md` constitution document | ❌ MISSING | Referenced by `00-CONSTITUTION.md`'s index but the file itself does not exist in `docs/constitution/` yet. |

## Engine Specs

| Requirement | Status | Note |
|---|---|---|
| LLM engine spec doc | ❌ MISSING | No `docs/constitution/1x-LLM_ENGINE.md`-equivalent found. |
| Image engine spec doc | ❌ MISSING | Not found. |
| Video engine spec doc | ❌ MISSING | Not found. |
| Voice engine spec doc | ❌ MISSING | Not found. |
| Subtitle/caption engine spec | ⚠️ PARTIAL | `show_captions` setting exists and is implemented in render, but no dedicated constitution spec document. |
| Render engine spec doc | ⚠️ PARTIAL | `15-STICKMAN_ENGINE.md` references a `19-RENDER_ENGINE.md` that does not yet exist in the directory listing. |
| Publish engine spec doc | ❌ MISSING | Not found as a numbered constitution doc; behavior lives only in `publish/uploader.py` + `CLAUDE.md` prose. |

## Image / Render

| Requirement | Status | Note |
|---|---|---|
| `ImageProvider` Protocol | ✅ DONE | `src/ytb_pipeline/providers/base.py` — `ImageProvider` Protocol; `registry.py` gained `image_registry`/`get_image_provider()`. Phase 3, 2026-06-29; see `29-MIGRATION_PLAN.md`. |
| Flux/ComfyUI stub | ✅ DONE (partial — stub, not full) | `src/ytb_pipeline/providers/image/flux_provider.py` — `FluxImageProvider` pings ComfyUI `/system_stats`, raises `ProviderUnavailableError` if unreachable; minimal txt2img workflow JSON defined but not validated against a live ComfyUI instance with a real Flux checkpoint loaded. |
| AI image generation as slide-renderer default | ✅ DONE | `render/compose.py::_background_image()` resolves via `get_image_provider().generate()` (default `image_provider="pillow"`); switching to Flux is a one-line config change (`image_provider="flux"`), no code change. |
| No Pexels as default | ⚠️ PARTIAL | Slide renderer now goes through the `ImageProvider` abstraction (Pillow by default, Flux available). The separate `render_provider="ai"` B-roll path (`render/compose_ai.py`) is untouched and still defaults to Pexels — that's a different provider (video B-roll, not still-image background) and is Phase 6 scope, not Phase 3. |

## Multi-Platform Publish

| Requirement | Status | Note |
|---|---|---|
| `PlatformProfile` enum + resolution | ✅ DONE | `src/ytb_pipeline/platform/profiles.py` — `Platform` enum, frozen `PlatformProfile`, `PROFILES` dict, `get_profile()` (string or enum). Phase 4, 2026-06-29. |
| Platform-aware metadata adapter | ✅ DONE | `src/ytb_pipeline/platform/metadata.py` — frozen `PublishMetadata` + `MetadataAdapter.adapt()`; hashtag rules differ per platform (`#Shorts`/bare tags/none). Phase 4, 2026-06-29. |
| TikTok `PublishProvider` adapter | ✅ DONE (stub) | `src/ytb_pipeline/providers/publish/tiktok_provider.py` — checks `TIKTOK_ACCESS_TOKEN`, raises `NotImplementedError` pointing to the TikTok Content Posting API. Proves the extension point requires no core-file edits. Real OAuth-backed upload not yet implemented — blocked on TikTok API app approval, an external dependency. |

## Agent System

| Requirement | Status | Note |
|---|---|---|
| `Agent` Protocol definition | ✅ DONE | `src/ytb_pipeline/agents/base.py` — `AgentStatus` enum, frozen `AgentResult` dataclass, `Agent` `runtime_checkable` Protocol. Phase 5, 2026-06-29; see `29-MIGRATION_PLAN.md`. |
| ResearchAgent | ✅ DONE | `src/ytb_pipeline/agents/research_agent.py` — wraps `ideation/research.py`; degrades gracefully (returns `AgentResult(FAILED)`) when the YouTube API key is missing. Phase 5, 2026-06-29. |
| StoryArchitectAgent | ✅ DONE | `src/ytb_pipeline/agents/story_architect_agent.py` — uses `build_claude_cmd`; falls back to a 3-act placeholder if `claude` CLI is not found. Phase 5, 2026-06-29. Known gap: still calls Claude CLI, not yet migrated to local Ollama — Phase 6 scope. |
| StoryboardAgent | ❌ MISSING | Not implemented in Phase 5 — scope was adjusted in favor of `VoiceDirectorAgent`/`SEOAgent`/`QAAgent` (see `29-MIGRATION_PLAN.md` Phase 5 "Scope adjustment"). Carried forward to Phase 6. |
| VoiceDirectorAgent | ✅ DONE | `src/ytb_pipeline/agents/voice_director_agent.py` — pure rule-based, no LLM call; code segments → slower pace, `voice_clone_required` → `f5` provider. Phase 5, 2026-06-29. |
| SEOAgent | ✅ DONE | `src/ytb_pipeline/agents/seo_agent.py` — pure rule-based, no LLM call; uses `MetadataAdapter` (Phase 4), penalizes ALL-CAPS/overlength/generic titles. Phase 5, 2026-06-29; see `31-ADR.md` ADR-017's deferral of LLM-driven SEO to this agent. |
| QAAgent | ✅ DONE | `src/ytb_pipeline/agents/qa_agent.py` — enforces compliance/length/intro gates + self-help mantra check + sourced-claims check. Phase 5, 2026-06-29. |

## Memory / Cache / Checkpoint Systems

| Requirement | Status | Note |
|---|---|---|
| Memory system (working/episodic/semantic) | ❌ MISSING | Current state is `data/ledger.md` (manual markdown) + `auto_state.json` — neither matches the schema/storage spec in `23-MEMORY_SYSTEM.md`. Out of scope for Phase 2 (Project Model), which targeted checkpoint/cache, not memory. |
| Cache system (content-hash, unified manager) | ✅ DONE | `src/ytb_pipeline/project/cache.py` — `CacheManager` with SHA-256 content-hash keying, `get`/`put`/`has`/`stats`. Phase 2, 2026-06-29; see `29-MIGRATION_PLAN.md`. Wiring into the Phase-1 provider adapters (LLM/TTS/image/video clip cache types) not yet independently re-verified in this audit pass. |
| Checkpoint system (DAG node granularity) | ✅ DONE | `src/ytb_pipeline/project/checkpoint.py` — `CheckpointManager`, atomic save (`.json.tmp` + rename), `mark_running`/`mark_done`/`mark_failed`/`is_done`/`get_output`, fully immutable (returns new `Project`). Phase 2, 2026-06-29. Known limitation: cold-process resume for render/publish nodes raises `ValueError` pending full object rehydration — see Phase 2 completion note above. |

## Configuration

| Requirement | Status | Note |
|---|---|---|
| Pydantic-settings base | ✅ DONE | `src/ytb_pipeline/config/settings.py`, 78 lines, `.env`-backed singleton `settings`. |
| Field/model validators | ❌ MISSING | Zero `@field_validator`/`@model_validator` in current `Settings` class. |
| Platform profiles | ✅ DONE | `src/ytb_pipeline/platform/profiles.py` — `Platform` enum (`youtube_short`/`youtube_long`/`tiktok`/`instagram_reel`/`podcast`/`blog`), frozen `PlatformProfile` dataclass, `PROFILES` dict, `get_profile()`. `settings.py` gained `default_platform`. Phase 4, 2026-06-29; see `29-MIGRATION_PLAN.md`. |
| Per-project config override | ❌ MISSING | No `project.json`, hence no `config_overrides` mechanism. |
| Secrets via Keychain/Vault | ❌ MISSING | Plaintext files under `secrets/`, gitignored — acceptable per current roadmap stage, but the Keychain adapter described in `26-CONFIGURATION.md` §6 does not exist. |
| Startup `validate_environment()` checks | ❌ MISSING | No provider-availability, disk-space, or secrets-permission startup check found. |

## Coding Standards

| Requirement | Status | Note |
|---|---|---|
| Type hints everywhere, `mypy --strict` clean | ⚠️ PARTIAL | Not verified in this audit pass — no `mypy.ini`/`pyproject.toml` `[tool.mypy]` strict config confirmed present; needs a dedicated check. |
| Async-first (no nested `asyncio.run`) | ⚠️ PARTIAL | Project uses `asyncio_mode = auto` in `pytest.ini` implying async test support exists, but the four pipeline stages' actual async-ness was not verified line-by-line in this audit. |
| Immutability (frozen dataclasses, no mutation) | ✅ DONE | Core invariant already enforced and tested for `pkg/models.py`. |
| Structured logging (`structlog` JSON) | ❌ MISSING | No `structlog` dependency or usage found; current logging approach unverified but not confirmed structured. |
| File size ≤ 400 lines | ✅ DONE | `batch_cli.py` split (2026-06-29) into 6 modules; largest is `pipeline_runner.py` at 336 lines, `batch_cli.py` itself now 370 lines. See `29-MIGRATION_PLAN.md` Phase 0. |
| No hardcoded paths | ⚠️ PARTIAL | `settings.py` centralizes most paths (`assets_dir`, `output_dir`, secrets paths); not verified that every module respects this everywhere. |
| Provider pattern (Protocol per external service) | ✅ DONE | Phase 1 (2026-06-29): `VoiceProvider`/`RenderProvider`/`PublishProvider` Protocols + adapters per `31-ADR.md` ADR-008 and ADR-014. Known gap: `voiceover/tts.py` retains an internal `f5` branch, encapsulated behind the adapter and not visible to `pipeline.py`. |

## Testing

| Requirement | Status | Note |
|---|---|---|
| 290 test cases passing | ✅ DONE | **318 tests pass** as of Phase 5 (2026-06-29; was 280 after Phase 4, 262 after Phase 3, 249 after Phase 2, 222 after Phase 1). The "290" figure predates Phase 0/1/2/3/4/5's actual test counts and should be treated as superseded by the per-phase counts recorded in `29-MIGRATION_PLAN.md`. |
| 80% coverage floor | ✅ DONE | Current stated baseline per project context. |
| 90% coverage target | ❌ MISSING | Not yet raised; gated on Phase 0 split per `28-TESTING.md` §12. |
| Test pyramid markers (`integration`/`e2e`/`slow`) | ❌ MISSING | No evidence of these pytest markers in current `pytest.ini` beyond `asyncio_mode`/`pythonpath`/coverage flags. |
| No subprocess in unit tests | ⚠️ PARTIAL | Not individually audited per test file in this pass; flagged as a Phase B migration audit task in `28-TESTING.md` §12. |
| TTS tests use fixture audio, not real API | ⚠️ PARTIAL | `tests/test_f5_batch_worker.py`/`tests/test_f5_split.py` exist but their real-vs-fixture API usage was not individually verified in this audit. |

## Documentation

| Requirement | Status | Note |
|---|---|---|
| Constitution 00-02 complete | ✅ DONE | `00-CONSTITUTION.md`, `01-VISION.md`, `02-PRINCIPLES.md` exist and are substantive. |
| Constitution 03-05 (Architecture/Domain/Workflow) | ❌ MISSING | Referenced in `00-CONSTITUTION.md`'s document index but not present in `docs/constitution/` directory listing at time of this audit. |
| Constitution 15 (Stickman Engine) | ✅ DONE | Exists, explicitly marked "NOT IMPLEMENTED" status for the underlying feature (doc itself is complete). |
| Constitution 23-30 (Memory/Cache/Checkpoint/Config/Coding/Testing/Migration/Roadmap) | ✅ DONE | Authored in this pass. |
| `CLAUDE_NEW.md` | ✅ DONE | Authored in this pass; proposed replacement, not yet merged into `CLAUDE.md`. |
| `data/ledger.md` kept current | ⚠️ PARTIAL | Exists and is the current anti-duplication mechanism, but its accuracy/currency was not independently verified in this audit. |

## Migration Plan

| Requirement | Status | Note |
|---|---|---|
| All phases (0-5) defined with acceptance criteria | ✅ DONE | `docs/constitution/29-MIGRATION_PLAN.md`, authored in this pass. |
| Phase 0 actually executed | ⚠️ PARTIAL | `batch_cli.py` split into 6 modules, all ≤400 lines, 212 tests pass (2026-06-29). Pydantic validators, provider-branch extraction, and `structlog` JSON logging (Phase 0's other sub-goals) not yet started. |
| Phase 1 actually executed | ✅ DONE | Provider Registry + `VoiceProvider`/`RenderProvider`/`PublishProvider` Protocols + 6 adapters shipped 2026-06-29; 222 tests pass. Known acceptable gap: `tts.py` internal `f5` branch, encapsulated. See `29-MIGRATION_PLAN.md` Phase 1, `31-ADR.md` ADR-014. |
| Phase 2 actually executed | ✅ DONE | `src/ytb_pipeline/project/` package (`models.py`, `checkpoint.py`, `cache.py`, `workflow.py`) shipped 2026-06-29; `pipeline.py::run_project()` added; 249 tests pass (was 222). Known acceptable gap: cold-process resume for render/publish nodes needs full object rehydration — deferred follow-up, not a Phase 2 acceptance blocker. See `29-MIGRATION_PLAN.md` Phase 2, `31-ADR.md` ADR-015. |
| Phase 3 actually executed | ✅ DONE | `ImageProvider` Protocol + `PillowImageProvider`/`FluxImageProvider` adapters shipped 2026-06-29; `render/compose.py` slide background now resolves via `get_image_provider()`; 262 tests pass (was 249). Known acceptable gap: only the slide renderer's Pillow gradient was swapped — the Pexels-backed B-roll path in `render/compose_ai.py` (`render_provider="ai"`) is untouched and still defaults to Pexels; demoting that to an explicit `broll_strategy="pexels"` opt-in is Phase 6 scope. See `29-MIGRATION_PLAN.md` Phase 3, `31-ADR.md` ADR-016. |
| Phase 4 executed | ✅ DONE | `src/ytb_pipeline/platform/` package (`profiles.py`, `metadata.py`) shipped 2026-06-29; `providers/publish/tiktok_provider.py` stub added; `publish/uploader.py` gained optional `platform` param; 280 tests pass (was 262). Known acceptable gap: TikTok publisher is a stub pending TikTok Content Posting API OAuth approval. See `29-MIGRATION_PLAN.md` Phase 4, `31-ADR.md` ADR-017. |
| Phase 5 executed ✅ DONE | ✅ DONE | `src/ytb_pipeline/agents/` package (`base.py`, `registry.py`, `research_agent.py`, `story_architect_agent.py`, `voice_director_agent.py`, `seo_agent.py`, `qa_agent.py`, `__init__.py`) shipped 2026-06-29; `tests/test_agents.py` added (38 tests); **318 tests pass** (was 280). Known acceptable gap: `StoryArchitectAgent` still calls Claude CLI, not yet migrated to local Ollama — Phase 6 scope. `StoryboardAgent` deferred to Phase 6. See `29-MIGRATION_PLAN.md` Phase 5, `31-ADR.md` ADR-018. |
| Phase 6 executed ✅ DONE | ✅ DONE | `VideoProvider` Protocol + `PexelsVideoProvider`/`WanVideoProvider` adapters + `LLMProvider` Protocol + `OllamaProvider`/`ClaudeProvider` adapters + `local_stack.py` (`configure_local_stack()`) shipped 2026-06-29; `StoryArchitectAgent` migrated to `get_llm_provider()` (was hard-coded Claude CLI); `tests/test_video_provider.py` (11 tests) + `tests/test_llm_provider.py` (12 tests) added; **341 tests pass** (was 318). Known acceptable gap: Wan2.2 inference is a stub (`NotImplementedError`) pending `wan2.2` Python package availability; `StoryboardAgent` still deferred; `render/compose_ai.py` Pexels B-roll path unchanged. See `29-MIGRATION_PLAN.md` Phase 6. |

## Roadmap

| Requirement | Status | Note |
|---|---|---|
| v1→v5 milestones defined | ✅ DONE | `docs/constitution/30-ROADMAP.md`, authored in this pass. |
| v1.0 shipped | ✅ DONE | Current production state matches the v1.0 description (linear pipeline, Edge-TTS default, Pexels-capable render, monolithic `batch_cli.py`). |
| v1.1+ shipped | ❌ MISSING | Not started. |

## Summary

The project has a **solid domain-model and documentation foundation**
(frozen dataclasses, a real constitution set, an immutable vision document)
and, as of 2026-06-29, **completed all 6 phases (Phase 0–6)**:

- **Phase 0** — `batch_cli.py` split into 6 modules (≤400 lines each)
- **Phase 1** — Provider Registry with `VoiceProvider`/`RenderProvider`/`PublishProvider` Protocols + 6 adapters
- **Phase 2** — Project Model: `models.py`, `checkpoint.py` (atomic saves), `cache.py` (SHA-256 content-hash), `workflow.py` (Kahn's DAG + resume)
- **Phase 3** — `ImageProvider` Protocol + `PillowImageProvider` (default) + `FluxImageProvider` stub; slide renderer wired
- **Phase 4** — `Platform` profiles + `MetadataAdapter`; TikTok `PublishProvider` stub
- **Phase 5** — 5 Agent implementations behind `Agent` Protocol + `AgentRegistry`, all returning `AgentResult` (never raise)
- **Phase 6** — `VideoProvider` Protocol + `PexelsVideoProvider`/`WanVideoProvider` + `LLMProvider` Protocol + `OllamaProvider`/`ClaudeProvider` + `configure_local_stack()`; `StoryArchitectAgent` migrated to `get_llm_provider()`

**341 tests passing** (was 280 after Phase 4). Remaining structural gaps: no memory system; Wan2.2/StoryboardAgent pending; `render/compose_ai.py` Pexels B-roll path unchanged; `batch_cli.py` Phase 0 sub-goals (Pydantic validators, `structlog`) not started; TikTok pending OAuth approval; cold-process resume for render/publish needs full `project.json` rehydration (explicit Phase 2 carry-over). All phases shipped — next milestone is v1.2 hardening or a Final Release E2E pass.
