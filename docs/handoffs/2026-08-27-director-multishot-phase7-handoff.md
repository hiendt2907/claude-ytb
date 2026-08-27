# Phase 7 — Director Multi-shot Handoff

**Status:** complete.  **Branch:** `codex/phase7-director`.

Previous handoffs: Phase 4 visual assets, Phase 5 subtitles, and Phase 6
audio mixer (`docs/handoffs/2026-08-27-audio-mixer-phase6-handoff.md`).  Phase
6 reconciliation added mixer-path coverage in `175982b`; the original Phase 6
run was 1111 passed, 3 skipped, 1 deselected.

## Delivered architecture

`input -> voiceover -> audio_quality -> scene_plan -> visual_assets -> render
-> render_quality -> publish`.  The `scene_plan` node owns planning and writes
`assets/projects/<slug>/scene_plan.json`; `visual_assets` requires that exact
file and only produces `VisualRequest[]`/`visual_manifest.json`; render reads
the same plan and verified manifest.  Non-story renderers receive a safe
not-applicable planning node.

`scene_planning.mode` is `legacy_single_shot` by default, yielding the old
single deterministic shot and zero LLM calls.  Opt-in `director` calls the
existing configured LLM provider once per Scene. Its request is bounded to
narration, scene visual intent, allowed characters and maximum shot count.
Its response has exactly `shots`, where every item has only `visual_intent`,
`characters`, and positive `duration_weight`. Unknown fields/characters,
empty/excess shots and invalid weights fail validation; malformed output gets
one repair attempt, then fails closed.

`prepare_scene_plan()` persists/reuses a validated plan with a fingerprint of
base narration/semantic inputs, profile/version and planning policy, planner
contract/ruleset and provider identity. It excludes MP4/subtitles, manifests,
ComfyUI availability, registry usage and audio layers. Changed narration,
visual intent, characters or policy rebuilds; a downstream failed shot does
not rerun Director. Provenance is stored in `planner_provenance`.

## ScenePlan/visual/timing behavior

ScenePlan v2 retains the existing `Scene`/`Shot` model. Director shot IDs are
semantic hashes of scene id, visual intent, characters and duplicate occurrence:
the same accepted output is stable; inserting/reordering unrelated shots keeps
unaffected identities; identical intentional shots get distinct IDs. IDs remain
separate from request fingerprints, generation keys and AssetRegistry IDs.

The deterministic normalizer reserves `min_shot_sec` for every shot, distributes
the remaining scene window by weights and assigns the final arithmetic residue
to the last shot. Therefore coverage is exact and narration remains timing
authority. Timeline now emits `shot_clips` for every ScenePlan Shot while
continuing to apply transitions only between narration Scenes. The prepared
story renderer resolves a card's visual by the persisted shot covering that
card's deterministic seek; it never asks Director or invokes generation.

VisualRequest already iterates every Shot. VisualManifest continues checkpointing
by shot id: valid A/B entries are retained while C fails/retries; an inserted
shot adds only a new entry, and removed shots are not required by the new
request set. AssetRegistry Phase 3.2 identity/provenance semantics are unchanged.
Prepared rerender remains ComfyUI-free after valid assets are prepared.

Audio/subtitles remain narration-derived; music/SFX are Timeline layers and do
not form scenes or shots. `mechanism_explainer` / `compose_ai.py` are unchanged.

## Evidence and scope

Tests added/extended: `tests/test_director_agent.py`,
`tests/test_render_scene_plan.py`, and `tests/test_pipeline_stage_selection.py`.
They cover persistence/reuse/invalidation, semantic IDs, strict output bounds,
multi-shot Timeline coverage, and the explicit DAG stage. All state uses
temporary test project paths; no runtime asset is intentionally written under
the repository asset roots.

Commits: `b2d4214`, `30519e7`, plus the completion commit following this
handoff. Final full suite: **1120 passed, 3 skipped, 1 deselected, 0 failed**
from 1124 collected items. Deferred:
candidate generation/ranking, VLM QC, new visual providers, short reuse, smart
crop, approval UI, compose_ai Timeline migration, AI music/SFX and Phase 8.

Definition of done: opt-in Director planning is persisted and bounded; legacy
planning stays LLM-free; stable semantic shot IDs and exact multi-shot coverage
flow through VisualRequest, manifest, Timeline and prepared rendering; Phase
1–6 architecture remains intact.
