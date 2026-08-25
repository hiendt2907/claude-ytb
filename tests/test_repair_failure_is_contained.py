"""A broken repair response must fail the candidate, not kill the batch.

The long-form `extend` step parses a second LLM response.  When that response
came back as malformed JSON the exception escaped `validate_or_repair_script`
as a traceback and terminated the whole `ytb batch start` process, discarding
the candidate that was already in hand.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ytb_pipeline.orchestrator.ideation_script_fix import (
    IdeationQualityFailure,
    validate_or_repair_script,
)


class _BrokenRepairProvider:
    """Returns a valid-looking script, then garbage for the repair round."""

    def __init__(self) -> None:
        self.calls = 0

    async def complete(self, prompt, **kwargs):
        self.calls += 1
        return "{ this is not json,,,"


def _thin_long() -> dict:
    from ytb_pipeline.content_contract import contract_for

    # Suy ra từ contract đang bật thay vì ghim số: cửa sổ runtime là tham số
    # vận hành, và test này không nói gì về độ dài Long.
    target_minutes = int(contract_for("long").viewer_runtime_bounds_sec[0] / 60)
    return {
        "ruleset_id": "2026-07-28.1",
        "slug": "qua-mong",
        "topic": "x",
        "title": "Quá mỏng",
        "description": "d",
        "tags": ["a"],
        "video_type": "long",
        "target_minutes": target_minutes,
        "voice_profile": "knowledge",
        "thumbnail_brief": {
            "visual_contradiction": "a", "subject": "b", "emotion": "c", "headline": "d",
        },
        "sections": [
            {
                "purpose": purpose, "time_goal": 0.4,
                "voiceover": f"Đoạn {index} rất ngắn nên Long sẽ không đạt thời lượng.",
                "visual_intent": "v", "pexels_query": "office desk",
                "caption": "c", "hook": None, "transition": None,
                "payoff": None, "emphasis": None,
            }
            # Đủ số section tối thiểu của contract production, để lỗi DUY NHẤT
            # là "nội dung quá mỏng" — đúng điều kiện kích hoạt bước vá.
            for index, purpose in enumerate(
                ["situation", "core_answer", "evidence", "application", "payoff"] * 5
            )
        ],
        "compliance": {
            "passed": True, "community": "PASS", "copyright": "PASS",
            "accuracy": "PASS", "advertiser": "PASS", "coppa": "PASS", "notes": "n",
        },
    }


async def test_broken_repair_json_raises_a_quality_failure_not_a_crash(tmp_path):
    provider = _BrokenRepairProvider()

    with pytest.raises(IdeationQualityFailure):
        await validate_or_repair_script(
            provider,
            _thin_long(),
            tmp_path / "qua-mong.json",
            ledger_text="",
            expected_video_type="long",
        )

    assert provider.calls >= 1, "the repair round must actually have been attempted"
