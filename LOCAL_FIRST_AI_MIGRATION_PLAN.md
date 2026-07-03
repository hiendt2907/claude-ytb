# Local-First AI Migration Plan

## Goal

Replace cloud-dependent AI stages with local-first providers while preserving the
existing YouTube pipeline contract:

- Replace Claude for ideation, SEO, QA, and script JSON generation.
- Replace Pexels as the default visual/B-roll source.
- Add or benchmark local Vietnamese TTS alternatives to F5-TTS.
- Keep voice and video synchronized by making audio the master timeline.
- Support flexible video types and platform-specific publishing.
- Keep YouTube/TikTok/Instagram/Facebook publishing behind provider adapters.

Publishing still requires each platform's API because uploading to social
platforms is inherently network-bound. The target is to remove cloud AI
dependency from ideation, voice, image, and video generation.

## Target Stack

| Capability | Local-first choice | Notes |
|---|---|---|
| LLM/script/SEO/QA | Ollama + Qwen3 | Default local LLM provider. |
| Coding/script JSON helper | Qwen Coder / DeepSeek Coder via Ollama | Optional provider for structured generation. |
| Vietnamese TTS | VieNeu-TTS-v2, viXTTS, F5-TTS fallback | Benchmark before changing default. |
| Image generation | ComfyUI + Flux | Default visual provider for segment images. |
| Video generation | Wan2.2 or LTX-Video | Use selectively for hook/high-impact scenes. |
| Timeline/render | ffmpeg/Pillow | Deterministic composition remains local. |
| Publishing | YouTube/TikTok/Instagram/Facebook adapters | Network/API stage only. |

## Architecture Principles

- Keep the existing provider registry pattern.
- Add providers instead of rewriting the pipeline.
- Keep `pkg/models.py` dataclasses frozen and enrich via `dataclasses.replace()`.
- Make audio the source of truth for timeline duration.
- Never silently fall back to cloud/stock providers.
- Cache generated assets by content hash.
- Keep Pexels only as an explicit opt-in fallback.
- Validate every boundary: script JSON, TTS output, generated media, final render,
  and publish result.

## Phase 0 - Baseline And Local Environment

Objectives:

- Add a local-mode configuration profile.
- Verify all local dependencies before running production jobs.
- Benchmark machine capacity before changing defaults.

Implementation:

- Add config fields as needed:
  - `llm_provider=ollama`
  - `tts_provider=vieneu` or `vixtts`
  - `image_provider=flux`
  - `video_provider=wan`
  - `broll_strategy=local_image_motion`
- Add `ytb doctor local` or extend the existing doctor command to check:
  - Ollama running and model available
  - ComfyUI running and Flux workflow usable
  - TTS model installed and can synthesize one Vietnamese sentence
  - Wan/LTX model path exists if enabled
  - ffmpeg/ffprobe available
  - disk space and output dirs
- Record benchmark numbers:
  - one script generation
  - one minute of Vietnamese TTS
  - one Flux image
  - one 5-second local video clip

Definition of done:

- A local doctor command reports readiness clearly.
- Missing model/service fails fast with actionable messages.
- No production behavior changes yet.

## Phase 1 - Replace Claude For Ideation

Objectives:

- Make `ytb batch start` use local LLM by default.
- Generate valid `scripts/<slug>.json` without Claude CLI.
- Preserve existing queue and ledger behavior.

Implementation:

- Route ideation through `LLMProvider` instead of `claude -p`.
- Use Ollama/Qwen3 to:
  - select topic while reading `data/ledger.md`
  - write script JSON matching the current schema
  - generate compliance block
  - generate title, description, tags, and per-segment fields
- Add a QA repair loop:
  - run `load_script()`
  - run `QAAgent`
  - if fail, ask local LLM to repair only the failing parts
  - retry a bounded number of times
- Keep `ytb batch start --cloud` or equivalent as an explicit escape hatch if
  needed, but not as the default.

Files likely involved:

- `src/ytb_pipeline/orchestrator/ideation_cmd.py`
- `src/ytb_pipeline/providers/llm/`
- `src/ytb_pipeline/agents/`
- `src/ytb_pipeline/ideation/generator.py`

Definition of done:

- `ytb batch start -n 1 --local` writes one valid script.
- Script passes `load_script()`.
- Queue and ledger are updated exactly as before.
- No Claude CLI call is required.

## Phase 2 - Local Vietnamese TTS Benchmark And Provider

Objectives:

- Compare F5-TTS against local Vietnamese alternatives.
- Add at least one new TTS provider.
- Pick default based on evidence, not assumption.

Candidates:

- VieNeu-TTS-v2
- viXTTS
- Existing F5-TTS

Benchmark criteria:

- Vietnamese tone accuracy
- punctuation/prosody handling
- voice cloning quality if reference audio is used
- long-form stability
- inference speed
- memory usage
- failure rate over a full script

Implementation:

- Add `VieNeuTTSProvider`.
- Add `ViXTTSProvider` if practical.
- Create a repeatable benchmark script with fixed Vietnamese test passages.
- Keep per-segment audio output and duration probing unchanged.

Files likely involved:

- `src/ytb_pipeline/providers/voice/`
- `src/ytb_pipeline/voiceover/tts.py`
- `assets/ref/`
- `tests/test_*tts*`

Definition of done:

- At least one non-F5 local Vietnamese TTS provider works end to end.
- Benchmark results are saved.
- `Script -> Voiceover` remains local and produces valid segment durations.

## Phase 3 - Replace Pexels With Local Image Motion

Objectives:

- Make local image generation the default visual path.
- Use Flux images plus deterministic motion instead of stock B-roll.
- Keep render stable and reasonably fast.

Implementation:

- Add `broll_strategy`:
  - `local_image_motion` default
  - `local_video`
  - `pexels` explicit opt-in only
- For each segment:
  - generate a `visual_prompt`
  - generate one Flux image
  - animate it with Ken Burns/pan/zoom for exactly `seg.duration_sec`
  - overlay emphasis/caption/terminal elements as currently supported
- Cache by prompt hash and dimensions.
- Add validation that generated image exists and is readable.

Files likely involved:

- `src/ytb_pipeline/render/compose_ai.py`
- `src/ytb_pipeline/providers/image/flux_provider.py`
- `src/ytb_pipeline/providers/registry.py`
- `src/ytb_pipeline/config/settings.py`

Definition of done:

- `RENDER_PROVIDER=ai` no longer requires `PEXELS_API_KEY` by default.
- A full video can render with local Flux images and ffmpeg motion.
- Pexels is only used when explicitly configured.

## Phase 4 - Selective Local AI Video

Objectives:

- Add true local video generation without making it mandatory for every segment.
- Use generated video only where it adds value.

Implementation:

- Add segment-level `video_type`:
  - `image_motion`
  - `ai_video`
  - `static_terminal`
- Use Wan/LTX only for:
  - first hook
  - `hook=true`
  - high-emphasis segments
  - major transitions
- If local video generation fails or exceeds timeout, fallback to
  `image_motion` with a clear warning.
- Cache video clips by prompt hash, dimensions, duration, and model.

Files likely involved:

- `src/ytb_pipeline/providers/video/wan_provider.py`
- `src/ytb_pipeline/providers/video/`
- `src/ytb_pipeline/render/compose_ai.py`

Definition of done:

- Mixed render works: some segments use generated video, others use image motion.
- No silent Pexels fallback.
- Render remains deterministic after assets are generated.

## Phase 5 - Voice/Video Sync Validation

Objectives:

- Guarantee video duration follows voice duration.
- Detect bad audio/video outputs before upload.

Implementation:

- Treat audio as master timeline.
- For each segment:
  - synthesize audio
  - probe `duration_sec`
  - generate/trim visual to exact duration
- Add final render validator:
  - video file exists
  - audio stream exists
  - resolution matches platform
  - duration drift is under threshold
  - no zero-duration segment
- If composition fails validation, retry render composition without rerunning
  LLM/TTS/visual generation.

Files likely involved:

- `src/ytb_pipeline/voiceover/tts.py`
- `src/ytb_pipeline/render/compose_ai.py`
- `src/ytb_pipeline/render/transitions.py`
- new render validation module

Definition of done:

- Bad renders fail before publish.
- Re-render can reuse existing script/audio/visual assets.
- Long and short videos keep audio/video alignment.

## Phase 6 - Multi-Platform Publish

Objectives:

- Let the same rendered asset or derived variants publish to multiple platforms.
- Keep platform constraints isolated in platform profiles and publish providers.

Implementation:

- Extend platform profiles:
  - `youtube_long`
  - `youtube_short`
  - `tiktok`
  - `instagram_reel`
  - `facebook_reel`
- Each platform defines:
  - dimensions
  - duration limits
  - title/description/tag rules
  - schedule capability
  - publish adapter
- Keep YouTube scheduling through `publishAt`.
- Add TikTok/Instagram/Facebook providers where credentials/API approval exist.
- If direct API is unavailable, produce an export package and manual publish queue.

Files likely involved:

- `src/ytb_pipeline/platform/profiles.py`
- `src/ytb_pipeline/platform/metadata.py`
- `src/ytb_pipeline/providers/publish/`
- `src/ytb_pipeline/publish/`

Definition of done:

- A job can target one or more platforms.
- Metadata adapts per platform.
- YouTube can upload and schedule automatically.
- Other platforms either publish through API or produce a clear manual export.

## Phase 7 - Project.json And Real Resume

Objectives:

- Move from `auto_state.json + ledger` toward `project.json` as canonical state.
- Resume correctly after process interruption.

Implementation:

- Persist rich outputs per node:
  - script
  - voiceover segment audio paths and durations
  - visual asset paths
  - rendered video path
  - publish result
- Rehydrate `Voiceover` and `RenderedVideo` from checkpoint output refs.
- Retain `ledger.md` for human-readable audit/history during migration.
- Keep backward compatibility with existing `scripts/*.json`.

Files likely involved:

- `src/ytb_pipeline/project/`
- `src/ytb_pipeline/pipeline.py`
- `src/ytb_pipeline/orchestrator/pipeline_runner.py`

Definition of done:

- Killing the process mid-run does not require recomputing completed nodes.
- Resume from voiceover/render/publish works in a fresh Python process.
- `auto_state.json` can eventually be deprecated.

## Overall Definition Of Done

- `ytb batch start -n 1 --local` creates a valid script without Claude.
- `ytb batch run` can produce a full video without Pexels or cloud TTS.
- Voice and visual timeline are synchronized per segment.
- Video type can be selected:
  - `image_motion`
  - `ai_video`
  - `mixed`
- Platform can be selected:
  - `youtube_long`
  - `youtube_short`
  - `tiktok`
  - `instagram_reel`
  - `facebook_reel`
- YouTube upload and scheduling continue to work.
- Pexels and cloud AI providers are explicit opt-in fallbacks only.

## Recommended Implementation Order

1. Phase 0 - Local doctor and benchmark.
2. Phase 1 - Local LLM ideation.
3. Phase 2 - TTS provider benchmark and integration.
4. Phase 3 - Local image-motion render replacing Pexels default.
5. Phase 5 - Render validation and sync hardening.
6. Phase 4 - Selective local AI video.
7. Phase 6 - Multi-platform publish.
8. Phase 7 - Full project/checkpoint migration.

The fastest path to practical local-first production is Phase 0 through Phase 3.
After those are complete, the system is no longer dependent on Claude, Pexels,
or cloud TTS for normal video production.
