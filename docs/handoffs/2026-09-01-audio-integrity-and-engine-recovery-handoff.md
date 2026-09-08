# Audio integrity + engine recovery — handoff for independent review

**Date:** 2026-09-01
**Branch:** `codex/production-readiness-e2e-gate1`
**Range under review:** `51c37ff..b8d105a` (13 commits)
**Status: Gate 1 is NOT reached.** No video has been rendered or published in
this cycle. Read §6 before treating anything here as done.

This document is written to be checked, not believed. Every claim below names
the commit that carries it and the command that reproduces the measurement.

---

## 1. Why this cycle exists at all

Commit `51c37ff` ("docs: Gate 1 evidence and handoff — **PASS**, both outputs
published private") declared Gate 1 passed. That claim was wrong, and the
operator found it by watching the two published videos: the narration was not
intelligible in places, and a character name was read out letter by letter.

The reason the gate missed it is worth stating plainly, because it shapes
everything after: **ffprobe validates the container, not the language.** The
previous cycle checked streams, duration and A/V drift, and reported content on
that basis. A well-formed 353-second 1920×1080 file can contain narration that
says something other than the script.

Nothing in this document should be read as a new PASS claim. See §6.

---

## 2. Defects fixed, with evidence

All nine are engine/contract defects, each fixed at the layer that owns it. No
hardcoding, no symptom patching, no loosened gate, no modified test used to hide
a failure. Two tests were **deleted**, both because they pinned defective
behaviour; both are named below.

| # | Commit | Defect | Layer that owned it |
|---|---|---|---|
| 1 | `57e9d3a` | `voiceover/pronunciation.py` (103 statements, 0% coverage) was imported nowhere; nothing stood between a written word and the voice | TTS text prep |
| 2 | `0f55317` | Audio gate compared *joined* script to *joined* transcript, averaging a local fault away | audio QA gate |
| 3 | `35683b3` | Gate failed correct audio because ASR writes digits where the script writes words | audio QA gate |
| 4 | `f24359d` | `silenceremove` leading trim ate the onset of short phrases | `_to_mp3` |
| 5 | `a615631` | `_split_long_clause` filled greedily to the cap and stranded a 4-char tail; both halves unspeakable | xKiro chunker |
| 6 | `a7c5a61` | STT `initial_prompt` steered the decoder into YouTube boilerplate | STT adapter |
| 7 | `51c149f` + `ba705b3` + `a8765c0` | A machine slug reached the voiceover and was read aloud as noise | QA rule + prompt + normaliser |
| 8 | `b76f386` | `decode("utf-8","replace")` turned corrupt gateway bytes into U+FFFD and carried on | wording engine |
| 9 | `0c1b481` | `silenceremove` trailing trim cut at the first **internal** silence | `_to_mp3` |
| 10 | `b8d105a` | Gate named the remedy for a bad segment and nothing performed it; project stuck forever | pipeline resume |

### 2.1 The measurements behind each

**#2 — averaging (`0f55317`).** Real round-trip on the published Long:

```
"Sáu giờ mười hai phút,"     -> "6h12 phút"                    0.80
"An vừa lau xong dãy tách,"  -> "Ăn bửa lâu xong giải tách."   0.69
whole script                                                    0.9219  PASS
worst segment ('Ô nào?')                                        0.107
```

The café owner's name "An" is spoken as "Ăn", a different word. 5,984 correct
characters diluted it to a pass.

**#4 + #9 — `silenceremove`, both halves.** One chunk, four encodes,
faster-whisper large-v3:

```
no filter            0.672s   "Em gọi"                                    ok
trailing trim only   0.641s   "Em gọi."                                   ok
leading trim only    0.495s   "Hãy đăng ký kênh để ủng hộ kênh..."        broken
both (production)    0.465s   "Cảm ơn các bạn đã theo dõi và hẹn gặp..."  broken
```

I fixed the leading half in `f24359d` **and asserted in that commit message
that the trailing half was safe.** That was wrong. Measured later:

```
"gọi năm lần nhưng không ai nhấc."   2.352s -> 1.251s
   "G.I.N. Merlin, nhưng không ai nhất." -> "G.I.N. Merlin"
```

`stop_periods=1` stops at the first **internal** silence. Across the twelve real
chunks captured while debugging: 11 lost 0–44 ms (genuine padding), 1 lost
1101 ms. ~25 ms of benefit per chunk against an unbounded downside, so `0c1b481`
removes the filter entirely.

Deleted test: `test_to_mp3_trims_provider_boundary_silence` asserted the filter
was present.

**#5 — chunker (`a615631`).** A 52-character sentence against a 48-char cap:

```
"Tách cà phê nguội rồi mà cậu chưa uống một ngụm"        0.21  hallucination
"nào."                                                   0.08  hallucination
"Tách cà phê nguội rồi mà cậu chưa uống một ngụm nào."   0.98  correct
"Tách cà phê nguội rồi mà cậu chưa uống"                 1.00  correct
```

Whole it reads at 0.98; split greedily both halves come back as a channel outro.
Now sized first (`ceil(len/max_chars)`) and aimed at the average: 28 + 23.

**#6 — STT prompt (`a7c5a61`).** 20 rendered segments, same audio files, only
the `initial_prompt` varied:

```
section 1    with 0.18   without 0.99
section 2    with 0.13   without 0.98
section 13   with 0.12   without 0.98
17 others    unchanged to within 0.01
none worse
```

All three failures returned one identical sentence — "Hãy subscribe cho kênh
Ghiền Mì Gõ..." — regardless of content. The audio was correct: sliced into
3-second pieces the same file transcribes as written. **This adapter is what
blocks a publish**, so it was failing good renders.

**#7 — spoken slug.** The Short's closing line contained
`minh-cham-hon-dong-nghiep-tre`. Synthesised and transcribed:

```
"Lần tới Video giải minh cờ hờ AMH Owner the owner Sơ đi tiếp từ chỗ..."
```

The segment still scored **0.92** — 200 correct characters diluted a 29-character
slug. Same averaging defect as #2, one level lower, inside a single segment; there
is no unit below a segment to score, so it is stopped at the script instead.

Three commits because the first was incomplete: `51c149f` added the QA rule while
the funnel prompt still said *"Make the final **spoken** CTA point to that
**exact** long-form topic"* next to the slug. `ba705b3` fixed the prompt. The
model still wrote the slug 3/3 times, so `a8765c0` substitutes it
deterministically with the Long's title and logs the substitution.

**#8 — mojibake (`b76f386`).** A generated Short carried
`caption: "Năm l��n đổ chuông trước giờ họp"` with a **clean** `title` beside it
— transport corruption, not model spelling. Invisible to the deterministic layer
twice over: `_encoding_valid` only tests for missing diacritics, and
`_NARRATION_KEYS` does not include `caption`. Only the LLM rubric caught it,
which is the wrong layer for a mechanical defect (§38).

**#10 — the engine defect (`b8d105a`).** This is the one worth the most scrutiny.

xKiro TTS is **not deterministic**. Same text, five calls:

```
"gọi năm lần nhưng không ai nhấc."   5/5 distinct audio hashes, score 0.94 each
"xe buýt chạy qua,"                  5/5 distinct audio hashes, score 1.00 each
"cất laptop,"                        5/5 distinct audio hashes, score 0.38-0.48
```

An earlier call on the first produced "G.I.N. Mơ Lân" at 0.79, confirmed in the
assembled segment. So a bad segment is transient and re-synthesis has a real
chance of fixing it.

The gate already recorded `metrics.transcript.worst_segment_index` and its issue
already named the remedy, `action="resynthesise_mismatched_segment"`. **Nothing
performed it.** `_reset_stale_nodes` returned `audio_quality` to pending and left
`voiceover` alone — its own comment said "retry QA on resume ... without ever
re-running TTS or render". The gate therefore re-scored the same bad bytes, failed
identically, and the project could not move. The only exit was `ytb batch reset`,
which discards the render and every generated image too.

Resume now deletes exactly the named segments plus the merged file, and returns
`voiceover` to pending; `_synth_all` reuses every segment whose file still exists,
so only the deleted ones are re-synthesised and all other provenance is untouched.
Bounded by `MAX_AUDIO_RESYNTH_ATTEMPTS`; when spent, the audio is left as evidence
and the gate fails closed.

---

## 3. Method change, mid-session

For the first eight defects I worked one at a time: measure one layer, find one
fault, fix, regenerate, repeat. The operator challenged this, correctly.

The proof it was wrong is `silenceremove`: I fixed one half, committed a claim
that the other half was safe, and found hours later that the other half was worse.
Measuring the whole filter once would have found both together.

Replaced with a three-layer sweep that collects every failure before fixing
anything, and attributes each to a layer by the *difference between layers*:

| signal | conclusion |
|---|---|
| raw low | TTS misreads that phrase → content/chunking |
| raw high, norm low | `_to_mp3` damaged it |
| norm high, segment low | assembly/pauses, or the STT instrument |

`scratchpad/sweep.py`.

---

## 4. Sweep results

276 measurements across both scripts:

```
to_mp3_damages         0
assembly_or_stt        0
tts_reads_it_wrong     6
ok                    270
```

The six were then checked against the assembled segment, because a 0.6-second
isolated clip is a poor STT input:

- **3 of 6 were measurement artefacts** — `cất laptop`, `xin lùi một ngày`,
  `không ai nhấc máy` all appear correctly in the assembled segment.
- 1 (`gọi năm lần`) was real in one call and correct in the next five.
- 1 (`kết quả êm`) is an awkward phrase; rewriting it to "một kết quả tốt"
  scores 1.00. Content, not engine.
- 1 (`xe buýt`) scored 1.00 on re-measurement.

**Conclusion: chunk-level scoring on short isolated clips is not a trustworthy
instrument.** Segment level is what production assembles and what a viewer hears.
At segment level both scripts have **0 failures**.

---

## 5. Artifact state

| | Long | Short |
|---|---|---|
| slug | `minh-cham-hon-dong-nghiep-tre` | `nam-lan-do-chuong-truoc-gio-hop` |
| title | Dòng Vàng Cuối Slide | Năm Lần Đổ Chuông Trước Giờ Họp |
| sections | 20 | 11 |
| narration chars | 6,047 | 1,286 (~75 s) |
| editorial receipt | passed, 9/10 | passed, 9/10 |
| preflight | ✓ | ✓ |
| TTS↔STT, segment level | **0 off / 20**, two independent runs | **0 off / 11** |
| slug leak | none | none |
| mojibake | none | none |

The Short's `source_long_slug` points at this Long, and its closing names the
Long by title ("video dài Dòng Vàng Cuối Slide"), not by slug.

Two independent Long screens — synthesis and transcription redone from scratch —
gave identical scores on 19 of 20 sections and differed by 0.01 on one.

`make test`: **1368 passed, 3 skipped, 1 deselected.**

---

## 6. What is NOT verified — please check this section hardest

Gate 1 requires a rendered, inspected, privately published Long **and** Short.
None of that has happened in this cycle.

**Not done:**

1. **No render.** Pipeline has not been run past `voiceover` for either script.
2. **No publish.** Nothing uploaded; the two URLs in `51c37ff` are from the
   previous, rejected cycle.
3. **TTS/STT invariant is verified at 3 of 5 points.** Points 1–3 (raw chunk,
   post-`_to_mp3`, assembled segment) all sit *before* the mixer and renderer.
   Points 4 (post-mix) and 5 (audio extracted from the final MP4) have tooling
   written (`scratchpad/verify_mp4.py`) that **has never been run**, because
   there is no MP4.
4. **No real-artifact inspection** of ScenePlan, visual generation, Vision
   Judge, subtitles, timeline or renderer. They have unit tests, but those run
   against fakes, so nothing yet demonstrates "the image matches the sentence
   being spoken", "visuals are not repetitive", or "subtitles match narration".
5. **No video quality inspection at all** — hook, pacing, dead air, whether
   music buries narration.
6. **A known risk, unmeasured:** `mix_timeline_audio` uses
   `amix=...:normalize=0` with fixed `gain_db` and **no sidechain ducking**.
   Music does not step back under narration. Whether that damages
   intelligibility is not yet measured.
7. **Gap report not updated.** `docs/handoffs/2026-08-28-production-readiness-gap-report.md`
   still carries no Resolution/Evidence/Commit rows for this work.
8. **Evidence doc stale.** `docs/production-readiness/2026-08-28-e2e-gate1-evidence.md`
   still describes the previous cycle and its withdrawn PASS.

---

## 7. Claims I made during this session and then retracted

An independent reviewer should know which of my earlier statements were wrong,
because some of them are in commit messages that remain in history.

| I claimed | Actually |
|---|---|
| Trailing `silenceremove` is safe (in `f24359d`) | It truncates at the first internal silence; `0c1b481` removes it |
| xKiro caches TTS by text, so repeats prove determinism | No cache: 5/5 distinct audio hashes. Waveform differs every call; only spoken content is stable |
| Short chunks cause hallucination | Disproved — `"Chưa."` at 5 chars scores 1.00. Patch reverted |
| Long chunks cause hallucination ("Ghiền Mì Gõ") | My probe bypassed production chunking. Through the real path, clean |
| The prompt fix solved the slug leak | Premature — it recurred; needed the normaliser |
| Slug leak was caused by the prompt not supplying the Long's title | False — `source_long_instruction` had always passed `title=` |

---

## 8. Reproducing the measurements

```bash
make test                                      # 1368 passed

# three-layer sweep (real xKiro TTS + local faster-whisper large-v3)
PYTHONPATH=src .venv/bin/python scratchpad/sweep.py \
    nam-lan-do-chuong-truoc-gio-hop minh-cham-hon-dong-nghiep-tre

# per-section screen through the real production synthesis path
PYTHONPATH=src .venv/bin/python scratchpad/tts_screen.py <slug> 0.82

# TTS determinism
PYTHONPATH=src .venv/bin/python scratchpad/flaky.py 5

# points 4 and 5 — requires a rendered MP4, not yet produced
PYTHONPATH=src .venv/bin/python scratchpad/verify_mp4.py <slug>
```

Helper scripts live in the session scratchpad
(`/private/tmp/claude-501/-Users-hiendang-claude-ytb/.../scratchpad/`), not in
the repo. They are diagnostic instruments, not production code; if they should
be kept, they need a home under `tools/` and tests of their own.

`QUALITY_STT_MODEL_PATH=assets/models/faster-whisper-large-v3` is required —
`small` is not accurate enough to adjudicate this. Same audio, 12 segments:
`small` gave 2 exact matches, `large-v3` gave 6, and the differences were ASR
homophones (`cậu/cột`, `chốt/chút`, `Bàn/Bản`), not TTS faults.

---

## 9. Repository state

Working tree carries only runtime artifacts:

```
 M assets/batch_workers.json
 M profiles/ban-so-6/continuity-ledger-season-02.json
?? assets/.asset_registry.json.lock
?? assets/asset_registry.json
?? assets/editorial_review_cache/ban-so-6/
?? assets/production_readiness/
```

Secrets audit on `main..HEAD`: no `XKIRO_API_KEY` value, OAuth token, client
secret or base64 media in the diff — only variable *names* in documentation and
settings code. `secrets/` and `.env` are untracked.

---

## 10. Suggested order for whoever continues

1. Run `--through render` for the Long; inspect ScenePlan, visuals, subtitles,
   timeline as real artifacts before rendering further.
2. Run `verify_mp4.py` — this is the first time points 4 and 5 of the invariant
   are exercised, and the mixer has no ducking, so measure before assuming.
3. Watch the video. §6 items 4–6 cannot be closed by a script.
4. Repeat for the Short.
5. Only then update the gap report and evidence doc, and state a verdict.

Do not treat §5's "0 off / 20" as a Gate 1 pass. It measures one property —
that the spoken audio matches the script through segment assembly — and says
nothing about visuals, timing, subtitles, mixing, or whether the video is worth
watching.
