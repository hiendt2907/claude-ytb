# Phase 8 — Long → Short Visual Asset Reuse Handoff

**Status:** complete. **Branch:** `codex/phase8-asset-reuse`.

Previous work: Phase 4 prepared visuals, Phase 6 audio layers, and Phase 7
persisted Director ScenePlan. Phase 8 preserves their boundaries.

## Actual implementation

Short editorial derivation already persists `strategy.source_long_slug` and
`source_section_index`. `render/derivative_lineage.py` turns that explicit
parent identity into `derivative_lineage.json` under the child project during
`visual_assets`. It loads the parent persisted ScenePlan and creates a shot link
only for an exact visual-intent/character match in the explicitly cited parent
Scene. The lineage schema is `parent_project_id`, `contract_version`, and a
child shot map to `parent_project_id`, `parent_scene_id`, `parent_shot_id`, and
policy version. There is no ordinal or fuzzy matching.

The production flow is parent prepared AssetRecord → child lineage → child
VisualRequest → reuse check or existing resolver → child VisualManifest → child
Timeline/prepared renderer. Short Script, narration timing, ScenePlan and
Timeline are never copied from the Long. Parent MP4 and Timeline are never read.

`_parent_reuse` validates the parent registry use, supported class
(`generated`, `legacy_generated`, `profile_local`), file existence, observed
SHA-256 and exact known prepared dimensions. Exact dimensions is the Phase 8
aspect policy: 16:9 assets do not silently become 9:16 assets; no crop, pan,
reframe or AI outpaint exists. Any missing/stale/removed/incompatible candidate
falls through to normal cache/generation resolution.

On a hit, `AssetRegistry.record_existing_use` adds the child project/scene/shot
usage under its existing lock without changing immutable provenance or creating
a second AssetRecord. VisualManifest records child-local `reuse_source` with
parent project/scene/shot/asset and policy. Multiple Shorts can attach uses to
one record; resume validates the same concrete file/hash as every other
manifest entry. Parent replanning or MP4 deletion does not mutate an already
prepared child; a later explicit child replan can re-evaluate lineage.

Tests: `tests/test_derivative_visual_reuse.py` covers explicit reuse,
no-duplicate provenance/use, and incompatible-aspect fallback. Existing visual,
scene-plan, timeline, Short editorial and renderer tests remain in the full
suite. Tests use temporary registry/project/cache paths and do not write media
to repository assets.

Commits: `8b9bd37` RED test checkpoint plus the implementation/docs commit that
follows this handoff. Full suite: **1122 passed, 3 skipped, 1 deselected, 0 failed**
from 1126 collected items.
Deferred: semantic embedding search, smart crop/reframing, video clipping,
candidate ranking/QC, new providers, and Phase 9. Definition of done: explicit
lineage, validated reuse-before-render, normal fallback, preserved provenance,
independent Short timing, and a pure prepared renderer.
