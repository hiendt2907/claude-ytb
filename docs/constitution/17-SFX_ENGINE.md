# 17 — SFX Engine

> Status: **PARTIALLY IMPLEMENTED (ad hoc).** A single hard-coded SFX
> (`whoosh`) exists today in `src/ytb_pipeline/render/transitions.py`. This
> document specifies the generalized SFX engine that path should migrate to.

## 1. Purpose

Sound effects are discrete, event-triggered audio cues — distinct from
background music (`16-MUSIC_ENGINE.md`), which is continuous and mood-driven.
SFX reinforce visual events: a transition cut, an emphasis callout, a
terminal "danger" card appearing. They are short (typically <1s), numerous
(many trigger types), and must stay perfectly in sync with the visual event
they accompany.

## 2. Current Implementation (Baseline)

`src/ytb_pipeline/render/transitions.py` today:

```python
XFADE_SEC = 0.4
SFX_DIR = Path("assets/sfx")
WHOOSH = SFX_DIR / "whoosh.wav"

def whoosh_sfx() -> Path:
    """Generates (once, cached) a whoosh via an FFmpeg lavfi noise sweep —
    no external asset dependency."""
    ...

def concat_with_transitions(clips, whoosh_before, out, *, xfade=XFADE_SEC) -> None:
    """Concatenates clips with xfade; mixes whoosh at boundaries where
    whoosh_before[k] is True, via `adelay` + `amix` in the same
    filter_complex as the video xfade chain."""
    ...
```

This works for exactly one trigger (`Segment.transition`) mapped to exactly
one effect (`whoosh`). It is not a general SFX engine: the trigger and the
effect are hard-coded together, and there is no library, no provider
abstraction, and no timing model independent of clip-boundary concatenation.

## 3. Responsibilities (Target Engine)

- Maintain a library of named SFX clips, organized by `SFXType`.
- Map domain triggers (segment flags, caption events, scene cuts) to SFX
  names via a declarative trigger table — never inline `if seg.transition:`
  branching scattered through render code.
- Resolve SFX from a provider (local library is default; cloud APIs are
  opt-in), exactly like Music and Voice providers.
- Place each resolved SFX at the correct timestamp in the assembled timeline.
- Normalize loudness across all SFX so no single effect overpowers others or
  the narration.

## 4. Provider Interface

```python
"""src/ytb_pipeline/sfx/provider.py (planned)."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from .models import SFXRequest, SFXClip


class SFXProvider(Protocol):
    name: str  # "library" | "elevenlabs_sfx" | "freesound"

    def is_available(self) -> bool: ...

    def resolve(self, request: SFXRequest) -> SFXClip:
        """Return a concrete audio clip for the requested SFXType. Local
        library providers do a tagged lookup; cloud providers may generate
        on demand (ElevenLabs SFX) — both return the same SFXClip shape."""
        ...
```

## 5. Data Model

```python
"""src/ytb_pipeline/sfx/models.py (planned)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class SFXType(str, Enum):
    WHOOSH = "whoosh"
    POP = "pop"
    CLICK = "click"
    DING = "ding"
    TRANSITION = "transition"   # generic scene-cut cue, distinct from whoosh
    AMBIENT = "ambient"          # low-level continuous texture, not a one-shot


class SFXTrigger(str, Enum):
    """Named, declarative trigger sources — what in the domain model causes
    an SFX to fire. Kept separate from SFXType so the mapping is data, not
    code branches."""

    SEGMENT_TRANSITION = "segment_transition"   # Segment.transition == True
    EMPHASIS_CHIP = "emphasis_chip"              # Segment.emphasis non-empty
    DANGER_CARD = "danger_card"                  # Segment.danger == True
    SCENE_CUT = "scene_cut"                      # any clip boundary, no flag


@dataclass(frozen=True)
class SFXRequest:
    sfx_type: SFXType
    trigger: SFXTrigger


@dataclass(frozen=True)
class SFXClip:
    audio_path: Path
    duration_sec: float
    sfx_type: SFXType
    provider: str


@dataclass(frozen=True)
class SFXCue:
    """A resolved SFX placed at an exact point on the assembled timeline —
    the unit the Render Engine actually mixes in."""

    clip: SFXClip
    at_ms: int            # absolute offset on the final timeline
    volume_db: float = 0.0  # relative gain after normalization
```

## 6. Trigger Mapping (Declarative)

```python
"""src/ytb_pipeline/sfx/trigger_map.py (planned)."""

TRIGGER_MAP: dict[SFXTrigger, SFXType] = {
    SFXTrigger.SEGMENT_TRANSITION: SFXType.WHOOSH,
    SFXTrigger.EMPHASIS_CHIP: SFXType.POP,
    SFXTrigger.DANGER_CARD: SFXType.DING,
    SFXTrigger.SCENE_CUT: SFXType.TRANSITION,
}


def triggers_for_segment(seg: "Segment", *, is_boundary: bool) -> list[SFXTrigger]:
    """Pure function: Segment + boundary flag -> list of triggers that fire.
    Replaces the inline `whoosh_before[k]` boolean threaded through
    `transitions.py` today with an explicit, testable mapping."""
    triggers: list[SFXTrigger] = []
    if is_boundary and seg.transition:
        triggers.append(SFXTrigger.SEGMENT_TRANSITION)
    if seg.emphasis:
        triggers.append(SFXTrigger.EMPHASIS_CHIP)
    if seg.danger:
        triggers.append(SFXTrigger.DANGER_CARD)
    return triggers
```

## 7. Supported Providers

| Provider | Mode | Notes |
|---|---|---|
| **Local library** | Default | `assets/sfx/` indexed by `SFXType`; today's `whoosh.wav` generation becomes one entry in this library instead of a special case. |
| **ElevenLabs SFX** | Cloud, opt-in | Used when the local library lacks a requested `SFXType` variant; gated by API key setting, same opt-in pattern as `elevenlabs_api_key` already in `Settings`. |
| **FreeSound API** | Cloud, opt-in | Broader catalog for one-off/rare SFX types not worth curating locally. |

## 8. Timing Sync

SFX must align to the **visual** transition frame, not an approximate
offset. The current `concat_with_transitions` already computes this
correctly for whoosh — `boundary_t[k]` is the exact xfade offset — the
target engine generalizes that computation into a reusable timing function
independent of any specific SFX:

```python
"""src/ytb_pipeline/sfx/timing.py (planned)."""

def cue_at_boundary(boundary_ms: int, clip: SFXClip, trigger: SFXTrigger) -> SFXCue:
    """SCENE_CUT/SEGMENT_TRANSITION cues anchor to the xfade midpoint so the
    sound peaks exactly as the visual cut completes (matches current
    `adelay={delay_ms}` placement in transitions.py)."""
    return SFXCue(clip=clip, at_ms=boundary_ms)


def cue_at_emphasis(word_start_ms: int, clip: SFXClip) -> SFXCue:
    """EMPHASIS_CHIP cues anchor to the word's on-screen appearance time —
    requires either segment-relative timing or Whisper word timestamps
    (18-SUBTITLE_ENGINE.md) for sub-segment precision."""
    return SFXCue(clip=clip, at_ms=word_start_ms)
```

## 9. Volume Normalization

All library SFX are normalized to a common target loudness at ingest time
(not at render time), so no per-render LUFS analysis is needed on the hot
path:

```python
"""src/ytb_pipeline/sfx/normalize.py (planned)."""

TARGET_LUFS = -18.0  # quieter than narration (~-16 LUFS typical TTS output)

def normalize_clip(src: Path, dst: Path) -> None:
    """ffmpeg loudnorm filter, two-pass, run once when a clip enters the
    library — not on every render."""
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(src), "-af",
         f"loudnorm=I={TARGET_LUFS}:TP=-1.5:LRA=11", str(dst)],
        capture_output=True, check=True,
    )
```

## 10. Migration Plan

1. **Extract `whoosh_sfx()` into the library provider** — move generation
   logic from `transitions.py` into `sfx/providers/local_library.py`, keep
   the lavfi-generated whoosh as the seed asset for `SFXType.WHOOSH`.
2. **Introduce `SFXCue`/`SFXRequest`/`trigger_map`** — replace the
   `whoosh_before: list[bool]` parameter on `concat_with_transitions` with a
   list of resolved `SFXCue`s computed by `triggers_for_segment`.
3. **Generalize the `amix` mixing code** in `transitions.py` (currently
   whoosh-specific `adelay` + `amix` block) to accept an arbitrary list of
   `SFXCue`s rather than one SFX type.
4. **Add `pop`/`ding`/`click` library assets** for `EMPHASIS_CHIP` and
   `DANGER_CARD` triggers, which currently produce no audio cue at all.
5. **Wire normalization** into library ingest so future assets (including
   cloud-resolved ones cached locally) share one loudness target.
6. **Render Engine integration** — once Timeline-based assembly lands
   (`19-RENDER_ENGINE.md`), SFX cues become first-class timeline overlays
   instead of being threaded through clip-concat parameters.
</content>
