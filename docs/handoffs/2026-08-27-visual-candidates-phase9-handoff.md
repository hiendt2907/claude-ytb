# Phase 9 — Visual Candidate Sets + Selection Checkpoints — Handoff

## 1. Status

**PASS.** Implementation, tests, architecture docs, and this handoff are
complete. `make test`: **1161 passed, 3 skipped, 1 deselected, 0 failed**
(verified twice consecutively). Repository clean after the full run
(`git status --short assets/` empty).

## 2. Branch

`codex/phase9-visual-candidates`, created from `codex/phase8-asset-reuse`
at commit `0995d0b` ("docs: finalize Phase 8 reuse handoff").

## 3. Previous handoffs

- `docs/handoffs/2026-08-27-derivative-visual-reuse-phase8-handoff.md` —
  Phase 8 parent-reuse resolution, which Phase 9 keeps strictly ahead of
  candidate generation.
- `docs/handoffs/2026-08-27-asset-registry-phase3.2-handoff.md` — the
  locked `AssetRegistry` identity model and "exact observation" matching
  Phase 9 builds on unchanged.
- `docs/handoffs/2026-08-27-visual-assets-phase4-handoff.md` — the
  `VisualAssetResolver`/`VisualManifest` boundary Phase 9 extends.

## 4. Objective

Add durable multi-candidate visual generation and deterministic candidate
selection/checkpoint infrastructure, while preserving current
single-candidate behaviour by default and leaving real semantic VLM
judging for Phase 10. Achieved exactly as scoped — no Phase 1–8
architecture reopened, no Phase 10 semantic judging implemented.

## 5. Architecture

```
VisualRequest
    -> Phase 8 parent reuse?            (unchanged, still first)
        YES -> selected AssetRecord      (no candidate machinery touched)
        NO  -> profile_local?
            YES -> direct resolve        (no candidate machinery touched)
            NO  -> CandidateSet (candidate_count > 1 only)
                    -> candidate AssetRecords (Phase 3.x identity, unchanged)
                    -> deterministic Selector (`selection_policy`)
                    -> selected AssetRecord
    -> VisualManifest (Shot -> selected asset_id, unchanged shape)
    -> Timeline -> prepared Renderer (unaware of candidates/selection)
```

New module: `src/ytb_pipeline/render/visual_candidates.py`. Modified:
`src/ytb_pipeline/render/visual_assets.py` (`VisualAssetResolver` gains an
opt-in `_resolve_candidates` branch; the `candidate_count <= 1` branch is
the byte-for-byte pre-Phase-9 code), `src/ytb_pipeline/content_profiles.py`
(`VisualGenerationProfile` gains `candidate_count`/`selection_policy`/
`candidate_policy_version`, default-preserving).

No new pipeline DAG node. Candidate generation/selection lives entirely
inside the existing `visual_assets` node.

## 6. Candidate contract/schema

```python
CandidateSlot:
    candidate_slot_id: str        # f"{shot_id}::candidate-{index:02d}"
    candidate_index: int
    seed: int
    status: str                   # pending | done | failed
    asset_id: str | None
    attempt_count: int
    last_error: str | None

VisualCandidateSet:
    shot_id: str
    request_id: str
    request_fingerprint: str
    generation_key: str
    candidate_policy_version: str
    target_candidate_count: int
    candidates: dict[str, CandidateSlot]
    selected_asset_id: str | None
    selection_status: str         # pending | selected | failed
```

## 7. Persisted location

`assets/projects/<slug>/visual_candidates.json` — one file per project,
constructed by `prepare_visual_assets()` and passed into
`VisualAssetResolver(candidate_store=...)`. Written via
`VisualCandidateStore.write()` (atomic tmp-file + `replace`), the same
pattern `VisualManifest`/`ScenePlan`/`DerivativeLineage` already use.
Deliberately **not** part of `AssetRegistry` (global provenance) or
`VisualManifest` (final Shot -> selected asset).

## 8. Identity model

Kept fully independent of `AssetRegistry`'s own locked concepts
(`asset_id`/`content_sha256`/`generation_key`/`local_path` — untouched):

- `candidate_slot_id` — a locator into one project's candidate set, never
  a media identity.
- `candidate_index` — 0-based ordinal slot position.
- `candidate_seed` — deterministic hash of `(generation_key, index)`.
- `asset_id` — the real `AssetRegistry` record a slot's generation
  produced/reused; unaffected by anything in this module.

Array index is never used as permanent media identity — `candidate_index`
only labels a slot inside one `VisualCandidateSet`; the actual media
identity is always the `AssetRecord`'s `asset_id`.

## 9. Seed derivation

```python
def candidate_seed(generation_key: str, candidate_index: int) -> int:
    if candidate_index == 0:
        return int(generation_key[:16], 16) % (2**32)
    digest = hashlib.sha256(f"{generation_key}\x1fcandidate\x1f{candidate_index}".encode()).hexdigest()
    return int(digest[:16], 16) % (2**32)
```

Slot 0 is **exactly** the pre-Phase-9 single-candidate seed formula —
never random/timestamp/PID/`hash()`. Stable across process restarts and
runtime ordering: verified by
`test_candidate_seeds_are_deterministic_across_repeated_calls` and
`test_same_request_and_policy_reproduces_the_same_slot_identities`.

## 10. `generation_key` relationship

Unchanged — still `render/visual_assets.py::_generation_key()`, the same
formula since Phase 3. Phase 9 does not create a new `generation_key` for
different candidate seeds; it exercises the capability Phase 3 already
built (one `generation_key` -> many `AssetRecord`s) intentionally for the
first time. Verified by
`test_same_generation_key_may_be_shared_by_many_candidate_asset_records`.

## 11. Candidate cache path behaviour

```python
def candidate_cache_path(cache_dir, generation_key, candidate_index):
    if candidate_index == 0:
        return cache_dir / f"{generation_key}.png"          # legacy filename
    return cache_dir / f"{generation_key}.candidate-{index:02d}.png"
```

Slot 0 keeps the historical filename exactly; slots 1+ get a distinct
suffix. No two slots can ever collide (verified by
`test_candidate_slots_never_collide_with_slot_zero_or_each_other`).

## 12. Old-cache compatibility

A pre-Phase-9 single-candidate project's existing cache file *is* slot 0's
cache file (same path, same seed formula). Raising `candidate_count` later
finds that file already on disk (`fresh = not asset_path.is_file()` is
`False`) and the Phase 3.2 exact-observation cache-hit match reuses its
existing `AssetRecord` — no migration script, no regeneration. Verified
end-to-end by
`test_candidate_count_increase_reuses_slot_zero_without_regenerating`.

## 13. `candidate_count` default/max

Default `1` (`content_profiles.VisualGenerationProfile.candidate_count`).
Hard maximum `4` (`content_profiles.MAX_CANDIDATE_COUNT`), enforced both
at profile-load time (`ContentProfileError` on out-of-range) and in
`__post_init__`. Chosen conservatively because ComfyUI candidate slots
generate **sequentially** on one constrained-unified-memory Mac — no
GPU/ComfyUI fan-out was added (§35 of the directive).

## 14. Per-candidate resume

`VisualCandidateStore` persists every slot's `status`/`asset_id`/
`attempt_count`/`last_error` after **every** slot attempt (not just at the
end), so a crash mid-generation resumes correctly. `candidate_is_valid()`
re-validates a `done` slot (registry record exists, file exists, SHA-256
and seed still agree, technical validation still passes) before trusting
it — a slot that regressed between runs is retried, not blindly reused.
Verified by
`test_multi_candidate_resume_skips_valid_slots_and_only_retries_the_failed_one`.

## 15. Validation

`validate_candidate_image()` — strictly technical: file exists and is
non-empty, `PIL.Image.verify()` succeeds, decoded dimensions are non-zero.
No aesthetic, semantic, or person/appearance scoring of any kind.

## 16. Deterministic selection

`selection_policy="first_valid"` — the only Phase 9 policy: lowest
`candidate_index` whose slot is valid wins. `resolve_selection_policy()`
raises `ValueError` for any other name (also enforced at profile-load
time via `content_profiles._KNOWN_SELECTION_POLICIES`). Deliberately
simple — Phase 10 adds real semantic/VLM judging behind the same
selection boundary.

## 17. `VisualManifest` integration

Unchanged shape: `VisualManifestEntry.asset_id` still ultimately answers
"which concrete `AssetRecord` is this Shot's prepared visual" — it is
always the *selected* candidate's `asset_id` when candidates were used,
indistinguishable at that layer from a single-candidate resolution.
Candidate detail lives only in `visual_candidates.json`.

## 18. `AssetRegistry` behaviour

Completely unchanged (`asset_registry.py` was not modified). Every
candidate — selected or not — gets its own permanent record via the
existing `record_generated()`; multiple candidates sharing one
`generation_key` is exactly Phase 3's designed-for capability.

## 19. Unselected candidate behaviour

Unselected but technically valid candidates remain registered in
`AssetRegistry`, untouched — never marked failed, never deleted, never
have their provenance rewritten. Only the `VisualCandidateSet`'s own
per-project `selected_asset_id`/`selection_status` fields record what was
chosen; `AssetRegistry` provenance stays a pure historical fact.

## 20. Policy-change behaviour

A `candidate_policy_version` bump alone preserves all existing candidate
progress (`VisualCandidateStore.get_or_create` only resets on a changed
`request_fingerprint`). Verified by
`test_policy_version_change_alone_preserves_existing_candidate_progress`.

## 21. Candidate count increase/decrease

- **Increase** (e.g. 1 -> 3): slot 0 reused via cache-hit exact-observation
  match (§12 above); only the new slots generate. Verified by
  `test_candidate_count_increase_reuses_slot_zero_without_regenerating`.
- **Decrease** (e.g. 3 -> 1): no `AssetRegistry` record or physical file is
  deleted; the resolver simply stops looking at the now-unused slots
  (garbage collection is explicitly out of scope). Verified by
  `test_candidate_count_decrease_does_not_delete_prior_candidate_records`.

## 22. Phase-8 reuse interaction

`_parent_reuse()` in `visual_assets.py` still runs — and, on a hit,
returns — before `VisualAssetResolver.resolve()` is ever called. Candidate
generation is therefore structurally unreachable after a successful
derivative reuse; nothing needed to change. Verified by
`test_successful_derivative_reuse_never_creates_candidate_state`.

## 23. Profile-local interaction

`resolve()`'s `profile_local` branch returns before the
`visual_generation`/candidate logic is even read. Verified by
`test_profile_local_resolution_never_creates_candidate_state`.

## 24. Concurrency behaviour

Unchanged from Phase 8/9's shared dependency: `AssetRegistry`'s own
`locked_json_update`-based process-safe writes. Candidate slots generate
strictly **sequentially** within one resolver call — no new concurrency
was introduced by this phase, and none was required by the directive.

## 25. Failure policy

`minimum_valid_candidates` is effectively `1`: as soon as any target slot
is valid, selection succeeds even if other slots failed. Zero valid
candidates raises `ValueError` and `visual_assets` fails closed — the
same fail-closed behaviour the pre-Phase-9 single-candidate path already
had on a ComfyUI failure. No infinite retry: each slot attempts exactly
once per `prepare_visual_assets()` call; a failed slot is retried only on
a subsequent call (checkpoint/resume, not an internal retry loop).

## 26. Tests

- `tests/test_visual_candidates.py` (22 tests) — pure-module coverage:
  seed determinism/distinctness, cache-path non-collision, technical
  validation, persistence/checkpoint/resume, `first_valid` selection.
- `tests/test_visual_assets.py` (+14 new tests) — `VisualAssetResolver`
  wiring: `candidate_count=1` byte-for-byte legacy path, multi-candidate
  generation, resume-after-partial-failure, zero-valid fail-closed, count
  increase/decrease, profile_local and Phase-8-reuse never invoking
  candidate machinery.
- `tests/test_visual_generation_profile.py` (+5 new tests) — config
  parsing/validation: default `candidate_count=1`, bound enforcement
  `[1, 4]`, unknown `selection_policy` rejection.
- Pre-existing `tests/test_asset_registry.py` (Phase 3.2) untouched and
  still fully passing — no weakening of any prior contract test.

## 27. Acceptance tests

`test_multi_candidate_acceptance_prepare_persist_select_then_rerender_without_regeneration`
(in `tests/test_visual_assets.py`): prepares a 3-candidate `VisualRequest`
through `prepare_visual_assets()`, asserts exactly 3 generation calls and
3 `AssetRecord`s, asserts the `VisualManifest` references the selected
asset, asserts `visual_candidates.json` was persisted, then re-runs
`prepare_visual_assets()` with a provider that raises on any
`generate_scene()` call — asserting zero regeneration and the identical
prepared path, and that all 3 candidate records (unselected included)
remain registered.

`test_default_candidate_count_one_end_to_end_matches_phase8_generated_visual_behavior`:
the mandatory default-behaviour regression — one generation call on cache
miss, zero on cache hit, no `visual_candidates.json` ever created, when
`candidate_count=1`.

## 28. Repository cleanliness

`git status --short assets/` is empty after a full `make test` run. Two
**pre-existing** test-isolation leaks were found and fixed as a
prerequisite for certifying a clean full-suite run (both wrote into the
real repository `assets/asset_registry.json`/`assets/projects/` because
they never overrode `settings.asset_registry_path`/`settings.projects_dir`
— the same leak class Phase 3/3.1 handoffs already documented and had
partially fixed elsewhere):

- `tests/test_story_auto_generate_cache.py`'s `profile` fixture now
  monkeypatches `settings.asset_registry_path` into `tmp_path`.
- `tests/test_pipeline_quality_integration.py`'s shared `_prepare_run()`
  helper now monkeypatches `settings.projects_dir` and
  `settings.asset_registry_path` into `tmp_path` (needed because
  `test_render_uses_renderer_declared_by_script_content_profile` drives
  the real `story` renderer branch of the DAG).

Neither fix changes any test's assertions or behaviour — both are pure
isolation fixes, deliberately minimal and scoped to only the files that
leaked, not a repo-wide audit.

## 29. Commits

On branch `codex/phase9-visual-candidates`:

1. `feat: add opt-in multi-candidate visual generation and selection` —
   `content_profiles.py`, `render/visual_assets.py`, new
   `render/visual_candidates.py`, `docs/CONTENT_PROFILE_TEMPLATE.md`.
2. `test: cover Phase 9 candidate identity, cache, resume, selection` —
   `tests/test_visual_candidates.py` (new), `tests/test_visual_assets.py`,
   `tests/test_visual_generation_profile.py`.
3. `test: fix pre-existing asset-registry test leaks into real assets/` —
   `tests/test_story_auto_generate_cache.py`,
   `tests/test_pipeline_quality_integration.py`.
4. `docs: document Phase 9 multi-candidate visual architecture` —
   `docs/constitution/03-ARCHITECTURE.md`, this handoff.

(Exact commit boundaries may be combined at commit time; see `git log` on
this branch for the authoritative record.)

## 30. Full `make test` result

```
1161 passed, 3 skipped, 1 deselected in ~23s
```

Verified clean twice consecutively. Zero failures. `assets/` clean.

## 31. Deferred work (explicitly out of scope for Phase 9)

Real semantic VLM judging, CLIP similarity search, embedding/vector DB,
aesthetic/person scoring, `DirectorAgent` changes, candidate generation
for `profile_local` or after a successful derivative reuse, smart
crop/AI reframing, Short clipping, new image models (Flux/Wan/LTX),
research pipeline changes, `compose_ai`/Timeline migration, frontend,
MCP, analytics changes, automatic `AssetRegistry` garbage collection. A
`VisualJudge` protocol was **not** introduced — Phase 9's `resolve_
selection_policy()` dict is already the minimal seam Phase 10 needs to
add a second, real policy without touching Phase 9's contract.

## 32. Definition-of-Done checklist

1. ✅ Explicit durable candidate-set contract exists (`VisualCandidateSet`/`CandidateSlot`/`VisualCandidateStore`)
2. ✅ `candidate_count` defaults to 1
3. ✅ Existing single-candidate behaviour remains compatible (byte-for-byte code path)
4. ✅ Multi-candidate generation is opt-in and bounded (`[1, 4]`)
5. ✅ Candidate slots have deterministic distinct seeds
6. ✅ Multiple candidates cannot overwrite one another (distinct cache paths)
7. ✅ One `generation_key` may retain multiple concrete `AssetRecord`s correctly
8. ✅ Candidate state resumes per slot
9. ✅ Valid completed candidates are not regenerated
10. ✅ Technical validation exists (non-semantic)
11. ✅ Deterministic selection exists (`first_valid`)
12. ✅ Zero valid candidates fails closed
13. ✅ Selected `AssetRecord` flows to `VisualManifest`
14. ✅ Unselected valid `AssetRecord`s remain preserved
15. ✅ Policy-only reselection does not unnecessarily regenerate
16. ✅ Phase-8 derivative reuse remains ahead of candidate generation
17. ✅ `profile_local` remains direct
18. ✅ Prepared renderer remains generation/selection-free (untouched)
19. ✅ Default `candidate_count=1` regression test passes
20. ✅ Multi-candidate acceptance test passes
21. ✅ Phase 1–8 architecture remains intact (no `asset_registry.py`, `story.py` render core, or DAG wiring changes)
22. ✅ Full `make test` passes (1161 passed, 0 failed)
23. ✅ Architecture docs updated (`03-ARCHITECTURE.md`)
24. ✅ Persistent Phase 9 handoff exists (this document)
25. ✅ Commits created
26. ✅ Repository clean except explicitly unrelated user work
27. ✅ STOP after Phase 9

## 33. Recommended Phase 10

Real semantic visual judging behind the existing `resolve_selection_policy()`
seam: add a `VisualJudge`-style provider-neutral protocol
(`evaluate(request, candidate AssetRecords) -> evaluations`), a second
selection policy name (e.g. `"vlm_ranked"`) that a profile opts into the
same way it opts into `candidate_count > 1` today, and technical-validation-
gated candidates as the only ones eligible for semantic scoring (never
re-score a candidate that already failed `validate_candidate_image`). Keep
`first_valid` as the permanent zero-cost fallback when no judge is
configured or a judge call fails, so the fail-closed behaviour Phase 9
established is never regressed by adding intelligence on top of it.

**STOP. DO NOT START PHASE 10 without new explicit direction.**
