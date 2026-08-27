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
        return "\n".join(
            f"{index}\n{_timestamp(cue.start_sec, separator=',')} --> {_timestamp(cue.end_sec, separator=',')}\n{cue.text}"
            for index, cue in enumerate(self.cues, start=1)
        ) + ("\n" if self.cues else "")

    def to_vtt(self) -> str:
        body = "\n\n".join(
            f"{_timestamp(cue.start_sec, separator='.')} --> {_timestamp(cue.end_sec, separator='.')}\n{cue.text}"
            for cue in self.cues
        )
        return f"WEBVTT\n\n{body}\n" if body else "WEBVTT\n"


def build_subtitle_track(voiceover, timeline, *, language: str = "vi") -> SubtitleTrack:
    """Use measured narration slots, never inferred final-video durations."""
    if len(voiceover.segments) != len(timeline.narration_clips):
        raise ValueError("Voiceover và Timeline narration clips phải khớp 1-1.")
    cues = tuple(
        SubtitleCue(clip.start_sec, clip.start_sec + clip.duration_sec, segment.narration)
        for segment, clip in zip(voiceover.segments, timeline.narration_clips)
    )
    return SubtitleTrack(language=language, cues=cues)


def write_subtitle_artifacts(track: SubtitleTrack, output_base: Path) -> tuple[Path, Path]:
    """Write deterministic sibling ``.srt`` and ``.vtt`` deliverables."""
    srt_path, vtt_path = output_base.with_suffix(".srt"), output_base.with_suffix(".vtt")
    srt_path.write_text(track.to_srt(), encoding="utf-8")
    vtt_path.write_text(track.to_vtt(), encoding="utf-8")
    return srt_path, vtt_path
