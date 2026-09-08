# Production Readiness — Gate 1 E2E Evidence

> Execution evidence, not a design document. Every entry below is copied from an
> actual command, log or state file on this machine. Where something was not
> executed, it says so rather than estimating.

Status at last update: **IN PROGRESS — no Gate verdict yet.**

## 1. Gate objective

Prove the current, feature-frozen factory can carry one real topic through:

```text
real topic -> accepted Long script -> accepted derivative Short script
  -> real xKiro TTS -> real ScenePlan -> real ComfyUI visuals
  -> real xKiro Vision Judge -> bounded recovery / Phase-13 review if needed
  -> subtitles + deterministic audio/Timeline -> render + render validation
  -> private YouTube publish, or an honestly external publish blocker
```

with no source-code editing during the successful attempt and no mocked
providers in the final production proof.

## 2. Git state

| Item | Value |
| --- | --- |
| Branch | `codex/production-readiness-e2e-gate1` |
| Phase-13 base | `97fe94190b41185f494e22e5a3eba6d6fd8489c2` |
| Source/test HEAD at takeover | `97546b8` |
| Continuation handoff | `2e4bb34` |
| Gate-1 P0 fix (this session) | `fe0e91e` |

## 3. Environment

| Item | Observed |
| --- | --- |
| Platform | macOS (Darwin 24.6.0), Apple Silicon |
| System Python | 3.14.6 |
| Venv Python (`.venv/bin/python`) | 3.13.5 |
| Operator CLI | `/Users/hiendang/.local/bin/ytb` -> `/Users/hiendang/claude-ytb/bin/ytb` |
| FFmpeg | 8.1.1 |
| ffprobe | 8.1.1 |

`.venv/bin/ytb` does not exist; tests run through `.venv`, the operator CLI runs
through the symlink above. Recorded as-is, not corrected.

## 4. Effective production profile

`ban-so-6` version `2.1.0`, activated earlier on this branch:

- `providers.llm=xkiro`, `providers.tts=xkiro`, `providers.render=story`;
- two candidates per generated Shot, `selection_policy=vlm_ranked`;
- real xKiro Judge model `qwen/qwen3.8-max:free`;
- `semantic_rejection_recovery=regenerate_once`, `hard_fail_on_judge_error=true`;
- editorial review gate: every dimension and the overall score must reach
  **9/10**. Not lowered at any point in this session.
- Short format window: 4–12 sections, 30–45 s viewer duration.

## 5. Accepted Long (pre-existing, re-verified)

| Field | Value |
| --- | --- |
| Slug | `minh-neu-rui-ro-trong-cuoc-hop` |
| Title | Chậm Hơn Trong Cuộc Họp: Im Lặng Hay Nói Thật? |
| Script | `scripts/minh-neu-rui-ro-trong-cuoc-hop.json` |
| Sections | 24 |
| Joined voiceover | 5,143 characters |
| SHA-256 | `0bb72d3f…c38f732d` |
| `auto_state` | `stage=ideation`, `status=ok`, `quality_status=pass`, `qa_status=pass` |

Derivative source is locked to section index `3` with the exact excerpt recorded
in the continuation handoff. Preserved unchanged in every attempt below.

## 6. Derivative Short — attempt log

Target slug `48-phut-mot-dong-rui-ro`, batch key
`shorts_funnel_batch_gate1_20260828`, entrypoint
`ytb batch start --replace-slug` with real xKiro throughout.

At takeover the orphaned physical candidate documented in the continuation
handoff was already gone: `scripts/48-phut-mot-dong-rui-ro.json` did not exist,
and `auto_state` still carried the stale revision-1 provenance
(`9d07f5d2…5d2440b3`). Nothing was copied, edited or promoted to change that.

| Attempt | Log | Outcome |
| --- | --- | --- |
| E2E-S-001 | `ideation_20260830_081829.log` | **Operator error, aborted by me.** Launched without `--profile`, so the prompt demanded the default profile `one-cup-cafe-6h` `1.1.0` instead of `ban-so-6` `2.1.0`. Killed before any artifact was written; `git status` confirmed no partial state. Classified OPERATOR, not an engine defect. |
| E2E-S-002 | `ideation_20260830_081943.log` | Correct profile. Rejected at first-pass contract validation: `Short strategy-v1 … situation needs a concrete tension marker`. Never reached QA or editorial review. |
| E2E-S-003 | `ideation_20260830_082534.log` | QA passed; editorial review **6/10** (human_truth 6, spoken_naturalness 6, causal_coherence 4, role_fidelity 8, useful_restraint 7). One editorial rewrite was produced but **discarded**: `Editorial rewrite phá Short strategy-v1 … tension marker`. Failed closed, archived. |
| E2E-S-004 | `ideation_20260830_083708.log` | Editorial review 2 reached **7/10** — the best score of the run. The follow-up rewrite was again **discarded** for the same marker reason; the run ended at **6/10** with the causal defect "mười phút" silently becoming "mười giờ". Failed closed, archived. |
| E2E-S-005 | `ideation_20260830_084815.log` | QA hook gate fired; the bounded hook repair rewrote the opening naturally, which **dropped the marker**, so final validation failed with the same `tension marker` error. Never reached editorial review. Failed closed, archived. |
| E2E-S-006 | `ideation_20260830_085402.log` | **Key evidence.** Three editorial reviews, all reporting the identical `reviewed_payload_sha256` `490f7976…d5f4d43c` and the identical **3/10**. Both rewrites were discarded (`Editorial rewrite phá Short strategy-v1`), so the entire bounded editorial budget was spent re-reviewing byte-identical content. Failed closed, archived. |
| E2E-S-007 | `ideation_20260830_090244.log` | Run on pre-fix code. Section 1 happened to retain a whitelisted marker, so rewrites **did** apply: distinct payload SHAs `abd7002e…`, `43717088…`, `f7dcd395…` and scores **6 → 7 → 5**. No `EDITORIAL_REWRITE_FAILED`. Confirms the mechanism from the opposite direction. Rejected on content. |
| E2E-S-008 | `ideation_20260830_091525.log` | First run on `fe0e91e`. Prompt verified to name the five markers. Died at the `narrator_reflection` QA gate before editorial review: my brief asked for Minh's inner thought, which violates the hard rule that the closing must be the narrator addressing the viewer with 'bạn'. OPERATOR. |
| E2E-S-009 | `ideation_20260830_092129.log` | Hook repair returned a well-anchored opening with no whitelisted marker; contract validation killed the run. **Exposed the third prompt site I had missed** — fixed in `5efe0ce`. |
| E2E-S-010 | `ideation_20260830_092704.log` | First run on `5efe0ce`. The hook repair fired at attempt 3 and the run **survived it** — direct proof the fix works, where E2E-S-005/009 died at that step. Rejected at attempt 6: the narrator-reflection repair cut the final section 321 → 252 chars, leaving 487 total = 28.4s against a 30.0s floor. **Exposed the length-floor P0** — fixed in `de0490e`. |
| E2E-S-011 | `ideation_20260830_094314.log` | **Terminated by me**, not a natural failure: I stopped it to run the static contract-matrix audit before spending further provider calls. No verdict; recorded so the attempt sequence stays honest. |
| E2E-S-012 | `ideation_20260830_095314.log` | First run on the closed matrix (`bacc0b6`), with a brief mirroring the seven-section structure that actually passed on 08-29. Outcome pending. |

Failed candidates are preserved under `assets/script_revisions/failed_ideation/`.
None was promoted, copied into place or hand-edited.

### 6.1 Operator-attributable contribution to the failures

Between E2E-S-003 and E2E-S-006 I progressively added mechanical, section-by-section
rules to the free-text `--idea` string in order to satisfy the deterministic
validator. This measurably degraded the semantic result: the most prescriptive
prompt (E2E-S-006) produced the worst editorial score of the run
(`spoken_naturalness 3`, `role_fidelity 2`, overall 3/10), and a literal example
sentence I supplied caused the model to write section 1 as third-person scene
description assigned to a character speaker — a hard fail in the profile rubric.
Classified OPERATOR / QUALITY. It is recorded here because it distorts any naive
reading of the score trend, and because it is a real usability finding about
steering the factory through `--idea`.

## 7. P0 engine defect found and fixed

**Classification: ENGINE BUG, P0 — blocked the Gate-1 milestone.**

### Evidence

`validate_short_strategy_v1` gates a Short's `situation` section on a **closed
lexical whitelist** of five Vietnamese tokens
(`nhưng`, `thật ra`, `đừng`, `không phải`, `vì sao`), previously inline at
`src/ytb_pipeline/orchestrator/ideation_script_fix.py:391`.

The two prompts whose output is judged by that gate never named those tokens:

- the Short generation instruction (`ideation_prompts.py`, `short_instruction`)
  asked only for "a concrete tension marker";
- the editorial-rewrite cold-open guard (`editorial_rewrite_prompt`) asked only
  for "an explicit tension marker".

A third, unrelated list at `ideation_prompts.py:196/200` advertises six markers
for the **Long** opening, including `sai lầm`, which the Short gate rejects.

Consequence: whenever the editorial reviewer cited section 1 — the most common
citation in this run — the returned rewrite was editorially improved but lexically
non-compliant, and `apply_editorial_rewrite` discarded the **entire delta**
(`Editorial rewrite phá Short strategy-v1`). The bounded editorial budget was then
consumed re-reviewing byte-identical payloads. E2E-S-006 proves this exactly:
three reviews, one payload SHA, one score.

The engine's only self-repair path for a sub-threshold Short therefore never
applied in E2E-S-003, 004, 005 or 006. E2E-S-007 is the control: when the marker
survived by chance, rewrites applied and the score climbed 6 → 7.

### Fix — commit `fe0e91e`

- Moved the whitelist to the shared contract as
  `content_contract.SHORT_SITUATION_TENSION_MARKERS`.
- `validate_short_strategy_v1` now builds its regex from that constant.
- The Short generation instruction and the editorial-rewrite cold-open guard now
  state the tokens verbatim, warning that a rewrite missing one is discarded whole.

Deliberately **not** done: no threshold lowered, no retry or budget added, no new
agent/model/Judge behaviour, no candidate-policy change. The 9/10 bar and all
fail-closed behaviour are unchanged. The fix only lets a rewrite satisfy the
contract it was already being validated against.

### Regression coverage

Added to `tests/test_content_strategy.py`:

- `test_short_situation_gate_accepts_only_the_markers_it_documents` — pins the
  closed-whitelist semantics, including that an editorially tense opening without
  a listed token is still rejected.
- `test_editorial_rewrite_guard_names_the_markers_the_short_gate_will_check`
- `test_short_generation_instruction_names_the_markers_the_gate_will_check`

All three fail on the pre-fix tree and pass after `fe0e91e`.

### Full suite after the fix

```text
1334 passed, 3 skipped, 1 deselected in 25.16s
```

Zero failures. Suite remains fully offline; no live provider is reachable from
`make test`.

## 8. Not yet executed

The following Gate-1 requirements have **not** been performed and are not claimed:

- full effective preflight (`ytb batch preflight … --live-providers --publish`);
- real xKiro TTS for this Long/Short pair;
- real ScenePlan, ComfyUI candidate generation, xKiro Vision Judge evaluation;
- Phase-12 bounded recovery observation;
- Phase-13 operator review CLI (not triggered yet);
- controlled restart/resume drill;
- `ffprobe` validation of final Long and Short media;
- artifact inventory, storage measurement, provider usage counts;
- private YouTube publish and `ytb batch verify`.

All of these are blocked behind admitting the derivative Short through the normal
entrypoint.

## 9. Unresolved findings

| ID | Class | Priority | Finding |
| --- | --- | --- | --- |
| G1-01 | ENGINE BUG | P0 | Short situation marker whitelist not stated in the prompts judged by it. **Resolved** in `fe0e91e`. |
| G1-02 | ENGINE BUG | P1 | Contract drift: `ideation_prompts.py:196/200` advertises `sai lầm` as a tension marker for the Long opening; the Short gate rejects it. Not touched — changing the Short gate's accepted set would loosen a quality gate, which Gate 1 forbids. Recorded for a later contract-unification pass. |
| G1-03 | ENGINE BUG | P1 | A discarded editorial rewrite still consumes an attempt from the bounded budget, and the next review re-scores an identical payload (cache hit). Wasted budget is silent. A rejected delta arguably should not spend a rewrite. Not fixed: it is no longer Gate-blocking after G1-01. |
| G1-04 | OPERATOR | P1 | `ytb batch start` silently falls back to the default content profile when `--profile` is omitted, producing a prompt that demands the wrong `profile_id`/`profile_version`. Cost one wasted xKiro run (E2E-S-001). A batch whose `auto_state` slot already declares a profile should not require the operator to repeat it. |
| G1-05 | QUALITY | P2 | Steering the factory through a long prescriptive `--idea` degrades semantic scores (§6.1). Worth a runbook note on writing story-level rather than rule-level ideas. |
| G1-06 | ENGINE BUG | P1 | An admitted script carries no `_qa`/`_editorial_review` receipt — both are `null` on the Long and the Short even though the review passed and `auto_state` records `quality_status=pass`. Admission cannot be audited from the artifact alone; it has to be reconstructed from the run log plus a canonical digest. Not fixed: not Gate-blocking, and writing a receipt would change the artifact the digest covers. |
| G1-07 | PROVIDER | P1 | The xKiro gateway returns a byte-identical completion for an identical prompt despite `temperature=0.7`, so an operator cannot resample a rejected candidate by retrying — the prompt must change. Proven by five one-second runs producing five identical 51,623-byte logs. |
| G1-08 | ENGINE BUG | P1 | **Resolved `ca6bafb`.** `visual_intent` is consumed as both the generation prompt and the Judge's pass/fail specification, but nothing said so, so it was written as prose and demanded legible in-frame text, held props and exact hand placement. 3/3 shots escalated to a human. After the fix: 10/24 → 4/24 unsatisfiable sections. |
| G1-09 | ENGINE BUG | P1 | **Resolved `f2df0cb`.** A contract rejection was reported as "LLM không trả JSON hợp lệ" for a document `json.loads` parses cleanly; the real cause (`Source provenance mâu thuẫn ở source_excerpt`) was only visible by grepping the run log. |
| G1-10 | OPERATOR | P1 | Every shot in the pre-fix Long required an operator disposition (3/3 observed). Unattended production was impossible; `ca6bafb` addresses the cause but the reduced rate has not yet been measured over a full run. |
| G1-12 | ENGINE BUG | P1 | `ca6bafb` closed three of the unsatisfiable-intent sub-cases but not all: `visual_intent` may still demand a transition action ("đặt khăn xuống"), stage two characters in separate places doing separate things, or specify a micro-expression ("nét mặt nghiêng hỏi"). A still frame carries a state, not a change of state. This is why 18/24 shots still needed an operator. Not fixed: found during a production run, and §7 forbids editing source mid-run. |
| G1-11 | PROVIDER | P1 | Three distinct xKiro failures within minutes (HTTP 200 with an empty body, HTTP 409, and an earlier `ConnectionResetError`). The engine stopped transparently each time and never fell back or overwrote a good artifact. Gate-2 reliability evidence. |

## 10. Editorial ceiling investigation

Prompted by 11 consecutive Short rejections, I tested whether the profile's
9/10-on-every-dimension bar is reachable at all, before spending more provider
calls. Measured over the whole review cache:

| Measure | Value |
| --- | --- |
| Editorial reviews ever scored | 77 |
| overall >= 9 | 5 |
| overall >= 9 **and** every dimension >= 9 (the real gate) | **5** |
| Highest score reached today (23 reviews) | 7 |

Every dimension has reached 9 or 10 at least once; `causal_coherence` is the
hardest (12/77 at >=9), `role_fidelity` the easiest (22/77). **The bar is
reachable, at roughly a 6.5% per-review rate.**

The two most recent full passes are dated `2026-08-29 00:45:25` and
`2026-08-29 07:57:01`. Those timestamps match, to the second, the `recorded_at`
of the Long and of this exact Short slug in `assets/auto_state.json`. A Short
for `48-phut-mot-dong-rui-ro` therefore **did** clear the bar one day before
this session.

This falsifies the hypothesis I was forming — that a 30-45s Short cannot carry
all its mandatory beats. It can; one did.

### What actually changed

The admitted revision is preserved at
`assets/script_revisions/48-phut-mot-dong-rui-ro/20260829_080517_887052.json`,
whose SHA-256 matches the `auto_state` provenance exactly. It was read for
diagnosis only — not copied, promoted or edited (§33). Its shape:

| # | purpose | speaker | chars |
| --- | --- | --- | --- |
| 1 | situation | **narrator** | 53 |
| 2 | core_answer | narrator | 73 |
| 3 | application | an | 54 |
| 4 | application | minh | 76 |
| 5 | evidence | minh | 87 |
| 6 | evidence | narrator | 112 |
| 7 | payoff | narrator | 87 |

Seven short sections, 542 characters, and the opening assigned to the
**narrator**.

Every attempt in this session forced four or five sections with `an` as the
section-1 speaker. That is an operator error of mine with a direct causal
chain: section 1 is the one slot carrying the hook anchor/stake gate, the
<=120-character cap and the marker whitelist at once, so putting a character
there forces her line into a clipped diagnostic — which is precisely the
recurring editorial finding *"An never speaks or asks a real question"*. Four
fat sections then leave no room to also show An's turn, Minh's reply, the
meeting response and the payoff, which is the other recurring finding, *"no
room to show X"*. The passing structure avoids both by opening on the narrator
and giving An her own unconstrained turn at section 3.

Classified OPERATOR, P1. Recorded in full because it invalidates any naive
reading of the score trend in section 6.

## 11. Repair/contract matrix

Three P0s in this session shared one shape: a bounded repair prompt judged by a
contract nobody told it about. After finding the third one at a time, I audited
every repair site by rendering it against a real strategy-v1 Short and the
`ban-so-6` profile, rather than continuing to discover them one supervised run
at a time.

| Repair site | Sections it can change | Marker whitelist | Total length floor |
| --- | --- | --- | --- |
| `hook_repair` | section 1 only | `5efe0ce` | `bacc0b6` |
| `narrator_reflection_repair` | final section only | n/a | `de0490e` |
| `editorial_rewrite` | any cited section | `fe0e91e` | `bacc0b6` |
| `repair_prompt` | the whole script | `bacc0b6` | already present |
| `short_expansion` | `evidence`/`application` only | n/a — cannot reach section 1 | already present |

`editorial_rewrite` was the most dangerous remaining gap: it rewrites several
sections at once, so it is the likeliest to pull the total under the duration
floor — the exact failure that killed E2E-S-010 via the reflection repair.

Two matrix-level regression tests now pin the whole table, so a new repair site
cannot be added without its governing contracts.

## 12. Short admitted — E2E-S-030

`ideation_20260830_122842.log`, through `ytb batch start --replace-slug` with
real xKiro.

```json
"passed": true, "overall_score": 9,
"human_truth": 9, "spoken_naturalness": 9, "causal_coherence": 9,
"role_fidelity": 9, "useful_restraint": 9
```

Verified against every condition the continuation handoff set:

| Condition | Result |
| --- | --- |
| File exists | 9,839 bytes, 11 sections, 666 characters |
| Editorial review accepted | `passed: true`, 9/10 on all five dimensions |
| The file IS the reviewed content | canonical digest `61f76648…` equals the run's `reviewed_payload_sha256` |
| Profile / funnel / source contract | `ban-so-6` `2.1.0`, `source_section_index=3`, CTA and playlist correct |
| SHA matches new provenance | `9dd3f37e…`, revision 2, recorded `2026-08-30T12:36:46+07:00` |
| Not an archived candidate copied into place | generated by the normal entrypoint |

`_qa` and `_editorial_review` are **null in the file**, exactly as they are for
the Long. Recorded as G1-06 below; the digest match is stronger evidence than a
self-written receipt, and nothing was hand-edited to add one.

### How it was reached — the provider caches identical prompts

Five consecutive runs of one unchanged brief (E2E-S-020…025) produced **five
byte-identical logs** (51,623 bytes, 1,066 lines each) in one second apiece.
There is no cache in this repository's code and `temperature` is 0.7, so the
caching is upstream at the xKiro gateway.

An operator therefore **cannot resample a rejected candidate by retrying**; the
prompt must change. Five genuinely different story variants then produced five
genuinely different outcomes:

| Attempt | Editorial scores |
| --- | --- |
| E2E-S-026 | 5 → 7 |
| E2E-S-027 | rejected before review |
| E2E-S-028 | 5 → 6 → 5 |
| E2E-S-029 | 7 → **8** |
| E2E-S-030 | 6 → **9 — admitted** |

This also corrects an earlier conclusion of mine recorded in section 6.1: what
looked like run-to-run variance was in fact the effect of my own edits between
runs. Classified PROVIDER, P1 (G1-07).

## 13. Real production run

`ytb batch preflight … --live-providers --publish` passed for both scripts.

`ytb batch run --batch-key … --through render --loop` then exercised, with no
mocks:

- **real xKiro TTS** — `assets/audio/minh-neu-rui-ro-trong-cuoc-hop_xkiro.mp3`,
  318.0 s, 7,633,023 bytes;
- **real ScenePlan** — 24 scenes / 24 shots;
- **real ComfyUI** — 86 generated PNGs, 4–6 candidates per shot;
- **real xKiro Vision Judge** — every candidate scored on semantic, character,
  composition and continuity;
- **Phase-12 bounded recovery**, allowed to run without interference.

### Phase-12 recovery worked

`scene-000-shot-00`, recovery round 0 → round 1:

| Candidate | semantic | character | composition | continuity |
| --- | --- | --- | --- | --- |
| round-0 #0 | 0.200 | 0.300 | 0.800 | 0.500 |
| round-0 #1 | 0.300 | 0.500 | 0.800 | 0.500 |
| round-1 #0 | 0.400 | **1.000** | 0.900 | 0.800 |
| round-1 #1 | 0.400 | **1.000** | 0.900 | 0.800 |

Recovery fixed the character defect outright. It could not fix the remaining
hard failure, `unreadable_required_text`.

### Phase-13 operator review — both dispositions exercised

| Shot | Disposition | Evidence |
| --- | --- | --- |
| `scene-000-shot-00` | `accept_existing` | `ast_bf926c9e…`, chosen after viewing both round-1 images |
| `scene-001-shot-00` | `manual_regenerate` then `accept_existing` | override `mvo_7f9773d9…` |

No JSON was edited by hand at any point; every decision went through
`ytb batch review`.

**A more specific instruction scored worse.** My `manual_regenerate` asked for
"a small wooden tray held in both hands, with a coffee cup on it". The two
resulting candidates scored `semantic=0.000` against the originals' `0.200`,
because the added cup became one more required object the generator did not
render. Recorded as an operator lesson: on this Judge, a more detailed override
adds requirements, and requirements are what fail.

## 14. Restart / resume drill

Executed with the supported CLI, no source edits between stop and resume.

Before `ytb batch stop`:

```text
input: done   voiceover: done   audio_quality: done   scene_plan: done
visual_assets: running        79 PNGs
```

`ytb batch stop` reported a graceful stop of 2 processes in the batch tree,
child processes included, with the ledger recording `stopped`. `ytb batch ps`
then showed nothing running.

After resuming with the same command:

| Artifact | Before | After | Result |
| --- | --- | --- | --- |
| TTS audio mtime | `1788068503` | `1788068503` | **not regenerated** |
| `scene_plan.json` | `ec304c06…` | `ec304c06…` | **byte-identical** |
| Generated PNGs | 79 | 80 | 79 reused, 1 new |
| `input`/`voiceover`/`audio_quality`/`scene_plan` | done | done | skipped |
| Pipeline position | `scene-000-shot-00` | `scene-001-shot-00` | advanced correctly |

Completed expensive work was reused; only the incomplete node resumed.

## 15. Root cause of the visual quality ceiling

Three of three shots exhausted recovery and escalated to an operator. Every
failure had one shape, while `character`, `composition` and `continuity` scored
**1.000** on essentially every candidate:

| Shot | `visual_intent` demanded | Judge hard failure |
| --- | --- | --- |
| `scene-000` | a laptop screen showing a highlighted line | `unreadable_required_text` |
| `scene-001` | An holding a tray | `missing_required_object` |
| `scene-002` | pointing at the screen, other hand on the table edge | `semantic_contradiction`, `missing_required_object` |

`visual_intent` is sent **verbatim twice**: to ComfyUI as the generation prompt,
and to the Vision Judge as the requirement, which scores the frame clause by
clause. Nothing in the prompt stack said so, so the field was written as prose
for a human reader and consumed as a complete pass/fail specification. Legible
in-frame text, a small held prop and an exact hand placement are precisely what
a diffusion model cannot guarantee.

The engine is not broken and the Judge is not too strict — the specification
handed to the Judge was unsatisfiable.

### Fix verified on real output — `ca6bafb`

The instruction now states how the field is consumed and forbids those three
demands. Regenerating the Long produced a measurable change:

| | `visual_intent` |
| --- | --- |
| Before | "màn hình laptop mở trang tài liệu có dòng bôi vàng" · "tay cầm khay" · "chỉ vào dòng bôi vàng, tay còn lại đặt trên mép bàn" |
| After | "Minh ngồi cúi trước laptop, mặt sáng nhạt vì màn hình, cốc cà phê gần cạn" · "Minh ngồi yên không chạm vào cốc" · "môi hơi mím lại, không nhìn về phía An" |

Sections carrying a demand the generator cannot satisfy: **10/24 → 4/24**.

The Judge's thresholds, hard-failure taxonomy and fail-closed behaviour were not
touched.

## 16. Long regenerated

New Long admitted at **9/10 on all five dimensions** on the second attempt
(`ideation_20260830_164819.log`): 24 sections, 5,984 characters, SHA
`cb90b42a…` matching `auto_state` revision 2.

The first attempt failed honestly and closed: `role_fidelity` hard fail (Minh's
voiceover contained third-person scene description) plus 205.7 s against a
297.0 s floor. The engine did not overwrite the admitted artifact with it, and
archived the previous Long to `assets/script_revisions/` with its SHA intact.

Regenerating the Long invalidated the admitted Short, whose `source_excerpt`
quotes the previous Long's section 3. The Short must therefore be regenerated
from the new Long before the pair can render — that work was still in progress
at the time of writing.

## 17. Provider incidents

Three distinct xKiro failures within minutes, on the same endpoint that had just
served the Long successfully:

| Incident | Symptom |
| --- | --- |
| 1 | HTTP 200 with a whitespace-only body |
| 2 | HTTP 409 |
| 3 | (earlier session) `ConnectionResetError [Errno 54]` |

Each time the engine stopped transparently, did not fall back to another
provider, and did not overwrite a good artifact — the behaviour the constitution
requires. Classified PROVIDER; useful reliability evidence for Gate 2.

## 18. Clean pair admitted and rendered

After `ca6bafb`, both scripts were regenerated through the normal entrypoint and
both cleared the 9/10 bar on every dimension:

| | Score | SHA | `auto_state` |
| --- | --- | --- | --- |
| Long `minh-neu-rui-ro-trong-cuoc-hop` | 9/10 on all five | `cb90b42a…` | revision 2 |
| Short `48-phut-mot-dong-rui-ro` | 9/10 on all five | `ec617b55…` | revision 3 |

The Short derives from the NEW Long: `source_section_index=8` and its
`source_excerpt` matches that section verbatim, so the funnel contract holds.
`ytb batch preflight … --live-providers --publish` passed for both.

### Long production run — complete

```text
input ✓ voiceover ✓ audio_quality ✓ scene_plan ✓
visual_assets ✓ render ✓ render_quality ✓ publish ✓
PIPELINE_STATE=SUCCESS stage=publish uploaded=False
```

No source code was edited during this run (HEAD `f2df0cb` throughout).

### ffprobe validation — Long

| Check | Observed |
| --- | --- |
| File present, non-zero | 33,408,336 bytes |
| Video stream | h264, **1920×1080**, 30/1 fps |
| Audio stream | aac, 44,100 Hz, 2 channels |
| Duration | **353.07 s** (profile window 300–420 s) |
| A/V drift | video 353.066667 s vs audio 353.053991 s = **12.7 ms** |
| Orientation | landscape, matches profile |

Artifact inventory:

| Artifact | Bytes |
| --- | --- |
| `minh-neu-rui-ro-trong-cuoc-hop.mp4` | 33,408,336 |
| `minh-neu-rui-ro-trong-cuoc-hop_thumb.jpg` | 349,230 (1920×1080) |
| `minh-neu-rui-ro-trong-cuoc-hop.srt` | 8,729 |
| `minh-neu-rui-ro-trong-cuoc-hop.vtt` | 8,697 |
| `minh-neu-rui-ro-trong-cuoc-hop_timeline.json` | 14,568 |

### Operator review load — the measurement that matters

| | Shots needing an operator disposition |
| --- | --- |
| Before `ca6bafb` | 3 of 3 observed (100%) |
| After `ca6bafb` | **18 of 24 (75%)** — 6 shots cleared automatically |

The fix is a real improvement and it is not sufficient. Judge scores moved from
`semantic` 0.200–0.400 to 0.600, and two whole hard-failure classes
(`unreadable_required_text`, `missing_required_object`) disappeared. What
remains is `semantic_contradiction`, and inspecting the surviving failures
identifies the next sub-case the contract does not yet cover:

- `scene-000` — "An đứng phía quầy lau tách" while Minh sits at the table: two
  characters staged in two places performing two different actions in one frame.
- `scene-003` — "An **đặt khăn xuống** cạnh quầy … nét mặt **nghiêng hỏi**": a
  *transition* action, which exists only across time, plus a highly specific
  facial expression.

A still frame can carry a **state**, not a **change of state**. The instruction
added in `ca6bafb` forbids readable text, held props and exact hand placement;
it does not yet forbid transition verbs, multi-character staging, or
micro-expressions. Recorded as G1-12, unresolved.
