# 19 — Render Engine

> Status: **MONOLITHIC RENDERERS (no Timeline model).** `render/compose.py`
> (slide renderer) and `render/compose_ai.py` (B-roll renderer) each
> independently implement segment-to-clip rendering, concatenation, and
> encoding. This document specifies the target Timeline-based architecture
> they should converge on.

## 1. Purpose

The Render Engine is the assembly stage of the pipeline: it takes a
`Voiceover` (segments with audio already attached) plus whatever visual
assets the active render strategy produces (slide gradients, B-roll clips,
future stickman frame sequences, future diffusion-generated clips) and
produces one final encoded video file per output profile. It is the single
point where all visual/audio/subtitle/music/SFX sources converge — every
other engine in this constitution (`15`–`18`, `16`–`17`) hands its output to
the Render Engine rather than writing video files itself.

## 2. Current Implementation (Baseline)

Two renderers exist side by side, selected via `settings.render_provider`
(`"slide" | "ai"`), each owning its full pipeline end to end:

- `compose.py::render_video()` — builds per-segment caption-card PNG frames
  (gradient background, terminal card, caption text), concatenates with
  plain `ffmpeg concat`.
- `compose_ai.py` — fetches B-roll per segment (`stock.fetch_broll`),
  overlays caption/terminal layer, concatenates via
  `transitions.concat_with_transitions()` (xfade + whoosh SFX at marked
  boundaries).

Both are **monolithic**: segment iteration, visual generation, overlay
compositing, and final encode are interleaved in one function per renderer,
with no shared intermediate representation. Adding a new visual source
(stickman, diffusion video) today means writing a third
`compose_*.py` from scratch, duplicating caption/terminal overlay code, SFX
boundary logic, and encode settings.

## 3. Target Architecture: Timeline-Based Assembly

Instead of "renderer owns everything," the target model separates **what
goes where in time** (Timeline) from **how each piece was produced**
(upstream engines: Stickman, Music, SFX, Subtitle, render-strategy visual
sources) from **how it gets encoded** (Renderer backend).

```
Voiceover (segments + audio, already rendered)
        │
        ▼
[per-segment visual source: slide | broll | stickman | diffusion]
        │
        ▼
Timeline Assembly  ──┬── add_overlays (caption cards, terminal, emphasis)
                      ├── add_subtitles (SubtitleTrack, burn-in or skip)
                      ├── add_music (MusicTrack, ducked under voice)
                      └── add_sfx (SFXCue list, mixed at boundaries)
        │
        ▼
encode_final (profile-specific FFmpeg encode)
        │
        ▼
RenderedVideo (video_path, thumbnail_path)
```

## 4. Timeline Data Model

```python
"""src/ytb_pipeline/render/timeline.py (planned)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Overlay:
    """A visual layer drawn on top of a clip — caption card, terminal card,
    emphasis chip, subtitle burn-in. Position/timing relative to the clip."""

    kind: str            # "caption" | "terminal" | "emphasis" | "subtitle"
    start_ms: int
    end_ms: int
    payload: dict        # kind-specific render data (text, color, danger flag...)


@dataclass(frozen=True)
class Clip:
    """One visual+audio unit on the timeline — the output of whatever
    render strategy produced this segment's visuals (slide PNG sequence,
    B-roll video, stickman frame sequence)."""

    clip_id: str
    segment_index: int
    video_path: Path           # pre-rendered visual source for this segment
    audio_path: Path           # this segment's voiceover audio
    start_ms: int               # absolute position on the final timeline
    duration_ms: int
    overlays: tuple[Overlay, ...] = ()
    transition_before: bool = False   # whoosh + xfade boundary, from Segment.transition


@dataclass(frozen=True)
class Timeline:
    """The fully-assembled, checkpointable representation of one video,
    independent of encode profile. Serializes to JSON for the checkpoint
    requirement in PROJECT_VISION.md §2.6 (DAG + checkpoint + resume)."""

    project_slug: str
    clips: tuple[Clip, ...]
    music_track: Path | None = None
    sfx_cues: tuple["SFXCue", ...] = ()
    subtitle_track: "SubtitleTrack | None" = None
    total_duration_ms: int = 0
```

## 5. Renderer Backend Protocol

```python
"""src/ytb_pipeline/render/backend.py (planned)."""

from typing import Protocol


class RenderBackend(Protocol):
    """Encodes an assembled Timeline to a final video file. Swappable per
    the provider pattern, though FFmpeg is expected to remain the default
    indefinitely — PyAV/MoviePy exist for specific gaps, not as equals."""

    name: str  # "ffmpeg" | "pyav" | "moviepy"

    def encode(self, timeline: "Timeline", profile: "OutputProfile") -> Path:
        ...
```

| Backend | Role |
|---|---|
| **FFmpeg** | Primary. All current rendering (`compose.py`, `compose_ai.py`, `transitions.py`) already shells out to `ffmpeg`/`ffprobe` via `subprocess`. Remains the default — fastest, most portable, zero extra Python dependency risk. |
| **PyAV** | Advanced, frame-level access — needed only for features FFmpeg's CLI filtergraph can't express cleanly (e.g. complex per-frame stickman compositing logic that's easier in Python than in a filter_complex string). Opt-in, not default. |
| **MoviePy** | Legacy / scripting convenience only. Not used by the current pipeline; documented as an option for quick prototyping, never the production path (it ultimately shells to FFmpeg anyway with more overhead). |

## 6. Render Stages

```python
"""src/ytb_pipeline/render/pipeline.py (planned)."""

def render(voiceover: "Voiceover", profile: "OutputProfile") -> "RenderedVideo":
    timeline = assemble_timeline(voiceover)        # Clip per segment, from active visual-source provider
    timeline = add_overlays(timeline)                # caption/terminal/emphasis Overlay per Clip
    timeline = add_subtitles(timeline)                # optional SubtitleTrack burn-in (18-SUBTITLE_ENGINE.md)
    timeline = add_music(timeline)                    # optional MusicTrack + ducking (16-MUSIC_ENGINE.md)
    timeline = add_sfx(timeline)                      # SFXCue placement (17-SFX_ENGINE.md)
    checkpoint_timeline(timeline)                      # write timeline.json BEFORE encode
    return encode_final(timeline, profile)             # FFmpeg backend -> RenderedVideo
```

Each stage takes and returns a `Timeline` (immutable, `dataclasses.replace`
pattern consistent with `pkg/models.py`'s existing convention) — stages
never mutate clips in place, matching the project's immutability rule.

## 7. Output Profiles

```python
"""src/ytb_pipeline/render/profiles.py (planned)."""

from dataclasses import dataclass


@dataclass(frozen=True)
class OutputProfile:
    name: str
    width: int
    height: int
    fps: int
    video_codec: str = "libx264"
    crf: int = 21
    preset: str = "medium"
    audio_codec: str = "aac"
    audio_bitrate: str = "192k"


PROFILES: dict[str, OutputProfile] = {
    "short": OutputProfile(name="short", width=1080, height=1920, fps=60),
    "long": OutputProfile(name="long", width=1920, height=1080, fps=30),
    "tiktok": OutputProfile(name="tiktok", width=1080, height=1920, fps=30),
    "podcast": OutputProfile(
        name="podcast", width=1280, height=720, fps=30,
        crf=28, preset="fast",  # audio-primary, lower video quality budget
    ),
}
```

| Profile | Resolution | FPS | Notes |
|---|---|---|---|
| Short | 1080×1920 | 60 | Matches current `compose.py` `W, H = 1080, 1920`; current pipeline does not set 60fps explicitly today — this profile formalizes the target. |
| Long | 1920×1080 | 30 | Matches `compose_ai.py`'s `LANDSCAPE_WH`. |
| TikTok | 1080×1920 | 30 | Same frame as Short; encode settings may differ (TikTok favors slightly lower bitrate ceilings). |
| Podcast | 1280×720 | 30 | Audio-primary: static/minimal visual, CRF relaxed since video is secondary. |

## 8. Checkpoint and Resume

Per `PROJECT_VISION.md` non-negotiable #6, the Timeline must be
checkpointed to disk **before** the encode stage runs:

```python
"""src/ytb_pipeline/render/checkpoint.py (planned)."""

def checkpoint_timeline(timeline: Timeline) -> Path:
    """Writes assets/output/_checkpoints/{slug}.timeline.json. Encode can
    then be re-run from this file without re-deriving clips/overlays/music/
    sfx/subtitles — the expensive upstream stages (B-roll fetch, stickman
    LLM calls, music generation) are never re-executed on a render retry."""
    ...

def resume_from_checkpoint(slug: str) -> Timeline | None:
    """Loads a previously checkpointed Timeline if present and the
    referenced clip/audio files still exist on disk; returns None (caller
    falls back to full assembly) if any referenced asset is missing."""
    ...
```

This generalizes the per-segment audio resume already present in
`voiceover/tts.py` (`_probe_duration_or_zero` skip-if-exists pattern) to the
render stage.

## 9. Current State

- `compose.py` / `compose_ai.py`: monolithic, no shared `Timeline`
  representation, no checkpoint before encode (a killed render restarts
  fully from segment 0).
- `transitions.py`: the only piece of cross-cutting timeline-like logic
  (xfade boundary computation + SFX mixing), currently scoped to whoosh
  only.
- No `OutputProfile` abstraction — resolution/fps/codec constants are
  hard-coded per file (`W, H = 1080, 1920` in `compose.py`,
  `PORTRAIT_WH`/`LANDSCAPE_WH` in `compose_ai.py`).
- No Podcast or TikTok profile exists at all.

## 10. Migration Notes

1. **Introduce `Timeline`/`Clip`/`Overlay`** as the shared intermediate
   representation; do not touch `compose.py`/`compose_ai.py` rendering logic
   yet — just wrap their existing per-segment outputs into `Clip` objects.
2. **Extract `OutputProfile`** from the scattered `W, H` / `PORTRAIT_WH` /
   `LANDSCAPE_WH` constants; both renderers read from `PROFILES[...]`
   instead of module-level tuples.
3. **Generalize `transitions.concat_with_transitions`** to consume
   `Timeline.clips` + `Timeline.sfx_cues` rather than `whoosh_before: list[bool]`
   (shared work item with `17-SFX_ENGINE.md` migration step 3).
4. **Add `add_music`/`add_subtitles` stages** once `16-MUSIC_ENGINE.md` and
   `18-SUBTITLE_ENGINE.md` ship their respective `MusicTrack`/
   `SubtitleTrack` producers.
5. **Add checkpoint write before encode** — lowest-risk, highest-value
   migration step; can land before the full Timeline refactor since it only
   needs a JSON dump of whatever data already exists at the pre-encode
   point in each renderer.
6. **Collapse `compose.py`/`compose_ai.py` into visual-source providers**
   feeding one shared `render/pipeline.py::render()` — the long-term target
   that makes adding stickman/diffusion sources a provider addition, not a
   new `compose_*.py` file.
</content>
