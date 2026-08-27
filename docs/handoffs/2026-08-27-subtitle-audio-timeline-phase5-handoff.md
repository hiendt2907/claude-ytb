# Phase 5 — Subtitle + Audio Timeline Layers Handoff

**Status:** complete  
**Branch:** `codex/phase4-visual-assets`

## Previous handoffs

- `2026-08-27-scene-plan-phase2-handoff.md`
- `2026-08-27-asset-registry-phase3.2-handoff.md`
- `2026-08-27-visual-assets-phase4-handoff.md`

## Objective and architecture

Phase 5 adds deterministic accessibility subtitle artifacts and explicit,
optional non-narration audio-layer representation without moving timing
authority into FFmpeg. The story chain is now:

```text
Narration -> ScenePlan -> VisualRequest -> VisualManifest -> Timeline
          -> prepared story renderer -> MP4 + SRT + VTT
```

Narration segment duration remains authoritative. Existing burned caption cards
remain a visual presentation feature; SRT/VTT are separate platform/accessibility
deliverables.

## Actual implementation

- `render/subtitle.py` adds frozen `SubtitleCue(start_sec, end_sec, text)` and
  `SubtitleTrack(language, cues)`, deterministic SRT/WebVTT serializers, and
  artifact writing.
- `build_subtitle_track(voiceover, timeline)` uses exactly one cue per measured
  `Timeline.narration_clips` slot. It exports the available Vietnamese text;
  it does not translate or invent word timestamps.
- `render/timeline.py` adds validated `AudioLayerClip` and optional
  `Timeline.music_clips`/`sfx_clips`. Their gain is constrained to -60..12 dB,
  fades are non-negative and fit inside their trim duration, and their presence
  does not alter `expected_duration_sec`.
- `render/story.py` emits `<slug>.srt` and `<slug>.vtt` beside the MP4,
  thumbnail, and timeline JSON before composition.

No current profile supplies music or SFX. Therefore the contract is present
and tested, but no music/SFX is mixed into production output. This preserves
narration-only rendering and avoids adding an unconfigured local-media source.
No new loudness normalization is introduced: the existing TTS concat `loudnorm`
remains the sole narration normalization path.

## Renderer and pipeline boundaries

No new DAG node was needed: subtitles are reusable derived artifacts built from
the already materialized Timeline at the story render boundary, not inside an
FFmpeg filter builder. The prepared visual boundary is unchanged: pipeline
still invokes `StoryRenderProvider.render_prepared()`, and subtitle generation
does not call ComfyUI or create AssetRecords. `mechanism_explainer` / `compose_ai`
were not migrated.

## Tests and cleanliness

`tests/test_subtitles.py` covers deterministic cue creation, narration timing,
ordering, positive duration, SRT, VTT, Vietnamese Unicode, multiline/special
text, invalid input, and isolated artifact paths. Timeline tests cover optional
audio validation and unchanged narration duration. Story render integration
checks `.srt` and `.vtt` are produced alongside the existing MP4.

The Phase 4 prepared-render test remains in place and continues to prove that
deleting the MP4 and disabling generation still permits a prepared rerender.
No runtime artifacts are committed.

Final verification: `make test` = **1111 passed, 3 skipped, 1 deselected,
0 failed**.

## Commits

```text
6b23559 test: define deterministic subtitle artifacts
06225b4 feat: add subtitle timeline artifacts
9aadefa test: verify story subtitle deliverables
```

## Definition of done

- [x] Deterministic subtitle contract and SRT/VTT serializers.
- [x] Subtitle timing derives from measured narration Timeline slots.
- [x] Burned captions remain independent and compatible.
- [x] Timeline represents optional music/SFX safely without changing duration.
- [x] Narration-only story rendering remains valid and emits subtitle artifacts.
- [x] No AI, translation, download, or compose_ai migration was added.
- [x] Architecture documentation and this persistent handoff exist.
- [x] Focused, integration, and full-suite verification completed.

## Deferred work / recommended next phase

Do not implement in Phase 5: profile-backed local music/SFX adoption and the
focused FFmpeg mixer it would require; automatic translation; word-level forced
alignment; music/SFX generation; visual QC; multi-shot planning; and
compose_ai Timeline migration. A next phase can add an explicit local-media
profile contract and deterministic mixer while retaining Timeline timing as
the authority.
