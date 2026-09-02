# Engine fixes measured out of Gate 1 attempts — 2026-09-02

Addendum to `2026-08-28-production-readiness-gap-report.md`. That document is a
point-in-time read-only audit and is left unedited; this one records what real
Gate 1 attempts on 2026-09-01..02 measured, and what was changed as a result.

Every item below was found by aggregating real production logs, not by reading
code looking for problems. The distinction matters: each one had already cost a
generation.

## The shape they share

Five of the six are the same failure: **a rule enforced in one place and not
stated in the other.** A gate rejects what the writer was never told; a repair
is scored against a bound nobody gave it; a provider fault is read one layer up
as a model fault. Individually each looks like bad luck. Together they are why
Gate 1 has taken as long as it has — a Long generation costs 8-16 minutes, and
any one of these threw the whole thing away.

## Resolved

### 1. `unrenderable_visual_intent` had no repair path

**Measured.** Three of five real rejections on 2026-09-01..02 were this rule
alone. The generation prompt already forbids all three forms in the same words,
and the gate's own docstring records that this is not enough. `hook`,
`narrator_reflection` and `series_dedup` each have a narrow repair; this rule
had none, so one bad clause in one section out of twenty discarded a generation
that had already cleared the editorial rubric.

**Fix.** A narrow repair that rewrites only the flagged sections' `visual_intent`
and re-checks the rewrite against the same gate. `visual_intent` is never
spoken, so this cannot move narration or the 9/10 bar.

**Evidence it works.** Run 2026-09-02 19:55 — `repair: visual_intent only,
sections [2, 9, 16]`, repaired once, never reappeared across four further
rounds. Commit `72699c5`.

### 2. The guard missed two forms the Judge was already rejecting

**Measured.** Judge scores across four consecutive shots: character ~1.0,
continuity ~1.0, composition 0.5-0.9, semantic 0.0-0.2 — the people and the
place are always right, only the ACTION fails, and every failing clause is a
directed gesture. Three such clauses passed the guard untouched.

**Fix.** Two patterns for pointing and for handing/turning an object toward a
person. Static posture still passes, which the same measurements establish. Not
added: "cúi người tập trung gõ" — its single observation is confounded with a
hand close-up in the same shot, so there is no clean evidence for it.

Commit `8e99d64`.

### 3. Vision transport faults lost the whole node

**Measured.** One read timeout during `visual_assets` killed the node after the
images had been generated. A Long makes roughly 250 Judge calls, so meeting at
least one transient fault is close to certain. The Judge already retried a
malformed response but not a request that produced none.

**Fix.** Up to three attempts with backoff for timeouts, connection errors and
429/5xx. 401/403/413 still fail on the first attempt. Commit `d639bd6`.

### 4. A Long repair was never told its length budget

**Measured**, run 2026-09-02 19:33:

    attempt 1   217.4s   floor 297.0s   -> extend
    repair: final narrator reflection only
    rewrite: editorial score below profile bar (x2)
    attempt 4   278.1s   floor 297.0s   -> lost

The reviewer's own `repair_brief` said "cắt bớt hoặc nén mục 11". The rewrite
obeyed, because `_short_total_length_bounds` returns None for anything that is
not a Short and the guard was therefore empty. The comment above that guard
already described the risk correctly; the helper just did not serve Longs.

**Fix.** `_total_length_bounds` answers for Longs with the window the generation
prompt already quotes. `narrator_reflection_repair_prompt` had the identical
hole and is fixed in the same commit. Commit `76213e5`.

### 5. An was written as a coach, twice

**Measured.** Two consecutive Longs rejected for the same role failure, with
different sentences each time, after an editorial rewrite that had been given a
specific and correct repair brief. The rule was present and the diagnosis was
present; the model reaches for a therapist's binary question when asked for "an
open question".

**Fix.** Profile 2.3.0 gives An's questions the same Ưu tiên/Tránh contrast the
spoken-naturalness rule beside it already has, quoting the rejected sentences
verbatim, plus a one-line test. 2.2.0 snapshotted first. Commit `2c6acd1`.

**Evidence.** Run 2026-09-02 20:16 cleared the editorial gate on the first
attempt and failed later for an unrelated transport fault.

### 6. The corrupt-response retry was invisible

**Measured.** A generation that failed three times left the same single log line
as one that failed once, so the gateway's corruption rate could not be told from
one bad minute. Probing right afterwards: 5/5 clean at 64 tokens, 3/3 clean at
1200, 3/3 corrupt at the 14000-token script generation. Size correlation is a
hypothesis; this logging is what would confirm or kill it.

Commit `e8363f9`. No behaviour change.

## Not resolved

- **Corruption at full generation size.** If the size correlation holds, the
  fix is a smaller generation, which is frozen v1 architecture. Retry is the
  only response available and it is bounded at three attempts.
- **The profile does not declare its stageable setting.** Nothing stops ideation
  writing scenes the profile cannot stage; today only the brief prevents it.
- **`gain_db` validation accepts up to +12 dB.**

## Instruments that lied

Recorded separately because it is the more dangerous category, and four of them
turned up in one session — all the same shape, silence read as success:

| instrument | reported | actually |
|---|---|---|
| `classify.py` | blamed a repaired rule | cause was `editorial_review` |
| `inspect_visuals.py` | `DONE` | project did not exist |
| `check_video.sh` | ran five layers, said nothing | no per-layer verdict |
| `gate1.sh` | `PASS` | ideation had crashed |

All four are fixed. `check_video.sh` now ends by saying that five clean layers
are still not a PASS, because nobody has watched the video yet.

## Status

No video yet. No verdict yet. `assets/production_readiness/gate1/attempts.tsv`
carries every attempt, its class and its owning layer, including two corrections
where an earlier row was wrong.
