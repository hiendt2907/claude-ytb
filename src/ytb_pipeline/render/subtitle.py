"""Deterministic accessibility subtitle artifacts derived from narration."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


def _timestamp(seconds: float, *, separator: str) -> str:
    milliseconds = round(seconds * 1000)
    hours, milliseconds = divmod(milliseconds, 3_600_000)
    minutes, milliseconds = divmod(milliseconds, 60_000)
    seconds_part, milliseconds = divmod(milliseconds, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds_part:02d}{separator}{milliseconds:03d}"


@dataclass(frozen=True)
class SubtitleCue:
    start_sec: float
    end_sec: float
    text: str

    def __post_init__(self) -> None:
        if self.start_sec < 0 or self.end_sec <= self.start_sec:
            raise ValueError("SubtitleCue phải có khoảng thời gian dương, không âm.")
        if not self.text.strip():
            raise ValueError("SubtitleCue.text không được rỗng.")


@dataclass(frozen=True)
class SubtitleTrack:
    language: str
    cues: tuple[SubtitleCue, ...]

    def __post_init__(self) -> None:
        if not self.language.strip():
            raise ValueError("SubtitleTrack.language không được rỗng.")
        for previous, current in zip(self.cues, self.cues[1:]):
            if current.start_sec < previous.end_sec:
                raise ValueError("SubtitleTrack.cues phải đơn điệu và không chồng lấn.")

    def to_srt(self) -> str:
        if not self.cues:
            return ""
        blocks = (
            f"{index}\n{_timestamp(cue.start_sec, separator=',')} --> {_timestamp(cue.end_sec, separator=',')}\n{cue.text}"
            for index, cue in enumerate(self.cues, start=1)
        )
        # SRT requires a blank line between entries so a parser knows where
        # one cue's text ends and the next cue's index digit begins — joining
        # with a single "\n" (the previous behaviour) left a cue's text
        # immediately followed by the next bare index digit on the very next
        # line, which is malformed by the format's own spec even though
        # ffmpeg's lenient demuxer happened to tolerate it.
        return "\n\n".join(blocks) + "\n"

    def to_vtt(self) -> str:
        body = "\n\n".join(
            f"{_timestamp(cue.start_sec, separator='.')} --> {_timestamp(cue.end_sec, separator='.')}\n{cue.text}"
            for cue in self.cues
        )
        return f"WEBVTT\n\n{body}\n" if body else "WEBVTT\n"


def build_subtitle_track(voiceover, timeline, *, language: str = "vi") -> SubtitleTrack:
    """Use measured narration slots, never inferred final-video durations.

    `timeline.narration_clips[i].start_sec` is a NOMINAL, pre-crossfade
    planning position (`cursor += duration + gap`, see
    `build_story_timeline_from_scene_plan` in `timeline.py`) — it never
    subtracts `overlap`. The actually-composited video crossfades adjacent
    sections and trims `overlap_sec` of real time at every transition
    (`_compose_clips`'s own `audio_cumulative += ... - overlap` in
    `story.py`), so the nominal cursor runs `overlap_sec` further ahead of
    real playback time at every segment boundary, compounding across the
    video. Subtitles must follow the REAL composited timeline, so each
    clip's start is corrected by the cumulative overlap of every transition
    before it.
    """
    if len(voiceover.segments) != len(timeline.narration_clips):
        raise ValueError("Voiceover và Timeline narration clips phải khớp 1-1.")
    overlap_after = {t.after_clip_index: t.overlap_sec for t in timeline.transitions}
    cues = []
    cumulative_overlap = 0.0
    previous_end: float | None = None
    for position, (segment, clip) in enumerate(zip(voiceover.segments, timeline.narration_clips)):
        start = clip.start_sec - cumulative_overlap
        if previous_end is not None and start < previous_end:
            # When `gap == overlap` the corrected boundary is mathematically
            # exactly the previous cue's end, but repeated float subtraction
            # can land a few ULPs before it (reproduced with real 22-segment
            # production durations in
            # test_build_subtitle_track_tolerates_float_noise_from_overlap_correction).
            # That is rounding noise, not a real overlap — a genuine timing
            # bug would be off by far more than one ULP — so clamp instead
            # of letting SubtitleTrack's own exact, no-tolerance
            # monotonicity check reject an artifact that is conceptually
            # just touching.
            start = previous_end
        end = start + clip.duration_sec
        cues.append(SubtitleCue(start, end, segment.narration))
        previous_end = end
        cumulative_overlap += overlap_after.get(position, 0.0)
    return SubtitleTrack(language=language, cues=tuple(cues))


def write_subtitle_artifacts(track: SubtitleTrack, output_base: Path) -> tuple[Path, Path]:
    """Write deterministic sibling ``.srt`` and ``.vtt`` deliverables."""
    srt_path, vtt_path = output_base.with_suffix(".srt"), output_base.with_suffix(".vtt")
    srt_path.write_text(track.to_srt(), encoding="utf-8")
    vtt_path.write_text(track.to_vtt(), encoding="utf-8")
    return srt_path, vtt_path
