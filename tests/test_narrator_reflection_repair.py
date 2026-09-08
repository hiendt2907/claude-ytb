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


def _short_funnel_payload() -> dict:
    payload = _payload()
    payload["video_type"] = "short"
    payload["strategy"] = {
        "long_form_slug": "minh-neu-rui-ro-trong-cuoc-hop",
        "cta_target": "minh-neu-rui-ro-trong-cuoc-hop",
        "source_long_slug": "minh-neu-rui-ro-trong-cuoc-hop",
    }
    closing = (
        "Có lẽ nếu bạn nói ra, người khác sẽ có chỗ kiểm tra lại. "
        "Xem video dài minh-neu-rui-ro-trong-cuoc-hop."
    )
    payload["sections"][-1]["voiceover"] = closing
    payload["sections"][-1]["narration"] = closing
    return payload


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


def test_narrator_reflection_prompt_locks_existing_short_funnel_bridge():
    prompt = script_fix.narrator_reflection_repair_prompt(
        _short_funnel_payload(),
        "closing is not direct",
    )

    assert "MANDATORY SHORT FUNNEL BRIDGE" in prompt
    assert "minh-neu-rui-ro-trong-cuoc-hop" in prompt
    assert "spoken voiceover" in prompt


def test_narrator_reflection_repair_rejects_dropped_short_funnel_bridge():
    with pytest.raises(ValueError, match="funnel bridge"):
        script_fix.apply_narrator_reflection_repair(
            _short_funnel_payload(),
            {"voiceover": "Có lẽ nếu bạn nói ra, người khác sẽ có chỗ kiểm tra lại."},
        )


def test_short_normalization_does_not_trim_away_required_funnel_bridge():
    payload = _short_funnel_payload()
    payload["profile_id"] = "ban-so-6"
    payload["profile_version"] = "2.1.0"
    payload["strategy"]["hook"] = {
        "core_answer": "Im lặng sẽ làm mất chỗ để người khác xác nhận lại."
    }
    payload["sections"] = [
        {
            "purpose": "situation",
            "voiceover": "Còn 48 phút, nhưng Minh vẫn chưa biết nên im hay nói.",
        },
        {
            "purpose": "core_answer",
            "voiceover": (
                "Im lặng sẽ làm mất chỗ để người khác xác nhận lại. "
                "Khi điều mình thấy chưa được kiểm tra, nó chỉ là một dòng trống."
            ),
        },
        {"purpose": "evidence", "voiceover": "Dòng trống này cậu chừa ra để làm gì?"},
        {"purpose": "evidence", "voiceover": "Còn số cũ? Cậu vẫn chưa nói nó cũ bao lâu."},
        {
            "purpose": "application",
            "voiceover": (
                "Số mới này không phải của em, em chưa được quyền sửa. "
                "Em sợ họ hỏi vì sao tối qua em chưa đối chiếu."
            ),
        },
        {
            "purpose": "evidence",
            "voiceover": (
                "Trong cuộc họp, dữ liệu em đang chiếu cũ hơn hai ngày, "
                "và em chưa đối chiếu xong."
            ),
        },
        {"purpose": "evidence", "voiceover": "Minh gật. Việc được ghi vào sổ."},
        {
            "purpose": "application",
            "voiceover": (
                "Người phụ trách giao việc đối chiếu trước cuối ngày. "
                "Minh gật đầu. Không ai nói cậu đúng. "
                "Người phụ trách dừng giữa bảng rồi ghi việc vào sổ."
            ),
        },
        {
            "purpose": "payoff",
            "voiceover": (
                "Có lẽ bạn cũng từng im lặng để tránh một câu hỏi, rồi giữ lại một "
                "con số mình biết chưa chắc đúng. Nói ra chưa chắc được xác nhận "
                "ngay, nhưng im lặng cũng để lại một việc phải làm đến cuối ngày. "
                "Tập sau, video dài minh-neu-rui-ro-trong-cuoc-hop sẽ cho thấy "
                "việc đối chiếu đó dẫn câu chuyện đi tiếp thế nào."
            ),
        },
    ]

    normalized, note = script_fix.normalize_short_narration(payload, "short")

    assert note is not None
    assert "video dài minh-neu-rui-ro-trong-cuoc-hop" in normalized["sections"][-1]["voiceover"]
