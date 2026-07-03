# 16 — Music Engine

> Status: **NOT IMPLEMENTED.** No background-music selection, generation, or
> mixing exists in `src/ytb_pipeline/` today. `assets/music/` exists as a
> directory but is currently empty/unused by any render code path.

## 1. Purpose

Background music sets tone and pacing without competing with narration. It
is a distinct concern from SFX (`17-SFX_ENGINE.md`): music is continuous,
mood-driven, and topic-scoped, where SFX is discrete, event-triggered, and
transition-scoped. Per `PROJECT_VISION.md` non-negotiable #2 (local inference
priority) and #3 (no stock-as-default), local music generation must be the
default path — a royalty-free library is an acceptable fallback, but cloud
generation (Suno) is opt-in only.

## 2. Responsibilities

- Select a music mood for a video from its topic/tone (via the ideation
  stage's `VideoIdea`/`Script`).
- Produce or retrieve an audio track per music type (intro/background/
  transition/outro).
- Match track duration to the video's total runtime (loop or trim).
- Mix the track under narration with volume ducking so dialogue stays clear.
- Stay swappable across providers exactly like every other capability
  (`21-PROVIDER_SYSTEM.md`).

## 3. Provider Interface

```python
"""src/ytb_pipeline/music/provider.py (planned)."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from .models import MusicRequest, MusicTrack


class MusicProvider(Protocol):
    """Port for any music source: local generative model, cloud API, or a
    curated royalty-free library lookup. All three must satisfy this same
    contract so the render stage never branches on provider identity."""

    name: str  # "musicgen" | "suno" | "library"

    def is_available(self) -> bool:
        """Cheap local check (model file present / API key set / library
        indexed). Used by the local-first selection strategy to skip
        unavailable providers without raising."""
        ...

    def generate(self, request: MusicRequest) -> MusicTrack:
        """Produce or fetch a track matching `request`. Must raise a typed
        error (never return a silently-wrong track) if the mood/duration
        cannot be honored."""
        ...
```

## 4. Data Model

```python
"""src/ytb_pipeline/music/models.py (planned)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class MusicType(str, Enum):
    INTRO = "intro"
    BACKGROUND = "background"
    TRANSITION = "transition"
    OUTRO = "outro"


class Mood(str, Enum):
    CALM_FOCUS = "calm_focus"       # educational, tutorial
    TENSE = "tense"                  # drama, security incident, urgency
    UPBEAT = "upbeat"                # celebratory, success, launch
    SUSPENSE = "suspense"            # mystery, investigation
    NEUTRAL_AMBIENT = "neutral_ambient"


@dataclass(frozen=True)
class MusicRequest:
    music_type: MusicType
    mood: Mood
    target_duration_sec: float
    topic: str = ""          # raw topic string, used by mood-mapping fallback
    seed: int | None = None  # reproducibility for local generative providers


@dataclass(frozen=True)
class MusicTrack:
    audio_path: Path
    duration_sec: float
    mood: Mood
    provider: str
    loopable: bool = False   # True => safe to loop-extend without a seam
```

## 5. Supported Providers

| Provider | Mode | Notes |
|---|---|---|
| **MusicGen / AudioCraft** | Local generation | Default. Runs on MPS/Metal on M4. Generates short loops per mood, cached by `(mood, duration_bucket)` key to avoid regenerating identical requests. |
| **Suno API** | Cloud | Opt-in fallback only, per `tts_provider`-style explicit config flag (e.g. `music_provider: "suno"`). Never silently substituted when local generation is slow. |
| **Royalty-free library** | Local lookup | Curated, license-cleared tracks indexed in `assets/music/library_index.json` (planned), tagged by mood. Lowest-cost fallback when generative quality is insufficient for a given mood. |

## 6. Mood Mapping

Topic → Mood is a deterministic lookup table with an LLM-assisted fallback
for topics that don't match a keyword rule, keeping the common case fast and
free of an extra LLM round-trip:

```python
"""src/ytb_pipeline/music/mood_mapping.py (planned)."""

KEYWORD_MOOD_RULES: dict[str, Mood] = {
    "tutorial": Mood.CALM_FOCUS,
    "explained": Mood.CALM_FOCUS,
    "security": Mood.TENSE,
    "incident": Mood.TENSE,
    "breach": Mood.TENSE,
    "launch": Mood.UPBEAT,
    "review": Mood.NEUTRAL_AMBIENT,
    "mystery": Mood.SUSPENSE,
    "investigation": Mood.SUSPENSE,
}


def resolve_mood(topic: str, *, llm_fallback: bool = True) -> Mood:
    """Substring-match `topic` against KEYWORD_MOOD_RULES (case-insensitive).
    Falls back to an LLM mood-classification call only if no keyword hits —
    keeps the default path keyword-only and instant."""
    lowered = topic.lower()
    for keyword, mood in KEYWORD_MOOD_RULES.items():
        if keyword in lowered:
            return mood
    if llm_fallback:
        return _classify_mood_via_llm(topic)
    return Mood.NEUTRAL_AMBIENT
```

| Topic pattern | Mood | Typical music style |
|---|---|---|
| Educational / tutorial / explainer | `calm_focus` | Soft piano/ambient pad, low tempo |
| Security incident / drama / breach | `tense` | Sparse low strings, rising tension |
| Launch / achievement / success | `upbeat` | Bright synth, mid-high tempo |
| Investigation / mystery | `suspense` | Sparse percussion, minor key |
| Review / neutral explainer | `neutral_ambient` | Lo-fi background bed |

## 7. Duration Matching

```python
"""src/ytb_pipeline/music/duration_match.py (planned)."""

def fit_to_duration(track: MusicTrack, target_sec: float) -> Path:
    """Return a path to an audio file exactly `target_sec` long.

    - track.duration_sec >= target_sec  -> trim with fade-out in the last
      1.5s (ffmpeg atrim + afade), never a hard cut.
    - track.duration_sec < target_sec and track.loopable -> loop via
      ffmpeg `-stream_loop` then trim to exact length, with a short
      crossfade at each loop seam to avoid an audible click.
    - track.duration_sec < target_sec and NOT loopable -> raise; caller
      must request a longer generation rather than loop a non-loopable
      track (looping non-loopable material produces an audible seam).
    """
```

## 8. Volume Ducking (Sidechain)

Music must duck under narration automatically — never require manual
keyframing per video. FFmpeg's `sidechaincompress` filter is the mechanism,
keyed off the voiceover track as the trigger signal:

```python
"""src/ytb_pipeline/music/ducking.py (planned)."""

def build_ducking_filter(music_label: str, voice_label: str, out_label: str) -> str:
    """Returns an ffmpeg filter_complex fragment that compresses `music_label`
    whenever `voice_label` is active, producing `out_label`.

    Equivalent CLI shape:
      ffmpeg -i music.wav -i voice.wav -filter_complex \
        "[1:a]asplit=2[sc][voiceout];
         [0:a][sc]sidechaincompress=threshold=0.05:ratio=8:attack=20:release=250[ducked]" \
        -map "[ducked]" ...
    """
    return (
        f"[{voice_label}]asplit=2[sc][voiceout];"
        f"[{music_label}][sc]sidechaincompress="
        f"threshold=0.05:ratio=8:attack=20:release=250[{out_label}]"
    )
```

Tuning notes:
- `threshold=0.05` — ducks on essentially any voiced narration (TTS output
  has consistent levels, so a low threshold is safe and doesn't need
  per-video tuning).
- `attack=20` (ms) — fast enough that music drops before the first syllable.
- `release=250` (ms) — slow enough that music doesn't pump audibly between
  words within a sentence; recovers fully in the inter-segment pause
  (`settings.pause_segment_ms = 500`, already > release time).

## 9. Current State

**NOT IMPLEMENTED.** `assets/music/` exists as an empty directory. No
`music_provider` setting in `config/settings.py`, no `MusicProvider`
implementations, no ducking filter wired into `render/compose.py` or
`render/compose_ai.py`. Today's videos are voice-only audio.

## 10. Implementation Roadmap

1. **Settings** — add `music_provider: str = "library"` and
   `music_enabled: bool = False` to `Settings` (default off until quality is
   validated, consistent with `show_captions` defaulting off today).
2. **Royalty-free library provider first** — fastest path to a working
   feature; curate ~20 license-cleared loops tagged by `Mood`, ship
   `library_index.json`.
3. **Mood mapping** — keyword table + LLM fallback (Ollama/Qwen3, local).
4. **Duration matching + ducking filters** — pure FFmpeg, testable without
   any model dependency.
5. **Render Engine integration** — Music Engine outputs one `MusicTrack` per
   video; Render Engine's `add_music` stage (`19-RENDER_ENGINE.md`) mixes it
   under the assembled timeline's audio.
6. **MusicGen/AudioCraft local provider** — once the library path is proven,
   add local generation as the new default, demoting the library to
   fallback per non-negotiable #2.
7. **Suno cloud provider** — explicit opt-in only, gated behind an API key
   setting, never auto-selected.
</content>
