# Phase 12 — Bounded Semantic-Rejection Recovery Handoff

Previous handoffs: [Phase 11 production vision provider](./2026-08-28-production-vision-provider-phase11-handoff.md), [Phase 10 VisualJudge](./2026-08-27-visual-judge-phase10-handoff.md), and [Phase 9 visual candidates](./2026-08-27-visual-candidates-phase9-handoff.md). Those phases remain locked; Phase 12 only adds an opt-in bounded response to a successful semantic rejection.

## 1. Status

**PASS — complete.** Phase 12 implements one durable, deterministic recovery round for an opted-in multi-candidate `vlm_ranked` Shot. The default remains Phase-11 fail-closed behavior. No Phase 13 work was started.

## 2. Branch

`codex/phase12-semantic-recovery`, created from accepted Phase-11 HEAD `11e1ef5`.

## 3. Previous handoffs

- Phase 9 established durable per-Shot candidate slots, deterministic generation, and generation/selection separation.
- Phase 10 established contextual semantic evaluations, `vlm_ranked`, evaluation caching, infrastructure fallback, and semantic fail-closed behavior.
- Phase 11 activated the authorized xKiro vision adapter without changing the Phase-10 port.

Phase 12 reuses those contracts. It adds no provider, Judge schema, renderer behavior, or AssetRegistry provenance field.

## 4. Objective

When all technically valid round-0 candidates receive a successful Judge result but none is eligible, an explicitly opted-in profile may generate exactly one additional deterministic candidate round and judge the combined set. The process either selects a valid winner or persists an exhausted terminal state. It never loops and never rewrites the request from Judge prose.

## 5. Final architecture

```text
VisualRequest
    -> round 0 candidate generation/checkpoint
    -> technical validation
    -> whole-set VisualJudge
    -> ranked selector
         -> eligible winner ------------------------> VisualManifest
         -> successful semantic rejection
              -> fail_closed -----------------------> fail
              -> regenerate_once
                   -> round 1 generation/checkpoint
                   -> technical validation
                   -> whole-set Judge (round 0 + 1)
                   -> winner OR durable exhausted fail
```

Generation remains in `visual_assets`. Judge evaluation remains provider-neutral. Selection remains deterministic after evaluation. `VisualManifest`, Timeline, and prepared renderer see only the selected concrete asset.

## 6. Profile policy schema

`VisualGenerationProfile` adds:

```json
{
  "visual_generation": {
    "candidate_count": 3,
    "selection_policy": "vlm_ranked",
    "semantic_rejection_recovery": "regenerate_once"
  }
}
```

Allowed values are exactly:

- `fail_closed`
- `regenerate_once`

Unknown values raise `ContentProfileError`. This is deliberately not an arbitrary retry-count field.

## 7. Default behavior

The field defaults to `fail_closed`, including when absent from existing profile JSON. Existing profiles therefore retain Phase-11 cost and failure semantics. `first_valid`, the unchanged single-candidate direct path, `profile_local`, and successful derivative reuse do not enter recovery.

## 8. Exact semantic-rejection definition

Recovery eligibility requires all of the following:

1. candidate generation produced at least one technically valid concrete asset;
2. the Judge returned a valid strict structured result (fresh or reusable from the evaluation store);
3. `select_vlm_ranked()` found no eligible candidate because every candidate hard-failed and/or scored below the configured threshold.

`RankedSelectionOutcome.semantic_rejection` carries this fact separately from a missing technical candidate or infrastructure fallback. Scores and reasons remain evaluation data, not prompt instructions.

## 9. Infrastructure and technical failures

Judge timeout, authentication, rate-limit, provider/transport failure, and malformed output after the existing one repair are infrastructure failures. They continue to follow `visual_judge.hard_fail_on_judge_error`: explicit `fallback_first_valid` when allowed, otherwise failure. Neither path starts round 1.

ComfyUI/generation failure, missing candidate bytes, SHA mismatch, corrupt media, and failed technical validation are also not semantic rejection. Failed round-1 slots remain checkpointed for ordinary retry; no new generation round is allocated.

## 10. Generation-round identity

`CandidateSlot` now persists `generation_round` (`0` or `1`). A missing field in legacy JSON loads as `0`. `VisualCandidateSet.existing_rounds()` and `existing_slots_for_round()` enumerate persisted rounds deterministically.

The hard engine limit is `MAX_GENERATION_ROUND = 1`. Slot construction rejects every other round number, so no round 2 can be represented through the normal API.

## 11. Round-0 compatibility

Every Phase-9 identity is unchanged:

- slot 0 ID: `<shot_id>::candidate-00`
- slot N ID: `<shot_id>::candidate-NN`
- slot 0 cache: `<generation_key>.png`
- later cache: `<generation_key>.candidate-NN.png`
- slot 0 seed: `int(generation_key[:16], 16) % 2**32`
- later seed: the existing SHA-256 candidate-index derivation

This preserves existing cache files and AssetRecords when recovery is disabled or newly enabled.

## 12. Round-1 slot IDs

Round-1 locator IDs are:

```text
<shot_id>::round-01::candidate-NN
```

The round marker prevents a new candidate from occupying a round-0 checkpoint. Slot ID remains a project-local checkpoint locator; it is not `asset_id`, `request_id`, request fingerprint, or generation key.

## 13. Seed derivation

Round-1 seed input is:

```text
generation_key + generation_round + candidate_index
```

It is SHA-256-derived and independent of runtime order, timestamp, PID, randomness, and Python `hash()`. Deterministic linear probing guarantees each round-1 seed differs from all four allowed round-0 seeds and all earlier round-1 seeds, even if the initial 32-bit digest collides. The collision fix does not change any round-0 formula.

## 14. Cache paths

Round-1 files use:

```text
<generation_key>.round-01.candidate-NN.png
```

They cannot overwrite the Phase-8/9 slot-0 cache or other round-0 candidates. Existing candidate validation still checks physical presence, observed SHA-256, technical decodability, seed, and matching immutable AssetRecord.

## 15. Generation-key semantics

Round 0 and round 1 intentionally share the same semantic `generation_key` because the accepted `VisualRequest`, profile generation inputs, prompt, and dimensions are unchanged. Concrete uniqueness comes from slot ID, seed, path, generated bytes, `content_sha256`, and `asset_id`. `generation_key` was not overloaded into a concrete media identifier.

## 16. Candidate-store schema

The existing project artifact remains:

```text
assets/projects/<slug>/visual_candidates.json
```

Each `VisualCandidateSet` now additionally persists:

- `recovery_policy`
- `recovery_policy_version` (`phase12-v1`)
- `recovery_status`
- `active_generation_round`
- `semantic_rejection_rounds`
- `rejected_evaluation_fingerprint`

Each `CandidateSlot` adds `generation_round`. Scores and reasons are not duplicated here.

## 17. Durable recovery state

`recovery_status` has the bounded values:

- `not_needed`
- `eligible`
- `running`
- `resolved`
- `exhausted`

The store writes atomically after state changes and after every candidate attempt. A round-0 rejection is recorded before round 1 starts. A second semantic rejection records round 1 and `exhausted` before the resolver raises.

## 18. Round-1 generation

With `regenerate_once`, an eligible round-0 semantic rejection sets `active_generation_round=1` and `recovery_status=running`. The resolver generates exactly `candidate_count` round-1 slots sequentially with the original request and generation settings. It does not call Director, change `visual_intent`, or use Judge reasons to alter the prompt.

Every successfully generated candidate receives its own normal immutable `AssetRecord`. A partial generation failure writes the failed slot and exits before the second Judge evaluation.

## 19. Whole-set rejudge

After round 1 is technically complete, `_select_vlm_ranked()` receives every valid candidate from round 0 and round 1. Its deterministic comparative indices are:

```text
generation_round * candidate_count + candidate_index
```

Thus a three-candidate project sends indices `0..2` for round 0 and `3..5` for round 1. The selector may legitimately choose a round-0 asset after seeing the larger set. It is not constrained to a round-1 winner.

## 20. Judge-call bound

At the application `VisualJudge.evaluate()` boundary, one recovery event has at most:

1. the initial round-0 evaluation;
2. one post-round-1 whole-set evaluation.

Each adapter evaluation retains Phase 11's separate at-most-one structured-output repair, so malformed responses can cause at most two transport requests per evaluation boundary. There is no third evaluation caused by another candidate round.

## 21. Exhaustion

If the second valid semantic evaluation has no eligible candidate, the candidate set persists:

```text
recovery_status = exhausted
semantic_rejection_rounds = [0, 1]
active_generation_round = 1
selection_status = failed
```

The resolver raises a clear `Semantic recovery exhausted` error. An unchanged rerun reuses both rounds and the persisted whole-set evaluation, makes zero generation/Judge calls, raises again, and never creates round 2.

## 22. Resume behavior

Candidate writes are per slot. If round-1 slots 0 and 1 are complete and slot 2 fails, restart behavior is:

```text
round 0: validate and reuse all valid slots
round 1 slots 0–1: validate and reuse
round 1 slot 2: retry
Judge: run only after round 1 is complete
```

If the whole-set evaluation was already persisted, it is reused according to Phase-10 exact candidate/context identity. Downstream manifest/render failure does not regenerate or rejudge valid preparation state.

## 23. Request changes

A changed `request_fingerprint` causes `VisualCandidateStore.get_or_create()` to replace that Shot's candidate-set state with a fresh round-0 set. Old registry records remain immutable provenance, but they are not silently attached to the changed request. Unrelated runtime timestamps, output deletion, and render state do not affect the request fingerprint.

## 24. Judge changes

Changing Judge provider, model, policy version, threshold/selector context invalidates evaluation/selection identity but not generation identity. Existing round media remains. The resolver rejudges the current persisted candidate set without ComfyUI regeneration. An exhausted set does not receive a replenished recovery budget merely because the Judge configuration changed.

## 25. Recovery-policy changes

- `fail_closed -> regenerate_once`: a persisted eligible round-0 rejection reuses round 0 and creates only round 1.
- `regenerate_once -> fail_closed`: existing round-1 media and immutable records remain; no new media is generated and no spent budget is restored.
- `regenerate_once -> regenerate_once`: unchanged exhausted state remains terminal.

Recovery policy affects control flow, not candidate generation identity.

## 26. Candidate-count changes

The Phase-9 rule remains: changing target candidate count does not delete historical slots or invalidate their AssetRecords. Active selection/generation considers slots below the current target count for each persisted round. Increasing a count can fill newly required indices; decreasing it preserves the unused historical records. The engine-level maximum remains four candidates per round.

## 27. AssetRegistry interaction

AssetRegistry was not modified. Every round-0 and round-1 concrete asset is registered through the existing exact-observation path with immutable:

- `asset_id`
- `generation_key`
- `content_sha256`
- local path
- dimensions
- seed
- provenance/use observations

Semantic scores, rejection state, recovery status, winner/loser flags, and Judge reasons are not added to AssetRegistry. Selected and unselected candidates remain unchanged legitimate records.

## 28. VisualManifest interaction

VisualManifest remains minimal: each Shot resolves to the final selected `asset_id` plus existing request/checkpoint metadata. It does not store recovery rounds or copy evaluations. A winner from either round is written through the same Phase-4 manifest path. Prepared render consumes this selected resolution only.

## 29. Evaluation-store interaction

`assets/projects/<slug>/visual_evaluations.json` remains the sole semantic evaluation artifact. Phase-10 exact identity still covers request fingerprint, candidate `asset_id`/SHA set, Judge provider/model/policy/contract. Adding round 1 changes candidate identity and naturally invalidates the round-0-only whole-set evaluation. An unchanged exhausted rerun reuses the combined evaluation.

The candidate store retains only the most recent rejected evaluation fingerprint and rejected round numbers for bounded control-flow evidence.

## 30. Cost bound

`candidate_count <= 4` and `MAX_GENERATION_ROUND=1` cap one Shot at eight concrete candidate slots across two rounds. Generation stays sequential for the constrained local ComfyUI environment. Failed infrastructure attempts may retry the same checkpointed slot on a later operator rerun, but cannot allocate a third round or more than eight slot identities.

No automatic candidate expansion, prompt mutation, Director regeneration, or semantic rejection loop exists.

## 31. Observability

Structured logs include Shot ID, target count, selection policy/version, recovery policy/status, semantic-rejection round, recovery start, selected asset, infrastructure fallback, and exhaustion with generation/Judge bounds. Logs contain no API key, image bytes, or base64 payload.

## 32. Tests

Phase 12 added **22 test functions / 23 collected cases**:

- `tests/test_semantic_recovery.py`: 13 functions / 14 cases, using fake local generation and Judge boundaries plus real candidate/evaluation/manifest stores under `tmp_path`.
- `tests/test_visual_candidates.py`: round-0 compatibility, deterministic round-1 identities, forced seed-collision handling, legacy JSON, persisted state, request reset, and candidate-count behavior.
- `tests/test_visual_generation_profile.py`: default, explicit opt-in, and invalid recovery policy.

Related Phase-8–12/registry/timeline regression passed **171 tests** before the full suite. Profile/template/Phase-12 focused validation passed **83 tests**. The previously flaky batch-worker concurrency test was isolated from configured Telegram progress transport without weakening its claims/assertions; it then passed ten consecutive no-coverage repetitions and the final full suite.

## 33. Acceptance evidence

The primary acceptance test prepares three round-0 candidates, receives successful semantic rejection, prepares three deterministic round-1 candidates, judges the six-candidate whole set, and selects round-1 candidate 1. It proves:

- six immutable AssetRecords remain;
- exactly two Judge evaluations occur;
- all six concrete seeds are distinct;
- both rounds share the intended semantic generation key;
- VisualManifest points to the selected round-1 asset;
- no semantic/recovery mutation leaks into AssetRegistry;
- a second prepared-assets call with generation and Judge explicitly blocked succeeds from persisted state with zero calls.

Separate acceptance coverage proves the second whole-set evaluation may instead select a round-0 asset, partial round-1 resume retries only its failed slot, and exhaustion performs no round-2 work on rerun.

## 34. Exact full `make test` result

Final run on 2026-08-28:

```text
collected 1270 items / 1 deselected / 1269 selected
1266 passed, 3 skipped, 1 deselected, 0 failed
coverage: 82%
duration: 22.99s
```

Phase 11 collected 1247 items. Phase 12 adds 23 truthful collected cases.

The first full run exposed one pre-existing test-isolation issue: the batch-worker concurrency fixture allowed configured Telegram progress I/O, causing its one-second barrier to expire. That run was `1265 passed, 3 skipped, 1 deselected, 1 failed`. Commit `b7e3b3b` mocks only `notify_progress` in that worker-scheduling fixture; concurrency assertions are unchanged. The final full run above is the acceptance result.

## 35. Repository cleanliness

All Phase-12 generation, candidate, evaluation, registry, manifest, and prepared-render tests use `tmp_path` and local 8×8 generated PNGs. No live xKiro or ComfyUI call is made by `make test`. After the full suite:

- `git status --short assets/` is empty;
- no candidate/evaluation/manifest/runtime media leaked into repository assets;
- `.env`, credentials, caches, and generated media are not committed.

## 36. Commits

- `01e9f4b` — `test: add Phase 12 semantic recovery contract` (RED)
- `e9a5e8c` — `feat: add bounded semantic rejection recovery` (GREEN)
- `98126f8` — `test: strengthen Phase 12 recovery invariants`
- `630d709` — `test: reproduce Phase 12 seed collision` (RED)
- `ad359c1` — `fix: guarantee distinct Phase 12 candidate seeds` (GREEN)
- `97d8d1c` — `docs: document Phase 12 semantic recovery architecture`
- `b7e3b3b` — `test: isolate batch worker progress notifications`

This handoff's containing commit is reported in the final response; a commit cannot truthfully contain its own hash without rewriting history.

## 37. Deferred work / non-goals

Not implemented: round 2 or unbounded retries, adaptive candidate-count expansion, Judge-guided prompt rewriting, Director reruns, regenerate-on-infrastructure-failure, concurrent generation/Judge fan-out, automatic model/provider switching, human approval UI/queue, global quality/beauty scoring, CLIP/vector search, smart crop/reframing, new generation models, Short clipping/reuse changes, research changes, `compose_ai` Timeline migration, MCP, analytics changes, or AssetRegistry garbage collection.

## 38. Definition-of-Done checklist

1. ✅ Existing profiles default to `fail_closed`.
2. ✅ `regenerate_once` is explicit opt-in and strictly validated.
3. ✅ Only successful semantic rejection can authorize recovery.
4. ✅ Judge infrastructure failure never triggers candidate recovery.
5. ✅ Generation/technical failure never becomes semantic rejection.
6. ✅ Round 0 retains exact Phase-9 IDs, seeds, and cache paths.
7. ✅ Round 1 has deterministic distinct slot IDs, seeds, and cache paths.
8. ✅ Forced 32-bit seed collision is resolved deterministically.
9. ✅ Both rounds retain the correct semantic generation key.
10. ✅ Candidate and recovery state persist atomically.
11. ✅ Legacy candidate JSON loads without migration.
12. ✅ Partial round-1 progress resumes per slot.
13. ✅ Round-1 completion triggers one combined-set evaluation.
14. ✅ Combined selection can choose a candidate from either round.
15. ✅ A second semantic rejection persists `exhausted` and fails closed.
16. ✅ Unchanged exhausted reruns make no generation/Judge calls.
17. ✅ Request changes start a fresh candidate chain.
18. ✅ Judge changes rejudge without media regeneration.
19. ✅ Recovery-policy changes preserve existing media and spent budget.
20. ✅ Candidate-count changes preserve historical slots/records.
21. ✅ AssetRegistry provenance remains immutable and score-free.
22. ✅ VisualManifest stores only the final selected resolution.
23. ✅ Phase-10 evaluation identity/cache remains authoritative.
24. ✅ Prepared rerender remains Director/Judge/ComfyUI-free.
25. ✅ Audio/subtitle/Timeline architecture is unchanged.
26. ✅ Generation and Judge call bounds are explicit and tested.
27. ✅ Tests are offline and repository-isolated.
28. ✅ Architecture/profile docs are updated.
29. ✅ Persistent Phase-12 handoff exists.
30. ✅ Full `make test` passes with zero failures.
31. ✅ Focused commits exist and repository assets are clean.
32. ✅ Work stops before Phase 13.

## 39. Recommended next phase

Before authorizing broader automated recovery, a future Phase 13 should add operator-visible rejection/exhaustion reporting and an explicit manual disposition contract (accept an existing candidate, request a bounded human-authored prompt change, or abandon the Shot). It should preserve the current two-round hard bound and must not infer automatic expansion from Judge prose. **No Phase 13 implementation is included here.**
