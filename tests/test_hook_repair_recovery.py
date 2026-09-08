"""Multi-violation recovery: `series_dedup` and `hook` failing together must
not let one repair silently swallow the other.

Root cause (real Qwen smoke,
`assets/script_revisions/failed_ideation/dung-doan-y-bang-mot-cau-hoi_...json`):
`validate_or_repair_script` only ever repaired `series_dedup` (title/topic).
A hook violation present in the SAME `QA_RESULT` was never touched by any
repair path, so after the identity fix the very next QA round saw the exact
same broken opening with no attempts left — the candidate was rejected for a
violation the loop never tried to fix, not because the fix failed.

These tests use `office-thread-fixture` (character_story, cast lan/duy),
never `ban-so-6`, and drive the REAL `QAAgent` and REAL
`validate_or_repair_script` loop — only the LLM provider is faked, returning
canned, deterministic JSON in the fixed order the loop is expected to call
it (identity repair first, then hook repair), so the test proves the actual
call graph rather than asserting an implementation detail.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ytb_pipeline.config.settings import settings
from ytb_pipeline.orchestrator.ideation_script_fix import validate_or_repair_script

FIXTURES_ROOT = Path(__file__).parent / "fixtures" / "content_profiles"
PROFILE_ID = "office-thread-fixture"
PROFILE_VERSION = "1.0.0"
DUPLICATE_TITLE = "Lan Ngừng Đoán Ý Duy Bằng Một Câu Hỏi"

def _filler(tag: str) -> str:
    # `tag` goes FIRST, not appended at the end: `normalize_short_narration`
    # trims an overlong Short section-by-section with `trim_to_sentence`, and
    # a trailing one-word "sentence" can get cut away entirely, leaving two
    # otherwise-identical fillers indistinguishable (a real false-positive
    # this test hit while being written). Keeping the distinguishing word up
    # front survives any such trim.
    return (
        f"{tag}, đoạn này chỉ để đủ độ dài tối thiểu cho Short theo hợp đồng "
        "thời lượng của profile test, hoàn toàn không liên quan tới nội dung "
        "repair đang được bài kiểm tra này xác nhận, chỉ là phần đệm cho đủ "
        "ký tự cần thiết theo đúng khung thời lượng đã khai báo."
    )


# Anchor without stake — a scene with a moment and a name but nothing at
# risk — matching exactly the shape `_check_story_hook` rejects.
WEAK_OPENING = (
    "Bảy giờ tối, Lan ngồi xuống chiếc bàn quen thuộc cạnh cửa sổ, nhìn ra "
    "ngoài trời đang tối dần."
)
REPAIRED_OPENING = (
    "Bảy giờ tối, Lan mở laptop. Tám giờ cậu phải nộp báo cáo ca chiều cho "
    "quản lý, nhưng vẫn còn ba mục chưa điền xong."
)


def _payload() -> dict:
    def section(purpose: str, voiceover: str) -> dict:
        return {
            "purpose": purpose, "time_goal": 0.4, "voiceover": voiceover,
            "narration": voiceover, "visual_intent": "vi", "pexels_query": "",
            "speaker_id": "narrator", "visual_asset": "opening.png",
            "caption": None, "hook": None, "transition": None,
            "payoff": None, "emphasis": None, "turn": None,
        }

    return {
        "ruleset_id": "2026-07-28.1",
        "profile_id": PROFILE_ID,
        "profile_version": PROFILE_VERSION,
        "slug": "lan-hoi-mot-cau",
        "topic": "Lan hỏi thẳng thay vì đoán ý Duy",
        "title": DUPLICATE_TITLE,
        "description": "d", "tags": ["a"],
        "video_type": "short", "voice_profile": "knowledge",
        "thumbnail_brief": {
            "visual_contradiction": "x", "subject": "y", "emotion": "z", "headline": "h",
        },
        "sections": [
            section("situation", WEAK_OPENING),
            section("core_answer", _filler("Một")),
            section("application", _filler("Hai")),
            section("payoff", "Ba, hãy hỏi thẳng quản lý trong ba mươi giây tới thay vì tự đoán."),
        ],
        "compliance": {
            "passed": True, "community": "PASS", "copyright": "PASS",
            "accuracy": "PASS", "advertiser": "PASS", "coppa": "PASS", "notes": "n",
        },
    }


class _RecordingProvider:
    """Returns canned identity-repair then hook-repair JSON, in call order."""

    def __init__(self) -> None:
        self.prompts: list[str] = []

    async def complete(self, prompt, **kwargs):
        self.prompts.append(prompt)
        if "keys title and topic" in prompt:
            return json.dumps({
                "title": "Lan Chọn Hỏi Thay Vì Tự Đoán",
                "topic": "Lan hỏi thẳng thay vì đoán ý Duy trong ca chiều",
            })
        if "Rewrite ONLY the opening narration" in prompt:
            return json.dumps({"voiceover": REPAIRED_OPENING})
        raise AssertionError(f"Unexpected LLM call: {prompt[:120]!r}")


@pytest.fixture(autouse=True)
def _use_fixture_profiles(monkeypatch):
    monkeypatch.setattr(settings, "content_profiles_dir", FIXTURES_ROOT, raising=False)


async def test_series_dedup_and_hook_failing_together_both_get_repaired(tmp_path):
    provider = _RecordingProvider()

    result = await validate_or_repair_script(
        provider,
        _payload(),
        tmp_path / "lan-hoi-mot-cau.json",
        ledger_text="",
        expected_video_type="short",
        semantic_history=[DUPLICATE_TITLE],
    )

    # Both repair prompts were actually issued, in the fixed order.
    assert len(provider.prompts) == 2
    assert "keys title and topic" in provider.prompts[0]
    assert "Rewrite ONLY the opening narration" in provider.prompts[1]

    # Title/topic changed (dedup fixed) ...
    assert result["title"] != DUPLICATE_TITLE
    # ... and ONLY the opening's spoken text changed for the hook fix.
    assert result["sections"][0]["voiceover"] == REPAIRED_OPENING
    assert result["sections"][0]["narration"] == REPAIRED_OPENING

    # Nothing else was touched: section count, purposes, other sections'
    # text, payoff/CTA, and compliance survive untouched.
    assert len(result["sections"]) == 4
    assert [s["purpose"] for s in result["sections"]] == [
        "situation", "core_answer", "application", "payoff",
    ]
    assert result["sections"][1]["voiceover"] == _filler("Một")
    assert result["sections"][2]["voiceover"] == _filler("Hai")
    assert "hãy hỏi thẳng" in result["sections"][3]["voiceover"]
    assert result["compliance"]["passed"] is True


async def test_hook_repair_is_single_shot_and_does_not_loop_forever(tmp_path):
    """If the model's hook rewrite is STILL rejected, the loop must fail
    closed after one bounded attempt, never retry the same repair forever."""
    class _StubbornProvider:
        def __init__(self) -> None:
            self.calls = 0

        async def complete(self, prompt, **kwargs):
            self.calls += 1
            if "keys title and topic" in prompt:
                return json.dumps({"title": "Lan Chọn Hỏi Thay Vì Tự Đoán", "topic": "t2"})
            if "Rewrite ONLY the opening narration" in prompt:
                # Still no stake — the QA gate must reject this again.
                return json.dumps({"voiceover": "Bảy giờ tối, Lan ngồi xuống bàn làm việc."})
            raise AssertionError(f"Unexpected LLM call: {prompt[:120]!r}")

    provider = _StubbornProvider()

    from ytb_pipeline.orchestrator.ideation_script_fix import IdeationQualityFailure

    with pytest.raises(IdeationQualityFailure):
        await validate_or_repair_script(
            provider,
            _payload(),
            tmp_path / "lan-hoi-mot-cau.json",
            ledger_text="",
            expected_video_type="short",
            semantic_history=[DUPLICATE_TITLE],
        )

    # Exactly one identity call and one hook call — never a retry loop.
    assert provider.calls == 2
