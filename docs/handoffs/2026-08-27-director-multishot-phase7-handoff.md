# Phase 7 — Director Multi-shot Handoff

**Status:** partial implementation on `codex/phase7-director`.

Phase 6 reconciliation added actual mixer-path coverage in
`tests/test_audio_mixer.py`; collection grew from 1114 selected tests after
that addition. The local-media implementation remains unchanged.

Phase 7 adds opt-in `scene_planning` policy (`legacy_single_shot` by default,
`director` available), bounded `DirectedShot` validation, and deterministic
`normalize_directed_shots`. The normalizer owns exact duration allocation;
semantic director output has only visual intent, allowed characters, and
positive weight. It rejects excessive shots, unknown characters and too-short
scene windows. Stable IDs currently follow the accepted ScenePlan ordinal.

Legacy builder and renderer remain unchanged; Director invocation/persistence
integration is deferred and no LLM runs in rendering. VisualRequest remains
shot-oriented, so normalized multi-shots can flow downstream once the planning
node is connected. No ComfyUI/provider changes, audio/subtitle changes or
compose_ai migration occurred.
