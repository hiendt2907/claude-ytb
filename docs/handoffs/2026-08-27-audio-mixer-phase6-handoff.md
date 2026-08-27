# Phase 6 — Audio Mixer Handoff

**Status:** complete. **Branch:** `codex/phase4-visual-assets`.

Previous work: Phase 2 ScenePlan, Phase 3.2 AssetRegistry, Phase 4 visual
assets, and Phase 5 subtitle/audio Timeline handoffs.

`RenderProfile.audio` is optional and frozen: one `BackgroundMusicProfile`
(`asset`, gain, fades, `loop`/`trim`) plus explicit `SoundEffectProfile`
events (asset, `at_sec`, gain, optional duration). Existing profiles without
audio remain narration-only.

Timeline derives `music_clips` and `sfx_clips` from this contract and its
authoritative narration `expected_duration_sec`. Music is trimmed or looped to
that duration; SFX is trimmed at the end and is rejected when it starts beyond
the end. These layers cannot change video/subtitle duration.

`render/audio_mixer.py` is the FFmpeg boundary: it validates local existing
audio files and streams, applies deterministic gain/fade/delay/trim, then
mixes narration exactly once using `amix=duration=first`. TTS concat loudnorm
remains the sole narration normalization. No AI, download, stock provider, or
AssetRegistry audio migration is added.

Story renderer invokes mixing only when Timeline has optional layers. SRT/VTT
stay narration-derived; prepared render still does not need ComfyUI;
mechanism_explainer/compose_ai are unchanged. The render node is deliberately
the deterministic mixing boundary—no extra checkpoint node is needed.

Verification: focused tests pass; full `make test` was rerun after Phase 6 and
all test failures were resolved. Test media/state remains isolated and no
runtime assets are committed.

Commits: `65c1705 feat: add deterministic local media audio mixer`; this
documentation commit. Deferred: local-media profile adoption fixtures,
multi-track DAW behavior, audio provenance migration, AI/download features,
translation/alignment, and compose_ai Timeline migration.

Definition of done: local profile contract, Timeline timing ownership,
deterministic mixer, duration preservation, subtitle/prepared-render/non-story
compatibility, architecture docs, and this persistent handoff are all present.
