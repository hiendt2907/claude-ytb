"""Canonical, renderer-aware content contract for every pipeline stage.

This is the only authority for format duration, hook timing, planning budgets,
and transition allowance.  Prompts may describe the contract, but must never
invent a second set of bounds.  Script, audio, render, and publish QA all use
these values so a video cannot pass one stage and fail another by design.
"""

from __future__ import annotations

from dataclasses import dataclass

from .config.settings import settings


CONTRACT_VERSION = "2026-07-28.1"
# F5's former post-process tempos (1.82–2.16x) caused Faster-Whisper to
# recover only 1% of a verified Long narration.  The voice profiles now keep
# tempo near natural speech (0.98–1.18x).  The old 1600 cpm calibration was
# measured from those accelerated artifacts, so retaining it would make newly
# generated scripts almost twice as long as their actual spoken runtime.  A
# native-F5 Long calibration measured 3,276 prepared Vietnamese characters in
# 145.975 seconds, or 1,346.55 cpm; use the rounded 1,347 cpm planning rate.
# Measured audio remains the runtime authority at the voiceover boundary.
F5_CHARS_PER_MIN = 1347.0
# Provisional xKiro calibration: one production Short measured on 2026-08-24
# spoke 1,398 prepared Vietnamese characters in 81.34 seconds (≈1,031 CPM).
# This must be replaced with the conservative p25 from a five-or-more sample
# calibration; xKiro must not inherit F5's separately measured rate.
XKIRO_CHARS_PER_MIN = 1030.0
# The current knowledge profile requests Edge at +96%.  An isolated Long E2E
# run measured 4,316 prepared Vietnamese characters in 161.4 seconds, or
# 1,604 CPM rounded.  Planning must follow the active profile, while measured
# audio remains the final runtime authority.
EDGE_CHARS_PER_MIN = 1_604.0
TRANSITION_OVERLAP_SEC = 0.4
SAFE_LOWER_RUNTIME_MARGIN_SEC = 10.0
SAFE_UPPER_RUNTIME_MARGIN_SEC = 15.0


@dataclass(frozen=True)
class ContentContract:
    video_type: str
    viewer_runtime_bounds_sec: tuple[float, float]
    minimum_sections: int
    answer_start_target_sec: float | None = None
    answer_start_deadline_sec: float | None = None
    situation_max_chars: int | None = None

    def transition_loss_sec(self, segment_count: int) -> float:
        """Known overlap removed by the renderer for this number of sections."""
        return max(0, segment_count - 1) * TRANSITION_OVERLAP_SEC

    def audio_runtime_bounds_sec(self, *, segment_count: int) -> tuple[float, float]:
        """Audio range that yields the stated viewer-visible final duration."""
        loss = self.transition_loss_sec(segment_count)
        lower, upper = self.viewer_runtime_bounds_sec
        return lower + loss, upper + loss

    def safe_character_bounds(
        self, *, chars_per_minute: float, segment_count: int
    ) -> tuple[int, int]:
        """Prompt target with room on both sides of the hard runtime boundary."""
        if chars_per_minute <= 0:
            raise ValueError("chars_per_minute phải > 0.")
        lower, upper = self.audio_runtime_bounds_sec(segment_count=segment_count)
        # The prompt target must leave enough runtime headroom for natural
        # provider variation.  The values are deliberately named so a future
        # calibration can adjust them without reintroducing magic numbers.
        safe_lower = min(upper, lower + SAFE_LOWER_RUNTIME_MARGIN_SEC)
        safe_upper = max(safe_lower, upper - SAFE_UPPER_RUNTIME_MARGIN_SEC)
        return int(chars_per_minute * safe_lower / 60), int(chars_per_minute * safe_upper / 60)

    def validate_audio_runtime(self, duration_sec: float, *, segment_count: int) -> None:
        self._validate(
            duration_sec,
            self.audio_runtime_bounds_sec(segment_count=segment_count),
            stage="audio",
        )

    def validate_viewer_runtime(self, duration_sec: float) -> None:
        self._validate(duration_sec, self.viewer_runtime_bounds_sec, stage="viewer")

    def _validate(self, duration_sec: float, bounds: tuple[float, float], *, stage: str) -> None:
        if duration_sec <= 0:
            raise ValueError("Duration không hợp lệ.")
        lower, upper = bounds
        label = "Short" if self.video_type == "short" else "Long"
        qualifier = "audio " if stage == "audio" else ""
        if duration_sec < lower:
            raise ValueError(f"{label} quá ngắn: {qualifier}{duration_sec:.1f}s; ít nhất {lower:.1f}s.")
        if duration_sec > upper:
            raise ValueError(f"{label} quá dài {upper:.0f}s: {qualifier}{duration_sec:.1f}s.")


_CONTRACTS = {
    "short": ContentContract(
        video_type="short",
        # E2E renderers can lose up to ~2s to transition overlap; keep the
        # production 60s floor while allowing the bounded test profile to
        # verify the complete downstream path without regenerating content.
        viewer_runtime_bounds_sec=(58.0, 90.0) if settings.e2e_test else (60.0, 90.0),
        minimum_sections=6,
        answer_start_target_sec=4.0,
        answer_start_deadline_sec=5.0,
        situation_max_chars=120,
    ),
    "long": ContentContract(
        video_type="long",
        viewer_runtime_bounds_sec=(180.0, 240.0) if settings.e2e_test else (720.0, 900.0),
        minimum_sections=8 if settings.e2e_test else 24,
    ),
}


def contract_for(video_type: str) -> ContentContract:
    try:
        return _CONTRACTS[video_type.strip().lower()]
    except (AttributeError, KeyError) as exc:
        raise ValueError(f"video_type không hợp lệ cho content contract: {video_type!r}") from exc


def chars_per_min_for_provider(provider: str) -> float:
    """Calibrated planning rate; measured audio remains the runtime authority."""
    normalized = provider.strip().lower()
    if normalized == "xkiro":
        return XKIRO_CHARS_PER_MIN
    return F5_CHARS_PER_MIN if normalized == "f5" else EDGE_CHARS_PER_MIN


def estimate_duration_sec(characters: int, *, chars_per_minute: float) -> float:
    if chars_per_minute <= 0:
        raise ValueError("chars_per_minute phải > 0.")
    return characters / chars_per_minute * 60
