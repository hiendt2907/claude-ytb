"""Canonical, renderer-aware content contract for every pipeline stage.

This is the only authority for format duration, hook timing, planning budgets,
and transition allowance.  Prompts may describe the contract, but must never
invent a second set of bounds.  Script, audio, render, and publish QA all use
these values so a video cannot pass one stage and fail another by design.
"""

from __future__ import annotations

from dataclasses import dataclass


CONTRACT_VERSION = "2026-07-23.1"
F5_CHARS_PER_MIN = 2_000.0
EDGE_CHARS_PER_MIN = 1_197.0
TRANSITION_OVERLAP_SEC = 0.4


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
        # A 10-second margin eliminates most first-pass length repairs while
        # keeping the script well inside the final viewer-runtime contract.
        safe_lower = min(upper, lower + 4.0)
        safe_upper = max(safe_lower, upper - 8.0)
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
        viewer_runtime_bounds_sec=(60.0, 90.0),
        minimum_sections=6,
        answer_start_target_sec=4.0,
        answer_start_deadline_sec=5.0,
        situation_max_chars=120,
    ),
    "long": ContentContract(
        video_type="long",
        viewer_runtime_bounds_sec=(720.0, 900.0),
        minimum_sections=24,
    ),
}


def contract_for(video_type: str) -> ContentContract:
    try:
        return _CONTRACTS[video_type.strip().lower()]
    except (AttributeError, KeyError) as exc:
        raise ValueError(f"video_type không hợp lệ cho content contract: {video_type!r}") from exc


def chars_per_min_for_provider(provider: str) -> float:
    """Calibrated planning rate; measured audio remains the runtime authority."""
    return F5_CHARS_PER_MIN if provider.strip().lower() == "f5" else EDGE_CHARS_PER_MIN


def estimate_duration_sec(characters: int, *, chars_per_minute: float) -> float:
    if chars_per_minute <= 0:
        raise ValueError("chars_per_minute phải > 0.")
    return characters / chars_per_minute * 60
