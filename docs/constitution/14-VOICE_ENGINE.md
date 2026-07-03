# 14 — VOICE ENGINE

## Purpose

Own text-to-speech synthesis end to end — provider selection, voice cloning,
prosody, Vietnamese pronunciation correctness, chunking, batching, and
resume — generalizing the project's existing `tts.py`/`f5_provider.py`/
`pronunciation.py` trio into a provider-agnostic engine with the same
local-first discipline as the rest of the stack.

## Provider Interface

```python
from typing import Protocol
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class TTSRequest:
    text: str
    voice_id: str
    pause_comma_ms: int = 150
    pause_sentence_ms: int = 400
    pause_segment_ms: int = 600
    speaking_rate: float = 1.0       # 1.0 = normal
    emphasis_words: tuple[str, ...] = ()
    reference_audio_path: str | None = None   # voice-clone reference, if applicable
    reference_text: str | None = None


@dataclass(frozen=True)
class TTSResult:
    audio_path: Path
    duration_sec: float
    provider: str
    voice_id: str
    cost_usd: float
    latency_ms: int


class VoiceProvider(Protocol):
    name: str
    is_local: bool
    supports_voice_cloning: bool

    async def synthesize(self, request: TTSRequest) -> TTSResult: ...
    async def health_check(self) -> bool: ...
```

## Supported Providers

| Provider | Type | Notes |
|---|---|---|
| **F5-TTS** | local | Vietnamese fine-tuned (`hynt/F5-TTS-Vietnamese-ViVoice`, the project's existing checkpoint). Zero-shot voice clone from a reference clip. Primary provider for the channel's anonymous narrator voice. Runs on MPS; segfaults on overly long single-pass text (existing `F5_MAX_CHARS=300` guard). |
| **Kokoro** | local | Lightweight, fast local alternative; useful for high-volume low-stakes synthesis (e.g. rapid draft-pass narration during iteration, before committing to the slower F5-TTS clone pass for final output). |
| **XTTS** | local | Multilingual voice-clone alternative to F5-TTS; candidate fallback if F5-TTS's Vietnamese checkpoint has a specific phrase/term it handles poorly. |
| **Edge-TTS** | online, free | The project's current default (`tts_provider="edge"`). No API key required, no voice cloning, coarser prosody control. Useful as a no-setup fallback and for rapid prototyping before F5-TTS voice-clone infrastructure is configured on a new machine. |
| **ElevenLabs** | cloud | Cloud fallback for highest-quality multi-voice/emotional-range needs beyond current local model capability; opt-in given per-character cost. |

Default chain: `[f5_tts_local, edge_tts_online, elevenlabs_cloud]` for the
channel's primary cloned-narrator voice; `kokoro_local` is selected
explicitly for draft/preview passes rather than sitting in the production
fallback chain, since draft and final audio should not be silently
interchangeable in the cache (different provider = different content hash,
per 09-ASSET_ENGINE, so this is enforced structurally, not just by
convention).

## Voice Cloning

```python
@dataclass(frozen=True)
class VoiceProfile:
    voice_id: str                 # e.g. "narrator_main"
    reference_audio_path: Path     # narrator.wav equivalent
    reference_text_path: Path       # narrator.txt equivalent — exact transcript of the reference clip
    provider: str                    # which VoiceProvider this profile is bound to
```

Rules carried over from the current `f5_provider.py` convention:
- Reference audio should be a single clean clip, ~6-10s, matching the
  target speaking style/energy of the narration (not the channel's average
  energy if a given video needs noticeably different pacing — a future
  multi-profile setup, below, exists for that case).
- `reference_text_path` must be the **exact** transcript of
  `reference_audio_path` — a mismatch degrades clone quality silently rather
  than erroring, so this pairing should be validated (e.g. a quick ASR
  round-trip check) whenever a new `VoiceProfile` is registered, not just
  trusted on file save.

## Prosody Control

```python
PAUSE_DEFAULTS = {
    "pause_comma_ms": 150,
    "pause_sentence_ms": 400,
    "pause_segment_ms": 600,
}
```

Voice Director (06-AGENTS) sets these per segment based on the scene's
`emotional_beat` (08-SCENE_ENGINE) — e.g. `tension` reduces all three pause
values proportionally (faster, tighter delivery), `payoff` increases
`pause_sentence_ms` before the final line of a segment for dramatic weight.
`speaking_rate` and `emphasis_words` are likewise beat-driven, but
`emphasis_words` must always be a subset of (never additions to)
`Segment.emphasis` — Voice Director directs delivery of content the script
already specified, it does not introduce new emphasis unilaterally
(06-AGENTS Voice Director responsibilities).

Provider capability varies: F5-TTS's pause control today is implemented as
explicit punctuation/silence insertion at the text-chunking layer (see
`_split_text` in `f5_provider.py`) rather than true SSML-style markup;
Edge-TTS supports SSML natively with finer control. The `TTSRequest`
interface is provider-agnostic; each adapter degrades the requested prosody
to whatever its underlying mechanism actually supports, logging a warning
when fidelity is reduced (10-LLM_ENGINE's structured-degradation pattern,
applied here).

## Vietnamese Phoneme Normalization

`pronunciation.py`'s two-layer approach is retained as-is at the engine
level, just promoted from a TTS-module-local concern to a Voice Engine-wide
preprocessing step applied to every request regardless of provider:

1. **`PRONUNCIATION` dict** — hand-verified English/brand/technical term →
   Vietnamese phonetic spelling, applied via word-boundary, case-insensitive
   substitution, multi-word phrases matched before single tokens (existing
   rule, unchanged).
2. **`OVERRIDES_FILE`** (`assets/ref/pronunciation_overrides.json`) —
   learned overrides verified via the existing ASR round-trip script
   (`scripts/verify_pronunciation.py`) and persisted permanently once
   confirmed.
3. **`transliterate_english()`** — rule-based fallback engine for terms not
   yet in either dictionary; output is provisional until verified, never
   trusted as final without the round-trip check.

This preprocessing runs **once, before provider dispatch** — `TTSRequest.text`
the engine actually sends to any provider has already been normalized;
on-screen caption text (Subtitle Agent, 06-AGENTS) uses the original
unmodified text, preserving the existing hard rule that brand names display
correctly on screen even when pronounced phonetically in audio.

## Text Chunking

```python
F5_MAX_CHARS = 300  # MPS segfault guard (existing constant, carried over)
```

Long narration is split at sentence boundaries (`.`, `!`, `?`, `…`) first;
a single sentence still exceeding the limit is further split at clause
boundaries (`,`, `;`, `:`) — never mid-word, never exceeding `max_chars`
under any circumstance (existing `_split_text` invariant, generalized to a
per-provider configurable ceiling rather than a single hardcoded constant,
since Kokoro/XTTS/Edge-TTS may have different — or no — equivalent limits).

## Multi-Voice Support (Future)

Not implemented today; the data model anticipates it:

```python
@dataclass(frozen=True)
class VoiceCast:
    """Maps narrative roles to VoiceProfiles for multi-character content."""

    profiles: dict[str, VoiceProfile]   # role name -> profile, e.g. {"narrator": ..., "character_a": ...}
```

Scene Engine's `Scene.characters` (08-SCENE_ENGINE) becomes the lookup key
into `VoiceCast` once a scene needs more than the anonymous single-narrator
voice — Voice Director resolves which `VoiceProfile` to use per segment
based on which character (if any) is "speaking" in that scene, defaulting to
the narrator profile when `characters` is empty, exactly matching today's
always-narrator behavior as the zero-character-cast special case.

## Batch Inference

The existing `f5_batch_worker.py` pattern — load the 5.4GB F5-TTS checkpoint
**once** per video (not once per segment), process every segment's job in
the same process via a JSON manifest, emit `JOB i/n ok <path>` progress
lines — is the canonical batching strategy and is retained unchanged at the
engine level:

```python
class F5BatchProvider(VoiceProvider):
    """Wraps the existing scripts/f5_batch_worker.py subprocess pattern
    behind the VoiceProvider interface — one manifest, one model load,
    many jobs."""

    name = "f5_tts_local"
    is_local = True
    supports_voice_cloning = True

    async def synthesize_batch(self, requests: tuple[TTSRequest, ...]) -> tuple[TTSResult, ...]:
        # 1. build manifest JSON (model/ckpt/vocab/device/ref_audio/ref_text/jobs)
        # 2. subprocess.run against .venv-tts/bin/python scripts/f5_batch_worker.py
        # 3. parse "JOB i/n ok <out>" / "JOB i/n skip (đã có) <out>" lines for progress
        # 4. probe each output's actual duration, build TTSResult per job
        ...
```

This is the one place in the Voice Engine where a single-request
`synthesize()` call is intentionally **not** the primary interface —
`VoiceProvider` should expose an optional `synthesize_batch()` for providers
where cold-start cost dominates, with the Voice Engine's dispatcher
preferring the batch path whenever the provider supports it and more than
one segment needs synthesis in the same run.

## Resume

Segments with a valid existing audio file are skipped on re-run — this is
the project's existing `tts.py::synthesize()` behavior
(`_probe_duration_or_zero(seg_path)` check before calling the provider) and
`f5_batch_worker.py`'s own manifest-level resume (`JOB i/n skip (đã có)`).
At the Engine level this becomes the standard Asset Engine cache-hit path
(09-ASSET_ENGINE) once `TTSRequest` is wrapped in `AssetSpec` — the same
mechanism that gives image/video caching also gives voice resume, rather
than voice having its own bespoke file-existence check as it does today.
Crucially, migrating to content-hash caching **fixes a latent bug**: today,
changing `script.voice` for an already-rendered slug does not invalidate
cached segment audio (the cache key is slug+index, not text+voice+provider);
content-hash addressing closes this gap by construction.

## Current State

- `voiceover/tts.py` — dispatcher selecting between `edge` (default,
  `edge_tts` library, online/free) and `f5` (local voice-clone) via
  `settings.tts_provider`. Edge path synthesizes per-segment sequentially
  with file-existence-based resume; F5 path delegates the whole script to
  `_synth_all_f5` for one-load batch processing.
- `voiceover/f5_provider.py` — F5-TTS adapter: builds the manifest, invokes
  `scripts/f5_batch_worker.py` in `.venv-tts` (separate Python 3.12
  environment, since F5-TTS/torch don't yet support the main pipeline's
  Python 3.14), handles the 300-char chunking guard.
- `voiceover/pronunciation.py` — the two-layer phoneme normalization
  described above, already implemented essentially as specified.
- `scripts/f5_batch_worker.py` — the batch worker process; already
  implements load-once-process-many and job-level resume exactly as
  described above.
- `scripts/verify_pronunciation.py` — the ASR round-trip verification tool
  for promoting provisional transliterations into permanent overrides.

This is the **most mature engine relative to its target spec** of any
engine in this document — the migration here is primarily about
interface extraction (wrap existing working code behind `VoiceProvider`),
not new capability development.

## Migration Notes

1. **Wrap before rewriting.** `EdgeTTSProvider` and `F5BatchProvider` should
   be thin adapters around the existing `tts.py`/`f5_provider.py`/
   `f5_batch_worker.py` code, preserving every existing behavior (chunking,
   resume, manifest format) — this is the lowest-risk migration of any
   engine in this document precisely because the underlying logic is
   already correct and battle-tested.
2. **Hoist pronunciation normalization to the engine boundary** so it runs
   identically regardless of which provider is selected, rather than being
   called only from the F5/edge-specific code paths as today (verify both
   current call sites actually invoke it identically before hoisting —
   if `tts.py`'s edge path and `f5_provider.py`'s path don't call
   `pronunciation.py` symmetrically today, that asymmetry should be fixed
   as part of, not incidental to, this migration).
3. **Replace the slug+index resume key with content-hash** once
   09-ASSET_ENGINE's registry exists — this is the fix for the voice-change
   cache-invalidation gap noted above, and should land as its own
   reviewable change, not silently bundled into the provider-wrapping work.
4. **Add Kokoro/XTTS adapters opportunistically** — neither is required for
   feature parity with today's pipeline (which only has edge + F5); they
   are additions that expand provider choice once the `VoiceProvider`
   interface is stable, not blocking work.
5. **Multi-voice (`VoiceCast`) waits on Scene Engine** — do not build
   multi-character voice casting ahead of `Scene.characters`
   (08-SCENE_ENGINE) landing; there is no consumer for it until then.
