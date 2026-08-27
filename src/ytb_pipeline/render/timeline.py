"""Deterministic Timeline domain model for the story renderer.

Narration audio duration is the authoritative timing source (measured
`Segment.duration_sec` after TTS). A `Timeline` is the DERIVED, validated
execution plan a renderer follows — never a competing source of truth
against the master `Script`/`Voiceover`, and never persisted as anything
more than a debug/postmortem artifact next to a render's own output.

    Voiceover + Segment  -->  build_story_timeline()  -->  Timeline  -->  renderer  -->  FFmpeg

A `Timeline` carries only plain domain data (indices, seconds, paths) — no
shell strings, no FFmpeg filter graphs, no LLM prose, no ComfyUI/provider
configuration. `render/story.py` translates a validated `Timeline` into
concrete FFmpeg operations; it must not redefine timing while doing so.

Production 2026-08-26 incident (`docs/handoffs/2026-08-26-story-renderer-
caption-transition-fix-handoff.md`): a 20-section Long was split into 162
caption cards, and the renderer crossfaded every CARD as if it were a
section boundary — 161 transitions instead of 19, silently dropping 55s
(14%) of narration. `Timeline.__post_init__` below makes that specific
class of bug a construction-time `ValueError`: `transitions` must cover
exactly `0 .. len(clips)-2`, once each, so a caller can never hand the
renderer more transition boundaries than there are real clip joins.

Track vocabulary is deliberately narrow in this v1 (only what
`render/story.py` actually needs: one video track, one narration track,
transitions between clips). Adding a `music_clips`/`sfx_clips`/
`subtitle_clips` tuple field later is additive — new optional fields with
`()` defaults — and does not require breaking this contract; there is no
need to pre-build empty placeholder subsystems for tracks nothing produces
yet.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..content_profiles import ContentProfile
    from ..pkg.models import Voiceover
    from .scene_plan import ScenePlan


class TimelineError(ValueError):
    """A Timeline (or one of its clips/transitions) violates its own contract."""


@dataclass(frozen=True)
class VideoClip:
    """One section's video-track slot, in nominal (non-overlapping) time.

    `duration_sec` is the RAW segment duration — gap padding lives on the
    `Transition` that follows this clip, never baked into the clip itself,
    so the arithmetic stays in one place.
    """

    index: int
    segment_index: int
    start_sec: float
    duration_sec: float

    def __post_init__(self) -> None:
        if self.index < 0:
            raise TimelineError("VideoClip.index phải >= 0.")
        if self.start_sec < 0:
            raise TimelineError(f"VideoClip[{self.index}].start_sec phải >= 0.")
        if self.duration_sec <= 0:
            raise TimelineError(f"VideoClip[{self.index}].duration_sec phải > 0.")


@dataclass(frozen=True)
class ShotClip:
    """A visual Shot placed inside its owning narration-aligned Scene."""
    scene_id: str
    shot_id: str
    start_sec: float
    duration_sec: float

    def __post_init__(self) -> None:
        if not self.scene_id or not self.shot_id or self.start_sec < 0 or self.duration_sec <= 0:
            raise TimelineError("ShotClip phải có identity, start không âm và duration dương.")


@dataclass(frozen=True)
class NarrationClip:
    """One section's narration-track slot — the authoritative timing input."""

    index: int
    segment_index: int
    start_sec: float
    duration_sec: float
    audio_path: Path

    def __post_init__(self) -> None:
        if self.index < 0:
            raise TimelineError("NarrationClip.index phải >= 0.")
        if self.start_sec < 0:
            raise TimelineError(f"NarrationClip[{self.index}].start_sec phải >= 0.")
        if self.duration_sec <= 0:
            raise TimelineError(f"NarrationClip[{self.index}].duration_sec phải > 0.")


@dataclass(frozen=True)
class AudioLayerClip:
    """Optional local music/SFX placement; narration remains separate."""

    asset_path: Path
    start_sec: float
    duration_sec: float
    gain_db: float = 0.0
    fade_in_sec: float = 0.0
    fade_out_sec: float = 0.0
    loop: bool = False

    def __post_init__(self) -> None:
        if self.start_sec < 0 or self.duration_sec <= 0:
            raise TimelineError("AudioLayerClip phải có start >= 0 và duration dương.")
        if not -60.0 <= self.gain_db <= 12.0:
            raise TimelineError("AudioLayerClip.gain_db phải nằm trong [-60, 12].")
        if self.fade_in_sec < 0 or self.fade_out_sec < 0:
            raise TimelineError("AudioLayerClip fade không được âm.")
        if self.fade_in_sec + self.fade_out_sec > self.duration_sec:
            raise TimelineError("Tổng fade của AudioLayerClip không được dài hơn clip.")


@dataclass(frozen=True)
class Transition:
    """The boundary right after `after_clip_index`, before the next clip.

    `overlap_sec` (crossfade) and `gap_sec` (silence/hold) are independent —
    a profile can decline to use one, the other, both, or neither. Exactly
    one `Transition` must exist per clip boundary (see `Timeline.__post_init__`).
    """

    after_clip_index: int
    overlap_sec: float = 0.0
    gap_sec: float = 0.0

    def __post_init__(self) -> None:
        if self.after_clip_index < 0:
            raise TimelineError("Transition.after_clip_index phải >= 0.")
        if self.overlap_sec < 0:
            raise TimelineError(
                f"Transition sau clip {self.after_clip_index}: overlap_sec không được âm."
            )
        if self.gap_sec < 0:
            raise TimelineError(
                f"Transition sau clip {self.after_clip_index}: gap_sec không được âm."
            )


_DEFAULT_FPS_TOLERANCE_DIVISOR = 1  # 1 frame of drift tolerated between tracks


@dataclass(frozen=True)
class Timeline:
    """Deterministic, validated execution plan for one story render.

    `expected_duration_sec` is the single authoritative number every other
    stage should compare against — computed once here from the narration
    track, the same shape as the pre-existing `expected_story_duration_sec`
    helper (kept for its own already-tested call sites; this field must
    always agree with it for the same inputs — see `build_story_timeline`).
    """

    fps: int
    width: int
    height: int
    video_clips: tuple[VideoClip, ...]
    narration_clips: tuple[NarrationClip, ...]
    transitions: tuple[Transition, ...]
    expected_duration_sec: float
    source_fingerprint: str = ""
    music_clips: tuple[AudioLayerClip, ...] = ()
    sfx_clips: tuple[AudioLayerClip, ...] = ()
    shot_clips: tuple[ShotClip, ...] = ()

    def __post_init__(self) -> None:
        if self.fps <= 0:
            raise TimelineError("Timeline.fps phải > 0.")
        if self.width <= 0 or self.height <= 0:
            raise TimelineError("Timeline.width/height phải > 0.")
        if not self.video_clips:
            raise TimelineError("Timeline cần ít nhất một video clip.")
        if len(self.video_clips) != len(self.narration_clips):
            raise TimelineError(
                f"Timeline có {len(self.video_clips)} video clip nhưng "
                f"{len(self.narration_clips)} narration clip — hai track phải "
                "khớp 1-1 theo section."
            )
        expected_boundaries = list(range(len(self.video_clips) - 1))
        actual_boundaries = sorted(t.after_clip_index for t in self.transitions)
        if actual_boundaries != expected_boundaries:
            raise TimelineError(
                "Timeline.transitions phải phủ đúng mỗi ranh giới clip đúng một "
                f"lần ({expected_boundaries!r}), nhận được {actual_boundaries!r}. "
                "Đây chính là lớp lỗi 'caption card bị coi là ranh giới section' "
                "(162 transition thay vì 19) — production 2026-08-26."
            )
        for transition in self.transitions:
            left = self.video_clips[transition.after_clip_index]
            right = self.video_clips[transition.after_clip_index + 1]
            if transition.overlap_sec >= min(left.duration_sec, right.duration_sec):
                raise TimelineError(
                    f"Transition sau clip {transition.after_clip_index}: overlap_sec "
                    f"({transition.overlap_sec:.3f}s) phải ngắn hơn cả hai clip liền kề."
                )
        for index in range(1, len(self.narration_clips)):
            previous = self.narration_clips[index - 1]
            current = self.narration_clips[index]
            if current.start_sec < previous.start_sec + previous.duration_sec:
                raise TimelineError(
                    "Timeline.narration_clips phải đơn điệu tăng và không chồng lấn "
                    f"(clip {index} bắt đầu trước khi clip {index - 1} kết thúc)."
                )
        if self.shot_clips and len({clip.shot_id for clip in self.shot_clips}) != len(self.shot_clips):
            raise TimelineError("Timeline.shot_clips có shot_id trùng lặp.")
        tolerance = _DEFAULT_FPS_TOLERANCE_DIVISOR / self.fps
        drift = abs(self.video_expected_duration_sec - self.narration_expected_duration_sec)
        if drift > tolerance:
            raise TimelineError(
                "Timeline lệch giữa video track và narration track: "
                f"video={self.video_expected_duration_sec:.3f}s, "
                f"narration={self.narration_expected_duration_sec:.3f}s, "
                f"lệch {drift:.3f}s > dung sai {tolerance:.3f}s (1 frame)."
            )

    def _track_expected_duration_sec(self, clip_durations: tuple[float, ...]) -> float:
        if not clip_durations:
            return 0.0
        total = sum(clip_durations)
        for transition in self.transitions:
            total += transition.gap_sec - transition.overlap_sec
        return total

    @property
    def video_expected_duration_sec(self) -> float:
        return self._track_expected_duration_sec(
            tuple(clip.duration_sec for clip in self.video_clips)
        )

    @property
    def narration_expected_duration_sec(self) -> float:
        return self._track_expected_duration_sec(
            tuple(clip.duration_sec for clip in self.narration_clips)
        )

    def to_json_dict(self) -> dict:
        def clip_dict(clip) -> dict:
            data = asdict(clip)
            for path_field in ("audio_path", "asset_path"):
                if path_field in data:
                    data[path_field] = str(data[path_field])
            return data

        return {
            "fps": self.fps,
            "width": self.width,
            "height": self.height,
            "expected_duration_sec": self.expected_duration_sec,
            "source_fingerprint": self.source_fingerprint,
            "video_clips": [clip_dict(clip) for clip in self.video_clips],
            "narration_clips": [clip_dict(clip) for clip in self.narration_clips],
            "transitions": [asdict(t) for t in self.transitions],
            "music_clips": [clip_dict(clip) for clip in self.music_clips],
            "sfx_clips": [clip_dict(clip) for clip in self.sfx_clips],
            "shot_clips": [clip_dict(clip) for clip in self.shot_clips],
        }

    def write_json(self, path: Path) -> None:
        """Persist as a debug/postmortem artifact — never a source of truth.

        Written next to a render's own output (e.g. `assets/output/<slug>_
        timeline.json`), the same way `<slug>_thumb.jpg` already sits beside
        `<slug>.mp4`. Reproduces `docs/handoffs/2026-08-27-content-profile-
        engine-refactor-plan.md`'s reproducibility goal without introducing a
        second competing source of truth against `scripts/<slug>.json`.
        """
        path.write_text(
            json.dumps(self.to_json_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )

    @classmethod
    def from_json_dict(cls, data: dict) -> "Timeline":
        return cls(
            fps=data["fps"],
            width=data["width"],
            height=data["height"],
            expected_duration_sec=data["expected_duration_sec"],
            source_fingerprint=data.get("source_fingerprint", ""),
            video_clips=tuple(VideoClip(**clip) for clip in data["video_clips"]),
            narration_clips=tuple(
                NarrationClip(**{**clip, "audio_path": Path(clip["audio_path"])})
                for clip in data["narration_clips"]
            ),
            transitions=tuple(Transition(**t) for t in data["transitions"]),
            music_clips=tuple(AudioLayerClip(**{**clip, "asset_path": Path(clip["asset_path"])}) for clip in data.get("music_clips", ())),
            sfx_clips=tuple(AudioLayerClip(**{**clip, "asset_path": Path(clip["asset_path"])}) for clip in data.get("sfx_clips", ())),
            shot_clips=tuple(ShotClip(**clip) for clip in data.get("shot_clips", ())),
        )

    @classmethod
    def read_json(cls, path: Path) -> "Timeline":
        return cls.from_json_dict(json.loads(path.read_text(encoding="utf-8")))


def _source_fingerprint(
    profile: "ContentProfile", segments, *, fps: int, width: int, height: int,
) -> str:
    digest = hashlib.sha256()
    digest.update(f"{profile.profile_id}\x1f{profile.version}".encode("utf-8"))
    digest.update(f"{fps}x{width}x{height}".encode("utf-8"))
    digest.update(
        f"{profile.render.inter_segment_gap_sec}\x1f"
        f"{profile.render.transition_overlap_sec}".encode("utf-8")
    )
    for index, segment in enumerate(segments):
        digest.update(
            f"{index}\x1f{segment.audio_path}\x1f{segment.duration_sec}".encode("utf-8")
        )
    return digest.hexdigest()


def build_story_timeline(
    voiceover: "Voiceover", profile: "ContentProfile", *, fps: int, width: int, height: int,
) -> Timeline:
    """The TimelineBuilder boundary: `Voiceover` + `Segment` -> validated `Timeline`.

    Compatibility wrapper (Phase 1 public signature, kept stable): builds the
    `ScenePlan` this render implies and delegates to
    `build_story_timeline_from_scene_plan`. Deterministic and pure — no
    FFmpeg, no I/O, no LLM.
    """
    from .scene_plan import build_story_scene_plan

    scene_plan = build_story_scene_plan(voiceover, profile)
    return build_story_timeline_from_scene_plan(
        scene_plan, voiceover, profile, fps=fps, width=width, height=height,
    )


def build_story_timeline_from_scene_plan(
    scene_plan: "ScenePlan", voiceover: "Voiceover", profile: "ContentProfile",
    *, fps: int, width: int, height: int,
) -> Timeline:
    """`ScenePlan` + `Voiceover` -> validated `Timeline`.

    Narration (`Segment.duration_sec`, already measured by TTS) is the
    authoritative timing input; the video track is built to match each
    Scene's own narration window 1-1 by construction — Timeline consumes the
    Scene boundaries `ScenePlan` already validated, it does not rediscover
    them. Gap and overlap come from the profile's own `render` contract,
    applied uniformly between every adjacent pair — exactly the two knobs
    `render_story_video` already reads today, just no longer computed inline
    with index-boundary conditionals scattered through the render loop.

    `ScenePlan` does not carry audio paths (that is Timeline's concern, not
    a visual planning concern), so the original segments are still consulted
    for `audio_path` by `source_segment_index`.
    """
    segments = voiceover.segments
    if len(scene_plan.scenes) != len(segments):
        raise TimelineError(
            f"ScenePlan có {len(scene_plan.scenes)} scene nhưng Voiceover có "
            f"{len(segments)} segment — hai bên phải khớp 1-1."
        )

    gap = profile.render.inter_segment_gap_sec
    overlap = profile.render.transition_overlap_sec

    video_clips: list[VideoClip] = []
    narration_clips: list[NarrationClip] = []
    transitions: list[Transition] = []
    shot_clips: list[ShotClip] = []
    cursor = 0.0
    for scene in scene_plan.scenes:
        index = scene.source_segment_index
        segment = segments[index]
        if segment.audio_path is None:
            raise TimelineError(f"Segment {index} thiếu audio_path — chưa qua TTS.")
        duration = scene.narration_end_sec - scene.narration_start_sec
        for shot in scene.shots:
            shot_clips.append(ShotClip(
                scene.scene_id, shot.shot_id, cursor + shot.relative_start_sec, shot.duration_sec,
            ))
        video_clips.append(
            VideoClip(index=index, segment_index=index, start_sec=cursor, duration_sec=duration)
        )
        narration_clips.append(
            NarrationClip(
                index=index, segment_index=index, start_sec=cursor,
                duration_sec=duration, audio_path=Path(segment.audio_path),
            )
        )
        if index < len(segments) - 1:
            transitions.append(Transition(after_clip_index=index, overlap_sec=overlap, gap_sec=gap))
        # Nominal, non-overlapping concatenation position — overlap only
        # shortens the FINAL composited output (`expected_duration_sec`
        # below), it never makes one clip's own declared start precede the
        # previous clip's own declared end.
        cursor += duration + gap

    expected_duration = sum(
        scene.narration_end_sec - scene.narration_start_sec for scene in scene_plan.scenes
    ) + len(transitions) * (gap - overlap)

    audio_profile = getattr(profile.render, "audio", None)
    music_clips: tuple[AudioLayerClip, ...] = ()
    sfx_clips: tuple[AudioLayerClip, ...] = ()
    if audio_profile and audio_profile.background_music:
        music = audio_profile.background_music
        music_clips = (AudioLayerClip(
            asset_path=profile.assets_dir / music.asset, start_sec=0.0,
            duration_sec=expected_duration, gain_db=music.gain_db,
            fade_in_sec=music.fade_in_sec, fade_out_sec=music.fade_out_sec,
            loop=music.mode == "loop",
        ),)
    if audio_profile:
        if any(effect.at_sec >= expected_duration for effect in audio_profile.sfx):
            raise TimelineError("SFX bắt đầu ngoài authoritative narration timeline.")
        sfx_clips = tuple(
            AudioLayerClip(
                asset_path=profile.assets_dir / effect.asset, start_sec=effect.at_sec,
                duration_sec=min(effect.duration_sec or max(0.001, expected_duration - effect.at_sec), max(0.001, expected_duration - effect.at_sec)),
                gain_db=effect.gain_db,
            ) for effect in audio_profile.sfx
        )

    return Timeline(
        fps=fps, width=width, height=height,
        video_clips=tuple(video_clips), narration_clips=tuple(narration_clips),
        transitions=tuple(transitions), expected_duration_sec=expected_duration,
        source_fingerprint=_source_fingerprint(profile, segments, fps=fps, width=width, height=height),
        music_clips=music_clips, sfx_clips=sfx_clips,
        shot_clips=tuple(shot_clips),
    )
