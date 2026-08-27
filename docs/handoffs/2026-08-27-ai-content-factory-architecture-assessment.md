# Architectural Assessment — `claude-ytb` as an "AI Content Factory"

Ngày: 2026-08-27
Người viết: Claude (subagent `architect`, read-only, không sửa file nào)
Bối cảnh: đánh giá kiến trúc theo "Master Prompt — AI YouTube Content Factory"
do user cung cấp, đối chiếu trực tiếp với code thật trong repo thay vì suy
đoán. Đây là đánh giá thuần tuý — **chưa implement gì**, đúng yêu cầu §40-42
của master prompt (dừng lại chờ duyệt kiến trúc trước khi code).

**Scope note:** read-only. No files written during the assessment itself.
Every claim below is anchored to a file the subagent actually read.

---

## A. Understanding of the product — and where the master prompt mismatches this repo

**What the prompt describes:** a local-first media production engine turning one idea into one master long-form video plus derivative Shorts/Reels, with AI agents doing research/writing/directing/QC and deterministic code doing state, assets, timing, rendering, reproducibility.

**What this repo actually is today:** ~80% of that, already shipped and running in production, but with a different centre of gravity than the prompt assumes:

- It is a **Vietnamese-language YouTube channel factory**, not a generic content engine. Narration, QA heuristics (`agents/qa_agent.py`), prompt artifacts (`profiles/*/prompts/*.md`), and even error messages are Vietnamese-first. "English subtitles" (prompt §37) is not a supported concept anywhere in the codebase.
- The unit of configuration is a **content profile** (`src/ytb_pipeline/content_profiles.py`, `profiles/<id>/profile.json`), not a "project template". A profile owns editorial prompts, format bounds (min/max seconds and sections per `short`/`long`), provider selection, voice cast, render timing, character identity anchors, and an opt-in LLM rubric gate. Two real profiles run today: `one-cup-cafe-6h` (`mechanism_explainer`, Pexels-origin B-roll, funnel Shorts) and `ban-so-6` (`character_story`, ComfyUI/IPAdapter-generated scenes, Long-only).
- **The prompt's "provider-agnostic, local-first, API-assisted when valuable" is already resolved differently here, deliberately.** Per `CLAUDE.md` §AI Rules and `config/settings.py`: LLM **and** TTS are cloud-primary via xKiro (`llm_provider="xkiro"`, `tts_provider="xkiro"`, `xkiro_llm_model="deepseek/deepseek-v4-pro"`). Ideation is *forbidden* from falling back to Claude/Codex — `ideation_cmd._configured_script_provider()` raises if the name isn't `"xkiro"`. Visuals/render stay local. Do **not** re-propose Ollama/MLX or "Claude/Codex for planning" — that was explicitly removed by amendment 2026-08-24/26.
- **Hardware discrepancy (flagging explicitly):** the master prompt says *MacBook Pro M4 Pro, 24 GB*. `CLAUDE.md` says **MacBook Pro M4** (not M4 Pro), and **no RAM/VRAM figure is documented anywhere in the repo** — grepped all `*.md`. `providers/image/comfyui_story_provider.py:47` contains a stray comment referencing "M4 Pro". So the actual machine class and memory budget are *unverified*. Section K below is written under that uncertainty rather than pretending 24 GB is a known fact.
- **Also flagging:** the prompt's aspiration "one 16:9 long + five Shorts from one command" is *not* what the channel strategy currently wants. `ban-so-6` sets `allow_short_generation: false` — a deliberate, confirmed-permanent Long-only decision (`docs/handoffs/2026-08-27-content-profile-engine-refactor-plan.md` §2b/Giai đoạn 2). A generic "always fan out to N shorts" architecture would regress that.

**Mental-model correction I'd insist on:** this repo already treats "long is the master IP, Shorts are derivative" — but derivation happens at the **script/knowledge level**, not the media level. That is the *right* choice and is stronger than what the prompt asks for. Details in M.

---

## B. End-to-end workflow — as built vs. as proposed

**Currently implemented (two disjoint phases, by design):**

```
Phase 1 — ideation (operator-triggered, cloud LLM, `ytb batch start`)
  topic/rules
   → local_script_prompt() assembled from profile prompt artifacts (orchestrator/ideation_prompts.py)
   → xKiro DeepSeek V4 Pro, json_output=True + response_schema (ideation/generation_schema.py)
   → process_and_sanitize()      deterministic wording/JSON/slug sanitizer (ideation/wording_engine.py)
   → validate_or_repair_script() bounded repair loop (ideation/ideation_script_fix.py)
      ├ script_contract.validate_script_payload()   SHAPE
      ├ QAAgent                                     Vietnamese CONTENT heuristics
      └ run_editorial_review()                      opt-in LLM 5-dim rubric, cached
   → scripts/<slug>.json + queue entry in assets/auto_state.json

Phase 1.5 — `ytb batch preflight` (offline admission gate, orchestrator/preflight.py)
   schema, runtime bounds, required purposes, orientation-vs-video_type,
   TTS readiness, render provider, local assets, thumbnail, ≥10 GB free disk

Phase 2 — production DAG (`python -m ytb_pipeline` subprocess, pipeline.run_project)
   input → voiceover → audio_quality → render → render_quality → publish
   each node checkpointed in assets/projects/<slug>/project.json
```

**Correction to the prompt's proposed order.** The prompt lists `... → narration → scene planning → asset generation → timeline → render`. This repo does **narration → (implicit) scene = script section → visual resolution inside render**, and that ordering is correct for narrated explainer/story content: narration is the authoritative timeline (see C and §19 answer below). What is genuinely *missing* is an explicit **scene-planning artifact between script and render**. Today, "one script section = one scene" is hardcoded by structure: `render/story.py` iterates `voiceover.segments` and calls `resolve_scene_image(segment, ...)` per section; `render/compose_ai.py` slices each segment into ~6s beats (`BEAT_TARGET_SEC=6.0`, `HOOK_BEAT_SEC=2.5`, `COLD_BEAT_SEC=1.3`). A section is 20–30s of narration, so the visual granularity is *derived*, not *directed*.

**Recommended corrected order (minimal delta, not a rewrite):**

```
topic → research* → strategy → master script (sections) → QA gates
      → narration (TTS, authoritative durations)
      → SCENE PLAN (new: sections × narration timing → shots, currently implicit)
      → visual asset resolution/generation (cached)
      → timeline (new: currently implicit inside renderer)
      → deterministic FFmpeg render → QC → publish
      → derivative Shorts (already script-level, from the Long's sections)
```

`research*` is the weakest link: `agents/research_agent.py` only wraps YouTube trending/hashtags and returns empty output when `YOUTUBE_API_KEY` is unset; it is **registered in `agents/__init__.py` but never called by the production DAG or by ideation**. Same for `StoryArchitectAgent`, `VoiceDirectorAgent`, `SEOAgent`. That is dead-ish infrastructure — a real technical-debt finding (see E).

---

## C. Source-of-truth model

**Already authoritative today:**

| Stage | Authoritative artifact | Where |
|---|---|---|
| Topic config / editorial law | `profiles/<id>/profile.json` + `prompts/*.md` | `content_profiles.py`; snapshotted at `versions/<semver>/` |
| Batch queue / schedule | `assets/auto_state.json` | `orchestrator/state_io.py` (`locked_json_update`) |
| Master content | `scripts/<slug>.json` (VideoIdea/Script/sections/strategy/compliance/thumbnail_brief) | `ideation/generator.py::load_script`, `pkg/models.py` |
| Per-video execution state | `assets/projects/<slug>/project.json` | `project/models.py`, `project/checkpoint.py` |
| Narration timing | segment `.mp3`/`.m4a` files + `duration_sec` in the voiceover node's `output_data` | `voiceover/tts.py`, `pipeline._voiceover_output_data` |
| Stock-asset provenance | `assets/asset_catalog.json` | `render/asset_catalog.py` |
| Generated scene images | content-hash cache `assets/generated_visuals/<profile_id>/` | `render/story.py::_generation_cache_key` |
| Series continuity | `profiles/<id>/continuity-ledger*.json` | `ideation/continuity.py` |

**Judgement:** the prompt's proposed `research.json / script.json / scene_plan.json / timeline.json` split is *partly* right and *partly* a regression risk here.

- Genuinely missing: **`research`** (no persisted research artifact at all — research is fused into one LLM call), **`scene_plan`**, **`timeline`**, **asset registry for generated (non-stock) assets** (the content-hash cache is a cache, not a registry: no record of prompt, seed, model, workflow, generation time — see §17/§29 gaps).
- Do **not** split `script.json` into script + voiceover-script + visual-directions as separate files. `Segment` already carries `narration`, `caption`, `visual_intent`, `visual_asset`, `scene_characters`, `pexels_query`, `purpose`, per-segment prosody overrides, `emphasis`, `transition`. Splitting would break `script_contract.py`, `qa_agent.py`, `preflight.py`, the profile version-snapshot replay guarantee, and the `script_sha256` release-manifest chain in `pipeline.publish_fn`. The correct move is to add **downstream derived artifacts**, never to fragment the upstream master.

**Proposed additions (derived, not authoritative-competing):**

- `assets/projects/<slug>/research.json` — populated only when a research stage exists; script generation records which research it consumed.
- `assets/projects/<slug>/scene_plan.json` — output of a new DirectorAgent-or-deterministic-planner node; consumes narration durations.
- `assets/projects/<slug>/timeline.json` — deterministic expansion of scene plan + audio into tracks; the renderer's *only* input.
- `assets/asset_registry.json` (or per-profile) — generalizes `asset_catalog.json` to cover generated assets with full reproduction metadata.

---

## D. Proposed architecture

The existing hexagonal layering (`docs/constitution/03-ARCHITECTURE.md`) is sound and should not be replaced. The delta is: **make the two implicit layers (scene plan, timeline) explicit, and make asset generation a first-class DAG node instead of a side effect inside the renderer.**

```
INTERFACE          bin/ytb CLI · listener.py (Telegram) · notify/telegram.py
                        │
APPLICATION        orchestrator/  (batch_cli/, queue_manager, preflight, ideation_cmd)
                   pipeline.run_project  →  project/workflow.WorkflowGraph + CheckpointManager
                        │
   ┌────────────┬───────┴────────┬──────────────┬───────────────┐
   ▼            ▼                ▼              ▼               ▼
IDEATION    NARRATION      *SCENE PLAN*    *ASSET GEN*      PUBLISH
(xKiro)     (xKiro TTS)     [GAP]          (ComfyUI/         (YouTube,
 + 3 QA      + timing        implicit in     catalog)          Drive)
 layers      probe           renderers      partly in
                                            render/story.py
                                 │
                                 ▼
                          *TIMELINE MODEL*  [GAP — implicit inside
                                             render/story.py &
                                             render/compose_ai.py]
                                 │
                                 ▼
                      DETERMINISTIC RENDERER (FFmpeg)
                      story.py | compose_ai.py | compose.py

DOMAIN   pkg/models.py (frozen: Segment, Script, Voiceover, RenderedVideo,
         ContentStrategy, HookPlan, ThumbnailBrief, ComplianceCheck)
         project/models.py (Project, WorkflowNode, NodeStatus)
         content_profiles.py (ContentProfile & friends)
```

**Components that already exist and need no redesign:** provider registry (`providers/registry.py` — six typed registries plus a separate `story_image_registry`, correctly noting that identity-anchored generation has a different port shape than `ImageProvider.generate`), checkpoint/DAG (`project/workflow.py`, `project/checkpoint.py`), stale-node reset (`pipeline._reset_stale_nodes`), profile version snapshots, the release-manifest hash chain in `publish_fn`.

**Real architectural gaps, in priority order:**

1. **No Timeline model.** `render/story.py` (~500 lines) and `render/compose_ai.py` (~577 lines, already flagged in `CLAUDE.md` as a >400-line violation) build FFmpeg graphs directly from `Voiceover.segments`. The 2026-08-26 caption-card incident (`docs/handoffs/2026-08-26-story-renderer-caption-transition-fix-handoff.md`: 393.9s audio → 338.8s video, 55s / 14% of narration lost because 162 caption cards were each crossfaded instead of 20 sections) is *exactly* the class of bug an explicit, assertable timeline prevents. This is the single strongest evidence-backed argument for the prompt's §22.
2. **No Scene Plan.** Visual granularity is a hardcoded constant, not a directorial decision.
3. **No asset registry for generated assets** (only a content-hash file cache; no seed/prompt/model/duration record → §29 reproducibility is unmet for ComfyUI output).
4. **No audio layer beyond narration.** No music, no SFX, no ducking. `voiceover/tts.py:636` applies `loudnorm=I=-16:TP=-1.5:LRA=11` to narration only.
5. **No subtitle file output.** Grep found zero `.srt`/`.vtt` generation. Captions are burned-in via Pillow (`render/story.py::_story_frame`, `render/compose_ai.py`). §20 of the prompt is entirely unimplemented.
6. **Four registered agents are never invoked** by any production path.

---

## E. Agent boundaries

**Implemented and load-bearing:**

| Agent | Input | Output | Why it exists | Status |
|---|---|---|---|---|
| Script generation (not a class — it's `ideation_cmd._cmd_start_local` + `ideation_prompts` + xKiro) | profile prompts, ledger, funnel context, analytics feedback, optional Long-source excerpt | full script JSON conforming to `generation_schema` | The only LLM creative act in the system | **Live** |
| `agents/qa_agent.QAAgent` | `Script`, `strict` | pass/fail + violations | Free deterministic Vietnamese content heuristics; runs on every attempt and again in `pipeline.input_fn` as defence-in-depth | **Live** |
| `agents/editorial_review_agent.run_editorial_review` | profile + raw payload + `LLMProvider` | 5-dim 0–10 scores, blocking findings, repair brief; cached by `(profile_fingerprint, script hash)` | Semantic judgments keywords can't express; **opt-in** per profile | **Live** (both profiles enable it, `minimum_score: 9`) |
| `ideation/script_contract.validate_script_payload` | raw payload | shape findings | Schema/purpose-vocabulary/cast shape; unconditional, non-opt-out | **Live** |

**Registered but dead:** `ResearchAgent`, `StoryArchitectAgent`, `VoiceDirectorAgent`, `SEOAgent` (`agents/__init__.py:11-14`). `StoryArchitectAgent` even degrades to `_placeholder_outline()` when the provider is unavailable — a pattern that would be wrong for a gate but is harmless because nothing calls it.

**Judgement vs the prompt's §34 agent list:**

- **Agree:** a real **DirectorAgent** is the highest-value new agent — but it should output a *scene plan schema*, and much of it should be **deterministic**, not LLM. Choosing "this 24-second section needs 4 shots" is arithmetic over narration duration + `visual_intent`; only *what the shot depicts* needs an LLM. Per §35 of the prompt itself, don't spend a model call on the arithmetic.
- **Disagree with a separate `VisualPromptAgent`:** merge it into the Director. The split creates a second prompt-governance surface for no benefit; `Segment.visual_intent` already carries the semantic payload and `visual_generation.style_prompt`/`negative_prompt` already carry the style law.
- **Disagree with a separate `StrategyAgent`:** `ContentStrategy` (`pkg/models.py:32`) is already produced inside script generation with hard validation (`format_id`, `core_mechanism`, `audience_problem`, `angle`, funnel triple, source-trace triple). Splitting it into a separate LLM call adds a round trip and a new failure mode for a field set that is already contract-enforced.
- **Disagree with a separate `ThumbnailAgent`:** `ThumbnailBrief` already comes out of the same first response with a ≤4-word headline constraint enforced in `__post_init__`. What's missing is *rendering* the brief well, which is deterministic work.
- **Agree** the four dead agents should be either wired or deleted. Recommendation: **delete `StoryArchitectAgent` and `SEOAgent`** (their responsibilities are already inside script generation + `platform/metadata.py`), **keep `ResearchAgent`** only if a real research stage is funded, and **delete `VoiceDirectorAgent`** (voice selection is now profile data: `voice_cast` + `ContentProfile.voice_for()`).
- **Add: a Shorts-derivation agent boundary.** It exists today but is scattered across `ideation_cmd.load_short_source_long_context / preassign_short_source_context / attach_preassigned_short_source_provenance` + `ideation_prompts` + `analytics/funnel.py`. It deserves one named module.

---

## F. Deterministic component boundaries

**Already correct:**

- `providers/registry.py` — name→class registries; `pipeline.py` explicitly documents "no more `if tts_provider == ...`".
- `providers/image/comfyui_story_provider.py` — single controlled ComfyUI integration point; uploads references via `/upload/image` rather than assuming a shared filesystem; polls `/history/<prompt_id>`; validates model availability via `/object_info/<node_class>` in `availability_status()`. This already satisfies most of the prompt's §17 "one controlled integration layer".
- `orchestrator/state_io.locked_json_update` — process-safe atomic JSON state (there are two batch workers; `pipeline._cleanup_after_success` explicitly refuses to delete the shared `_frames_ai` root for this reason).
- `project/checkpoint.CheckpointManager` + `project/workflow.WorkflowGraph` — write-through node state.
- `render/asset_catalog.AssetCatalog` — provenance + LRU-style reuse ranking for licensed stock.
- `orchestrator/preflight.py` — offline, side-effect-free admission.

**Should exist, doesn't:**

- **TimelineEngine** — pure function `(Voiceover, ScenePlan, ProfileRenderConfig) → Timeline`, plus an invariant assertion `sum(video track) == sum(audio track) ± ε`. This is the direct, testable antidote to the 55s-drift incident.
- **FFmpegRenderer** — `Timeline → commands`. Today FFmpeg invocation is spread across `render/story.py`, `render/compose_ai.py`, `render/compose.py`, `render/transitions.py`, `render/stock.py`, and even `pipeline.render_evidence_for` (which shells `ffprobe` from the orchestrator layer — a small layering violation).
- **AssetStore/Registry** for generated assets (see G).
- **SubtitleEngine** — nonexistent.
- **AudioMixer** — nonexistent.

---

## G. Data contracts

Only showing what's **new or changed**; existing frozen dataclasses in `pkg/models.py` stay as-is.

**Scene (new; derived from an existing `Segment`, never replacing it):**

```json
{
  "scene_id": "s003",
  "section_index": 3,
  "narration_start_sec": 41.82,
  "narration_end_sec": 63.10,
  "purpose": "evidence",
  "shots": [
    {"shot_id": "s003-a", "start_sec": 41.82, "duration_sec": 6.0,
     "visual_type": "generated_image", "motion": "slow_push_in",
     "characters": ["minh"], "visual_intent": "...",
     "asset_ref": "sha256:...", "vertical_strategy": "regenerate_vertical",
     "fallback": ["existing_asset", "text_card"]}
  ]
}
```

Note `visual_type` here should be a *closed vocabulary declared by the profile* — mirroring how `PurposePolicy.vocabulary` already works — not a global enum. `Segment.video_type` today already has `image_motion | ai_video | static_terminal`, so there's a naming collision to resolve (`Segment.video_type` vs `VideoIdea.video_type` = `short|long` are two different things with the same field name — genuine naming debt).

**VisualRequest (new; the ComfyUI decoupling boundary — see L):**

```json
{"request_id":"...","capability":"scene_image","width":832,"height":1216,
 "characters_present":["minh","an"],"prompt":"...","negative_prompt":"...",
 "seed":184920,"style_ref":"profile:ban-so-6@2.0.0","cache_key":"sha256:..."}
```

**AssetRecord (new; generalizes `asset_catalog.json` to cover generated assets):**

```json
{"asset_id":"sha256:...","asset_type":"image","path":"assets/generated_visuals/ban-so-6/....png",
 "source":"comfyui_story","provider_mode":"duo","model":"sd_xl_base_1.0.safetensors",
 "ipadapter":"ip-adapter-plus_sdxl_vit-h.safetensors","seed":184920,
 "steps":30,"cfg":6.5,"denoise":0.5,"prompt":"...","negative_prompt":"...",
 "input_refs":["identity/minh.png","identity/an.png","recognition.png"],
 "profile_fingerprint":"...","generated_at":"...","duration_ms":41230,
 "dimensions":[832,1216],"scene_ids":["s003-a"],"status":"ok"}
```

Today `render/story.py::_generation_cache_key` hashes exactly the right inputs (profile id+version, dims, sorted `scene_characters`, `visual_intent`, style/negative prompts, steps, cfg, weights, denoise — and `profile_fingerprint` transitively covers the identity reference images) but **discards the seed and every generation parameter**. You can invalidate correctly; you cannot *reproduce or explain* an image after the fact. That's the §29 gap.

**Timeline (new):**

```json
{"fps":30,"width":1920,"height":1080,
 "tracks":{"video":[{"asset_id":"...","in":0.0,"out":6.0,"motion":"push_in_1.06"}],
           "narration":[{"path":"assets/audio/....mp3","at":0.0,"duration":21.28}],
           "overlay":[{"type":"caption_card","text":"...","at":0.0,"duration":5.2}],
           "music":[], "sfx":[]},
 "transitions":[{"between":["s002","s003"],"type":"xfade","overlap":0.4}],
 "invariants":{"expected_duration_sec":393.897,"tolerance_sec":0.2}}
```

`render/story.py` already has `expected_story_duration_sec() = sum(audio) + gap×(N−1) − overlap×(N−1)`. Promote that to a Timeline invariant checked *before* encoding, not discovered after.

**Short (new, formalizing what already exists in `ContentStrategy`):** `source_long_slug`, `source_section_index`, `source_excerpt` already exist and are hard-validated (`script_contract.py:404-431` requires `source_long_slug == long_form_slug`). Add `reused_asset_ids` and `regenerated_asset_ids` when Shorts start reusing media.

**RenderJob:** currently implicit in the `render` WorkflowNode's `output_ref`/`output_data`. Fine as-is until the Timeline exists.

---

## H. Directory structure

**Existing (do not churn):** `src/ytb_pipeline/{agents,config,ideation,orchestrator,pkg,platform,project,providers,publish,render,voiceover,analytics,notify,media}`, `profiles/<id>/`, `scripts/`, `docs/constitution/`, `docs/handoffs/`, `tests/`.

**Real problem: there is no per-project workspace.** A single video's artifacts are scattered across at least six locations:

```
scripts/<slug>.json                            master script
assets/auto_state.json                         queue entry
assets/projects/<slug>/project.json            checkpoints
assets/audio/<...>.mp3                         narration segments
assets/output/<slug>.mp4, <slug>_thumb.jpg     render
assets/output/_frames_ai/<slug>/               render workspace
assets/generated_visuals/<profile_id>/         scene image cache (per-profile, not per-project)
assets/quality_reports/                        QA reports
assets/script_revisions/<slug>/                rejected/replaced drafts
```

The prompt's §30 workspace layout is directionally right, but a blind migration would break `pipeline._reset_stale_nodes`, `_cleanup_after_success`, `preflight._validate_local_assets`, `publish/drive.py`, and every existing on-disk project — and `CLAUDE.md` Pull Request Rules forbid schema breaks without a migration + compatibility loader.

**Recommendation: additive convergence, not a move.** Introduce `assets/projects/<slug>/` as the workspace root for *new* artifacts only (`research.json`, `scene_plan.json`, `timeline.json`, `assets/` symlinks or asset-id references, `logs/`), keep `project.json` where it already is, and leave narration/render/global caches where they are. Cross-project asset caches (`generated_visuals`, `asset_catalog.json`) should stay **global/per-profile deliberately** — that's what makes reuse across episodes possible, which is exactly what the prompt's "reusable media assets" goal needs. Per-project workspaces would *defeat* reuse if applied naively.

---

## I. Pipeline state machine

**Already implemented** (`project/models.py`, `pipeline.py`, `project/workflow.py`):

```
NodeStatus: pending → running → done | failed | skipped
DAG: input → voiceover → audio_quality → render → render_quality → publish
```

Resumability that already works and is better than the prompt assumes:

- `stage_names(through)` lets you run partially (`through="render"`).
- `load_or_create_project()` clears **all** nodes when `script_sha256`, `ruleset_id`, or `content_profile_fingerprint` changes, or when `ruleset_id != CONTRACT_VERSION`. Comment is explicit about why: *"otherwise old narration/render could be uploaded with new metadata."* This is a correct, strict invalidation policy.
- `_reset_stale_nodes()` re-pends: `publish` done-but-never-actually-uploaded; `render`/`voiceover` done-but-output-file-missing (unless downstream is done and can rehydrate); both QA nodes when their downstream boundary isn't done.
- `publish_fn` re-verifies the whole release manifest (script hash, ruleset, QA verdict, editorial verdict against the *current* profile bar via `validate_editorial_release_approval`) rather than trusting a historical DONE node. Genuinely good defensive design.

**Gaps vs the prompt's §31/§32:**

- **No `retrying` state and no `max_attempts`.** `WorkflowNode.retry_count` exists but no bounded-retry policy consuming it was found. `CLAUDE.md` §Workflow Rules *claims* `retry failed (tới max_attempts)` — that's doc drift.
- **No sub-node granularity.** "Image generation crashed at scene 37" (prompt §31) currently loses the whole `render` node; only the content-hash file cache in `assets/generated_visuals/` saves the earlier 36 images from being regenerated. That cache is doing checkpoint duty without checkpoint semantics.
- **`running` is not treated as `pending` on resume** in the code read, despite `CLAUDE.md` requiring it. Worth verifying in `project/workflow.py` before relying on it.

---

## J. Failure / fallback strategy

**Current, actual behaviour:**

| Failure | Today | Judgement |
|---|---|---|
| LLM (xKiro) unavailable | `_cmd_start_local` `SystemExit` with a doctor hint; **no fallback by policy** | Correct. Do not add fallback — `CLAUDE.md` forbids it, and silently swapping models changes content quality invisibly. |
| LLM returns invalid JSON | Raw response archived to `assets/script_revisions/failed_ideation/`, logged to `ideation_errors.jsonl`, **exactly one** fresh regeneration (`reserve_invalid_json_regeneration`) | Correct and bounded. |
| Script fails QA terminally | Archived, slug marked `REJECTED — do not reuse` in `generated_summaries`, `max_rejected_candidates = 1` then hard exit | Correct — deliberately refuses to burn tokens looping. |
| ComfyUI unavailable / errors | `ProviderUnavailableError` propagates; `resolve_scene_image` docstring says **fail-closed by design**, no silent substitution; write-through cache means no corrupt partial file | **Correct for `character_story`.** Substituting a different character's face is worse than failing. Do not "improve" this into the prompt's §28 cascade. |
| Bad/unwanted generated image | **No detection at all.** No semantic QC on visuals. | Real gap (prompt §27's "does the visual represent the scene"). |
| TTS failure | `validate_audio(voiceover)`; then `audio_quality` node with optional local Faster-Whisper transcript check (`quality_stt_model_path`, off by default) | Partially covered. |
| Audio content defect (`quality_status="failed"`) | Blocks render in **every** `quality_gate_mode`, with an explicit rationale comment in `enforce_checkpointed_audio_quality` | Excellent; well-reasoned. |
| Local QA tooling crash | Blocks only in `strict`; downgrades to `warning` otherwise | Correct distinction (defect vs tooling). |
| Render drift / wrong dimensions | `validate_final_video`, `render_validation_max_drift_sec = 1.0`, `_valid_clip` treats out-of-tolerance resumed clips as stale | Good, but reactive: the 55s incident passed the *segment* checks and only surfaced at the whole-file level. |
| Publish | `dry_run=True` default; `_record_continuity` failure logged but never fails an already-published video | Correct. |
| Drive backup | Failure logged, keeps local copy | Correct. |
| OOM | **Nothing.** No memory guard, no concurrency limit for ComfyUI, no VRAM/RAM budgeting. `MIN_FREE_DISK_BYTES` guards disk only. | Real gap, and it interacts with the two-worker batch design. |

**Disagreement with the prompt's §28:** the proposed cascade `generated_video → image_to_video → generated_image + camera motion` is the *right shape for a generic explainer* but is **wrong for `character_story`**, where any visual substitution risks identity/continuity breakage that a viewer notices across episodes. Fallback policy must be **profile-declared**, not engine-global — exactly like `long_opening_mode`/`short_ending_mode` already are. A `visual_generation.on_failure: "fail_closed" | "degrade"` field would fit the existing contract perfectly.

---

## K. Feasibility on the actual machine

**Caveat repeated:** the machine is documented as **MacBook Pro M4**, memory **undocumented**. Do not silently assume 24 GB. Everything below should be re-validated against the real `system_profiler` output before any commitment. There is a `ytb batch benchmark-local` command (`orchestrator/local_benchmark.py`, `batch_cli/commands.py:289`) that appears purpose-built for exactly this measurement and should be run first.

**SAFE LOCAL (proven in production here):**
- FFmpeg composition/encode (x264 `veryfast` intermediates, `medium` final) — the entire render path.
- Pillow frame/caption/thumbnail compositing.
- SDXL 1.0 base + IPAdapter-plus + CLIP-ViT-H via ComfyUI, 30 steps, 832×1216 / 1344×768 — this is *running today* for `ban-so-6`. SDXL fp16 ≈ 7 GB weights + IPAdapter/CLIP-Vision overhead; comfortable on any 24 GB-class unified-memory Mac, tight but workable on 16 GB.
- Faster-Whisper local STT for transcript QA (opt-in, `int8` on CPU is explicitly supported and validated against `float16` incompatibility in `Settings.model_post_init`).
- All state, queue, cache, checkpoint I/O.

**POSSIBLE BUT HEAVY:**
- **Flux** (`flux_checkpoint_name = "flux1-dev-fp8.safetensors"`) — fp8 Flux-dev is ~12 GB weights plus T5-XXL text encoder (~5–9 GB). Co-resident with anything else this is memory-marginal on 24 GB and infeasible alongside two concurrent batch workers. Per `CONSTITUTION_CHECKLIST.md:164`, `flux_provider.py` is a **stub never validated against a live Flux checkpoint**. Treat Flux as unproven here, not as a shipped capability.
- Parallel ComfyUI generation across the two batch workers — no coordination exists; two SDXL jobs in flight is the most likely real OOM path in this repo today.
- Long-video full-timeline re-encodes (a 6–7 min Long with 20 sections and 162 caption cards is already many hundreds of intermediate encodes).

**SHOULD USE API / OPTIONAL (and already is):**
- LLM (xKiro/DeepSeek V4 Pro) — correct call; `SCRIPT_LLM_MAX_TOKENS = 14000` for a Vietnamese Long would be painful locally and quality-critical.
- TTS (xKiro) — correct call; F5-TTS local exists (`voiceover/f5_provider.py`, `f5_daemon_pool.py`, `MAX_F5_TEMPO`, `F5_MIN_INFERENCE_CHARS = 160` because "F5 has substantial per-inference overhead") and remains an explicit opt-in.
- **Video generation (Wan2.2):** `providers/video/wan_provider.py` exists but `wan_model_path` defaults to empty. Wan 2.2 at any usable resolution/length is **not feasible** on a 24 GB unified-memory Mac for production throughput. Independent judgement: **do not pursue local text-to-video on this machine at all.** The repo's existing answer — still images plus deterministic camera motion, plus licensed B-roll clips — is the right answer and already satisfies the prompt's §6/§7. Section 6 of the master prompt is effectively *already implemented* here; it should be recorded as done, not as a target.

---

## L. ComfyUI strategy

**Where the repo already is:** `comfyui_story_provider.py` builds workflow graphs **programmatically in Python** with symbolic node keys (`"ckpt"`, `"ipaloader"`, `"ipa_first"`, `"sampler"`), not by loading and patching an exported workflow JSON with numeric node IDs. Model names come from `settings` (`comfyui_sdxl_checkpoint`, `comfyui_clip_vision_model`, `comfyui_ipadapter_model`) and are validated against `/object_info` before use. Three modes (`establishing` / `solo` / `duo`) are selected by `len(unique(characters_present))`. The module docstring documents the *failed* experiments (character-sheet references reproducing panel layouts; dual global IPAdapters and region-masked identities both leaking identity between characters) and why low-denoise img2img from an approved two-person keyframe is the only approach that held.

**That is already better than what the prompt asks for.** The prompt warns "don't couple to ComfyUI node IDs" — this code never touches node IDs. Do *not* "fix" this by moving to exported-workflow-JSON templating; that would be a regression toward the exact coupling the prompt warns about.

**What is still missing at the ComfyUI boundary:**

1. **No `VisualRequest` port.** `resolve_scene_image` (in `render/story.py` — the *render* layer) calls the provider directly with provider-shaped kwargs (`characters_present`, `solo_weight`, `duo_denoise`). A generic explainer profile wanting ComfyUI images has no path in. The registry comment acknowledges this: `story_image_registry` is deliberately separate from `image_registry` because the shapes differ. That's honest, but it means "ComfyUI" is currently a `character_story`-only capability.
2. **Seed is passed in but never recorded.** `generate_scene(..., seed=...)` — and `_generation_cache_key` doesn't include it, so the cache key is seed-independent while the output is seed-dependent. Reproduction of a specific image is currently impossible.
3. **No concurrency control, no queue depth awareness, no `/interrupt` handling.** `_POLL_ATTEMPTS = 240` × 1.5s = 6 min hard ceiling per image, serial.
4. **Capability negotiation is partial** — `availability_status()` checks three model names, which is good, but there's no version/hash pinning of the checkpoint, so "same config, different weights on disk" silently produces different output with the same cache key.

**Recommended (small, contained):** define `VisualProvider.render(VisualRequest) -> AssetRecord` as the single port; keep `comfyui_story_provider.py` as its first adapter, unchanged internally; move the `visual_asset`-vs-generate decision out of `render/story.py` into the (new) asset-generation node. This also decouples the scene-image capability from `narrative_mode == "character_story"`, which `content_profiles.py:604` currently enforces at load time.

---

## M. Long vs Short — where this repo already is, concretely

**The master prompt's core demand — "Shorts must be intelligently reconstructed from master content, never cropped" — is ALREADY IMPLEMENTED, at the script level, and enforced by code, not convention.** This is the most important thing for the user to know, because the prompt implies it's a greenfield requirement.

Concrete mechanism, end to end:

1. `ideation_cmd.load_short_source_long_context(script_path, long_slug)` reads the **Long's `scripts/<slug>.json`**, drops hook/retention/closing sections, scores the remainder by Vietnamese purpose keywords (`giải thích`+3, `dấu hiệu`+3, `cạm bẫy`+3, `bằng chứng`+2, `thực hành`+2, `ví dụ`+1…), and returns the top 3 candidates plus the Long's `evidence_register`.
2. `available_short_source_context()` removes sections already consumed by a previously generated Short in the same batch → **no two Shorts derive from the same Long section**.
3. `preassign_short_source_context()` narrows to exactly one candidate *before* the LLM call, so provenance is workflow input, not model-authored metadata.
4. The LLM writes a **completely new narration** for the Short, guided by `short_funnel_structure.md` (selected via `format_prompts.short`) — it does not copy the excerpt.
5. `attach_preassigned_short_source_provenance()` writes `source_long_slug` / `source_section_index` / `source_excerpt` back into `strategy`, and **hard-fails on any conflict** ("Source provenance mâu thuẫn").
6. `script_contract.py:404-431` requires `source_long_slug == long_form_slug`; `ContentStrategy.__post_init__` requires the funnel triple and source triple to each be complete-or-absent.
7. `ideation_cmd._validate_short_generation_request()` refuses to spend an LLM call unless `--batch-key` (prefixed `shorts_funnel_batch_`), `--long-form-slug`, `--playlist`, `--cta-target` are present and `cta_target == long_form_slug`, and the Long exists in the same batch (or is an explicitly allowed archived external Long).
8. `ideation/series.py::next_episode()` refuses to produce a Short whose parent Long hasn't published (`ready()`).
9. `analytics/funnel.py` verifies the whole funnel graph post hoc.
10. `content_rules.short_ending_mode = "funnel_bridge"` lets a Short deliberately leave the substantive answer to the Long (`ideation_prompts.py:254-263`), and `voiceover/validation.py:23` enforces that a strategy-v1 Short still gives its promised answer before swipe-off.

**Distance from the prompt's vision — precisely:**

| Prompt requirement | Status |
|---|---|
| Short rewritten, not cropped | **Done** (script level, contract-enforced) |
| One research effort → many outputs | **Partial** — the Long's *script* is the shared source; there is no separate research package to share |
| Short reuses long-form **assets** | **Not done** — Shorts render independently through `compose_ai.py`/`story.py`; there is no asset reuse from the parent Long |
| Vertical recomposition strategies (`safe_crop`/`smart_crop`/`regenerate_vertical`…) | **Not done, and not needed yet** — orientation is enforced *per video type* (`pipeline.validate_render_orientation`, `preflight._ORIENTATION_BY_VIDEO_TYPE`), and each format is generated natively. There is no cropping to fix because there is no shared media. |
| "5 Shorts from one Long" in one command | **Not done, and partly unwanted** — Shorts are generated one at a time with per-Short section pre-assignment; `ban-so-6` disables Shorts entirely |

**Independent judgement:** the prompt's §26 (`vertical_strategy`) is a solution to a problem this repo doesn't have. Because Shorts are generated natively at 1080×1920 with their own narration, **do not build a crop/recompose subsystem.** Build asset *reuse* instead (a Short whose section derives from Long section 7 should be able to reference the already-generated scene image for that section — regenerated at portrait dims via the same content-hash key, since `_generation_cache_key` already includes `dims`). That's a ~20-line change once an asset registry exists, and it delivers the real economic win (no duplicate SDXL generations) without any cropping machinery.

---

## N. MVP definition

Since the system is already in production, "MVP" must mean *the smallest increment that proves the missing architecture*, not a from-scratch build.

**Proposed MVP: an explicit Timeline for one existing renderer.**

- Extract a `Timeline` frozen dataclass + a pure `build_timeline(voiceover, profile) -> Timeline`.
- Rewrite **`render/story.py` only** (not `compose_ai.py`) to consume `Timeline`.
- Assert `abs(timeline.expected_duration_sec - probed_output_duration) <= tolerance` before *and* after encode.
- Zero behaviour change required: byte-comparable or duration-comparable output on the existing `ban-so-6` fixture.

Why this and not a scene planner or a research agent: the 2026-08-26 handoff is documented evidence that timeline drift is the failure mode that has actually cost real production output (55s / 14% of a Long, silently). It is also the prerequisite for music/SFX/subtitles/Shorts-asset-reuse. And it forces the `compose_ai.py` >400-line split that `CLAUDE.md` already mandates before new logic lands there.

**Explicit MVP non-goals:** no research agent, no scene planner, no new profile, no Flux, no Wan2.2, no subtitle files, no music.

---

## O. Implementation phases (dependency-ordered)

Narration and visual generation are already done, so the prompt's own suggested Phase 2/3 ordering is a no-op here — reordered accordingly.

- **Phase 0 — Measure and reconcile (no code).** Run `ytb batch benchmark-local`; record actual machine model + unified memory; correct `CLAUDE.md`'s hardware line if needed. Reconcile documented-vs-real retry policy (`max_attempts`, `running`→`pending`). Decide fail-closed-vs-degrade policy ownership (profile field). Complete Giai đoạn 5 of the existing refactor plan — build a **third profile from `docs/CONTENT_PROFILE_TEMPLATE.md` with zero engine code changes**; if engine changes are needed, that's the real gap list.
- **Phase 1 — Timeline model** (the MVP above). Split `compose_ai.py` as a precondition.
- **Phase 2 — Asset registry with full reproduction metadata.** Add seed/model/prompt/params/duration records; unify `asset_catalog.json` (stock) and `generated_visuals/` (generated) under one `AssetRecord` contract. Unblocks §29 reproducibility and Short asset reuse.
- **Phase 3 — `VisualRequest` port + asset-generation as a DAG node.** Moves generation out of `render/story.py`; gives per-scene checkpointing (fixes "crashed at scene 37"); decouples ComfyUI from `character_story`; adds a concurrency guard (the OOM mitigation).
- **Phase 4 — Scene plan.** Only now is it worth making shot granularity a directorial decision rather than a constant, because Phase 1–3 give it somewhere to write to and something to generate.
- **Phase 5 — Subtitles (`.srt`/`.vtt`) + audio layer (music/SFX/ducking).** Both are pure Timeline consumers; trivially additive after Phase 1, near-impossible before it.
- **Phase 6 — Short asset reuse from the parent Long** (per M). Requires Phase 2.
- **Phase 7 — Research artifact + visual semantic QC.** Lowest priority: research has no evidence of being a current quality bottleneck (the editorial rubric with `minimum_score: 9` is doing that work), and visual semantic QC costs a VLM call per image.

Each phase is independently shippable and satisfies `CLAUDE.md`'s incremental-evolution and backward-compatibility rules.

---

## P. Do NOT implement yet (scope guard)

Grouped by reason.

**Because the repo has already decided otherwise (would violate `PROJECT_VISION.md` / `CLAUDE.md`):**
1. Any local LLM (Ollama, MLX-LM, `local_stack`) or any ideation fallback to Claude/Codex.
2. Any change making Pexels *more* load-bearing. It is a **known, tracked invariant violation** (`CLAUDE.md` §Nguyên tắc 3; `settings.broll_strategy = "pexels"`, `video_provider = "pexels"`). Don't expand on it; don't pretend it's fine.
3. Changing default provider/renderer/TTS as part of any of the above phases.

**Because the prompt's generic vision doesn't fit this repo:**
4. **Vertical recomposition / smart-crop subsystem** (§26) — Shorts are natively vertical. Solves a non-problem.
5. **A blanket visual-fallback cascade** (§28) — breaks `character_story` identity guarantees. Make fallback profile-declared instead.
6. **Micro-agents** `StrategyAgent`, `VisualPromptAgent`, `ThumbnailAgent` (§34) — their outputs already come from the single script-generation call under hard contracts.
7. **Splitting `script.json`** into research/voiceover-script/visual-directions files — breaks contract validation, preflight, QA, version-snapshot replay, and the `script_sha256` release chain.
8. **Moving all artifacts into per-project workspaces** (§30) — would defeat cross-episode asset reuse and break resume/cleanup paths. Converge additively.
9. **MCP tool surface** (§36) — explicitly deferred by the prompt itself; and the CLI + Telegram surfaces already cover operator control.

**Because they're infeasible or unproven on this hardware:**
10. **Local text-to-video (Wan2.2 / LTX)** — `wan_model_path` is empty; not viable at production throughput on an M4-class unified-memory Mac.
11. **Flux as a production path** — `flux_provider.py` is a stub never validated against a live checkpoint (`CONSTITUTION_CHECKLIST.md:164`); memory-marginal.
12. **Continuous AI-generated long video** (prompt §6) — already correctly rejected in practice; nothing to build.

**Because they need a decision first:**
13. Deleting the four dead agents (`ResearchAgent`, `StoryArchitectAgent`, `VoiceDirectorAgent`, `SEOAgent`) — product decision on whether a research stage is ever funded.
14. Re-enabling Shorts for `ban-so-6` — confirmed permanent Long-only.

---

## Technical debt found while assessing (per `CLAUDE.md` Repository Evolution Rules)

| Item | Evidence | Severity |
|---|---|---|
| `render/compose_ai.py` ~577 lines, >400-line limit, explicitly flagged in `CLAUDE.md` and still unsplit | file itself | HIGH — blocks new render logic by the repo's own rule |
| Generated-image seed and generation params discarded; `_generation_cache_key` excludes seed | `render/story.py:279-296` | HIGH — §29 reproducibility unmet |
| `WorkflowNode.retry_count` exists but no bounded-retry policy; `CLAUDE.md` claims `max_attempts` exists | `project/models.py:52`, `pipeline.py` | MEDIUM — doc drift |
| Four agents registered, never invoked in any production path | `agents/__init__.py:11-14` | MEDIUM — dead code / misleading architecture |
| `Segment.video_type` (`image_motion｜ai_video｜static_terminal`) collides in name with `VideoIdea.video_type` (`short｜long`) | `pkg/models.py:77` vs `:155` | MEDIUM — naming debt, real confusion risk |
| Orchestrator shells `ffprobe` directly (`pipeline.render_evidence_for`) | `pipeline.py:121` | LOW — layering violation, belongs in the render layer |
| `profile_environment()` hardcodes `"VIDEO_PROVIDER": "pexels"` as a "compatibility capability used by doctor" for story profiles that never call VideoProvider | `content_profiles.py:773` | LOW — a lie told to `doctor`; should be a capability declaration |
| `profile_fingerprint()` appends `profile.root / "profile.json"` twice when `visual_generation` is set | `content_profiles.py:731` | LOW — harmless (hash is stable), but confusing |
| No ComfyUI concurrency guard while two batch workers run | `batch_cli/workers.py`, `comfyui_story_provider.py` | MEDIUM — most likely OOM path |
| Zero subtitle-file output despite YouTube caption value | grep: no `.srt`/`.vtt` anywhere | MEDIUM — product gap |

---

## Stop point

Per §40–42 of the master prompt: nothing implemented, nothing created, nothing modified during the assessment itself. Awaiting architectural review on, specifically: **(1)** the Phase-1 Timeline MVP scope, **(2)** whether fallback policy becomes a profile field, **(3)** the real machine/memory figure, and **(4)** whether a research artifact is funded at all or the four dead agents get deleted.

Key files for the reviewer: `CLAUDE.md`, `src/ytb_pipeline/pipeline.py`, `src/ytb_pipeline/content_profiles.py`, `src/ytb_pipeline/render/story.py`, `src/ytb_pipeline/render/compose_ai.py`, `src/ytb_pipeline/providers/image/comfyui_story_provider.py`, `src/ytb_pipeline/orchestrator/ideation_cmd.py`, `src/ytb_pipeline/project/models.py`, `docs/constitution/03-ARCHITECTURE.md`, `docs/constitution/38-EDITORIAL_QUALITY_LAYERS.md`, `docs/handoffs/2026-08-26-story-renderer-caption-transition-fix-handoff.md`, `docs/handoffs/2026-08-27-content-profile-engine-refactor-plan.md`.
