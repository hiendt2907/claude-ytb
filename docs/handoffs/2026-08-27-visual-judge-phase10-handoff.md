# Phase 10 — Semantic Visual Judge + Ranked Candidate Selection — Handoff

## 1. Status

**IMPLEMENTATION PASS; production VLM activation is explicitly unavailable.**

The provider-neutral Judge contract, strict schema, durable evaluations,
ranked selector, invalidation, fallback/fail-closed behavior, resume, and real
prepared-render acceptance test are complete. The repository has no configured
provider capable of attaching and inspecting images, so Phase 10 deliberately
does not claim a production VLM adapter or fake vision through a text-only LLM.
This is the real provider-capability blocker required by the directive's §23.

Full suite: **1222 passed, 3 skipped, 1 deselected, 0 failed**.

## 2. Branch

`codex/phase10-visual-judge`, based directly on accepted Phase 9 branch
`codex/phase9-visual-candidates` at `281586f`.

## 3. Previous handoffs

- `docs/handoffs/2026-08-27-visual-candidates-phase9-handoff.md`
- `docs/handoffs/2026-08-27-derivative-visual-reuse-phase8-handoff.md`
- `docs/handoffs/2026-08-27-visual-assets-phase4-handoff.md`
- `docs/handoffs/2026-08-27-asset-registry-phase3.2-handoff.md`

## 4. Objective

Evaluate already-generated, technically-valid candidate `AssetRecord`s against
their exact `VisualRequest`, persist contextual evaluations, and add an opt-in
ranked selector without coupling judgment to generation, rendering, or
`AssetRegistry` provenance.

## 5. Architecture

```
VisualRequest
    -> Phase 8 derivative reuse?       YES -> selected AssetRecord
    -> profile_local?                  YES -> direct AssetRecord
    -> CandidateSet
    -> technical validation
    -> technically-valid AssetRecords
    -> optional VisualJudge
    -> durable CandidateEvaluation[]
    -> deterministic Selector
    -> selected AssetRecord
    -> VisualManifest
    -> Timeline
    -> prepared Renderer
```

No top-level DAG node was added. Evaluation and selection stay inside the
existing `visual_assets` preparation boundary. Renderer code was not given any
Judge, candidate, VLM, or generation dependency.

## 6. VisualJudge contract

`render/visual_judge.py` defines the provider-neutral `VisualJudge` protocol:

```python
evaluate(
    request: VisualRequest,
    candidates: tuple[JudgeCandidate, ...],
    context: JudgeContext,
) -> JudgeResult
```

The port contains no ComfyUI node IDs, cache layout, FFmpeg filters, provider
SDK objects, or mutable registry state.

## 7. Production provider adapter

No production adapter was added because none can be implemented honestly from
the current provider capabilities:

- `providers/base.py::LLMProvider.complete()` accepts text only.
- xKiro/DeepSeek V4 Pro and the Claude CLI wrapper implement that text-only
  contract and expose no image attachment.
- image providers generate media; they do not inspect candidate images.

`evaluate_via_transport()` supplies reusable strict JSON/repair orchestration,
but it is not represented as an image-capable adapter. Tests inject a fake
`VisualJudge`; production `vlm_ranked` with no injected Judge follows the
configured infrastructure-failure policy. No live network call was added.

## 8. Judge input

The bounded input is:

- `VisualRequest.visual_intent`, characters, semantic constraints, request ID;
- `JudgeCandidate.asset_id`, concrete local path, observed content SHA-256,
  candidate index;
- `JudgeContext.scene_id`, shot ID, video slug.

The entire project/repository, runtime analytics, ComfyUI workflow, registry
history, and provider implementation details are excluded.

## 9. Strict output schema

`JudgeResult` contains one `CandidateEvaluation` for every known candidate and
the Judge provider/model/contract version. Parsing rejects:

- unknown, missing, or duplicate candidate IDs;
- missing evaluations;
- unknown top-level/evaluation fields;
- wrong-type or out-of-range scores;
- unknown hard-failure codes;
- non-JSON or malformed structures.

Unknown provider-specific fields such as sampler/checkpoint/workflow therefore
cannot enter evaluation state.

## 10. Evaluation schema

```text
CandidateEvaluation
    asset_id
    semantic_score       [0.0, 1.0]
    character_score      [0.0, 1.0]
    composition_score    [0.0, 1.0]
    continuity_score     [0.0, 1.0]
    hard_failures[]      controlled codes only
    reasons[]            max 5, max 200 chars each
```

No beauty, attractiveness, body, age, gender, or racial desirability dimension
exists.

## 11. Evaluation persistence path

`assets/projects/<slug>/visual_evaluations.json`, implemented by
`VisualEvaluationStore`. It is an atomic project-local checkpoint separate
from both `visual_candidates.json` and global `AssetRegistry` provenance.

## 12. Evaluation fingerprint

An evaluation set is reusable only when all match exactly:

- `request_fingerprint`;
- complete `{asset_id: content_sha256}` candidate identity;
- Judge provider and model;
- Judge policy version;
- Judge contract version (`phase10-v1`).

A changed request, changed bytes, added/removed candidate, policy bump, model,
provider, or contract invalidates the evaluation. Runtime ordering/timestamps
do not participate.

## 13. Hard vs soft failures

Hard failures are controlled request-fidelity gates such as missing required
character/object, wrong main character/environment, major semantic
contradiction, unreadable required text, or unsupported format. A hard-failed
candidate is never eligible regardless of score.

Soft scores compare semantic completeness, character correctness, composition,
and continuity among otherwise usable candidates.

## 14. Scoring and ranking formula

The deterministic Phase 10 v1 aggregate is:

```text
0.50 * semantic_score
+ 0.25 * character_score
+ 0.15 * composition_score
+ 0.10 * continuity_score
```

Eligible candidates sort by descending aggregate score, then ascending
`candidate_index`. This makes score ties deterministic.

## 15. Thresholds

`visual_judge.minimum_score` defaults to `0.5` and is validated in
`[0.0, 1.0]`. A candidate below the threshold is ineligible even when it is
technically valid and has no hard-failure code.

## 16. Selector fingerprint and invalidation

`VisualCandidateSet` now persists `selection_policy`, `selection_mode`, and
`selector_fingerprint`. The selector fingerprint hashes:

- selector contract `phase10-selector-v1`;
- selection policy;
- target candidate count;
- for `vlm_ranked`: Judge provider/model/policy, minimum score,
  `hard_fail_on_judge_error`, and Judge contract version.

It is deliberately independent of generation identity. A stale selector makes
the manifest resolution stale but leaves candidate slots, files, and
`AssetRecord`s intact.

## 17. Policy-change behavior

Changing only `first_valid -> vlm_ranked`, Judge policy/model/provider,
threshold, fallback behavior, or candidate count returns through selection and
updates `VisualManifest`; valid candidates are revalidated and reused. The
mandatory prepare-level regression proves a reusable old manifest cannot hide
the policy change and that ComfyUI call count stays unchanged.

## 18. Fallback behavior

Judge infrastructure/provider failure with
`hard_fail_on_judge_error=false` records:

```text
selection_mode = fallback_first_valid
fallback_used = true
judge_error = <bounded error text>
```

and selects deterministic `first_valid`. The fallback is explicit, never a
fake successful semantic score, and is treated as retryable on the next
preparation. With the flag true, `visual_assets` fails.

## 19. Semantic rejection behavior

A successful Judge result where all candidates hard-fail or fall below the
threshold fails the Shot closed. It never falls back to `first_valid`. Phase 10
does not generate additional candidates or loop.

## 20. Repair policy

`evaluate_via_transport()` attempts the initial strict response plus at most
one repair request. A second malformed response becomes
`JudgeInfrastructureError`. Transport errors are infrastructure failures and
are handled by the same explicit profile fallback policy at the resolver.

## 21. Resume behavior

Phase 10 uses whole-set comparative evaluation: a complete exact-match
evaluation set is reused without another Judge call; any relevant mismatch
rejudges the complete technically-valid set once. It does not claim
per-candidate partial evaluation resume.

Candidate generation is still independently per-slot. If judging fails after
three valid candidates exist, the next run calls only the Judge; it makes zero
new generation calls.

## 22. Candidate-generation separation

Candidate media is prepared and persisted before judging. Technical
validation gates Judge input. Selector/evaluation changes never rewrite
generation keys, seeds, cache paths, candidate slots, or generated files.

## 23. AssetRegistry invariants

`asset_registry.py` is unchanged. Selected and unselected records retain their
original `asset_id`, `generation_key`, `content_sha256`, path, asset class, and
immutable provenance. No `quality_score`, `judge_score`, `winner`, or
`bad_asset` field is written. The same asset can legitimately receive a high
score for request A and a low score for request B.

## 24. VisualManifest integration

Manifest shape remains minimal: Shot -> final selected `asset_id`. Evaluation
arrays remain only in `visual_evaluations.json`; candidate detail remains only
in `visual_candidates.json`.

## 25. Phase 8 reuse interaction

Successful derivative reuse stays first and returns before candidate
generation or judging. It makes zero Judge calls and requires no evaluation
artifact.

## 26. profile_local interaction

`profile_local` remains a direct `AssetRecord` resolution and makes zero Judge
calls.

## 27. candidate_count=1 behavior

Default `candidate_count=1` plus `first_valid` stays on the pre-Phase-9 single
candidate path. It makes zero Judge calls and creates neither candidate nor
evaluation state.

## 28. first_valid behavior

`first_valid` remains available for any allowed candidate count and picks the
lowest-index technically-valid slot. It makes zero Judge calls.

## 29. VLM-ranked behavior

For `candidate_count>1` plus `vlm_ranked`, the resolver loads/reuses exact
evaluations, judges only when missing/stale, excludes hard-failed/below-threshold
candidates, and selects the deterministic highest eligible result. With the
current repository providers this path needs an injected `VisualJudge`; no
production vision adapter is claimed.

## 30. Observability

Logs record Shot ID, target candidate count, selection policy/version,
evaluation reuse versus fresh evaluation, hard-failure count, selected
`asset_id`, selection mode, and fallback error. Raw image payloads are never
logged.

## 31. Tests

Phase 10 added/extended:

- `tests/test_visual_judge.py` — protocol schema, strict parsing, repair,
  hard gates, threshold, ranking, deterministic tie-break;
- `tests/test_visual_evaluation_store.py` — exact persistence identity and
  invalidation;
- `tests/test_visual_assets.py` — resolver integration, zero-call paths,
  fallback/fail-closed, evaluation reuse, retry, reselection without
  regeneration, registry invariants;
- `tests/test_visual_generation_profile.py` and
  `tests/test_content_profile_template.py` — profile contract/defaults;
- `tests/test_profile_multivoice_render.py` — real FFmpeg prepared-rerender
  acceptance.

Collection grew from Phase 9's 1165 total items to 1226: **61 Phase 10 test
items added**. Focused Judge/candidate/profile suite: **125 passed**.
Relevant Phase 8/pipeline/render/audio/subtitle suite: **93 passed**.

## 32. Acceptance tests

The fake-Judge ranked path generates three candidate records, scores candidate
0 at 0.65, candidate 1 at 0.92, and candidate 2 at 0.99 with a hard failure.
Candidate 1 wins, evaluation state persists, candidate 2 cannot win, and all
three records remain.

The prepare-level reselection test first selects candidate 0 under
`first_valid`, then switches only policy to `vlm_ranked`; Judge selects
candidate 2 with zero additional generation calls and the manifest updates.

The FFmpeg acceptance test renders the ranked selection, deletes the final
MP4, blocks `VisualAssetResolver.resolve`, and rerenders from the persisted
ScenePlan/prepared asset map. The MP4 is rebuilt while provider/Judge call
counts remain exactly 3/1.

## 33. Repository cleanliness

All Phase 10 tests use temporary project, cache, registry, image, audio, and
output paths. After `make test`, `git status --short assets/` is empty. No
runtime test artifact leaked into repository `assets/`.

## 34. Commits

1. `4b96614` — `feat: add semantic visual judge contracts`
2. `a7767d4` — `test: require prepare-time visual reselection`
3. `86b76d9` — `fix: invalidate stale visual selections without regeneration`
4. `50a95a7` — `test: prove ranked visuals support prepared rerender`
5. `691c017` — `docs: document Phase 10 visual judging architecture`
6. The commit containing this file — `docs: add Phase 10 visual judge handoff`

No Phase 1–9 history was amended or rewritten.

## 35. Full make test result

```text
collected 1226 items / 1 deselected / 1225 selected
1222 passed, 3 skipped, 1 deselected, 0 failed
coverage: 82%
duration: 24.31s
```

## 36. Deferred work

Deferred exactly as requested: authorized production vision adapter; bounded
regeneration after semantic rejection; candidate expansion; CLIP/vector
search; global/aesthetic/person scoring; smart crop/reframing; Short clipping;
new generation models; Director redesign; research changes; compose_ai
Timeline migration; approval UI; MCP; analytics; AssetRegistry garbage
collection.

## 37. Definition-of-Done checklist

1. ✅ Provider-neutral `VisualJudge` contract exists.
2. ⚠️ No current provider supports vision; the production-adapter blocker is
   documented and no fake adapter is claimed.
3. ✅ Judge output is strict and validated.
4. ✅ Evaluations are durable.
5. ✅ Identity includes request, exact asset bytes, and Judge context.
6. ✅ Stale evaluations are not reused.
7. ✅ `first_valid` remains unchanged.
8. ✅ `vlm_ranked` is opt-in.
9. ✅ Ranking is deterministic.
10. ✅ Hard-failed candidates cannot win.
11. ✅ All semantic candidates rejected fails closed.
12. ✅ Infrastructure failure follows explicit fallback policy.
13. ✅ Semantic rejection never silently falls back.
14. ✅ Selector changes reselect without regeneration.
15. ✅ Judge changes rejudge without regeneration.
16. ✅ Candidate progress survives Judge failure.
17. ✅ Phase 8 reuse is Judge-free.
18. ✅ `profile_local` is Judge-free.
19. ✅ Default one-candidate path is Judge-free.
20. ✅ AssetRegistry provenance is unchanged.
21. ✅ VisualManifest contains only final selection.
22. ✅ Prepared renderer is Judge/generation-free.
23. ✅ Ranked acceptance passes.
24. ✅ Reselection-without-regeneration acceptance passes.
25. ✅ Phase 1–9 tests remain green.
26. ✅ Full `make test` passes.
27. ✅ Architecture docs updated.
28. ✅ This persistent handoff exists.
29. ✅ Focused commits created.
30. ✅ Repository clean except this handoff before its commit.
31. ✅ Stopped before Phase 11.

Production VLM DoD remains explicitly **not claimed** until an authorized
image-input provider exists; all provider-neutral Phase 10 work and its fake
acceptance harness are complete.

## 38. Recommended next phase

First add and validate one authorized, genuinely image-capable provider adapter
behind the existing `VisualJudge` port (mocked transport tests plus an explicit
operator smoke test outside `make test`). Only after that should a later phase
consider a bounded regenerate-after-rejection policy. Do not combine provider
activation with candidate expansion or renderer changes.

**STOP. Phase 11 was not started.**
