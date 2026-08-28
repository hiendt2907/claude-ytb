"""Bounded recovery for a production narrator-reflection rejection.

Gate 1 produced two otherwise-valid Long candidates whose only remaining QA
violation was ``narrator_reflection``.  The repair loop had narrow recovery
for identity and hook failures, but no way to apply the QA suggestion to the
closing.  These tests keep the boundary honest: exactly the final spoken
section may change, and the repair is attempted at most once.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import ytb_pipeline.orchestrator.ideation_script_fix as script_fix


BROKEN_CLOSING = (
    "Minh đã gửi dòng cảnh báo và giờ chỉ có thể chờ cuộc họp trả lời. "
    "Tập sau, Minh sẽ biết điều gì xảy ra."
)
REPAIRED_CLOSING = (
    "Nếu bạn từng giữ lại một cảnh báo vì sợ mình làm chậm cả nhóm, có lẽ "
    "sự im lặng ấy cũng có một cái giá. Tập sau, Minh sẽ biết cuộc họp đã "
    "đọc dòng cậu gửi như thế nào."
)


def _payload() -> dict:
    return {
        "slug": "gate-one-reflection-repair",
        "topic": "một cảnh báo chưa được nói ra",
        "title": "Dòng Cảnh Báo Trước Cuộc Họp",
        "video_type": "long",
        "sections": [
            {
                "purpose": "situation",
                "voiceover": "Bảy giờ, cuộc họp còn một tiếng và rủi ro vẫn chưa được ghi.",
                "narration": "Bảy giờ, cuộc họp còn một tiếng và rủi ro vẫn chưa được ghi.",
                "speaker_id": "narrator",
            },
            {
                "purpose": "payoff",
                "voiceover": BROKEN_CLOSING,
                "narration": BROKEN_CLOSING,
                "speaker_id": "narrator",
            },
        ],
        "continuity": {"threads_opened": ["Phản hồi của cuộc họp."]},
        "compliance": {"passed": True},
    }


def _isolate_contract(monkeypatch, qa_outputs: list[dict]) -> None:
    """Exercise the real repair loop while isolating unrelated schema gates."""

    monkeypatch.setattr(
        script_fix,
        "validate_script_payload",
        lambda _payload: SimpleNamespace(publishable=True, findings=()),
    )
    monkeypatch.setattr(script_fix, "validate_release_purposes", lambda _payload: None)
    monkeypatch.setattr(script_fix, "load_content_profile", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(script_fix, "load_script", lambda _path: SimpleNamespace())

    class SequencedQA:
        def __init__(self) -> None:
            self.outputs = iter(qa_outputs)

        async def run(self, _context):
            return SimpleNamespace(
                status=script_fix.AgentStatus.SUCCESS,
                output=next(self.outputs),
            )

    monkeypatch.setattr(script_fix, "QAAgent", SequencedQA)


class _ClosingProvider:
    def __init__(self, response: str = REPAIRED_CLOSING) -> None:
        self.response = response
        self.calls: list[tuple[str, dict]] = []

    async def complete(self, prompt, **kwargs):
        self.calls.append((prompt, kwargs))
        return json.dumps({"voiceover": self.response}, ensure_ascii=False)


@pytest.mark.asyncio
async def test_narrator_reflection_repair_changes_only_final_voiceover(monkeypatch, tmp_path):
    _isolate_contract(
        monkeypatch,
        [
            {
                "passed": False,
                "violations": [{"rule": "narrator_reflection", "detail": "closing is not direct"}],
            },
            {"passed": True, "violations": []},
        ],
    )
    original = _payload()
    provider = _ClosingProvider()

    result = await script_fix.validate_or_repair_script(
        provider,
        original,
        tmp_path / "candidate.json",
        ledger_text="",
        max_attempts=3,
        strict=True,
    )

    assert len(provider.calls) == 1
    prompt, kwargs = provider.calls[0]
    assert "Rewrite ONLY the final narrator reflection" in prompt
    assert kwargs["response_schema"]["additionalProperties"] is False
    assert result["sections"][-1]["voiceover"] == REPAIRED_CLOSING
    assert result["sections"][-1]["narration"] == REPAIRED_CLOSING
    assert result["sections"][0] == original["sections"][0]
    assert result["title"] == original["title"]
    assert result["continuity"] == original["continuity"]
    assert original["sections"][-1]["voiceover"] == BROKEN_CLOSING


@pytest.mark.asyncio
async def test_narrator_reflection_repair_is_single_shot(monkeypatch, tmp_path):
    rejection = {
        "passed": False,
        "violations": [{"rule": "narrator_reflection", "detail": "still invalid"}],
    }
    _isolate_contract(monkeypatch, [rejection, rejection])
    provider = _ClosingProvider(response=BROKEN_CLOSING)

    with pytest.raises(script_fix.IdeationQualityFailure):
        await script_fix.validate_or_repair_script(
            provider,
            _payload(),
            tmp_path / "candidate.json",
            ledger_text="",
            max_attempts=3,
            strict=True,
        )

    assert len(provider.calls) == 1
