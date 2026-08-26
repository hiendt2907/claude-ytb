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


async def test_ideation_rejects_missing_release_purpose_before_qa(tmp_path):
    """Generation admission must match preflight's required-purpose gate.

    A candidate Long that omitted ``evidence`` previously passed the ideation
    schema and rule-based QA, then failed only when batch preflight ran.  It
    must be rejected before an LLM repair or a queue write is attempted.
    """
    payload = _thin_long()
    for section in payload["sections"]:
        if section["purpose"] == "evidence":
            section["purpose"] = "application"

    provider = _BrokenRepairProvider()
    with pytest.raises(IdeationQualityFailure, match="evidence"):
        await validate_or_repair_script(
            provider,
            payload,
            tmp_path / "missing-evidence.json",
            ledger_text="",
            expected_video_type="long",
        )

    assert provider.calls == 0


async def test_long_can_use_two_bounded_extensions_before_rejection(tmp_path, monkeypatch):
    """A small first delta must not consume the whole Long-repair budget.

    Free/fast models regularly under-deliver a large requested character count.
    The repair loop may request one more bounded delta, but never a full rewrite.
    """
    from types import SimpleNamespace
    import ytb_pipeline.orchestrator.ideation_script_fix as script_fix

    class TwoStepProvider:
        def __init__(self) -> None:
            self.calls = 0
            self.max_tokens: list[int] = []

        async def complete(self, *_args, **_kwargs):
            self.calls += 1
            self.max_tokens.append(_kwargs["max_tokens"])
            added = "Một chi tiết cụ thể của buổi sáng ở bàn số 6. " * (
                2 if self.calls == 1 else 230
            )
            return json.dumps({
                "sections": [{
                    "purpose": "evidence",
                    "time_goal": 0.5,
                    "voiceover": added,
                    "visual_intent": "Một hành động đang diễn ra.",
                    "pexels_query": "office desk",
                    "caption": "",
                    "hook": False,
                    "transition": None,
                    "payoff": None,
                    "emphasis": None,
                }],
            }, ensure_ascii=False)

    class PassingQA:
        async def run(self, _context):
            return SimpleNamespace(status=script_fix.AgentStatus.SUCCESS, output={"passed": True})

    monkeypatch.setattr(script_fix, "QAAgent", PassingQA)
    def fake_load_script(path):
        candidate = json.loads(path.read_text(encoding="utf-8"))
        total = sum(
            len(section.get("voiceover", ""))
            for section in candidate.get("sections", [])
            if isinstance(section, dict)
        )
        if total < 5_000:
            raise ValueError("nội dung quá mỏng")
        return SimpleNamespace()

    monkeypatch.setattr(script_fix, "load_script", fake_load_script)
    provider = TwoStepProvider()

    result = await validate_or_repair_script(
        provider,
        _thin_long(),
        tmp_path / "two-deltas.json",
        ledger_text="",
        max_attempts=3,
        strict=False,
        expected_video_type="long",
    )

    assert provider.calls == 2
    assert provider.max_tokens == [4096, 4096]
    assert len(result["sections"]) == len(_thin_long()["sections"]) + 2
