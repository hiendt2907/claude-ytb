# 18 — Subtitle Engine

> Status: **PARTIALLY IMPLEMENTED (baked-in, no separate track).** Word-reveal
> captions exist in `src/ytb_pipeline/render/compose.py`
> (`_reveal_steps`, `_draw_caption`, `_caption_clip`), but they are burned
> directly into video frames at render time. There is no standalone SRT/VTT
> artifact and no Whisper integration.

## 1. Purpose

Subtitles/captions serve two distinct audiences and must eventually serve
both: (1) viewers watching with sound off or who benefit from on-screen text
synced to speech, and (2) platform accessibility/SEO systems that consume a
separate caption track (YouTube `captions.insert`, TikTok auto-captions).
Today's implementation only serves audience (1), and only as pixels baked
into the video — it cannot be uploaded as a caption track, edited
independently, or reused across render strategies (slide vs B-roll vs future
stickman).

## 2. Current Implementation (Baseline)

`compose.py` today, word-reveal lower-third captions:

```python
def _reveal_steps(caption: str, duration: float) -> list[tuple[str, float]]:
    """Chia caption thành các mốc hiện dần từng từ, chia đều thời lượng."""
    words = caption.split()
    # ... even split of `duration` across word count, no real per-word timing
```

This computes a *uniform* per-word reveal interval from segment duration —
it is not derived from actual speech timing (no forced alignment, no
Whisper). It is also rendered straight into frame PNGs via `_draw_caption` +
`_caption_clip`, then muxed with FFmpeg — there is no intermediate SRT/VTT
artifact, so the captions cannot be exported, edited, or uploaded as a
YouTube caption track independent of the burned-in video.

`settings.show_captions: bool = False` — currently **off by default**; only
cold-open titles, terminal cards, and emphasis chips render unconditionally.

## 3. Responsibilities (Target Engine)

- Produce **timed** subtitle data (`SubtitleTrack`) from either:
  (a) known voiceover segment timestamps (fast, no ASR needed, accurate for
  TTS-generated audio where ground truth timing exists), or
  (b) Whisper transcription of the final mixed audio (needed only when
  ground-truth segment timing is unavailable — e.g. external/recorded
  voice).
- Export the track to SRT/VTT/ASS formats independent of rendering.
- Support multiple caption *styles* (lower-third, full-screen,
  word-highlight, karaoke) as render-time presentation choices applied to
  the same underlying timed-word data.
- Either burn the styled captions into the video (FFmpeg `subtitles` filter)
  or hand the SRT/VTT off to the Publish Engine for upload as a separate
  track.

## 4. Provider Interface

```python
"""src/ytb_pipeline/subtitle/provider.py (planned)."""

from __future__ import annotations

from typing import Protocol

from .models import SubtitleSource, SubtitleTrack


class SubtitleProvider(Protocol):
    name: str  # "segment_timing" | "whisper" | "manual"

    def is_available(self) -> bool: ...

    def transcribe(self, source: SubtitleSource) -> SubtitleTrack:
        """Produce a SubtitleTrack with word- or phrase-level timestamps.
        `segment_timing` derives timing analytically from known segment
        durations (zero ASR cost); `whisper` runs local ASR on the mixed
        audio; `manual` reads operator-edited timing from the script."""
        ...
```

## 5. Data Model

```python
"""src/ytb_pipeline/subtitle/models.py (planned)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class SubtitleFormat(str, Enum):
    SRT = "srt"
    VTT = "vtt"
    ASS = "ass"   # styled captions: karaoke/word-highlight need ASS, not SRT


class CaptionStyle(str, Enum):
    LOWER_THIRD = "lower_third"      # current compose.py default position
    FULL_SCREEN = "full_screen"
    WORD_HIGHLIGHT = "word_highlight"  # current word is bold/colored
    KARAOKE = "karaoke"                # per-syllable progressive fill


@dataclass(frozen=True)
class SubtitleSource:
    audio_path: Path
    segments: tuple["Segment", ...] = ()   # known timing, when available
    use_asr: bool = False                   # force Whisper even if segments known


@dataclass(frozen=True)
class WordTiming:
    text: str
    start_ms: int
    end_ms: int


@dataclass(frozen=True)
class SubtitleCue:
    """One displayed caption line/phrase, made of one or more WordTiming."""

    words: tuple[WordTiming, ...]
    start_ms: int
    end_ms: int


@dataclass(frozen=True)
class SubtitleTrack:
    cues: tuple[SubtitleCue, ...]
    source_provider: str   # "segment_timing" | "whisper" | "manual"
    language: str = "vi"
```

## 6. Supported Providers

| Provider | Mode | Notes |
|---|---|---|
| **Segment timing** | Default, local, zero-cost | Derives `WordTiming` analytically: split `Segment.narration` into words, distribute evenly (or proportional to word length) across `Segment.duration_sec` and `audio_path`. This is what `_reveal_steps` already does today — the migration formalizes it into a provider that emits `SubtitleTrack` instead of frame-reveal steps directly. |
| **Whisper (local ASR)** | Local, used when ground truth absent | Runs `whisper` (e.g. `faster-whisper` on MPS) against the combined voiceover audio, emits real word-level timestamps. More accurate than even-split, required once F5-TTS/Kokoro voices introduce variable-speed delivery where even-split timing drifts. |
| **Manual** | Operator-edited | Reads timing overrides from the script/`project.json` when an editor has hand-tuned caption timing. |
| **YouTube auto-CC** | Platform-side fallback | Not generated by this engine at all — YouTube generates its own captions post-upload. Documented here only because it's a competing option; never the path when this engine's output is available, since platform auto-CC quality is lower and not controllable per style. |

## 7. Subtitle Formats

- **SRT** — plain timed text, sufficient for `LOWER_THIRD` and
  `FULL_SCREEN` styles and for YouTube `captions.insert` upload.
- **VTT** — web-native equivalent of SRT, used if/when a web player (Blog
  platform target) needs `<track>` captions.
- **ASS/SSA** — required for `WORD_HIGHLIGHT` and `KARAOKE` styles, since
  per-word/per-syllable styling (color ramps, bold toggles) needs ASS's
  inline override tags — SRT/VTT cannot express sub-cue styling.

```python
"""src/ytb_pipeline/subtitle/export.py (planned)."""

def to_srt(track: SubtitleTrack) -> str:
    """One SRT block per SubtitleCue; standard `HH:MM:SS,mmm` timestamps."""
    ...

def to_ass(track: SubtitleTrack, style: CaptionStyle) -> str:
    """Emits \\k karaoke tags per word for KARAOKE, \\c color override tags
    per active word for WORD_HIGHLIGHT. Falls back to to_srt-equivalent
    plain cues for LOWER_THIRD/FULL_SCREEN (ASS still used for consistent
    font/position styling even without per-word effects)."""
    ...
```

## 8. Timing Derivation

```python
"""src/ytb_pipeline/subtitle/timing.py (planned)."""

def derive_from_segments(segments: tuple["Segment", ...]) -> SubtitleTrack:
    """Default path — zero ASR cost. For each segment, split `narration`
    into words and distribute across `duration_sec` proportional to word
    character length (better than pure even-split: short words like "là"
    get less screen time than "implementation")."""
    cues = []
    cursor_ms = 0
    for seg in segments:
        words = seg.narration.split()
        total_chars = sum(len(w) for w in words) or 1
        seg_ms = int(seg.duration_sec * 1000)
        word_timings = []
        offset = 0
        for w in words:
            share_ms = int(seg_ms * len(w) / total_chars)
            word_timings.append(WordTiming(
                text=w, start_ms=cursor_ms + offset,
                end_ms=cursor_ms + offset + share_ms,
            ))
            offset += share_ms
        cues.append(SubtitleCue(
            words=tuple(word_timings),
            start_ms=cursor_ms, end_ms=cursor_ms + seg_ms,
        ))
        cursor_ms += seg_ms
    return SubtitleTrack(cues=tuple(cues), source_provider="segment_timing")
```

## 9. Style Options

| Style | Description | Format needed |
|---|---|---|
| `lower_third` | Current default position/behavior in `compose.py` — caption block in the lower third of frame, word-reveal animation | SRT/ASS |
| `full_screen` | Large centered text, used for cold-open hooks or single-emphasis moments | SRT/ASS |
| `word_highlight` | Full caption line visible, current word bold/colored — common "podcast clip" style | ASS only |
| `karaoke` | Per-syllable progressive color fill, music-video style | ASS only |

## 10. Word-Reveal Animation (Current Behavior, Preserved)

The existing `_reveal_steps` / `_draw_caption` / `_caption_clip` behavior in
`compose.py` is preserved as the rendering implementation of
`CaptionStyle.LOWER_THIRD` — the migration does not change what viewers see
today, it separates *what is shown* (now: `SubtitleTrack`/`SubtitleCue`)
from *how it's painted* (`_draw_caption` continues to paint PNG frames, now
driven by `WordTiming` data instead of `_reveal_steps`'s uniform split).

## 11. Export Paths

```python
"""src/ytb_pipeline/subtitle/pipeline.py (planned)."""

def burn_in(video_path: Path, track: SubtitleTrack, style: CaptionStyle) -> Path:
    """FFmpeg `subtitles` filter (SRT/ASS) burned into the final encode —
    used for platforms without a separate caption-track API (TikTok,
    Instagram Reels) or when the operator wants captions un-removable."""
    ...

def export_for_upload(track: SubtitleTrack, fmt: SubtitleFormat) -> Path:
    """Writes a standalone .srt/.vtt file for Publish Engine to upload via
    `captions.insert` (YouTube) — keeps captions as an editable, removable
    track rather than baked pixels."""
    ...
```

## 12. Current State

- Caption word-reveal: **implemented**, baked into video in `compose.py`,
  gated by `settings.show_captions` (default `False`).
- Standalone SRT/VTT generation: **not implemented**.
- Whisper ASR integration: **not implemented**.
- ASS/karaoke/word-highlight styles: **not implemented**.
- YouTube caption-track upload: **not implemented** (`uploader.py` does not
  call `captions.insert`).

## 13. Migration Plan

1. **Extract `_reveal_steps` into `derive_from_segments`** — same algorithm,
   moved to `subtitle/timing.py`, returning `SubtitleTrack` instead of
   frame-reveal tuples.
2. **Adapt `_draw_caption`/`_caption_clip`** to consume `SubtitleCue`/
   `WordTiming` rather than the raw `(text, t)` tuples `_reveal_steps`
   produces today — same visual output, decoupled data source.
3. **Add SRT export** (`to_srt`) and wire an optional `subtitle_export:
   bool` setting to write `.srt` alongside the rendered video.
4. **Add Whisper provider** for cases where segment timing is unreliable
   (e.g. once F5-TTS/Kokoro variable-rate delivery is in use) — install as
   an opt-in alternate `SubtitleProvider`, selected via settings.
5. **ASS export + word_highlight/karaoke styles** — once SRT path is
   stable, add ASS export and the two styled-caption render paths.
6. **YouTube caption upload** — extend `uploader.py`'s `publish()` to call
   `captions.insert` with the exported SRT, decoupling caption delivery from
   burn-in (operator can choose burn-in, upload-track, or both per video).
</content>
