# 28 — Testing

## Purpose

This document defines the testing strategy for `claude-ytb`, raising the
bar from the current 290-test, 80%-coverage baseline toward the
discipline a checkpointed, multi-provider, multi-platform DAG system
requires to stay trustworthy under refactor. It works alongside
`27-CODING_STANDARD.md` §7 (test-relevant coding rules) and
`02-PRINCIPLES.md` (SOLID/Provider Pattern, which is what makes most of
this testable in the first place).

## 1. Coverage Target

**90% line coverage on `src/ytb_pipeline/`, raised from the current 80%.**
Coverage is measured via the existing `pytest.ini` config
(`--cov=ytb_pipeline`). The raised bar specifically targets the modules
this document set is introducing or refactoring (`CacheManager`,
`CheckpointManager`, `Settings` validators, provider registries) — these
are exactly the modules where an untested edge case becomes a silent
production data-loss or recomputation bug, not a cosmetic issue.

Coverage is a floor, not a target to game: a file at 95% coverage with no
assertions on its core behavioral contract (e.g., a cache test that calls
`put()`/`get()` but never asserts the *correct* hash was computed) provides
less real confidence than a file at 85% with assertions that pin the
contract. Reviewers (`code-reviewer` agent, per project rules) check for
this, not just the coverage percentage.

## 2. Test Pyramid

| Layer | Share | Marker | Scope |
|---|---|---|---|
| Unit | 70% | (default, unmarked) | Pure functions, frozen-dataclass construction/`replace()`, cache-key derivation, checkpoint state transitions, config validators — no real I/O, all external services mocked/faked. |
| Integration | 20% | `@pytest.mark.integration` | Real file I/O against a temp directory, real FFmpeg invocation on a small fixture clip, real SQLite read/write against a temp `.db` file. |
| E2E | 10% | `@pytest.mark.e2e` | Full pipeline run end-to-end with `DRY_RUN=true`, exercising ideation→voiceover→render→publish-prep against fixture inputs, asserting a complete `project.json`/output artifact is produced. |

The pyramid shape (mostly unit, a meaningful integration layer, a thin E2E
layer) is enforced by review, not by a coverage tool — a PR that adds ten
new integration tests and zero unit tests for genuinely pure new logic
(e.g., a new cache-key hashing function) is a pyramid violation even if
total coverage looks fine.

## 3. Unit Tests

- Pure functions with no I/O: cache key derivation (`24-CACHE_SYSTEM.md`
  §2), checkpoint state machine transitions (`25-CHECKPOINT_SYSTEM.md` §6),
  `Settings` field/model validators, domain object `replace()`-based
  enrichment chains.
- All external services (LLM, TTS, image/video providers, YouTube/Drive
  APIs, Telegram) are mocked or faked at the `Protocol` boundary — a unit
  test for a pipeline stage injects a fake `VoiceProvider` that returns
  fixed bytes, it never calls a real adapter.
- AAA structure (Arrange-Act-Assert) per the project's standard test shape:

```python
async def test_cache_key_is_deterministic_across_dict_ordering() -> None:
    # Arrange
    params_a = {"voice_id": "v1", "speed": 1.0}
    params_b = {"speed": 1.0, "voice_id": "v1"}  # same content, different order

    # Act
    key_a = compute_cache_key(type="tts", provider="f5", model="f5-vi", params=params_a, prompt="xin chào")
    key_b = compute_cache_key(type="tts", provider="f5", model="f5-vi", params=params_b, prompt="xin chào")

    # Assert
    assert key_a == key_b
```

## 4. Integration Tests

Marked `@pytest.mark.integration`, excluded from the default fast run
(§9). Cover:

- Real FFmpeg invocation against a short fixture clip — asserting the
  actual subprocess call produces a valid output file with expected
  duration/resolution, not just that "ffmpeg was called with these args"
  (which a unit test with a mocked subprocess already covers).
- Real SQLite read/write for `CacheManager`'s registry and
  `CheckpointManager`'s persistence, against a temp `.db` file per test
  (never the real `data/` files), verifying schema correctness and that
  concurrent-ish read/write sequences behave as expected.
- Real file-system cache writes under a temp `assets/cache/` directory,
  verifying eviction (`24-CACHE_SYSTEM.md` §8) actually deletes files from
  disk, not just registry rows.

## 5. E2E Tests

Marked `@pytest.mark.e2e`. A small, fixed set of tests that run the full
pipeline with `DRY_RUN=true` against canned fixture inputs (a short
fixture script, fixture TTS provider returning pre-recorded audio, fixture
image/video providers returning placeholder assets) and assert:

- A complete `project.json` is produced with every expected checkpoint
  node `"done"`.
- No real network call occurs anywhere in the run (asserted via a network
  guard fixture that fails the test if any non-localhost socket is
  opened) — this is what `DRY_RUN=true` plus offline-first fixtures is
  meant to guarantee, and the guard makes the guarantee enforced, not just
  assumed.
- Resume behavior: an E2E test that kills the pipeline mid-run (simulated
  by raising at a specific checkpointed node) and re-invokes it, asserting
  already-`"done"` nodes are not recomputed (verified via a call-count
  spy on the fixture providers).

## 6. TTS Tests

Unit and integration tests for voiceover code **never call a real TTS
API/model** (no real Edge-TTS network call, no real F5-TTS local
inference invocation in the default test run — local inference is still
slow enough on a shared CI-style run to be a `slow`-marked exception, not
the default). Instead:

- A short, pre-recorded fixture audio file (`tests/fixtures/audio/sample_short.wav`,
  a few seconds, checked into the repo) stands in for any provider's
  output.
- The fake `VoiceProvider` used in tests returns that fixture's bytes
  regardless of input text — tests assert pipeline *behavior* (segment
  ordering, pause insertion logic, cache interaction) against the fixture,
  never assert anything about real synthesized speech content/quality
  (that's a manual/human-review concern, not an automated test concern).
- A single `@pytest.mark.slow` (or `@pytest.mark.integration`) test may
  exist to confirm a real local F5-TTS invocation still produces valid
  audio after a dependency upgrade — run manually or in a periodic job,
  never in the default `pytest` invocation.

## 7. YouTube API Tests

Tests for `publish/uploader.py` and related modules mock
`google-api-python-client` responses rather than hitting the real YouTube
Data API:

- Use a fixture/fake `googleapiclient.discovery.build()` return value (or
  a hand-rolled fake matching the small subset of the API surface actually
  used) so a test can assert "upload was called with these exact metadata
  fields" without any real quota usage, real video upload, or real OAuth
  flow.
- A test asserting `dry_run=True` short-circuits before any API client
  call is constructed at all is required — this is the single most
  safety-critical assertion in the test suite, since a regression here
  means a "dry run" test accidentally publishes a real video.

## 8. Batch CLI Tests

`batch_cli.py`'s current 1330 lines mix CLI parsing, orchestration, and
stage invocation, which forces today's tests into heavy mocking of the
whole module surface to test any one behavior. The testing-relevant fix
(mirroring `27-CODING_STANDARD.md` §8 and `29-MIGRATION_PLAN.md` Phase 0):

- Extract business logic (queue selection logic, ledger-entry formatting,
  OAuth token refresh decision logic, retry/backoff calculation) into pure
  functions in their own modules (`QueueManager`, `LedgerWriter`,
  `OAuthManager`, per the split plan).
- Test those pure functions directly with plain unit tests — no
  `subprocess`, no mocking of the CLI parser, no mocking of three
  unrelated stages just to test one function's logic.
- The remaining thin CLI entrypoint (`PipelineRunner` + arg parsing) gets a
  small number of integration-level tests asserting argument wiring is
  correct (`--tts-provider f5` actually reaches `Settings`), not
  exhaustive behavioral coverage — the behavior itself is already covered
  by the extracted pure-function unit tests.

## 9. pytest Configuration

`pytest.ini` (current + target):

```ini
[pytest]
asyncio_mode = auto
pythonpath = src
markers =
    integration: real I/O (filesystem, FFmpeg, SQLite) — excluded from default CI run
    e2e: full pipeline DRY_RUN=true run — excluded from default CI run
    slow: real local-model inference or other slow-but-correct checks — manual/periodic only
addopts = -m "not integration and not e2e and not slow" --cov=ytb_pipeline --cov-report=term-missing
```

Running the full suite including integration/E2E explicitly:

```bash
.venv/bin/pytest -m "integration or e2e" tests/
```

## 10. CI

Default CI (and default local `make test`) runs **unit tests only**
(`addopts` above already excludes `integration`/`e2e`/`slow` by default).
Rationale: integration tests depend on FFmpeg being installed and
sometimes-flaky filesystem timing; E2E tests are comparatively slow and
exercise the same logic unit tests already pin more precisely at the
function level. Integration and E2E suites run:

- On demand via `make test-integration` / `make test-e2e` targets.
- Before a release tag / major merge to `main`, as a manual or
  pre-release-gated step — not on every commit.

## 11. Current State

290 test cases, `pytest-asyncio` with `asyncio_mode = auto`, 80% measured
coverage, heavy mocking concentrated in `tests/test_batch_cli.py` because
`batch_cli.py` itself is a monolith with no extracted pure functions to
test in isolation.

## 12. Migration

1. **Phase A.** Raise the coverage gate from 80% to 90% only *after*
   Phase 0 of `29-MIGRATION_PLAN.md` (the `batch_cli.py` split) lands —
   raising the bar before the split would force low-value tests against
   the monolith instead of real tests against extracted pure functions.
2. **Phase B.** Add `integration`/`e2e`/`slow` markers to `pytest.ini` and
   retroactively tag any existing test that does real I/O (FFmpeg,
   network, real subprocess) that isn't already isolated — auditing
   `tests/test_uploader.py`, `tests/test_render_ai.py`, and
   `tests/test_f5_batch_worker.py` first, since these are the modules most
   likely to currently blur the unit/integration line.
3. **Phase C.** Add the network-guard E2E fixture (§5) and the
   `dry_run` short-circuit assertion (§7) as new, explicit tests if they
   don't already exist in equivalent form — these are the two highest-
   leverage tests in the whole suite given the cost of a false negative
   (an accidental real publish).
4. **Phase D.** As `CacheManager`/`CheckpointManager` are implemented
   (`24-CACHE_SYSTEM.md`, `25-CHECKPOINT_SYSTEM.md`), write their unit
   tests test-first (TDD, per the project's global testing rule), not
   retrofitted after implementation.
