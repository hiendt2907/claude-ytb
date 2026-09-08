# Phase 13 — Operator Review, Human Disposition & Engine Freeze Handoff

Previous handoffs: [Phase 12 bounded semantic recovery](./2026-08-28-semantic-recovery-phase12-handoff.md), [Phase 11 production Vision provider](./2026-08-28-production-vision-provider-phase11-handoff.md), and [Phase 10 VisualJudge](./2026-08-27-visual-judge-phase10-handoff.md). Their contracts remain locked. Phase 13 adds the final v1 AI-engine boundary after bounded automation.

## 1. Status

**PASS — complete.** Semantic fail-closed and recovery exhaustion now create a
durable, process-safe operator review. Operators can accept a managed existing
candidate, authorize one human-instructed regeneration attempt, or abandon the
Shot. The product distinguishes review and abandonment from infrastructure
failure. The v1 AI engine is feature-frozen after this phase.

## 2. Branch

`codex/phase13-operator-disposition`, created from completed Phase-12 HEAD
`96389e2`.

## 3. Previous handoffs

- Phase 10 owns contextual strict evaluation, selection, cache and semantic
  fail-closed semantics.
- Phase 11 owns the authorized production xKiro image-capable Judge adapter.
- Phase 12 owns the only autonomous semantic-rejection recovery round and its
  durable exhaustion state.

Phase 13 changes none of those identities, Judge schemas, provider transports
or autonomous limits.

## 4. Phase 13 objective

End AI autonomy cleanly after a successful semantic rejection can no longer be
resolved within Phase 12's configured budget. Persist enough bounded context
for a human decision, apply that decision audibly and resumably, then continue
through the same `VisualManifest`/Timeline/prepared-render path without a web
UI, new queue, new provider or unbounded generation.

## 5. Final AI-engine architecture

```text
Script -> Narration -> ScenePlan / Director -> VisualRequest
    -> Phase 8 reuse OR candidate generation
    -> technical validation -> VisualJudge -> ranked selection
    -> optional Phase 12 regenerate_once
    -> autonomous boundary ends
       -> operator review when required
          -> accept_existing
          -> manual_regenerate (one attempt)
          -> abandon
    -> VisualManifest -> Timeline -> prepared Renderer
```

Successful derivative reuse, `profile_local`, `first_valid`, an eligible VLM
winner and infrastructure fallback remain review-free.

## 6. Autonomous boundary

AI autonomy is bounded. The engine may generate round 0 and, only when the
profile opts in and a valid Judge result rejects every candidate, Phase 12
round 1. It may never create autonomous round 2. Judge reasons/scores never
rewrite `visual_intent`, the generation prompt, ScenePlan or Director output.

Manual regeneration is on the human side of the boundary: the operator writes
one explicit bounded instruction and the normal pipeline later executes the
persisted attempt. It is not an autonomous recovery round.

## 7. Review triggers

A review is created only for:

1. `semantic_fail_closed`: valid semantic evaluation has no eligible candidate
   and recovery policy is `fail_closed`;
2. `semantic_recovery_exhausted`: both allowed automated rounds are complete,
   validly evaluated and rejected.

Later lifecycle reasons are `manual_semantic_rejection` and
`accepted_asset_invalid`. Judge timeout/auth/rate-limit/provider/transport
failure, malformed response after repair, ComfyUI failure, corrupt/missing
media and other infrastructure/technical errors do not create a review.

## 8. Review artifact and schema

Project-local artifact:

```text
assets/projects/<slug>/visual_review.json
```

Contract version: `phase13-review-v1`. Each `VisualReviewEntry` stores:

- deterministic `review_id`, `shot_id`, `scene_id`;
- `request_id` and exact `request_fingerprint`;
- bounded request snapshot: `visual_intent`, characters, dimensions,
  resolution kind and semantic constraints;
- status, review reason and recovery status;
- exact candidate `asset_id` history and evaluation fingerprint;
- disposition, selected asset, selection mode and bounded error;
- optional `ManualVisualOverride` and timestamps.

It does not copy provider secrets, raw image bytes, full registry provenance,
raw model payloads or all evaluation records. Read-only access does not create
the file.

## 9. Status lifecycle

`ReviewStatus` values are `pending`, `resolved`, `abandoned`, and `stale`.

```text
semantic halt -> pending
pending + accept/manual winner -> resolved
pending + abandon -> abandoned
request fingerprint changes -> previous current decision becomes stale
resolved asset invalid -> pending / accepted_asset_invalid
manual semantic rejection -> remains pending / manual_semantic_rejection
```

A terminal disposition cannot be applied twice. An unchanged repeated semantic
halt derives the same review ID and reuses its durable state.

## 10. Accept-existing contract

`accept_existing` requires a current pending review and an `asset_id` present
both in the entry's recorded candidate history and the current automated or
manual candidate checkpoint for that Shot. The candidate must have an
`AssetRecord`, existing physical file, matching observed SHA-256 and a passing
technical image validation. A foreign registry asset, stale candidate,
missing record/file, SHA mismatch or corrupt image is rejected.

## 11. Human override auditability

Human acceptance may deliberately override a semantic Judge rejection. The
review persists disposition `accept_existing`, selected asset and
`selection_mode=operator_override`. The candidate checkpoint records the same
selection mode and `VisualManifest` receives the final asset resolution.
Existing Judge evaluations remain unchanged, preserving why automation
rejected the asset and why a human later accepted it.

## 12. Manual regeneration contract

Disposition `manual_regenerate` requires one non-empty instruction of at most
1000 characters. The CLI records state only; it calls neither ComfyUI nor the
Judge. On the next normal pipeline run, visual preparation initializes and
executes one manual candidate set using the existing profile candidate count
(bounded 1–4), existing generator and existing selector/Judge policy.

Only one `ManualVisualOverride` may be submitted for a review. A rejected or
interrupted attempt does not replenish this budget.

## 13. Original versus derived VisualRequest

The original `VisualRequest` is never mutated. `derive_manual_visual_request()`
creates a frozen derived request that preserves scene, Shot, characters,
dimensions, resolution kind and semantic constraints, and appends the explicit
operator instruction to the visual intent. It receives a distinct deterministic
request ID/fingerprint linked to the original request fingerprint and override.

## 14. Manual generation identity

Contract version: `phase13-manual-override-v1`. The deterministic override
fingerprint hashes contract version, original request fingerprint, Shot ID and
normalized instruction. It derives:

- `override_id = mvo_<24 hex>`;
- `derived_request_id = mvr_<24 hex>`;
- a separate derived request fingerprint;
- deterministic manual candidate slot IDs containing Shot + override + index;
- deterministic seeds from manual generation key + candidate index;
- cache names ending `.manual-candidate-NN.png`;
- evaluation key `<shot>::manual::<override_id>`.

Repeated identical accepted input produces identical identity; timestamps,
PID, Python `hash()` and randomness are absent.

## 15. Generation-key implications

The manual generation key hashes the existing automated generation key with
the manual override fingerprint and manual contract version. It therefore
does not collide with round 0/1 automated cache identity, while retaining a
traceable relationship to the same profile/generation configuration. Each
result still receives an ordinary immutable concrete AssetRecord with its
actual path, seed and content SHA.

## 16. Manual candidate behavior

Manual candidates generate sequentially through the existing story provider.
Every slot persists `pending|running|done|failed`, seed, attempt count,
`asset_id` and last error immediately. If slots 0/1 are done and slot 2 fails,
restart validates/reuses 0/1 and retries only slot 2. Completed automated
candidates and the original evaluation remain intact. No adaptive candidate
expansion or new provider path exists.

## 17. Judge behavior

The completed manual set is evaluated through the existing Phase-10 strict
whole-set Judge and selector. It uses the current configured provider/model,
minimum score, hard failures, deterministic ranking and infrastructure
fallback policy. Results persist under the manual evaluation-store key, so
they do not overwrite the original Shot evaluation.

An eligible winner resolves the review. A valid semantic rejection records
the manual evaluation fingerprint, appends manual assets to review history,
sets `manual_semantic_rejection`, and remains pending. An unchanged rerun makes
zero new generation or Judge calls. Infrastructure failure retains Phase-10
fallback/hard-fail semantics and is not recast as semantic rejection.

## 18. No-autonomous-round-2 proof

The existing `MAX_GENERATION_ROUND=1` remains unchanged and no call uses
`generation_round=2`. Phase-13 manual paths use separate override IDs,
generation keys, cache names and store keys rather than extending
`VisualCandidateSet` with another automated round. Review creation stops
automation; only a persisted human disposition can start manual generation.

## 19. Abandon semantics

`abandon` transitions a pending review to `abandoned`, records disposition and
`selection_mode=operator_abandon`, and selects no asset. The next pipeline run
raises `VisualAbandonedError` before generator/Judge work. Workflow node and
project become `abandoned`, not `failed`. A material request change makes the
old abandonment stale and allows a fresh automated request.

## 20. Pipeline output states

Operators can distinguish:

- `SUCCESS` — exit 0;
- `REVIEW_REQUIRED` — exit 3;
- `ABANDONED` — exit 4;
- `INFRASTRUCTURE_FAILED` — exit 1.

`ProjectStatus`/`NodeStatus` persist review-required and abandoned checkpoints.
The top-level CLI prints `PIPELINE_STATE=<STATE>` with the node. Script revision
retains its prior separate exit 2. WorkflowGraph still wraps node exceptions,
but reads the explicit domain halt attributes before checkpointing.

## 21. Staleness

Review identity is tied to exact VisualRequest fingerprint and reason/context.
A changed request fingerprint marks all non-stale reviews for that Shot stale,
including pending manual, accepted and abandoned dispositions. A changed
output MP4, subtitle, runtime timestamp, ComfyUI availability, registry use
list, audio/music/SFX config or downstream render state does not stale a visual
review. Operator commands reject stale/non-pending entries.

An accepted asset is revalidated on every preparation. Missing bytes, changed
SHA or failed technical probe reopen the same review as
`accepted_asset_invalid`; no alternate asset is silently chosen.

## 22. Locking and concurrency

`VisualReviewStore` uses the repository's sidecar `file_lock` plus
`locked_json_update` atomic replacement for every transition and manual-slot
update. Concurrent disposition attempts serialize; exactly one can leave
pending state and later contenders receive a state-transition error. Reads
also take the lock but do not create artifacts. Candidate/evaluation/manifest
stores retain their existing atomic persistence behavior.

## 23. CLI

```bash
ytb batch review list <project>
ytb batch review show <project> <shot>
ytb batch review accept <project> <shot> --asset-id <ast_id>
ytb batch review regenerate <project> <shot> --instruction "..."
ytb batch review abandon <project> <shot>
```

Project IDs are resolved beneath configured `projects_dir` with traversal
rejected. Invalid action/state/candidate exits 2 deterministically. `list` and
`show` are read-only. All disposition commands are administrative state
transitions; manual generation occurs only on the next pipeline execution.

## 24. Observability

`list` shows Shot, status, reason, candidate count, recovery and disposition.
`show` adds bounded request/character/constraint context, candidate path and
technical status, Judge dimension scores, hard failures/reasons, evaluation
history, selection mode and manual override state. Logs record project/Shot,
review ID/reason, staleness and reuse/manual selection events without API keys,
base64 or image bytes.

## 25. AssetRegistry invariants

AssetRegistry was not redesigned. Automated and manual candidates remain
ordinary immutable concrete media observations with separate `asset_id`,
generation key, content SHA, path, dimensions, seed, class and use history.
Review status, human disposition, Judge scores and winner/loser labels are not
written into provenance. Accepting one asset does not mutate the others.

## 26. Evaluation-history invariants

Original automated evaluations remain under the Shot key. Manual evaluations
use the override-specific store key and the unchanged exact evaluation
identity. A human accept does not edit or fabricate scores. Manual semantic
rejection remains a valid historical evaluation and never turns into an
infrastructure error or fake passing result.

## 27. VisualManifest invariants

VisualManifest still stores only final Shot resolution plus existing request
checkpoint data. A review halt marks the Shot pending, not as a selected fake
asset. Human accept/manual winner writes the selected AssetRecord through the
normal manifest contract. Abandon selects nothing. Review/evaluation payloads
are not copied into the manifest.

## 28. Renderer purity

Prepared render imports neither review CLI nor provider/Judge execution. Once
the manifest resolves all Shots, deleting the final MP4 and disabling Director,
Judge and ComfyUI still permits deterministic rerender. Phase-13 review occurs
only inside visual preparation; Timeline, subtitles, optional music/SFX and
mechanism_explainer behavior are unchanged.

## 29. Tests

Phase 13 added **38 collected cases** over the Phase-12 count (1270 -> 1308):

- `tests/test_visual_review.py`: 12 review-domain/store/identity/concurrency cases;
- `tests/test_operator_disposition.py`: 13 end-to-end visual-preparation cases;
- `tests/test_visual_review_cli.py`: 7 CLI cases;
- `tests/test_pipeline_cli_states.py`: 4 explicit product-state cases;
- `tests/test_project.py`: 2 new parametrized workflow halt cases.

Tests use `tmp_path`, generated 8×8 PNGs and fake generator/Judge/provider
boundaries. No live xKiro, ComfyUI, YouTube or external media is required.
Focused Phase-8–13 visual/render/audio regression passed 263 tests before the
full run.

## 30. Acceptance tests

Direct acceptance coverage proves:

1. successful `fail_closed`/exhaustion produces one idempotent review and no
   manifest selection;
2. human accept selects an intact managed candidate despite prior VLM
   rejection, persists audit mode, then resumes with zero provider calls;
3. manual disposition derives new request/generation identity, generates a
   bounded set, judges it, persists a separate evaluation and resolves;
4. partial manual generation preserves completed slots and retries only the
   failed slot;
5. manual semantic rejection remains pending and unchanged rerun performs zero
   work;
6. abandon persists a non-failure terminal state and blocks providers;
7. foreign/missing/SHA-changed assets cannot be accepted or silently reused;
8. request change stales manual/abandon state and permits fresh automation;
9. concurrent dispositions have one winner;
10. happy and infrastructure-fallback paths create no review artifact.

## 31. Full `make test`

Final run on 2026-08-28:

```text
collected 1308 items / 1 deselected / 1307 selected
1304 passed, 3 skipped, 1 deselected, 0 failed
coverage: 83%
duration: 23.68s
```

Phase 12 collected 1270 items; the 38-case increase is the direct Phase-13
coverage listed above.

## 32. Repository cleanliness

After the full suite, both `git status --short` and
`git status --short assets/` were empty before this handoff was created. No
review, candidate, evaluation, manifest, registry, cache, media or temporary
Judge artifact leaked into real repository assets. Only this handoff remains
to be committed at the time of writing.

## 33. Commits

- `835df60` — `test: add Phase 13 review domain contract` (RED)
- `b8f4a9b` — `feat: add durable operator review contract` (GREEN)
- `de0f2cb` — `test: add operator disposition integration contract` (RED)
- `b7ecd06` — `feat: integrate operator disposition into visual preparation` (GREEN)
- `0854bc8` — `test: add explicit operator workflow halt states` (RED)
- `9e8f711` — `feat: persist review and abandonment workflow states` (GREEN)
- `eff4bdf` — `test: add visual review operator CLI contract` (RED)
- `246cf87` — `feat: add visual review operator CLI` (GREEN)
- `1824225` — `fix: harden operator disposition resume states`
- `fc1c192` — `docs: freeze AI engine and audit production readiness`

The containing documentation commit is reported in the final response; a
commit cannot truthfully contain its own hash without rewriting history.

## 34. AI engine feature-freeze statement

After Phase 13, AI Content Factory engine feature development is frozen for
v1. Bug fixes are allowed. New agents, models, autonomous recovery loops,
candidate policies or AI workflows are not allowed until real production
readiness evidence proves a concrete need.

## 35. Production Readiness Gap Report

[2026-08-28-production-readiness-gap-report.md](./2026-08-28-production-readiness-gap-report.md)
contains the required read-only A–N audit, P0/P1/P2 priorities and exact first
real E2E milestone. None of its findings was implemented during Phase 13.

## 36. Deferred work

Deferred to the Production Readiness workstream: clean-machine/config
reconciliation, comprehensive effective preflight, real Long + derivative
Short provider smoke, live private YouTube publish/verify, environment lock,
restart/outage drills, runbook, basic usage counters, storage policy and release
compatibility matrix.

Explicitly not implemented: autonomous round 2, unlimited/adaptive generation,
Judge-guided prompt rewriting, new agents/models/providers, candidate ranking
redesign, approval web UI, Telegram review workflow, manual upload replacement,
CLIP/vector search, beauty/body/desirability scoring, smart crop/reframing,
Director redesign, research changes, `compose_ai` Timeline migration, MCP,
analytics changes or AssetRegistry garbage collection.

## 37. Definition-of-Done checklist

1. ✅ Fail-closed and Phase-12 exhaustion create durable review.
2. ✅ Infrastructure/technical failure does not create review.
3. ✅ Repeated identical halt is idempotent.
4. ✅ Successful automation is review-free.
5. ✅ Review schema is bounded and provider-neutral.
6. ✅ Accept validates Shot history, record, file, SHA and media.
7. ✅ Human override remains auditable without editing evaluations.
8. ✅ Original VisualRequest remains immutable history.
9. ✅ Manual derived request/generation identity is deterministic and separate.
10. ✅ One review permits one manual regeneration attempt.
11. ✅ Partial manual candidate progress resumes per slot.
12. ✅ Manual set uses existing strict Judge/selector semantics.
13. ✅ Manual semantic rejection does not regenerate again.
14. ✅ There is no autonomous generation round 2.
15. ✅ Abandon is explicit and distinct from infrastructure failure.
16. ✅ Product states distinguish success/review/abandon/infrastructure failure.
17. ✅ Request changes stale prior human decisions.
18. ✅ Invalid accepted bytes reopen review without auto-selection.
19. ✅ Review updates are process-safe and atomic.
20. ✅ Required operator CLI exists and is state-only.
21. ✅ AssetRegistry provenance is unchanged.
22. ✅ Evaluation history remains contextual and immutable.
23. ✅ VisualManifest remains the minimal final resolution.
24. ✅ Prepared renderer remains Director/Judge/ComfyUI-free.
25. ✅ Audio/subtitle/mechanism_explainer paths remain compatible.
26. ✅ Focused and full tests pass with no asset leakage.
27. ✅ Architecture/profile documentation is current.
28. ✅ Production-readiness gap report exists and is read-only.
29. ✅ v1 AI engine feature freeze is explicit.
30. ✅ Phase-13 implementation/tests/docs/handoff have commits.

## 38. Recommended next workstream

Start the **Production Readiness Phase**, not a Phase 14 AI feature phase.
Close only evidence-backed P0 install/config/preflight gaps and execute the
exact supervised real-provider milestone:

> Starting from one real topic/configuration, produce a real Long video and
> derivative Short using real providers, with no code edits during execution,
> and either publish or reach an explicit operator-resolvable state.

Stop and preserve evidence after that milestone before authorizing any engine
feature change.
