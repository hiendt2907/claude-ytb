# 03 — ARCHITECTURE

## Purpose

This document specifies the layered, hexagonal structure of `claude-ytb`:
which code belongs in which layer, how dependencies are allowed to point,
where ports and adapters live, how data flows across the four production
stages, and where the system is designed to be extended. It is the
structural implementation of the principles in `02-PRINCIPLES.md` and the
non-negotiable decisions in `PROJECT_VISION.md`.

## Layered + Hexagonal Overview

```
                         ┌─────────────────────────────────────────┐
                         │            INTERFACE LAYER               │
                         │  CLI (batch_cli) · Telegram listener ·   │
                         │  (future) HTTP API / TUI                 │
                         └───────────────────┬───────────────────────┘
                                             │ invokes
                         ┌───────────────────▼───────────────────────┐
                         │           APPLICATION LAYER                │
                         │  Orchestrator · WorkflowGraph executor ·   │
                         │  Checkpoint manager · Provider resolver    │
                         └───┬──────────┬──────────┬──────────┬───────┘
                  uses ports │          │          │          │
        ┌──────────────────▼─┐ ┌──────▼─────┐ ┌──▼───────┐ ┌▼────────────┐
        │   LLMProvider port  │ │VoiceProvider│ │ImageProv. │ │PublishProv. │
        └──────────┬───────────┘ └─────┬──────┘ └────┬──────┘ └──────┬──────┘
                   │                    │              │               │
   ┌───────────────▼──┐   ┌────────────▼───┐  ┌───────▼────────┐ ┌────▼─────────┐
   │ INFRASTRUCTURE     │   │ INFRASTRUCTURE │  │ INFRASTRUCTURE │ │ INFRASTRUCTURE│
   │ xKiro adapter       │  │ xKiro adapter  │  │ Flux adapter   │ │ YouTube API   │
   │ Codex/Claude CLI    │  │ F5/Edge adapters│ │ Pexels adapter │ │ Drive adapter │
   └─────────────────────┘   └────────────────┘  └────────────────┘ └───────────────┘

                         ┌─────────────────────────────────────────┐
                         │              DOMAIN LAYER                 │
                         │  Frozen dataclasses: Project, Research,   │
                         │  Outline, Narrative, Scene, Shot, Asset,  │
                         │  Timeline, RenderJob, PublishJob, ...     │
                         │  Zero outward dependencies.               │
                         └─────────────────────────────────────────┘
```

Dependency rule: arrows of *knowledge* point inward only. Interface knows
about Application. Application knows about Domain and depends on Provider
ports (interfaces it defines). Infrastructure adapters know about Domain and
implement Provider ports — but Application and Domain never import
Infrastructure directly.

## Layer Definitions

### Domain Layer

Location: `src/ytb_pipeline/pkg/models.py` (current), to be expanded per
`04-DOMAIN.md`. Pure data: frozen dataclasses with no behavior beyond simple
derived properties and no imports of Pillow, FFmpeg, provider clients, or any
SDK. This layer encodes the non-negotiable platform independence from
`PROJECT_VISION.md` §2.7 — it must never contain a YouTube-specific field
bolted onto a generic concept.

### Application Layer

Location: `src/ytb_pipeline/orchestrator/` (current `batch_cli.py`, to be
decomposed per `01-VISION.md` v3). Owns:

- The `WorkflowGraph` executor — walks `WorkflowNode`s in dependency order.
- The checkpoint manager — persists/loads node outputs (`05-WORKFLOW.md`).
- The provider resolver — reads `config/settings.py` (Pydantic) and
  constructs the configured adapter for each `Provider` port, by name.
- Stage coordinators for ideation, voiceover, render, publish — each
  coordinates calls to its `Provider` port and produces/consumes Domain
  objects. These currently live partially in `ideation/`, `voiceover/`,
  `render/`, `publish/` — those packages are Application-layer coordinators
  plus their own Infrastructure adapters today; the target state (v2)
  separates the coordinator (Application) from the SDK-calling adapter
  (Infrastructure) within each.

This layer defines the `Provider` port interfaces themselves (e.g., an
abstract `LLMProvider.generate(prompt: str) -> str`), since ports are
*application* contracts that infrastructure must satisfy — this is the
Dependency Inversion half of hexagonal architecture.

### Infrastructure Layer

Location: concrete adapter modules — `voiceover/tts.py` (Edge-TTS),
`voiceover/f5_provider.py` (F5-TTS), `render/stock.py` (Pexels),
`render/compose.py` / `render/compose_ai.py` (Pillow/FFmpeg),
`publish/uploader.py` (YouTube Data API), `publish/drive.py` (Google Drive),
`claude_cli.py` (Claude API). Each adapter implements exactly one Provider
port and contains all SDK-specific code (auth, request/response shapes,
SDK-specific error handling). No other layer imports these modules directly
— only the provider resolver in the Application layer instantiates them, by
configured name.

### Interface Layer

Location: `orchestrator/batch_cli.py` (CLI entrypoint, to shrink to a thin
client per v3), `listener.py` (Telegram control surface), `notify/telegram.py`
(notifications out). This layer translates an external trigger (CLI args, a
Telegram command) into an Application-layer call (start/resume a `Project`
run) and translates Application-layer results back into human-facing output
(console text, Telegram messages). It contains no business logic — no
quality-gate decisions, no provider selection logic.

## Ports and Adapters (Hexagonal Detail)

| Port (interface, owned by Application) | Adapters (Infrastructure, implement the port) |
|---|---|
| `LLMProvider` | xKiro (cloud, default) · Codex CLI → Claude CLI (ideation fallback cascade) |
| `VoiceProvider` | xKiro (cloud, default) · F5-TTS (local opt-in) · Edge-TTS / ElevenLabs (configured alternatives) |
| `ImageProvider` | Flux local diffusion (default per v2) |
| `VideoProvider` | Local image-to-video / animation pipeline (default) · Pexels stock (`stock.py`, explicit opt-in fallback only, never default) |
| `RenderProvider` (composition strategy) | `compose.py` (slide/gradient strategy) · `compose_ai.py` (local Pexels-origin B-roll + beat-sync strategy) · `story.py` (profile-owned character illustrations + multi-voice timeline) |
| `PublishProvider` | YouTube Data API (`uploader.py`) · Google Drive backup (`drive.py`) · (planned) TikTok, Instagram, Podcast RSS, Blog CMS adapters |

### Content profile boundary (implemented 2026-08-25)

`profiles/<profile_id>/` is the unit of topic configuration. It owns editorial
prompts, format bounds, provider selection, voice cast, renderer timing, local
assets, and optional series continuity. The shared queue stores `profile_id` on
each item and `PipelineRunner.build_env()` resolves an isolated environment for
that subprocess before the normal DAG starts. There is no profile-specific DAG.

This is separate from `platform/profiles.py`: a content profile answers what
and how to tell; a platform profile answers where and under which publishing
constraints to deliver it. Adding a topic must be a data-directory operation,
not a branch in pipeline/domain code.

### Content profile — extended contract (added 2026-08-26/27, generalized 71-commit line)

A `profile.json` may declare, beyond the base fields above:

- **`format_prompts`** (`{"short": "<prompt name>", "long": "<prompt name>"}`)
  — lets a profile give the Short and the Long transcript a *different*
  structural prompt (e.g. `long-transcript-structure.md` vs
  `short-funnel-structure.md`) instead of one undifferentiated `editorial`
  prompt for both. Validated at load time: every name referenced must exist
  in `prompts`; only `short`/`long` are legal keys.
- **`editorial_review`** (`{"enabled", "rubric_prompt_name", "minimum_score",
  "max_rewrites"}`) — an **opt-in** LLM-judged quality gate, separate from
  the deterministic `qa_agent.py` heuristics (see
  `38-EDITORIAL_QUALITY_LAYERS.md` for the boundary between the two).
  Implemented in `agents/editorial_review_agent.py`: scores a script 0-10 on
  five fixed dimensions (`human_truth`, `spoken_naturalness`,
  `causal_coherence`, `role_fidelity`, `useful_restraint`), cached by
  `(profile_fingerprint, script content hash)` so an unchanged script is
  never re-reviewed. A profile that never declares this block triggers zero
  extra LLM calls — existing profiles are unaffected unless they opt in.
- **`content_rules.allow_short_generation`** (default `true`) — a series can
  stop producing *new* Shorts while keeping every already-rendered Short
  readable (`ContentProfile.supports_generation()` separates "can this
  format still be generated" from "can this format still be loaded").
- **`content_rules.story_primary_speaker_id` /
  `story_supporting_speaker_id`** — a `character_story` profile names its own
  two-cast role contract instead of the engine assuming any fixed speaker
  keys; empty (default) keeps the older, more permissive cast contract.
- **`content_rules.long_opening_mode`** (`channel_greeting` | `pain_first` |
  `story_context`) and **`short_ending_mode`** (`final_action` |
  `funnel_bridge`) — the opening/closing shape of a Long or Short is a
  per-profile editorial choice, not a hardcoded channel-wide convention.
- **`content_rules.require_next_episode_bridge`** — a serialized story can
  require its closing to name what continues into the next episode.

### Profile version snapshots

`profiles/<profile_id>/versions/<semver>/` holds an immutable copy of
`profile.json` (and any versioned prompt/bible files) taken at the moment the
active `version` field was bumped. `load_content_profile(profile_id,
version=...)` resolves a specific snapshot so an already-rendered or archived
script keeps working against the exact contract it was produced under, even
after the active profile has moved on. Every profile that bumps its version
is expected to keep a matching snapshot directory — this is a convention
enforced by consistent authoring, not (yet) a loader-level check.

Each port is a small, focused interface (Interface Segregation per
`02-PRINCIPLES.md`) — e.g. `VoiceProvider` exposes `synthesize(script:
VoiceScript) -> Asset` and a `capabilities()` descriptor (supports cloning?
supports SSML? max input length?), not the full surface of any one TTS SDK.

## Data Flow Across Stages

```
Topic
  │
  ▼
[IDEATION]  Research → KnowledgeBase → Outline → Narrative → Story/Script
  │  (LLMProvider port; xKiro default, then Codex CLI → Claude CLI on failure)
  ▼
[VOICEOVER] VoiceScript → synthesized Audio Asset + Subtitle/timing data
  │  (VoiceProvider port; xKiro default; local F5 remains explicit opt-in)
  ▼
[RENDER]    Scene/Shot/Frame plans → ImagePrompt/VideoPrompt → visual Assets
            → Timeline assembly → RenderJob → final video Asset
  │  (ImageProvider/VideoProvider/RenderProvider ports; local diffusion
  │   default, Pexels stock opt-in only)
  ▼
[PUBLISH]   Asset + metadata → PublishJob → platform upload + Drive backup
  │  (PublishProvider port; network call is inherent here)
  ▼
Published content + analytics feedback (future: feeds back into Memory/KB)
```

Every arrow above is also a checkpoint boundary — see `05-WORKFLOW.md` for
the exact node list and checkpoint contract. The `Project` object accumulates
state as it flows top to bottom; nothing downstream is recomputed from raw
inputs if its upstream checkpoint already exists.

## Timeline — story renderer (Phase 1 MVP, added 2026-08-27)

`src/ytb_pipeline/render/timeline.py` introduces the ordering the render
layer must follow for the `story` renderer (`render/story.py`):

```
Narration  = timing authority   (Segment.duration_sec, measured by TTS)
Timeline   = deterministic derived execution plan (render/timeline.py)
Renderer   = Timeline consumer  (render/story.py translates it into FFmpeg)
```

`Timeline` (and its `VideoClip`/`NarrationClip`/`Transition` parts) is plain
domain data — no shell strings, no FFmpeg filter graphs, no LLM prose, no
provider configuration — built once via `build_story_timeline(voiceover,
profile, ...)` before any FFmpeg call, and validated at construction time
(`Timeline.__post_init__`): clip counts must match 1-1 between the video and
narration tracks, `transitions` must cover every clip boundary exactly once,
overlap must be shorter than its neighbouring clips, and the video/narration
tracks' computed expected durations must agree within one frame. This is a
structural fix for the production 2026-08-26 incident (162 caption-card
crossfades applied as if they were 20 section boundaries, silently dropping
55s/14% of narration, see `docs/handoffs/2026-08-26-story-renderer-caption-
transition-fix-handoff.md`) — that specific shape of bug is now a
`TimelineError` raised before any `ffmpeg` process starts, not a discrepancy
discovered by probing the finished `.mp4`.

`Timeline` is a **derived artifact, not a competing source of truth**: it is
rebuilt deterministically from `Voiceover`/`Segment` + the profile's
`render` contract on every render, and persisted only as a debug/postmortem
JSON next to the render's own output (`assets/output/<slug>_timeline.json`,
alongside the existing `<slug>_thumb.jpg` convention) — never inside
`scripts/<slug>.json` or `assets/projects/<slug>/project.json`.

Scope note: only `render/story.py` consumes `Timeline` in this phase;
`compose.py`/`compose_ai.py` are unchanged.

## ScenePlan — story renderer (Phase 2 MVP, added 2026-08-27)

`src/ytb_pipeline/render/scene_plan.py` makes explicit a decision the story
renderer already made implicitly before Phase 2: what each section's visual
should be, independent of when it plays. The full authoritative hierarchy
for the `story` renderer is now:

```
Script      = WHAT is being said
Narration   = HOW LONG it actually lasts (Segment.duration_sec)
ScenePlan   = WHAT should visually represent each narration window (render/scene_plan.py)
Timeline    = WHEN every renderable element appears  (render/timeline.py)
Renderer    = HOW those Timeline elements become media (render/story.py -> FFmpeg)
```

`ScenePlan` is deliberately **not** a second `Timeline`: a `Scene`'s
`narration_start_sec`/`narration_end_sec` window is the segment's own raw
narration span only (no `inter_segment_gap_sec`, no
`transition_overlap_sec` — those stay exclusively Timeline/renderer
transition arithmetic). `ScenePlan.__post_init__` enforces the same class of
invariant `Timeline` enforces for transitions: the number of `Scene`s must
equal the number of narrative segments, in order, never the number of
presentation elements (caption cards) — a caption card never becomes a
`Scene`, a `Shot`, or a scene boundary.

v1 scope is intentionally a 1:1 passthrough of the existing renderer
behaviour: one `Scene` per script segment, exactly one `Shot` per `Scene`
covering the whole scene window, reusing existing `Segment` semantic fields
(`purpose`, `visual_intent`, `scene_characters`, `visual_asset`,
`video_type`) rather than a parallel master-script schema. No LLM call is
introduced — `build_story_scene_plan()` is pure and deterministic, with
stable `scene_id`/`shot_id` values derived from segment index (not random
UUIDs), so an identical `Script`+`Narration`+profile always rebuilds an
identical `ScenePlan`. A future Director phase may enrich or replace how
`ScenePlan` is populated (e.g. one section -> multiple shots); it should not
require another renderer rewrite, only a different builder behind the same
contract.

`build_story_timeline()` (the Phase 1 public boundary) is now a thin
compatibility wrapper: it builds the implied `ScenePlan` and delegates to
`build_story_timeline_from_scene_plan(scene_plan, voiceover, profile, ...)`,
which is what `render/story.py` actually calls. Timeline genuinely consumes
`ScenePlan`'s scene boundaries rather than independently rediscovering them
from `voiceover.segments`.

Persistence: `ScenePlan` is written to `assets/projects/<slug>/scene_plan.json`
(the existing per-project state root, alongside `project.json`) — unlike
`Timeline`'s per-output artifact, `ScenePlan` is project-specific rather than
a reusable render-output cache. Like `Timeline`, it is a derived,
always-rebuildable debug/postmortem artifact, never read back by any stage
as a source of truth; a legacy project missing `scene_plan.json` is
unaffected, since every render rebuilds it fresh.

## Director ScenePlan v2 (Phase 7)

Story production now has an explicit persisted planning boundary:

```
Narration -> scene_plan -> visual_assets -> VisualManifest -> Timeline -> prepared renderer
```

`scene_planning.mode` defaults to `legacy_single_shot`; that mode remains
LLM-free and yields the historical one-shot Scene.  Opt-in `director` mode
uses the configured existing LLM provider once per semantic Scene.  Its strict
JSON contract accepts only `visual_intent`, allowed `characters`, and positive
`duration_weight`; malformed output receives at most one repair attempt.

`prepare_scene_plan()` persists `assets/projects/<slug>/scene_plan.json` and
reuses it only when its planning fingerprint matches narration semantics and
timing, profile policy, planner contract/ruleset, and provider identity.  The
fingerprint intentionally excludes rendered files, manifests, ComfyUI state,
and optional audio.  Each Director shot gets a deterministic semantic hash
(`scene + intent + characters + duplicate occurrence`), rather than an
ordinal ID, so inserting/reordering an unrelated shot does not remap an
existing asset.

The deterministic normalizer—not the LLM—allocates the Scene's exact narration
window. `Timeline.shot_clips` records every resolved Shot within that window;
their durations sum to the scene duration and never multiply narration.  The
prepared renderer consumes these persisted semantics and prepared assets only;
it does not call Director, an LLM, or ComfyUI.  `compose_ai.py` remains outside
this story-only capability.

## Derivative visual reuse (Phase 8)

An editorially rewritten Short remains independent: it has its own Script,
Narration, ScenePlan, VisualRequests, VisualManifest and Timeline. When its
existing `strategy.source_long_slug/source_section_index` identifies a parent
Long, `visual_assets` persists `derivative_lineage.json` beside the child
project state. A child Shot gets a reuse source only when a Shot in that exact
parent Scene has identical visual intent and character semantics; there is no
ordinal, filename, generation-key, byte-hash, or similarity-search fallback.

Before reuse the resolver validates the parent AssetRecord/use, physical bytes
and SHA-256, supported asset class, and exact prepared media dimensions. This
is deliberately fail-safe across 16:9 and 9:16: it performs no crop, reframing
or parent-MP4 use. A miss calls the normal local/cache/ComfyUI resolver. A hit
adds an idempotent Short use to the same global AssetRecord and records mutable
reuse provenance only in the Short manifest. The renderer remains unaware of
whether its prepared image originated locally, was generated, or was reused.

## Visual Assets — prepared story boundary (Phase 4)

For `character_story`, `visual_assets` runs between audio quality and render.
It builds the deterministic ScenePlan and provider-neutral `VisualRequest`s,
then `VisualAssetResolver` is the sole owner of local-asset lookup, generation
cache, ComfyUI calls, and AssetRegistry registration. Per-project
`visual_manifest.json` checkpoints each shot (`pending`/`running`/`done`/
`failed`) against its request fingerprint and registered asset ID.

`render_prepared_story_video()` accepts only verified prepared paths; it does
not import or call a visual provider. A render retry therefore succeeds after
ComfyUI is unavailable as long as the manifest, registry record, file, and
observed content hash remain valid. The direct `render_story_video()` wrapper
is retained only for legacy callers and performs preparation before entering
the prepared core.

AssetRegistry remains protected by its existing process-safe file lock. ComfyUI
is a server-side prompt queue, so Phase 4 adds no second distributed queue.

## Subtitle and audio timeline layers (Phase 5)

Phase 5 keeps Narration as the measured timing authority. The story Timeline
now represents separate optional `music_clips` and `sfx_clips` through the
validated `AudioLayerClip` contract; neither changes `expected_duration_sec`
or duplicates narration. No shipped content profile enables optional music/SFX
yet, so no mix path or loudness pass was added. Narration continues to be
normalized once by the existing TTS concatenation path.

`render/subtitle.py` derives one Vietnamese subtitle cue per narration segment
from `Timeline.narration_clips`, then emits sibling `<slug>.srt` and
`<slug>.vtt` files during story rendering. These accessibility artifacts are
distinct from the existing burned caption cards and do not provide translation
or word-level alignment.

## Deterministic local audio mixing (Phase 6)

`render.audio` optionally configures one local background music track and
explicit local SFX events. Timeline owns start, trim/loop, fades and gain,
while narration remains authoritative and optional layers cannot extend it.
`render/audio_mixer.py` validates local audio streams and mixes narration once
with FFmpeg `amix=duration=first`; the existing TTS loudnorm remains the only
narration normalization. No AI or network media selection is involved.

## Asset Registry — character_story visuals (Phase 3.2, added 2026-08-27)

`src/ytb_pipeline/render/asset_registry.py` adds a durable provenance/
catalog layer for `character_story` generated visuals. It is purely
additive observability/reproducibility — NOT a provider redesign:
`render/story.py`'s existing generation, caching, and ComfyUI call
behaviour is byte-for-byte unchanged; `resolve_scene_image()` still
resolves and returns a `Path` exactly as before, and the renderer keeps
consuming paths. Two corrective revisions preceded this one — see
`docs/handoffs/2026-08-27-asset-registry-phase3.2-handoff.md` for the full
rationale of both identity defects found and fixed.

```
asset_id           opaque identity of ONE registered concrete asset/
                   provenance record (a uuid4 — unrelated to content,
                   request, or path identity)
content_sha256     identity/EVIDENCE of the bytes observed AT
                   REGISTRATION TIME — an INDEX, not a primary key
generation_key     identity of the semantic generation/cache REQUEST
                   (== the existing `_generation_cache_key` in story.py)
local_path         a LOCATOR of the observed file, not an identity
```

These four are kept **fully independent**. Two mistakes were made and
corrected on the way here:

- Phase 3's first attempt derived `asset_id` deterministically from
  `generation_key`, making the two 1:1 in practice — wrong, because **one
  `generation_key` may map to zero, one, or MANY `AssetRecord`s** (e.g. the
  same semantic request regenerated after a checkpoint change).
  `find_by_generation_key()` always returns a list.
- Phase 3.1 fixed that, but then used `content_sha256` ALONE as a
  universal upsert/dedup key — the same mistake one level down.
  **`content_sha256` proves byte equality only** — not same provenance,
  not same generation event, not same asset class, not same generation
  request, not same physical/cache entry. `find_by_content_sha256()` is a
  SEARCH index that may legitimately return many records; it is never
  used internally to decide record identity.

The corrected (Phase 3.2) matching rule is **exact observation**:
`local_path` + `content_sha256` + a *compatible* `asset_class`, plus
`generation_key` (and, for a fresh generation, `seed`) where applicable.
Concretely (`_match_generation_observation`/`_match_profile_local_
observation` in `asset_registry.py`):

- A **cache hit** (`is_fresh_generation=False`) reuses an existing
  `generated` OR `legacy_generated` record when `local_path` +
  `content_sha256` + `generation_key` all agree — this is the common "same
  cached file reused by many projects" path, and it is what keeps that
  case down to ONE record no matter which class first created it.
- A **fresh generation** (`is_fresh_generation=True`) only ever matches
  within the `generated` class (never silently adopting/upgrading a
  `legacy_generated` record — `asset_class` is immutable once set), and
  additionally requires the existing record's `seed` to agree. Identical
  locator/hash/generation_key evidence with a **conflicting seed** is
  treated as a distinct historical event, not a duplicate observation —
  it creates a new record; the old one's `seed` is never overwritten.
- A **profile-local** lookup is scoped strictly to `asset_class ==
  "profile_local"` — a `generated`/`legacy_generated` record with
  identical bytes never satisfies it, and vice versa.
- **Different paths with identical bytes never automatically merge.** Path
  mutation (the file at a path replaced with different bytes) never
  rewrites an existing record either — a content mismatch at upsert time
  always produces a new record, leaving the old one's provenance intact.

The full match-then-insert-or-reuse decision for both `record_generated`
and `record_local_asset` happens inside ONE `locked_json_update` critical
section — never "read, decide, then re-lock to insert", which would let
two racing workers observing the same cache hit both create a record.

Three provenance classes (`asset_class`), because they are not
interchangeable and must never auto-merge into one another even when
bytes coincide:

```
generated          fresh ComfyUI result THIS call just produced
                   -> provenance_status = "complete"
legacy_generated   a cache HIT with no prior registry record — the file
                   may predate this registry, or a checkpoint/provider
                   change, so its true original parameters are NOT
                   certain and none are fabricated
                   -> provenance_status = "legacy_unknown"
profile_local      a fixed, hand-placed profile asset (Segment.
                   visual_asset) — never generated, so it carries no
                   generation metadata at all, but its OWN provenance
                   (which file, which profile) is fully known
                   -> provenance_status = "complete"
```

A `legacy_generated` record is **never silently upgraded** to `complete`
on a later cache hit just because the current request's full config
happens to be reconstructable — historical provenance is immutable;
`asset_class` is never mutated after a record is created.

Every record's `uses` list carries the Phase 2 deterministic `scene_id`/
`shot_id` plus the video's slug — the same append-only, dedup-on-repeat
pattern `render/asset_catalog.py` already uses for Pexels stock-footage
reuse tracking.

Persistence: `assets/asset_registry.json` (sibling to, and structurally
independent from, `asset_catalog.json` which only tracks licensed Pexels
reuse), written through `orchestrator/state_io.py::locked_json_update` —
the same exclusive-`flock` + atomic-rename helper `asset_catalog.py` uses.
`fcntl.flock` is enforced by the kernel per OPEN FILE DESCRIPTION, not per
process, so `tests/test_asset_registry.py`'s thread-based concurrency
tests (each thread opens its own descriptor via `file_lock()`) exercise
the identical kernel-level serialization a second batch-worker OS process
would; a real `multiprocessing`/fork-based variant was tried and reverted
after it destabilised unrelated tests elsewhere in the suite (forking a
pytest worker process is a known hazard, unrelated to this registry's own
correctness). `tests/test_state_io.py` separately proves the locking
primitive itself. `scene_id`/`shot_id`/`video_slug` are optional keyword
arguments on `resolve_scene_image()`; every caller that omits them (every
pre-Phase-3 test, and any future caller that doesn't care about
provenance) gets zero registry I/O and the exact prior behaviour — only
`render_story_video()`'s own call site passes them.

## Extension Points

- **New AI provider for an existing capability**: implement the relevant
  `Provider` port in a new Infrastructure module; register it in
  `config/settings.py`'s provider name → adapter mapping. No Application or
  Domain code changes required.
- **New publish platform**: implement `PublishProvider` for that platform
  plus a render preset (aspect ratio, duration limits, caption style) in the
  render stage's preset table. No upstream stage changes required.
- **New domain object** (e.g., a new `SFX` or `Memory` subtype): add the
  frozen dataclass to the Domain layer per `04-DOMAIN.md`'s conventions;
  wire it into the relevant `WorkflowNode`'s input/output contract in
  `05-WORKFLOW.md`.
- **New quality gate**: add a `WorkflowNode` with a boolean pass/fail output
  inserted into the DAG before the node it gates (typically before
  Storyboard finalization or before Publish) — gates are first-class DAG
  nodes, not inline `if` statements inside another stage's code.
- **New interface surface** (HTTP API, TUI): add a new Interface-layer
  module that calls the same Application-layer orchestrator entrypoints
  `batch_cli.py` and `listener.py` already call — it must not duplicate
  orchestration logic.
