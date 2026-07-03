# 27 — Coding Standard

## Purpose

This document is the binding, enforceable coding standard for
`src/ytb_pipeline/` and `scripts/`. It operationalizes the principles in
`02-PRINCIPLES.md` (SOLID, Clean Architecture, immutability) into concrete,
checkable rules. A pull request that violates any **MUST** rule below is
not mergeable regardless of whether it "works."

## 1. Python Version

Target **Python 3.13+**. Use modern syntax it enables: `match` statements
where they clarify branching over chained `if/elif`, `X | Y` union syntax
in type hints (not `typing.Union`), `tomllib` for any TOML reads. Do not
maintain compatibility with Python versions below 3.13 — there is exactly
one runtime target (the developer's MacBook Pro M4), so there is no
compatibility matrix to preserve.

## 2. Type Hints

Type hints are **required on every function signature** (parameters and
return type) and every class attribute, with no exceptions for "obvious"
or private functions. `mypy --strict` must pass with zero errors on
`src/ytb_pipeline/`. Specifically:

- No bare `Any` except at a genuine external boundary (e.g., an
  untyped third-party SDK's raw response) — and even then, narrow it to a
  `TypedDict` or parse it into a domain dataclass immediately, not pass
  `Any` further into pipeline code.
- No `# type: ignore` without a trailing comment explaining *why* the
  ignore is necessary and that it isn't masking a real bug.
- Prefer `Protocol` classes for structural typing of `Provider` ports (see
  §11) over `abc.ABC` — Protocols don't force inheritance, which keeps
  adapters decoupled from a shared base class per `02-PRINCIPLES.md`'s
  Dependency Inversion principle.

## 3. Async

Prefer `async`/`await` for all I/O-bound work: provider calls (LLM, TTS,
image/video generation, YouTube/Drive API), file I/O on large media assets,
and the listener daemon's command dispatch. Concretely:

- **No `asyncio.run()` inside a function that's already part of an async
  call chain.** `asyncio.run()` is only acceptable once, at the single
  top-level CLI entrypoint or daemon startup — never nested, never called
  from inside a pipeline stage that might itself be invoked from an async
  context. Nested `asyncio.run()` is a guaranteed `RuntimeError` waiting to
  happen the moment a caller becomes async, and a code smell even before
  that.
- CPU-bound work that has no async-native library (e.g., some local model
  inference, Pillow rendering) should run via
  `asyncio.to_thread()`/`loop.run_in_executor()` rather than blocking the
  event loop, when it sits in a code path that also awaits I/O.
- Provider adapters expose `async def` methods on their `Protocol`
  interface even if a specific adapter's underlying SDK is currently
  synchronous — wrap the sync call in `asyncio.to_thread()` inside that one
  adapter, so the port's contract stays consistently async and callers
  never need to know which adapters are "really" sync underneath.

## 4. Immutability

**Never mutate.** This is the single most load-bearing convention in the
codebase (per `CLAUDE.md`: "KHÔNG BAO GIỜ mutate bản gốc"). Concretely:

- All domain objects (`pkg/models.py`'s `VideoIdea`, `Script`, `Voiceover`,
  `RenderedVideo`, `PublishResult`, and every object added to
  `04-DOMAIN.md`) are `@dataclass(frozen=True)`.
- To "add a field" or "enrich" an object, use `dataclasses.replace(obj,
  field=new_value)` to produce a new instance. Never write
  `obj.field = new_value` against a frozen instance (it will raise at
  runtime, which is the intended guardrail, not an obstacle to work around
  with `object.__setattr__`).
- Collections held by domain objects are immutable types where practical
  (`tuple` over `list`, a frozen mapping pattern over a plain `dict`) so a
  caller can't mutate a "copy" they received and corrupt shared state.
- This extends to configuration and cache/checkpoint records: a
  `CheckpointRecord` (per `25-CHECKPOINT_SYSTEM.md`) update produces a new
  record; the `CheckpointManager` replaces the map entry, it does not
  mutate a record object in place.

## 5. Error Handling

- Catch **specific exception types**, never a bare `except:` and never a
  blanket `except Exception:` used to silently continue. If a broad catch
  is genuinely necessary at a boundary (e.g., the top-level CLI loop must
  not crash on any unhandled stage error), it must log the full exception
  with structured context (§6) and re-raise or explicitly convert to a
  typed result — it must never just `pass` or `continue`.
- Define typed exceptions per failure domain where a caller needs to branch
  on failure kind (e.g., `ProviderUnavailableError`, `QuotaExceededError`,
  `InvalidScriptError`) rather than parsing exception message strings.
- Validate at every system boundary (API response, file read, env var,
  user/Telegram input) before the value crosses into domain or pipeline
  code — fail fast with a clear, specific message naming the offending
  field/value, consistent with `26-CONFIGURATION.md`'s fail-fast-at-startup
  posture.

## 6. Logging

**Structured logging via `structlog`, emitting JSON.** `print()` and the
stdlib `logging.info(...)`-with-string-interpolation pattern are both
disallowed in `src/ytb_pipeline/` (test code and one-off `scripts/` may use
`print` for direct human-facing CLI output, but never inside pipeline/domain
modules).

```python
import structlog

logger = structlog.get_logger(__name__)

logger.info(
    "voiceover.segment.synthesized",
    project_id=project.id,
    segment_index=3,
    provider="f5",
    duration_ms=4210,
    cache_hit=False,
)
```

Rules:

- Every log call includes a stable, dot-namespaced event name as the first
  positional argument (`"voiceover.segment.synthesized"`), not a free-form
  sentence — this makes logs grep-able and machine-parseable.
- Every log call inside a pipeline stage includes `project_id` (and
  `node_id` once `25-CHECKPOINT_SYSTEM.md` exists) so that all log lines
  for one production run can be correlated without manual timestamp
  matching.
- A correlation ID (`project_id`, or a `run_id` for non-project-scoped
  operations like cache warming) is bound once via
  `structlog.contextvars.bind_contextvars(...)` at the start of a
  run/request and automatically appears on every subsequent log line for
  that context — not re-passed as a kwarg at every call site by hand.
- Log levels: `debug` for provider request/response payloads (verbose,
  off by default), `info` for node start/complete events, `warning` for
  retried-but-recovered failures, `error` for failures that abort a node,
  `critical` reserved for failures that abort an entire run (e.g., CRAT/
  audit-chain-equivalent integrity failures, were this project to adopt
  one).

## 7. Testing

See `28-TESTING.md` for the full strategy. Coding-standard-relevant rules:

- All async test functions run under `pytest-asyncio` with
  `asyncio_mode = auto` (already set in `pytest.ini`) — no manual
  `@pytest.mark.asyncio` decoration needed or wanted.
- If Redis is introduced (per `23-MEMORY_SYSTEM.md`'s optional hot cache),
  unit tests use a fake/in-memory Redis (`fakeredis`), never a real Redis
  instance, and never `AsyncMock` standing in for actual data structure
  semantics (a `ZSET`/`HASH` op should behave like one in tests, not return
  whatever a mock was told to return).
- **No `subprocess` calls inside unit tests.** Tests that need to verify
  FFmpeg/real-process behavior are integration tests (`@pytest.mark.integration`),
  excluded from the default fast unit run.

## 8. File Size

**Maximum 400 lines per file.** This is a hard ceiling, not a guideline —
`src/ytb_pipeline/orchestrator/batch_cli.py` is currently **1330 lines**
and is the canonical example of the defect this rule exists to prevent (see
`29-MIGRATION_PLAN.md` Phase 0 for its split plan into `QueueManager`,
`PipelineRunner`, `LedgerWriter`, `OAuthManager`). When a file approaches
300 lines, that is the signal to extract a cohesive sub-responsibility into
its own module — not to wait until 400 is breached and then scramble.

Target typical size: 200–300 lines. A file under ~50 lines that exists
solely to satisfy this rule (over-fragmentation) is also a smell — split by
genuine responsibility boundary (per `02-PRINCIPLES.md` Single
Responsibility), not by arbitrary line count alone.

## 9. Naming

- Functions and variables: `snake_case`, descriptive
  (`synthesize_segment_audio`, not `synth` or `do_tts`).
- Booleans: `is_`/`has_`/`should_`/`can_` prefix (`is_dry_run`,
  `has_cached_output`, `should_retry`).
- Classes, dataclasses, `Protocol`s, enums: `PascalCase`
  (`VoiceProvider`, `RenderedVideo`, `PlatformProfile`).
- Module-level constants: `UPPER_SNAKE_CASE`
  (`DEFAULT_MAX_CACHE_GB = 20`).
- Custom async generators/coroutines follow the same `snake_case` +
  intent-revealing name convention as any function — no special prefix
  beyond what `async def` already signals.

## 10. Imports

**Absolute imports only.** `from ytb_pipeline.pkg.models import Script`, never
`from ..pkg.models import Script` or `from .models import Script`. This
keeps module identity unambiguous regardless of which directory a file is
moved to during the splits required by `29-MIGRATION_PLAN.md`, and matches
the existing `pythonpath = src` convention in `pytest.ini` (which makes
`ytb_pipeline` importable as a top-level package from anywhere in the test
suite).

## 11. Provider Pattern

Every external service or swappable capability (LLM, Voice, Image, Video,
Publish, and — per `26-CONFIGURATION.md` §6 — Secrets) is defined as a
`Protocol` interface in the application layer, with concrete SDK usage
confined to adapter modules implementing that Protocol:

```python
from typing import Protocol

class VoiceProvider(Protocol):
    async def synthesize(
        self, text: str, voice_id: str, *, speed: float = 1.0
    ) -> bytes:
        """Return synthesized audio bytes (WAV). Must be idempotent for
        identical (text, voice_id, speed) given the Cache System sits in
        front of this call, not inside it."""
        ...
```

Rules:

- Domain and pipeline modules import only the `Protocol`, never a concrete
  SDK (`elevenlabs`, `google.generativeai`, the F5-TTS package, etc.)
  directly. Concrete imports live exclusively inside
  `src/ytb_pipeline/providers/<capability>/<adapter_name>.py`.
- A `Provider` chosen at runtime is resolved through a small registry
  function (`resolve_voice_provider(settings) -> VoiceProvider`), not a
  scattered `if tts_provider == "edge": ... elif ... :` chain repeated at
  every call site — exactly one resolution function per capability, called
  once per run, with the resolved instance passed down.
- Adding a new adapter must require adding exactly one new file under
  `providers/<capability>/` and one line in that capability's registry
  function — never an edit to an existing adapter or to domain/pipeline
  code.

## 12. Comments

Comments explain **why**, never **what** — the code itself says what it
does; a comment restating that in English is noise. Existing Vietnamese
domain comments in the codebase (e.g., `CLAUDE.md`'s own Vietnamese
sections, `settings.py`'s field comments) are acceptable and should
continue for **domain/business-rule context** (niche rules, content
policy, channel-specific judgment calls) — Vietnamese is the team's native
language for that kind of reasoning. Comments explaining a non-obvious
*engineering* decision (why a retry count is 3, why a timeout is 30s, why a
lock is needed here) may be in English or Vietnamese; consistency within one
file/module is preferred over a hard global rule on language.

## 13. Dependencies

- Every runtime dependency is explicit in `requirements.txt` (or the
  project's equivalent dependency manifest), pinned to a known-good
  version range — no dependency is allowed to be "available because some
  other package happens to pull it in transitively."
- Before adding a new dependency, check: does an existing dependency
  already cover this need? Is there a local-first option consistent with
  `PROJECT_VISION.md`'s local-inference-priority before reaching for a
  cloud SDK?
- Dev-only dependencies (test runners, linters, type checkers) are
  separated from runtime dependencies (a `requirements-dev.txt` or
  equivalent extras group) so a production install doesn't pull test
  tooling onto the M4's disk unnecessarily.

## 14. No Hardcoded Paths

All filesystem paths route through `settings` (`assets_dir`, `output_dir`,
`youtube_client_secrets`, etc.) — never a literal `"assets/output/foo.mp4"`
string constructed inline in a pipeline module. If a new path concept is
needed (e.g., `assets/cache/` per `24-CACHE_SYSTEM.md`), it gets a new
`Settings` field (or a computed property derived from `assets_dir`), so
every path is relocatable by changing one config value, never by grepping
the codebase for string literals.

## Checklist (per PR)

- [ ] `mypy --strict` clean
- [ ] No file over 400 lines (no new file added that's already over, no
      existing file pushed further over without a tracked split plan)
- [ ] No `print()`/`logging.info(f"...")` string-interpolation logging in
      `src/ytb_pipeline/`
- [ ] No bare `except:`
- [ ] No mutation of a frozen dataclass (no `object.__setattr__` workaround)
- [ ] No new concrete SDK import outside `providers/`
- [ ] No new hardcoded path literal
- [ ] Tests added/updated; `pytest` green; coverage per `28-TESTING.md`
