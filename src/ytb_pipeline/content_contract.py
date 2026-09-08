"""Canonical, renderer-aware content contract for every pipeline stage.

This is the only authority for format duration, hook timing, planning budgets,
and transition allowance.  Prompts may describe the contract, but must never
invent a second set of bounds.  Script, audio, render, and publish QA all use
these values so a video cannot pass one stage and fail another by design.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .config.settings import settings

if TYPE_CHECKING:
    from .content_profiles import ContentProfile


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
# Measured xKiro calibration, 2026-08-24.  A Short spoke 1,398 prepared
# characters in 81.34s (1,031 cpm); a Long spoke 13,282 in 718.6s (1,109 cpm).
# The 7.6% gap is systematic, not noise: a Long is one continuous read while a
# Short spends proportionally more time in inter-phrase silence.  Planning a
# Long at the Short rate produced 718.6s against a 730s floor and failed at the
# voiceover boundary, so the two formats keep separate rates.
#
# These are central estimates, deliberately NOT a conservative low percentile.
# A low rate over-estimates runtime, so the generator writes too few characters
# and the audio undershoots the floor — which is exactly the failure above.
# Neither direction is safe; accuracy plus proportional margin is what protects
# the contract.  Both rates are n=1 and want a five-sample recalibration.
XKIRO_CHARS_PER_MIN = 1030.0
XKIRO_LONG_CHARS_PER_MIN = 1109.0
# The current knowledge profile requests Edge at +96%.  An isolated Long E2E
# run measured 4,316 prepared Vietnamese characters in 161.4 seconds, or
# 1,604 CPM rounded.  Planning must follow the active profile, while measured
# audio remains the final runtime authority.
EDGE_CHARS_PER_MIN = 1_604.0
TRANSITION_OVERLAP_SEC = 0.4
# Proportional, not a fixed second-count.  A flat 10s was 16% of the Short floor
# but only 1.4% of the Long floor, so Long planning had effectively no buffer
# against narration-rate error.  A fraction keeps the same protection at both
# scales.  5%/6% covers the residual rate uncertainty while leaving a usable
# writing window inside the narrower Long contract.
SAFE_LOWER_RUNTIME_MARGIN_RATIO = 0.05
SAFE_UPPER_RUNTIME_MARGIN_RATIO = 0.06
# The Short `situation` gate is a CLOSED lexical whitelist, not a concept a
# writer can satisfy merely by being editorially tense.  Production 2026-08-30
# proved that stating it only as "a concrete tension marker" is unusable: an
# editorial rewrite that fixed the cited scene but dropped these exact tokens
# was discarded whole (`Editorial rewrite phá Short strategy-v1`), and the
# bounded editorial budget was then spent re-reviewing byte-identical payloads.
# It lives in the shared contract so the checker and every prompt judged by it
# stay one source of truth instead of drifting apart.
SHORT_SITUATION_TENSION_MARKERS: tuple[str, ...] = (
    "nhưng",
    "thật ra",
    "đừng",
    "không phải",
    "vì sao",
)


@dataclass(frozen=True)
class ContentContract:
    video_type: str
    viewer_runtime_bounds_sec: tuple[float, float]
    minimum_sections: int
    answer_start_target_sec: float | None = None
    answer_start_deadline_sec: float | None = None
    transition_overlap_sec: float = TRANSITION_OVERLAP_SEC
    inter_segment_gap_sec: float = 0.0
    runtime_tolerance_sec: float = 0.0

    def situation_char_budget(self, *, chars_per_minute: float) -> int:
        """Longest opening hook that still starts the answer by the target.

        This replaces a static 120-character literal that had been calibrated
        against Edge (1,604 cpm).  At the slower xKiro rate the same 120
        characters take 6.99s, so a model obeying the prompt was still rejected
        by `_validate_short_strategy_structure` at the hard 5s gate.  Deriving
        the budget from the active rate keeps the prompt and the gate in sync
        for every provider, and aiming at the target (not the deadline) keeps
        headroom for provider variation.
        """
        if chars_per_minute <= 0:
            raise ValueError("chars_per_minute phải > 0.")
        if self.answer_start_target_sec is None:
            raise ValueError(f"Contract '{self.video_type}' không có answer_start_target_sec.")
        return int(chars_per_minute * self.answer_start_target_sec / 60)

    def transition_loss_sec(self, segment_count: int) -> float:
        """Known overlap removed by the renderer for this number of sections."""
        return max(0, segment_count - 1) * (
            self.transition_overlap_sec - self.inter_segment_gap_sec
        )

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
        safe_lower = min(upper, lower * (1 + SAFE_LOWER_RUNTIME_MARGIN_RATIO))
        safe_upper = max(safe_lower, upper * (1 - SAFE_UPPER_RUNTIME_MARGIN_RATIO))
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
        accepted_lower = lower - self.runtime_tolerance_sec
        if duration_sec < accepted_lower:
            raise ValueError(
                f"{label} quá ngắn: {qualifier}{duration_sec:.1f}s; "
                f"ít nhất {accepted_lower:.1f}s."
            )
        if duration_sec > upper:
            raise ValueError(f"{label} quá dài {upper:.0f}s: {qualifier}{duration_sec:.1f}s.")


def _build_contract(
    video_type: str, content_profile: "ContentProfile | None" = None
) -> ContentContract:
    """Dựng contract từ settings TẠI THỜI ĐIỂM GỌI, không đóng băng lúc import.

    Cửa sổ runtime là một tham số vận hành, không phải hằng số biên dịch: định
    dạng thắng đổi theo dữ liệu kênh, và mỗi lần chỉnh không được kéo theo một
    lần sửa code. Dựng theo từng lời gọi cũng khiến `settings` được tôn trọng
    thật — bản cũ đóng băng `_CONTRACTS` lúc import nên việc đổi settings lúc
    chạy (kể cả monkeypatch trong test) hoàn toàn vô hiệu.
    """
    if video_type == "short":
        # E2E renderers can lose up to ~2s to transition overlap; keep the
        # operator's floor while letting the bounded test profile verify the
        # complete downstream path without regenerating content.
        profile_format = content_profile.format_for("short") if content_profile else None
        configured_lower = (
            profile_format.viewer_min_sec if profile_format else settings.short_viewer_min_sec
        )
        configured_upper = (
            profile_format.viewer_max_sec if profile_format else settings.short_viewer_max_sec
        )
        lower = configured_lower - 2.0 if settings.e2e_test else configured_lower
        return ContentContract(
            video_type="short",
            viewer_runtime_bounds_sec=(lower, configured_upper),
            minimum_sections=(
                profile_format.min_sections if profile_format else settings.short_min_sections
            ),
            answer_start_target_sec=4.0,
            answer_start_deadline_sec=5.0,
            transition_overlap_sec=(
                content_profile.render.transition_overlap_sec
                if content_profile else TRANSITION_OVERLAP_SEC
            ),
            inter_segment_gap_sec=(
                content_profile.render.inter_segment_gap_sec if content_profile else 0.0
            ),
            runtime_tolerance_sec=(
                profile_format.runtime_tolerance_sec if profile_format else 0.0
            ),
        )
    profile_format = content_profile.format_for("long") if content_profile else None
    return ContentContract(
        video_type="long",
        viewer_runtime_bounds_sec=(
            (180.0, 240.0) if settings.e2e_test
            else (
                (profile_format.viewer_min_sec, profile_format.viewer_max_sec)
                if profile_format
                else (settings.long_viewer_min_sec, settings.long_viewer_max_sec)
            )
        ),
        minimum_sections=(
            8 if settings.e2e_test
            else profile_format.min_sections if profile_format
            else settings.long_min_sections
        ),
        transition_overlap_sec=(
            content_profile.render.transition_overlap_sec
            if content_profile else TRANSITION_OVERLAP_SEC
        ),
        inter_segment_gap_sec=(
            content_profile.render.inter_segment_gap_sec if content_profile else 0.0
        ),
        runtime_tolerance_sec=(
            profile_format.runtime_tolerance_sec if profile_format else 0.0
        ),
    )


def contract_for(
    video_type: str, content_profile: "ContentProfile | None" = None
) -> ContentContract:
    try:
        normalized = video_type.strip().lower()
    except AttributeError as exc:
        raise ValueError(f"video_type không hợp lệ cho content contract: {video_type!r}") from exc
    if normalized not in ("short", "long"):
        raise ValueError(f"video_type không hợp lệ cho content contract: {video_type!r}")
    return _build_contract(normalized, content_profile)


def chars_per_min_for_provider(provider: str, *, video_type: str | None = None) -> float:
    """Calibrated planning rate; measured audio remains the runtime authority.

    `video_type` selects a format-specific rate where one has been measured.  A
    Long is a single continuous read, so it runs faster than a Short of the same
    character count; planning both at one rate is what broke the Long floor.
    """
    normalized = provider.strip().lower()
    if normalized == "xkiro":
        if (video_type or "").strip().lower() == "long":
            return XKIRO_LONG_CHARS_PER_MIN
        return XKIRO_CHARS_PER_MIN
    return F5_CHARS_PER_MIN if normalized == "f5" else EDGE_CHARS_PER_MIN


def effective_chars_per_min(
    provider: str, *, video_type: str | None = None, content_profile: "ContentProfile | None" = None,
) -> float:
    """chars_per_min_for_provider, bù thêm hệ số nhịp đọc riêng của profile.

    Hằng số CPM chung đo trên kênh 1-giọng; một profile hội thoại nhiều giọng
    có overhead chuyển giọng giữa các segment mà hằng số đó không tính tới.
    Đo được ~7-8% chênh lệch có hệ thống cho ban-so-6 qua hai lần render Long
    thật (không phải nhiễu một lần). content_profile.providers.tts_pace_factor
    là hệ số hiệu chỉnh riêng đó; mặc định 1.0 cho profile không khai.
    """
    base = chars_per_min_for_provider(provider, video_type=video_type)
    factor = content_profile.providers.tts_pace_factor if content_profile is not None else 1.0
    return base * factor


def estimate_duration_sec(characters: int, *, chars_per_minute: float) -> float:
    if chars_per_minute <= 0:
        raise ValueError("chars_per_minute phải > 0.")
    return characters / chars_per_minute * 60
