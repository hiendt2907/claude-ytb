# 38 — EDITORIAL QUALITY LAYERS

## Purpose

`claude-ytb` judges "is this script actually good" through **two
independent, intentionally separate layers**, plus a third layer that judges
only shape, not quality. As of 2026-08-27 there is no code coupling between
the two quality layers and no written rule for which one should own a new
content requirement. This document is that rule, written before any more
content requirements are added to either layer — see
`docs/handoffs/2026-08-27-content-profile-engine-refactor-plan.md` §1
(Giai đoạn 0) for the audit that produced it.

## The three layers, in the order every script passes through them

### 1. `ideation/script_contract.py` — deterministic SHAPE validation

Verifies schema, required fields, section count bounds, purpose vocabulary,
cast/turn field consistency. Never judges whether the *content* of a field is
good — only whether the JSON has the shape the rest of the pipeline can rely
on. Always runs, for every profile, unconditionally. Cannot be disabled by a
profile; a profile cannot opt out of having a valid shape.

### 2. `agents/qa_agent.py` — deterministic CONTENT heuristics

Vietnamese keyword/structural checks: hook anchor+stake, immediate-action
closing, narrator-lesson closing, absolute-claim hints, health/finance hints,
duplicate sections, etc. Free (no LLM call), instant, and therefore always
runs regardless of LLM budget. Can be wrong in both directions — a keyword
match is a proxy, not an understanding — but it is cheap enough to run on
every attempt of every script, including retries.

### 3. `agents/editorial_review_agent.py` — LLM-judged semantic rubric

An **opt-in** (`editorial_review.enabled`) call to the profile's own LLM
provider, scoring 0-10 on five fixed dimensions (`human_truth`,
`spoken_naturalness`, `causal_coherence`, `role_fidelity`,
`useful_restraint`) against the profile's own declared rubric text. Costs one
LLM call per distinct script (cached by content hash), and can catch
judgments no keyword list can express — e.g. "does this scene's cause and
effect actually hold together," which requires understanding the scene, not
matching a phrase.

## Deciding where a NEW content rule belongs

Ask, in order:

1. **Can this rule be expressed as a keyword/structural check without a
   large false-positive/false-negative rate?** (e.g. "the closing must
   contain a direct-address marker like 'bạn'/'lần tới'" — yes, this is a
   `qa_agent.py` rule.) If yes → **layer 2**.
2. **Does verifying this rule require understanding the scene's meaning,
   not just its surface words?** (e.g. "does the causal turn between two
   characters actually make sense," "does this feel human or does it read
   like a lecture") → **layer 3**, and it likely maps to one of the five
   existing `EDITORIAL_REVIEW_DIMENSIONS` rather than a sixth.
3. **Never implement the same requirement in both layers.** If a
   `qa_agent.py` heuristic and an `editorial_review` rubric dimension can
   both reject the same failure mode, that is a real duplication risk — pick
   one owner. The heuristic layer is the right owner when the failure mode
   is common enough to be worth catching for free on every retry; the rubric
   layer is the right owner when the failure mode is too semantically
   subtle for a keyword list to catch without also rejecting good scripts.
4. **A rubric dimension is not a place to bury a keyword rule "because it's
   easier."** Adding a sixth ad-hoc dimension to `editorial_review` costs an
   LLM call's worth of judgment on every script for every profile that opts
   in — reserve it for genuinely semantic judgments, not something
   `_check_*` in `qa_agent.py` could do for free.

## Known current split (informative, not exhaustive)

| Rule | Layer | Why |
|---|---|---|
| Section/purpose schema shape | `script_contract.py` | Pure shape, zero judgment |
| Hook anchor + stake marker | `qa_agent.py` | Keyword-detectable, cheap, runs every attempt |
| Immediate-action / narrator-lesson closing | `qa_agent.py` | Structural pattern on the final segment |
| "Does the causal turn make sense" | `editorial_review` (`causal_coherence`) | Requires reading the scene, not a keyword |
| "Does the narrator sound human, not templated" | `editorial_review` (`human_truth`, `spoken_naturalness`) | Same |

## Consequence for future profiles

A new `character_story` or `mechanism_explainer` profile does not have to
declare `editorial_review` — it is opt-in and every existing profile keeps
working without it. But if a profile finds itself repeatedly failing on a
quality dimension that no `qa_agent.py` heuristic can express without
excessive false positives, that is the signal to opt into
`editorial_review` for that profile rather than growing `qa_agent.py`'s
keyword lists past the point they can stay accurate.
