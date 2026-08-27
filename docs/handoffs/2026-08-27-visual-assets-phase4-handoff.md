# Phase 4 — Visual Assets Handoff

**Status:** accepted and complete  
**Branch:** `codex/phase4-visual-assets`  
**Scope:** Phase 4 only; no next-phase implementation is included.

## Previous handoffs

- `docs/handoffs/2026-08-27-scene-plan-phase2-handoff.md`
- `docs/handoffs/2026-08-27-asset-registry-phase3-handoff.md`
- `docs/handoffs/2026-08-27-asset-registry-phase3.1-handoff.md`
- `docs/handoffs/2026-08-27-asset-registry-phase3.2-handoff.md`

## Objective and final production DAG

Phase 4 makes character-story visuals a resumable pre-render product. The
production DAG is:

```text
input -> voiceover -> audio_quality -> visual_assets -> render -> render_quality -> publish
```

`visual_assets` is applicable only to the `story` renderer. Other profiles,
including `mechanism_explainer`, keep their existing rendering route.

## Implementation map

- `src/ytb_pipeline/render/visual_assets.py`: frozen request contract,
  project manifest, validation, controlled resolver, and preparation stage.
- `src/ytb_pipeline/render/story.py`: prepared-only core renderer plus a
  legacy convenience wrapper.
- `src/ytb_pipeline/providers/render/story_provider.py`: exposes
  `render_prepared()` for production use.
- `src/ytb_pipeline/pipeline.py`: executes `visual_assets` after
  `audio_quality`, validates prepared inputs, and invokes `render_prepared()`.
- `tests/test_visual_assets.py`, `tests/test_profile_multivoice_render.py`,
  `tests/test_pipeline_quality_integration.py`, and
  `tests/test_pipeline_stage_selection.py`: Phase 4 contract, DAG, and
  prepared-render coverage.
- `docs/constitution/03-ARCHITECTURE.md`: records the prepared visual boundary.

## VisualRequest

`VisualRequest` is a frozen, provider-neutral dataclass with:

```text
request_id, request_fingerprint, scene_id, shot_id,
visual_intent, characters, dimensions, resolution_kind,
semantic_constraints
```

`build_visual_requests(scene_plan, profile, dimensions=...)` is the sole
deterministic builder. It currently produces one request for every v1 shot.
Its fingerprint covers profile id/version and visual policy, resolution kind,
scene/shot ids, visual intent, characters, and dimensions. Provider runtime
state is not included. No ComfyUI graph, sampler, cache path, checkpoint, or
FFmpeg detail enters this contract.

## Derived artifacts and persistence

`prepare_visual_assets()` builds `ScenePlan` from `Voiceover + ContentProfile`
and writes `assets/projects/<project-id>/scene_plan.json`. It immediately
builds `VisualRequest[]` from that plan and persists
`assets/projects/<project-id>/visual_manifest.json`.

The manifest schema is:

```text
source_fingerprint
shots[shot_id] = {
  request_id, request_fingerprint, status,
  asset_id, attempt_count, last_error
}
```

The explicit statuses are `pending`, `running`, `done`, and `failed`.
`VisualManifest` is project checkpoint state; it is neither the global
AssetRegistry nor the generated-file cache.

## Resolver and ComfyUI boundary

`VisualAssetResolver.resolve()` is the single decision owner:

```text
VisualRequest + segment + shot
  -> profile-local AssetRecord, or
  -> generated cache hit + AssetRecord, or
  -> existing ComfyUI provider call + generated AssetRecord
```

For a generated request it retains the previous generation-key, seed, prompts,
dimensions, style/negative prompt, steps, CFG, IPAdapter, sampler, scheduler,
and cache behavior. A cache miss calls the existing story image provider once;
a cache hit makes no provider call. A profile-local shot records a
`profile_local` asset and makes no provider call.

Therefore ComfyUI is allowed only from `VisualAssetResolver` inside the visual
preparation path. The normal production renderer does not call it.

## Prepared rendering and compatibility

`render_prepared_story_video(voiceover, output_dir, profile, scene_plan,
prepared_assets)` is the core. It only creates Timeline/FFmpeg/Pillow output
from already validated assets.

`render_story_video()` remains a compatibility wrapper for direct legacy
callers: it prepares a missing manifest, then delegates to the prepared core.
`pipeline.run_project()` does not use that fallback. It loads the persisted
ScenePlan when available (otherwise deterministically rebuilds it), requires a
manifest, validates it against AssetRegistry and file hashes, and calls the
provider's `render_prepared()` method. Missing or incomplete manifests block
before composition; they never cause a render-time visual fallback.

## Resume, invalidation, and failures

On a restart after shots 1–36 reached `done` and shot 37 failed, preparation
validates and reuses shots 1–36 without generating them again. It retries shot
37, persists its new `running`/`done` or `failed` state, and continues later
shots only after it succeeds. Earlier successful checkpoints are retained if a
later provider call fails.

A `done` entry is reusable only when all four checks pass:

1. request fingerprint matches;
2. the referenced AssetRecord still exists;
3. its physical `local_path` exists; and
4. the observed SHA-256 still equals the record's `content_sha256`.

Failure of one check invalidates only that shot. A changed request fingerprint,
missing registry record, deleted file, or changed bytes causes that request to
be re-resolved; it does not regenerate the complete project. Failed generation
marks the current manifest entry `failed`, records `last_error`, preserves
earlier `done` entries, fails the visual-assets node, and prevents render.

## Registry and cache invariants

Phase 3.2 identity semantics are unchanged: `asset_id` is opaque;
`content_sha256` is observed-byte evidence; `generation_key` identifies a
generation/cache request; and `local_path` is a locator. Exact-observation
matching remains in `AssetRegistry`; cache hits without a trustworthy prior
record are registered as `legacy_generated`, fresh outputs as `generated`,
and fixed profile assets as `profile_local`.

The existing process-safe AssetRegistry lock remains the shared-state guard.
No additional distributed ComfyUI queue was introduced: the implementation
continues to submit through ComfyUI's server-side prompt queue.

## Acceptance evidence

`test_story_renderer_preserves_audio_timeline_when_a_section_has_many_caption_cards`
performs the prepared-render acceptance case: it first prepares visuals, deletes
the final MP4, replaces `VisualAssetResolver.resolve` with an assertion that
generation must not run, validates manifest/registry inputs, and successfully
calls `render_prepared_story_video()` to rebuild the video.

Tests use temporary project, registry, cache, audio, and output locations.
Runtime registry artifacts created during tests were removed; the final tracked
change is documentation only.

## Verification

```text
make test = 1108 passed, 3 skipped, 1 deselected, 0 failed
```

Phase 4 commits:

```text
b76febb test: add visual asset resolver contract
f53a145 fix: separate prepared story rendering from visual generation
384da79 test: cover visual-assets pipeline stage
fd60ed2 docs: record prepared visual asset boundary
6254247 test: prove prepared render avoids generation
```

## Definition of done

- [x] Deterministic, provider-neutral VisualRequest and builder.
- [x] Per-shot durable manifest and resume lifecycle.
- [x] Resolver exclusively owns local/cache/provider/registry decisions.
- [x] Production DAG prepares visuals before render.
- [x] Prepared renderer fails closed and never generates images.
- [x] Registry/file/hash validation and shot-level invalidation.
- [x] Cache-hit, cache-miss, profile-local, and provider-failure behavior.
- [x] Compatibility retained for direct renderer callers and non-story profiles.
- [x] Acceptance test and full suite evidence above.

## Explicitly deferred / non-goals

- Multiple shots per scene, a DirectorAgent, or an LLM planning layer.
- Changes to ComfyUI workflow, visual prompt behavior, generation parameters,
  or Phase 3.2 registry identity rules.
- Migration of `compose_ai.py` or `mechanism_explainer`.
- A distributed generation queue or broader concurrency redesign.

## Recommended next phase (do not implement here)

Use the stable prepared-visual boundary to add a separately scoped visual
quality/review stage, or a richer multi-shot ScenePlan builder, with the same
manifest and prepared-render contracts preserved.
