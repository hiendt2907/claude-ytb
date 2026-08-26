# Handoff — Qwen Short: duration repair done, story hook remains

Date: 2026-08-26  
Author: Codex  
Status: committed and tested. No queue, render, TTS, or publish.

## Scope and commits

Goal: make `qwen/qwen3.8-max:free` produce Short narration within the 30–45s
contract without hand editing a candidate.

1. `92b3d5f test: reproduce bounded short expansion repair` — RED tests.
2. `589390d fix: make short duration repair profile-driven` — GREEN engine
   change and regressions.

The default model remains `deepseek/deepseek-v4-pro`. Qwen was selected only
for the smoke process with `XKIRO_LLM_MODEL`, not persisted in settings.

## Root cause and engine outcome

Qwen returns schema-valid JSON but does not reliably count Vietnamese characters.
The former repair path also had ambiguous one-based versus zero-based indexes,
targeted only the hard minimum, exposed late core/payoff beats through position
logic, and could silently trim the ending after an oversized delta.

The repair now:

- lets every profile declare `editorial_contract.short_expansion_purposes`;
  legacy v1 profiles retain `evidence` and `application` compatibility;
- validates those purposes against the profile vocabulary, supports case-insensitive
  matching, and fails closed when no beat is explicitly allowed;
- gives the LLM only legal **zero-based** indexes plus min/target/max char budget;
- accepts exactly one bounded append, never a full rewrite;
- checks projected total before mutation, rejecting oversize rather than trimming
  the final payoff/CTA;
- allows one additional bounded attempt if the first repair is invalid.

`make test` passed after the change. Regressions cover retry, late immutable
core/payoff, overflow, custom profile vocabulary, and case-folded purpose labels.

## Real Qwen smoke (no publish)

```bash
DRY_RUN=true XKIRO_LLM_MODEL='qwen/qwen3.8-max:free' \
bin/ytb batch start --profile ban-so-6 --num-of-vid 1 --type-of-vid short \
  --batch-key shorts_funnel_batch_qwen38max_free_repair_smoke_20260826 \
  --idea 'Minh định tự đoán yêu cầu của An, rồi dừng lại hỏi một câu: việc này dùng cho ai?'
```

Log: `assets/batch_logs/ideation_20260826_092957.log`.

| Measurement | Result |
|---|---:|
| Initial Qwen script | about 336 chars, under contract |
| Prompt delta budget | min 143, aim 252, max 380 chars |
| Allowed index | `[2]`, zero-based `application` |
| Actual returned delta | 196 chars |
| Repaired script | 532 chars |
| Profile safe range | 497–668 chars; absolute 473–710 |

Therefore the duration issue is solved by the engine with a real provider,
not by manually fixing a script.

## Current stop: independent character-story hook QA

The repaired 532-char candidate passed duration validation but was rejected at
`QA_RESULT 2` with:

```text
rule=hook
"Cảnh mở đầu chưa neo được khoảnh khắc hoặc chưa có gì để mất."
```

The opening has an anchor ("Sáu giờ hai mươi", Minh, the third rewrite) but
no explicit deadline, consequence, or thing at stake. It was archived correctly:

`assets/script_revisions/failed_ideation/minh-hoi-dung-mot-cau_20260826_093025_326400.json`.

There is no queued script, video artifact, or YouTube call. Do not hand-edit
this candidate.

Relevant code:

- `src/ytb_pipeline/agents/qa_agent.py::_check_story_hook()` already requires
  anchor plus stake for all `narrative_mode == "character_story"`; do not weaken it.
- `src/ytb_pipeline/orchestrator/ideation_prompts.py` generation rules need to
  state this same story opening contract.
- The full JSON recovery prompt handles hook repair explicitly only for Long,
  so a Short character story can reproduce this failure.

## Next task

At engine level, align generation and repair prompts with the existing generic
character-story QA contract: a Short opening must contain a concrete anchor,
an unfinished obligation/deadline/consequence, and an immediate action or
question. Do not hardcode `ban-so-6`, Minh/An, or a fixed sentence template.

Keep QA fail-closed. Start with RED tests for anchor-without-stake and for a
Short `rule=hook` recovery prompt. Then run the identical Qwen smoke command;
only after `batch start` passes, preflight and run the dry-run pipeline. Never
publish in this task.
