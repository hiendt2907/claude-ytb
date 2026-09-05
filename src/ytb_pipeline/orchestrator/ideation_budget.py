"""Prompt budgets, computed when asked rather than when the module is imported.

`ideation_prompts` used to derive twenty-odd constants at import time, reading
`settings.tts_provider` as it went. Two consequences, both real: changing the
profile or provider mid-process had no effect, and tests had to reload the
module to see a new setting. Worse, the values silently belonged to whatever
settings existed at first import — which is not necessarily the profile the run
is for.

This module holds the same arithmetic behind a function. Step 3a keeps the
numbers byte-identical (no profile threaded yet, exactly as before); Step 3b
threads the profile through so the planning rate is the profile's corrected one
rather than the raw provider rate.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING

from ..content_contract import ContentContract, chars_per_min_for_provider, contract_for
from ..analytics.quality_report import REQUIRED_PURPOSES_BY_VIDEO_TYPE

if TYPE_CHECKING:
    from ..content_profiles import ContentProfile


@dataclass(frozen=True)
class PromptBudget:
    """Every length figure a generation prompt quotes, from one contract."""

    short_contract: ContentContract
    long_contract: ContentContract
    long_min_minutes: int
    long_max_minutes: int
    short_min_minutes: float
    short_max_minutes: float
    short_answer_start_target_sec: float
    planning_chars_per_min: float
    long_planning_chars_per_min: float
    short_situation_max_chars: int
    short_min_chars: int
    short_max_chars: int
    short_safe_min_chars: int
    short_safe_max_chars: int
    short_target_chars: int
    short_prompt_sections: int
    short_required_purposes: str
    short_payoff_max_chars: int
    short_body_section_chars: int
    long_min_chars: int
    long_max_chars: int
    long_safe_min_chars: int
    long_safe_max_chars: int


def build_budget(
    tts_provider: str, content_profile: "ContentProfile | None" = None
) -> PromptBudget:
    """The arithmetic, unchanged from the constants it replaces."""
    short = contract_for("short", content_profile)
    long_contract = contract_for("long", content_profile)

    short_rate = chars_per_min_for_provider(tts_provider, video_type="short")
    long_rate = chars_per_min_for_provider(tts_provider, video_type="long")

    situation_max = short.situation_char_budget(chars_per_minute=short_rate)
    short_low_sec, short_high_sec = short.audio_runtime_bounds_sec(
        segment_count=short.minimum_sections
    )
    short_min = int(short_rate * short_low_sec / 60)
    short_max = int(short_rate * short_high_sec / 60)
    short_safe_min, short_safe_max = short.safe_character_bounds(
        chars_per_minute=short_rate, segment_count=short.minimum_sections
    )
    sections = short.minimum_sections
    payoff_max = int(short_safe_max * 0.20)

    long_low_sec, long_high_sec = long_contract.audio_runtime_bounds_sec(
        segment_count=long_contract.minimum_sections
    )
    long_safe_min, long_safe_max = long_contract.safe_character_bounds(
        chars_per_minute=long_rate, segment_count=long_contract.minimum_sections
    )

    return PromptBudget(
        short_contract=short,
        long_contract=long_contract,
        long_min_minutes=int(long_contract.viewer_runtime_bounds_sec[0] / 60),
        long_max_minutes=int(long_contract.viewer_runtime_bounds_sec[1] / 60),
        short_min_minutes=short.viewer_runtime_bounds_sec[0] / 60,
        short_max_minutes=short.viewer_runtime_bounds_sec[1] / 60,
        short_answer_start_target_sec=short.answer_start_target_sec or 4.0,
        planning_chars_per_min=short_rate,
        long_planning_chars_per_min=long_rate,
        short_situation_max_chars=situation_max,
        short_min_chars=short_min,
        short_max_chars=short_max,
        short_safe_min_chars=short_safe_min,
        short_safe_max_chars=short_safe_max,
        # Midpoint of the active safe band, not a literal. A hardcoded midpoint
        # once sat ABOVE short_max_chars, so the trimmer computed a growth ratio,
        # changed nothing, and still reported success.
        short_target_chars=(short_safe_min + short_safe_max) // 2,
        short_prompt_sections=sections,
        short_required_purposes=", ".join(REQUIRED_PURPOSES_BY_VIDEO_TYPE["short"]),
        short_payoff_max_chars=payoff_max,
        short_body_section_chars=max(
            80,
            (short_safe_max - situation_max - payoff_max) // max(1, sections - 2),
        ),
        long_min_chars=int(long_rate * long_low_sec / 60),
        long_max_chars=int(long_rate * long_high_sec / 60),
        long_safe_min_chars=long_safe_min,
        long_safe_max_chars=long_safe_max,
    )


@lru_cache(maxsize=8)
def _cached_ambient_budget(tts_provider: str, contract_epoch: tuple[float, ...]) -> PromptBudget:
    return build_budget(tts_provider)


def ambient_budget() -> PromptBudget:
    """Budget for the CURRENT settings, with no profile threaded.

    Keyed on the settings that feed it, so changing a setting mid-process yields
    a new budget instead of replaying the one built at import. Step 3b replaces
    the callers of this with an explicitly threaded profile; until then this
    reproduces the previous numbers exactly.
    """
    from ..config.settings import settings

    epoch = (
        float(settings.short_viewer_min_sec),
        float(settings.short_viewer_max_sec),
        float(settings.short_min_sections),
        float(settings.long_viewer_min_sec),
        float(settings.long_viewer_max_sec),
        float(settings.long_min_sections),
        float(settings.e2e_test),
    )
    return _cached_ambient_budget(settings.tts_provider, epoch)
