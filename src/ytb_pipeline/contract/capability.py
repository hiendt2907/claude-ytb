"""What a provider can actually do, captured at the start of a run.

Planning rates live here rather than in the contract layer because they are a
property of the *provider*, not of the story. A profile that swaps its TTS
provider must get the new rate without any storytelling rule moving.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..content_contract import (
    EDGE_CHARS_PER_MIN,
    F5_CHARS_PER_MIN,
    XKIRO_CHARS_PER_MIN,
    XKIRO_LONG_CHARS_PER_MIN,
)

# Step 4a moves these tables out of `content_contract` for real; importing them
# here first keeps a single copy of the measured numbers while the call sites
# migrate. Duplicating them would recreate the drift this refactor exists to end.
_RATES: dict[str, tuple[float, float]] = {
    # provider -> (short cpm, long cpm)
    "xkiro": (XKIRO_CHARS_PER_MIN, XKIRO_LONG_CHARS_PER_MIN),
    "f5": (F5_CHARS_PER_MIN, F5_CHARS_PER_MIN),
    "edge": (EDGE_CHARS_PER_MIN, EDGE_CHARS_PER_MIN),
}


@dataclass(frozen=True)
class ProviderCapabilitySnapshot:
    """Measured, provider-specific facts a run plans against."""

    tts_provider: str
    chars_per_min_short: float
    chars_per_min_long: float

    def chars_per_min(self, video_type: str) -> float:
        return (
            self.chars_per_min_long
            if video_type.strip().lower() == "long"
            else self.chars_per_min_short
        )

    def fingerprint_payload(self) -> dict[str, object]:
        return {
            "tts_provider": self.tts_provider,
            "chars_per_min_short": self.chars_per_min_short,
            "chars_per_min_long": self.chars_per_min_long,
        }


def capability_for(tts_provider: str) -> ProviderCapabilitySnapshot:
    """Snapshot the rates for `tts_provider`, falling back to the Edge table.

    The fallback matches `chars_per_min_for_provider` exactly; changing it here
    without changing it there would put the prompt and the gate on different
    numbers again.
    """
    normalized = tts_provider.strip().lower()
    short_rate, long_rate = _RATES.get(normalized, (EDGE_CHARS_PER_MIN, EDGE_CHARS_PER_MIN))
    return ProviderCapabilitySnapshot(
        tts_provider=normalized,
        chars_per_min_short=short_rate,
        chars_per_min_long=long_rate,
    )
