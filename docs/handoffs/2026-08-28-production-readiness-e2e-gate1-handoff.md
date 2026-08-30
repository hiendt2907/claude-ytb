# Production Readiness — Gate 1 Handoff

Evidence document: [`docs/production-readiness/2026-08-28-e2e-gate1-evidence.md`](../production-readiness/2026-08-28-e2e-gate1-evidence.md)

Source gap report: [`2026-08-28-production-readiness-gap-report.md`](./2026-08-28-production-readiness-gap-report.md)

Continuation source: [`2026-08-30-production-readiness-gate1-continuation-handoff.md`](./2026-08-30-production-readiness-gate1-continuation-handoff.md)

## 1. Status

Branch `codex/production-readiness-e2e-gate1`. AI-engine feature freeze held
throughout: no new agent, model, candidate policy, recovery architecture or
Judge behaviour was added. Every change is a bug fix with focused regression
coverage.

## 2. Gate objective and what was actually proven

One real topic carried end to end through the real configured providers, with
no mocks and no source edits during a successful attempt.

| Stage | Result |
| --- | --- |
| Long script through `ytb batch start` | **9/10 on all five rubric dimensions** |
| Derivative Short through `--replace-slug` | **9/10 on all five**, `source_excerpt` matching the Long verbatim |
| `ytb batch preflight … --live-providers --publish` | PASS for both |
| Real xKiro TTS | 352.8 s (Long), 42.6 s (Short) |
| Real ScenePlan | 24 shots (Long), 11 (Short) |
| Real ComfyUI | 150+ candidate images, 4–6 per shot |
| Real xKiro Vision Judge | every candidate scored |
| Phase-12 bounded recovery | ran to exhaustion naturally, never interfered with |
| Phase-13 operator review | 25 dispositions, all through `ytb batch review` |
| Restart / resume drill | completed, reuse verified |
| Render + `ffprobe` | both outputs valid |
| Private YouTube publish | **Long published and API-verified** |

## 3. Render validation

| Check | Long | Short |
| --- | --- | --- |
| Size | 33,408,336 B | 8,847,744 B |
| Video | h264 1920×1080 @30 | h264 1080×1920 @30 |
| Audio | aac 44.1 kHz stereo | aac 44.1 kHz stereo |
| Duration | 353.07 s (window 300–420) | 42.73 s (window 30–45) |
| A/V drift | 12.7 ms | 7.7 ms |
| SRT / VTT / thumbnail / timeline | all present | all present |

## 4. Publish result

**`PUBLISHED_PRIVATE`** for both outputs, verified through the YouTube Data API
rather than stdout:

```json
{"exists": true, "title": "Dòng Rủi Ro Bị Xóa Trước Cuộc Họp",
 "privacy_status": "private", "publish_at": null}

{"exists": true, "title": "Còn Hai Tiếng, Một Dòng Rủi Ro",
 "privacy_status": "private", "publish_at": null}
```

- Long — `https://youtu.be/j7wZIAyH0HI`
- Short — `https://youtu.be/p_C-GjVbgxg`

Both had thumbnails set, were backed up to Drive, and were written to the
`ban-so-6` continuity ledger. One non-fatal warning: the Short's funnel CTA
comment could not be posted (`youtube.commentThread`, `forbidden`) — an account
permission matter, not a pipeline failure.

The Short reached publish only after two further fixes (`8db7775`, `74fba8d`)
and a full checkpoint reset; see §6 and §8.

## 5. Restart / resume proof

Stopped mid-`visual_assets` with `ytb batch stop`, resumed with the same
command, no source edits between.

| Artifact | Before | After |
| --- | --- | --- |
| TTS audio mtime | `1788068503` | `1788068503` — not regenerated |
| `scene_plan.json` | `ec304c06…` | `ec304c06…` — byte-identical |
| Generated images | 79 | 80 — 79 reused |
| Completed nodes | 4 done | still done, skipped |
| Position | `scene-000-shot-00` | `scene-001-shot-00` — advanced |

## 6. P0 fixes made

Fourteen defects, every one the same shape: **a contract enforced in one place
and never stated to the component required to satisfy it.**

| Commit | Defect |
| --- | --- |
| `fe0e91e` | Short situation marker whitelist absent from the generation and editorial-rewrite prompts |
| `5efe0ce` | …and from the hook repair |
| `de0490e` | Reflection repair not told the Short length floor |
| `bacc0b6` | Remaining repair sites audited as a matrix and closed |
| `3ecd9d4` | Repairs told the floor but not the cap, so they overshot (70.4 s vs 45.0 s) |
| `1f9a2cc` | Generation instructed "exactly 4 sections" — the profile minimum stated as a rule — a shape the editorial gate rejects |
| `818e19f` | Character budget quoted from one duration gate while a second gate measured with a different rate |
| `628216d` | Two repair sites quoted another profile's budget |
| `ca3a0d1` | Normalization deleted a valid funnel bridge, then QA failed the script for its absence |
| `97dae03` | A Judge hint field (`section_refs`) crashed an entire production run |
| `ca6bafb` | `visual_intent` consumed as both image prompt and pass/fail spec, never documented as either |
| `f2df0cb` | Contract rejections reported as "invalid JSON" for documents that parse cleanly |
| `8db7775` | Admission verdict never persisted, so production re-judged identical bytes and could reverse itself |

`make test`: **1349 passed, 3 skipped, 1 deselected, 0 failed.** The suite stays
offline; no live provider is reachable from it.

## 7. The finding that matters most for output quality

Three of three shots in the first production run exhausted recovery and
escalated to a human, while `character`, `composition` and `continuity` scored
**1.000** on essentially every candidate. Every failure demanded something a
still frame cannot carry:

| Shot | Demanded | Judge |
| --- | --- | --- |
| `scene-000` | readable highlighted text on a laptop screen | `unreadable_required_text` |
| `scene-001` | a tray held in a hand | `missing_required_object` |
| `scene-002` | pointing at the screen, other hand on the table edge | `semantic_contradiction` |

`visual_intent` is sent verbatim to ComfyUI as the generation prompt **and** to
the Vision Judge as the requirement. Nothing said so, so it was written as prose
for a human reader and enforced as a specification.

After `ca6bafb`:

| | Before | After |
| --- | --- | --- |
| Typical `semantic` | 0.200–0.400 | 0.600 |
| Hard-failure classes | 3 | 1 |
| Unsatisfiable sections in the Long | 10/24 | **4/24** |
| Shots needing an operator | 3/3 (100%) | **18/24 (75%)** |

Real improvement, and **not sufficient**. The engine was never broken and the
Judge was never too strict; the specification handed to the Judge was
impossible. No threshold, hard-failure taxonomy or fail-closed behaviour was
touched.

## 8. Unresolved

| ID | Class | Pri | Finding |
| --- | --- | --- | --- |
| G1-12 | ENGINE BUG | P1 | `ca6bafb` did not close every unsatisfiable-intent sub-case. `visual_intent` may still demand a **transition action** ("đặt khăn xuống"), stage **two characters in two places doing two things** in one frame, or specify a **micro-expression** ("nét mặt nghiêng hỏi"). A still frame carries a state, not a change of state. This is why 18/24 shots still needed an operator. Cheapest next win; same single contract paragraph. |
| G1-07 | PROVIDER | P1 | The xKiro gateway returns byte-identical completions for identical prompts despite `temperature=0.7`. An operator cannot resample a rejected candidate by retrying — the prompt must change. Proven by five one-second runs producing five identical 51,623-byte logs. |
| G1-11 | PROVIDER | P1 | Three distinct xKiro failures within minutes: HTTP 200 with an empty body, HTTP 409, and an earlier `ConnectionResetError`. The engine stopped transparently every time, never fell back, never overwrote a good artifact. Gate-2 reliability evidence. |
| G1-10 | OPERATOR | P1 | Editorial admission is a low-probability event per attempt. Five varied briefs were needed to admit one Short; a 24-section Long at 9/10 on every dimension took two. Combined with G1-07 this makes throughput planning hard. |
| G1-04 | OPERATOR | P1 | `ytb batch start` silently falls back to the default content profile when `--profile` is omitted, even when the batch slot declares one. Cost one wasted xKiro run. |
| G1-13 | OPERATOR | P1 | No per-node checkpoint reset exists, so a code fix cannot take effect on an in-flight project: the node that would apply it is already `done` and is skipped. The only supported recovery is `ytb batch reset`, which discards completed TTS, visuals and render. `CLAUDE.md` documents `ytb checkpoint reset <project_id> <node_id>` as intended; it is not implemented. |
| G1-02 | ENGINE BUG | P1 | The Long opening prompt advertises `sai lầm` as a tension marker; the Short gate rejects it. Left alone deliberately — changing the accepted set would loosen a gate. |
| G1-03 | ENGINE BUG | P1 | A discarded editorial rewrite still consumes an attempt from the bounded budget and the next review re-scores an identical payload from cache. No longer Gate-blocking after `fe0e91e`. |

## 8b. Gate verdict

**PASS.**

Publish sub-result: **`PUBLISHED_PRIVATE`** for both the Long and the derivative
Short, each verified through the YouTube Data API.

The successful attempt ran without any source edit: HEAD `74fba8d` throughout,
real providers at every stage, no mock, no hand-written state, and every
operator decision issued through `ytb batch review`.

Honest qualifications on that PASS:

- The successful run was not the first attempt. Fifteen P0 defects were fixed
  along the way, each captured, classified and committed separately before a new
  attempt, per §32.
- The Short required a full checkpoint reset because a code fix cannot reach a
  node already marked `done`, and `ytb checkpoint reset <project> <node>` — named
  in `CLAUDE.md` — is not implemented. Recorded as G1-13.
- 18 of 24 Long shots still required an operator disposition. The factory
  produces the product; it does not yet produce it unattended.

## 9. Repository state

Committed: source and tests for the fourteen fixes, this handoff, and the
evidence document. Not committed, correctly: `assets/editorial_review_cache/`,
`assets/production_readiness/`, generated media, provider caches, `.env`, OAuth
material. No secret appears in any diff.

## 10. Recommended next work

1. **Close G1-12** — one paragraph in the same `visual_intent` contract, adding
   transition verbs, multi-character staging and micro-expressions to what a
   still frame cannot be asked for. Expected to move the operator-review rate
   well below 75%.
2. Then re-measure the review rate over a full 24-shot run before anything else;
   that number decides whether unattended production is realistic.
3. Gate 2 reliability, using G1-07 and G1-11 as the starting evidence.

Do not start Operator UX, packaging or a new AI phase before those.
