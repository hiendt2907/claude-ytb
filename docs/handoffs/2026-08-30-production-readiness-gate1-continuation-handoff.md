# Production Readiness Gate 1 — Continuation Handoff

Snapshot time: **2026-08-30 08:10 +07:00**.

Previous required context:

- [Phase 13 operator disposition](./2026-08-28-operator-disposition-phase13-handoff.md)
- [Production-readiness gap report](./2026-08-28-production-readiness-gap-report.md)
- [Phase 11 production vision provider](./2026-08-28-production-vision-provider-phase11-handoff.md)
- [Architecture constitution](../constitution/03-ARCHITECTURE.md)

This is an operational continuation handoff, not the final Gate-1 evidence or
completion handoff. The required final artifacts are still:

- `docs/production-readiness/2026-08-28-e2e-gate1-evidence.md`
- `docs/handoffs/2026-08-28-production-readiness-e2e-gate1-handoff.md`
- an evidence-backed status update to
  `docs/handoffs/2026-08-28-production-readiness-gap-report.md`

## 1. Status

**IN PROGRESS — Gate 1 has no verdict yet.**

The AI engine remains feature-frozen after Phase 13. Do not begin a Phase 14,
Gate 2, Operator UX, release packaging, or v1.0 work from this handoff. Only
finish the current real Long + derivative Short production proof and make a
P0 fix if a captured, reproducible engine defect blocks that proof.

Current milestone state:

| Area | Actual state |
| --- | --- |
| Gate branch | `codex/production-readiness-e2e-gate1` |
| Phase-13 base | `97fe94190b41185f494e22e5a3eba6d6fd8489c2` |
| Latest documentation HEAD before this update | `cfa7fa7` |
| Latest source/test HEAD | `97546b8` |
| Production profile | `ban-so-6` `2.1.0` |
| Real Long ideation | PASS and persisted |
| Derivative Short ideation | Not admitted. An interrupted attempt left an unreviewed physical candidate whose SHA does not match state provenance |
| Full production preflight | Must be rerun after the Short is admitted and provenance matches |
| Real TTS / visuals / Vision Judge / render | Not yet executed for this Long/Short pair |
| Restart/resume drill | Not yet executed |
| Private YouTube publish | Not yet attempted |
| Gate verdict | Not declared |

## 2. Locked Gate objective

Prove the current factory, through normal operator entrypoints, can produce:

```text
real topic
  -> accepted Long script
  -> accepted derived Short script
  -> real xKiro narration
  -> real ScenePlan
  -> real ComfyUI visuals
  -> real xKiro Vision evaluation
  -> bounded recovery / Phase-13 review if needed
  -> subtitles + deterministic audio/timeline
  -> prepared render + render quality
  -> private YouTube publish, or an honestly external publish blocker
```

No mocks may substitute for providers in the final production proof. Do not
manually create or edit `scene_plan.json`, `visual_manifest.json`, Timeline,
candidate/evaluation/review state, AssetRegistry entries, or pipeline stage
state.

## 3. P0 work already completed on this branch

The branch starts at accepted Phase 13 and contains the following focused
Gate-1 work. Do not rewrite this history.

### Effective preflight and production-profile activation

- `17c0341` — `test: add production preflight readiness contract`
- `321547b` — `test: cover profile LLM readiness in preflight`
- `84ac998` — `fix: add effective production preflight`
- `cf1731f` — `test: define Gate 1 story profile activation`
- `069156e` — `config: activate Gate 1 story production profile`
- `209e8ff` — `test: isolate production story profile integration`
- `b18b82a` — `test: pin legacy visual cache contract`

The effective `ban-so-6` profile now uses:

- profile version `2.1.0`;
- `providers.llm=xkiro`, `providers.tts=xkiro`, `providers.render=story`;
- two candidates per generated Shot;
- `selection_policy=vlm_ranked`;
- real xKiro Judge model `qwen/qwen3.8-max:free`;
- `semantic_rejection_recovery=regenerate_once`;
- `hard_fail_on_judge_error=true`;
- the existing Minh/An identity and duo reference images.

### Real-run ideation defects captured and fixed

- `20afd55` — bound narrator-reflection repair.
- `984c1c3` — distinguish dialogue colons from staging.
- `80054d5` — heal the explicit compliance aggregate.
- `ee01898` — preserve the Short cold-open through editorial review.
- `7e0e5ac` — exempt the declared derivative source from semantic dedup.
- `63761b4`, `f40cff3` — reproduce and revalidate reflection repair after
  editorial rewrite.
- `8017c41`, `c62b932` — reproduce and preserve the spoken Short funnel
  bridge.
- `f09d3ce`, `651a041` — reproduce and preserve derivative source identity
  during Short replacement.
- `65ce4d0`, `57d1088` — preserve the funnel bridge through reflection repair.
- `d0c6042`, `0dead5f` — preserve the funnel bridge through Short
  normalization.
- `6953f36`, `d6ce3ca` — keep a spoken Long CTA from colliding with the
  reflection boundary.
- `7b16d4a`, `01a96f0` — fail/fit repaired Short duration without dropping the
  bridge.
- `97546b8` — preserve complete sentences in Short normalization and fail
  closed when an atomic sentence cannot fit. This fixed the production-proven
  fragments `rồi.` and `cùng Minh xác.`.

These are P0 readiness fixes backed by focused tests. They are not authority to
lower the editorial threshold, add retries, or redesign the AI engine.

## 4. Last verified automated test truth

After `97546b8`:

```text
pytest collected: 1335
selected: 1334
passed: 1331
skipped: 3
deselected: 1
failed: 0
```

The focused Short-normalization regression group passed `13 passed`.

If Claude changes source code after taking over, it must add focused coverage,
run that coverage, then run `make test` again before starting a new supervised
production attempt. Tests remain offline; never put a live provider call into
`make test`.

## 5. Real Long accepted state

Long slug:

```text
minh-neu-rui-ro-trong-cuoc-hop
```

Title:

```text
Chậm Hơn Trong Cuộc Họp: Im Lặng Hay Nói Thật?
```

Persisted script:

```text
scripts/minh-neu-rui-ro-trong-cuoc-hop.json
```

Observed contract:

- profile `ban-so-6` `2.1.0`;
- `video_type=long`;
- 24 sections;
- 5,143 joined voiceover characters;
- SHA-256
  `0bb72d3fd70bd4f867bd7715d6db3d8ebdb42255dd09cbdf0474f488c38f732d`;
- `assets/auto_state.json` reports `stage=ideation`, `status=ok`,
  `quality_status=pass`, `qa_status=pass`;
- production log: `assets/batch_logs/ideation_20260829_003258.log`.

The derivative source is the accepted Long section index `3` (zero-based),
with this exact excerpt:

> An không hỏi tiếp ngay. Cô kéo chiếc ghế đối diện, đặt khay xuống rồi nhìn
> ra cửa kính. Bên ngoài, chiếc xe buýt đầu tiên vừa đỗ lại. Minh vẫn để con
> trỏ đứng yên ở cuối dòng bôi vàng. Cà phê nguội, tay cậu đặt lên bàn, ngón
> trỏ gõ nhẹ lên mép giấy một lần rồi dừng. Cậu không nói số liệu cũ hơn bao
> lâu. An quay lại nhìn dòng bôi vàng, rồi hỏi.

Preserve `source_long_slug`, `source_section_index=3`, and the exact excerpt.
Do not replace it with another Long segment just to make admission easier.

## 6. Derivative Short state — read this before doing anything

Target Short slug:

```text
48-phut-mot-dong-rui-ro
```

Batch key:

```text
shorts_funnel_batch_gate1_20260828
```

At the snapshot no `ytb batch start` process is alive. The latest interrupted
attempt left this physical file:

```text
scripts/48-phut-mot-dong-rui-ro.json
```

It is **not an admitted production Short**. Exact evidence:

- file mtime: `2026-08-30 08:09:55 +07:00`;
- physical SHA-256:
  `d91f252d0bf43c4f4b071f224f3f046940cf23d6784fa16df6936ffb6a3a4a65`;
- `_qa=null` and `_editorial_review=null` in the physical JSON;
- the file has the intended profile, Long source identity and four speaker
  turns, but these structural fields do not replace admission;
- `assets/auto_state.json` still points to revision `1`, recorded at
  `2026-08-29T07:57:01+07:00`, with the different SHA-256
  `9d07f5d2b1985f17443bdc415fe189c8822299de57150828d09bf23b5d2440b3`;
- the latest log ends after `QA_RESULT 2` passed and contains no final
  editorial result, persistence acknowledgement, or candidate admission.

This is an orphaned provisional candidate produced before the operator
session was interrupted. Do not render, publish, copy, or manually approve it.
Do not edit the JSON, state, or ledger to make the hashes agree. A subsequent
normal `batch start --replace-slug` attempt must complete editorial admission
and atomically update the project provenance.

### Attempts after the original 07:37 handoff snapshot

| Log | Actual outcome |
| --- | --- |
| `ideation_20260830_073108.log` | xKiro call ended without response, validation, rejection, or artifact. The process was no longer alive when rechecked. Classified as interrupted/provider no-response, not semantic PASS. |
| `ideation_20260830_074030.log` | Structural QA passed, but final editorial score stayed 5. Direct character speech was embedded in narrator voiceover; An's café beat had no causal handoff to the meeting. Failed closed and archived. |
| `ideation_20260830_074759.log` | Role-separated prompt still ended at editorial score 5. An remained paraphrased instead of receiving a live turn, and the meeting consequence was asserted rather than shown. The production normalizer emitted 608 characters without manufacturing fragments. Failed closed and archived. |
| `ideation_20260830_075838.log` | Four-turn An/narrator/Minh/narrator structure reached QA, but the rewrite merged Minh's café reply and meeting interruption, omitted a concrete response after “Khoan”, and finished at editorial score 4. Final duration validation also measured 24.9 seconds, below the 30-second floor. Failed closed and archived. |
| `ideation_20260830_080749.log` | The provider returned a candidate; normalization emitted 658 characters and `QA_RESULT 2` passed. The operator session was then interrupted before editorial/admission. It left the orphaned JSON documented above. This is neither a pass nor an editorial rejection. |

The three completed semantic failures are content-attempt failures, not new
engine correctness defects. They demonstrate that the 9/10 profile bar and
duration floor remain fail-closed. The interrupted 08:07 attempt must not be
used as evidence that the Short passed.

### Earlier completed failures

| Log | Actual outcome |
| --- | --- |
| `ideation_20260830_070553.log` | Structural QA passed, final editorial score 7; `human_truth=6`; no concrete personal cost/stake for Minh. Failed closed. |
| `ideation_20260830_071635.log` | The rewrite reached a believable cost but expanded to approximately 53 seconds. Failed closed on Short duration. |
| `ideation_20260830_072231.log` | Editorial repair remained causally weak and expanded to approximately 52 seconds. Failed closed. |

Earlier logs under `assets/batch_logs/ideation_20260829_*.log` capture bounded
contract, hook, source, reflection, funnel-bridge, sentence-fragment, duration,
and editorial failures. Failed candidates are preserved under
`assets/script_revisions/failed_ideation/`; do not promote one manually.

The quality threshold is intentionally strict: every editorial dimension and
overall score must reach 9/10. Do not lower it merely to make Gate 1 pass. A
content candidate rejected by the current engine is a failed attempt, not an
engine bug by itself.

## 7. START HERE — exact takeover procedure

1. Confirm branch and Git state, then verify no stale ideation process has
   appeared. There was no live process at this snapshot.

   ```bash
   git branch --show-current
   git status --short
   pgrep -fl 'ytb batch start' || true
   tail -n 220 assets/batch_logs/ideation_20260830_080749.log
   ```

2. Do not treat the orphaned physical Short as a pass. Before moving on,
   require a newly completed normal replacement attempt and all of the
   following:

   - `scripts/48-phut-mot-dong-rui-ro.json` exists;
   - profile/version, strategy, Long source identity, CTA, QA and editorial
     status are valid;
   - `_qa` and `_editorial_review` record the accepted result;
   - the new file SHA matches newly updated `auto_state` provenance;
   - the file is not an archived failed candidate copied into place.

3. Retry only through the normal `batch start --replace-slug` entrypoint. Keep the
   story bounded, show the concrete cost and decision causally, preserve An as
   a café owner rather than a workflow coach, keep the final evidence humble,
   and preserve the exact Long source and spoken CTA. Do not edit a generated
   JSON candidate by hand. The best-supported four-turn structure from the
   latest attempts is An's live hook, narrator core answer and concrete bridge,
   Minh's meeting interruption, then narrator-observed colleague response,
   cost, grounded reflection and spoken Long CTA. It still must pass the
   provider/editorial path; this note is not manual approval.

4. Once both scripts physically exist and validate, run the real effective
   preflight:

   ```bash
   YOUTUBE_PRIVACY=private /Users/hiendang/.local/bin/ytb batch preflight \
     minh-neu-rui-ro-trong-cuoc-hop 48-phut-mot-dong-rui-ro \
     --live-providers --publish
   ```

   Capture the output in the Gate evidence document. This checks effective
   profile/provider config, live ComfyUI inventory, xKiro Vision capability,
   local tools/storage, and publish credentials without generating media.

5. Inspect current operator help before running, then render the exact batch:

   ```bash
   /Users/hiendang/.local/bin/ytb batch run --help
   /Users/hiendang/.local/bin/ytb batch stop --help
   /Users/hiendang/.local/bin/ytb batch ps --help

   YOUTUBE_PRIVACY=private /Users/hiendang/.local/bin/ytb batch run \
     --batch-key shorts_funnel_batch_gate1_20260828 \
     --through render \
     --loop
   ```

6. Perform the required controlled restart/resume drill at a safe, meaningful
   checkpoint. Record checkpoint/candidate/evaluation state before stopping,
   use the supported CLI, then rerun the same batch command:

   ```bash
   /Users/hiendang/.local/bin/ytb batch ps
   /Users/hiendang/.local/bin/ytb batch stop

   YOUTUBE_PRIVACY=private /Users/hiendang/.local/bin/ytb batch run \
     --batch-key shorts_funnel_batch_gate1_20260828 \
     --through render \
     --loop
   ```

   Evidence must show completed expensive stages/candidates/evaluations were
   reused and only incomplete work resumed. Do not simulate corruption.

7. If a Shot reaches `REVIEW_REQUIRED`, use only the Phase-13 CLI:

   ```bash
   /Users/hiendang/.local/bin/ytb batch review list <project>
   /Users/hiendang/.local/bin/ytb batch review show <project> <shot-id>
   ```

   Then choose `accept`, `regenerate`, or `abandon` from the actual evidence.
   Never edit review/candidate/manifest JSON directly.

8. Validate every final Long and Short MP4 using real `ffprobe`: file and
   streams present, non-zero size, sensible duration, expected orientation,
   audio present, A/V drift within current tolerance. Inventory actual SRT,
   VTT, thumbnail, ScenePlan, VisualManifest, candidate/evaluation/review,
   Timeline, audio and output artifacts. Measure project/cache/output sizes.

9. If existing YouTube authorization passes preflight, publish **private**:

   ```bash
   YOUTUBE_PRIVACY=private /Users/hiendang/.local/bin/ytb batch run \
     --batch-key shorts_funnel_batch_gate1_20260828 \
     --publish \
     --loop
   ```

   Verify returned IDs using:

   ```bash
   /Users/hiendang/.local/bin/ytb batch verify <youtube-id-or-slug>
   ```

   Never make the Gate smoke public automatically.

10. Finish the required evidence, final Gate handoff, and gap-report status.
    The final verdict must be exactly `PASS`, `BLOCKED`, or `FAIL`; the publish
    sub-result must distinguish private publish, an external publish blocker,
    and a product bug.

## 8. Provider/environment evidence already observed

Prior supervised checks on this branch/environment established:

- the installed operator CLI is `/Users/hiendang/.local/bin/ytb`;
- `.venv/bin/ytb` does not exist, although tests run through `.venv`;
- real xKiro LLM and TTS health checks passed;
- the Phase-11 real Vision smoke passed using image bytes and
  `qwen/qwen3.8-max:free`;
- ComfyUI was reachable and required story assets/models were observed;
- FFmpeg/ffprobe are available;
- `YOUTUBE_PRIVACY=private` is mandatory for the Gate publish.

Do not substitute these notes for the post-Short effective preflight. Rerun and
capture it because configuration/provider availability can change.

One previous xKiro attempt, logged at
`assets/batch_logs/ideation_20260829_002639.log`, ended with
`ConnectionResetError [Errno 54]`. This is classified as `PROVIDER` and belongs
to later Gate-2 reliability evidence unless it blocks all current Gate-1
progress. The operator response was a bounded retry, not a code workaround.

## 9. Repository cleanliness and artifact rules

Before this handoff, Git showed only these known runtime directories as
untracked:

```text
?? assets/editorial_review_cache/ban-so-6/
?? assets/production_readiness/
```

They are real-run/runtime evidence and are not part of this documentation
commit. The many failed candidates and logs are also runtime artifacts. Do not
commit generated video/audio/image caches, `.env`, OAuth material, xKiro keys,
tokens, raw provider payloads containing binary/base64 media, or other secrets.

After every test/production checkpoint inspect:

```bash
git status --short
git status --short assets/
git diff --cached
```

Do not clean or delete real evidence merely to make status visually empty.
Classify it and keep it untracked/ignored as appropriate.

## 10. Gate-1 completion checklist remaining

- [x] Phase-13 feature freeze preserved.
- [x] Gap report read and Gate-blocking P0s selected.
- [x] Effective production preflight implemented and tested.
- [x] Gate profile activates real story candidates, xKiro Judge and bounded
  recovery.
- [x] Real Long generated and admitted through the normal entrypoint.
- [ ] Derivative Short physically generated and admitted through the normal
  entrypoint.
- [ ] Full effective live/publish preflight captured for both scripts.
- [ ] Real xKiro TTS completed for this pair.
- [ ] Real ComfyUI candidates completed.
- [ ] Real xKiro Vision evaluation completed.
- [ ] Phase-12 recovery allowed to run naturally.
- [ ] Phase-13 review CLI used if `REVIEW_REQUIRED` occurs.
- [ ] Controlled stop/resume proof completed.
- [ ] Long and Short render completed and validated with `ffprobe`.
- [ ] Private publish attempted when existing authorization permits.
- [ ] Artifact/storage/usage observations recorded.
- [ ] Every supervised attempt classified and documented.
- [ ] Required evidence document created.
- [ ] Gap report updated with evidence-backed resolutions/status.
- [ ] Final Gate-1 handoff created.
- [ ] Final verdict declared honestly.

After Gate 1, the intended roadmap is Gate 2 reliability/restart/provider
failure, operator experience without requiring source edits, release
hardening/install/version/storage/runbook, then v1.0. **Do not start any of
those from this handoff.**
