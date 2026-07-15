"""Test Agent system (Phase 5) — registry + 5 agent cụ thể.

Dùng `pytest-asyncio` auto mode (asyncio_mode=auto, xem pytest.ini/pyproject)
để gọi trực tiếp `await agent.run(context)` trong test `async def`.
"""

from __future__ import annotations

import subprocess

import pytest

from tests.conftest import chars_for_minutes, passing_compliance
from ytb_pipeline.agents import (
    Agent,
    AgentResult,
    AgentStatus,
    QAAgent,
    ResearchAgent,
    SEOAgent,
    StoryArchitectAgent,
    VoiceDirectorAgent,
    agent_registry,
)
from ytb_pipeline.agents.registry import AgentRegistry
from ytb_pipeline.config.settings import settings
from ytb_pipeline.pkg.models import ComplianceCheck, Script, Segment

GREETING = "Mến chào các bạn,"


def _long_segment(text: str) -> Segment:
    return Segment(caption="", narration=text)


def _make_script(*, target_minutes=None, narration_segments=None, topic="chu de mau",
                  title="Tiêu đề mẫu", compliance_passed=True, code=""):
    compliance = ComplianceCheck(passed=compliance_passed)
    if narration_segments is None:
        if target_minutes is not None:
            first = GREETING + " " + chars_for_minutes(target_minutes)
        else:
            first = chars_for_minutes(1.0)
        narration_segments = [first]
    segments = tuple(
        Segment(caption="", narration=n, code=code) for n in narration_segments
    )
    return Script(
        topic=topic,
        title=title,
        description="d",
        tags=("a",),
        compliance=compliance,
        body="\n".join(narration_segments),
        segments=segments,
        **({"target_minutes": target_minutes} if False else {}),
    )


# ---------------------------------------------------------------------------
# AgentRegistry
# ---------------------------------------------------------------------------

def test_registry_register_get_available():
    registry = AgentRegistry()
    agent = ResearchAgent()
    registry.register(agent)

    assert registry.get("research") is agent
    assert registry.available() == ["research"]


def test_registry_get_unknown_raises_keyerror():
    registry = AgentRegistry()
    with pytest.raises(KeyError):
        registry.get("does_not_exist")


def test_global_agent_registry_has_all_five():
    assert agent_registry.available() == [
        "qa",
        "research",
        "seo",
        "story_architect",
        "voice_director",
    ]


@pytest.mark.parametrize(
    "agent_cls",
    [ResearchAgent, StoryArchitectAgent, VoiceDirectorAgent, SEOAgent, QAAgent],
)
def test_agent_protocol_isinstance(agent_cls):
    assert isinstance(agent_cls(), Agent)


# ---------------------------------------------------------------------------
# AgentResult / AgentStatus
# ---------------------------------------------------------------------------

def test_agent_result_is_frozen():
    result = AgentResult(agent_name="x", status=AgentStatus.SUCCESS, output={})
    with pytest.raises(Exception):
        result.output = {"changed": True}  # type: ignore[misc]


def test_agent_status_enum_values():
    assert AgentStatus.SUCCESS == "success"
    assert AgentStatus.FAILED == "failed"
    assert AgentStatus.SKIPPED == "skipped"


# ---------------------------------------------------------------------------
# ResearchAgent
# ---------------------------------------------------------------------------

def test_research_agent_can_run_with_topic():
    agent = ResearchAgent()
    assert agent.can_run({"topic": "ai"}) is True


def test_research_agent_can_run_without_topic():
    agent = ResearchAgent()
    assert agent.can_run({}) is False


def test_research_agent_required_context_keys():
    agent = ResearchAgent()
    assert "topic" in agent.required_context_keys


async def test_research_agent_run_without_api_key_graceful(monkeypatch):
    monkeypatch.setattr(settings, "youtube_api_key", "")
    agent = ResearchAgent()

    result = await agent.run({"topic": "ai", "type_of_vid": "short"})

    assert result.status == AgentStatus.SUCCESS
    assert result.output == {
        "trending_tags": [],
        "related_topics": [],
        "hashtag_pool": [],
    }


async def test_research_agent_run_with_api_key_calls_research_trending(monkeypatch):
    monkeypatch.setattr(settings, "youtube_api_key", "fake-key")

    def fake_research_trending(region="VN"):
        return {
            "research": [{"topic": "abc"}],
            "seo_pool": {"hashtags": ["#x"], "keywords": ["kw"]},
        }

    monkeypatch.setattr(
        "ytb_pipeline.agents.research_agent.research_mod.research_trending",
        fake_research_trending,
    )
    agent = ResearchAgent()

    result = await agent.run({"topic": "ai", "type_of_vid": "short"})

    assert result.status == AgentStatus.SUCCESS
    assert result.output["related_topics"] == ["abc"]
    assert result.output["hashtag_pool"] == ["#x"]
    assert result.output["trending_tags"] == ["kw"]


async def test_research_agent_run_handles_exception_gracefully(monkeypatch):
    monkeypatch.setattr(settings, "youtube_api_key", "fake-key")

    def boom(region="VN"):
        raise RuntimeError("network down")

    monkeypatch.setattr(
        "ytb_pipeline.agents.research_agent.research_mod.research_trending", boom
    )
    agent = ResearchAgent()

    result = await agent.run({"topic": "ai", "type_of_vid": "short"})

    assert result.status == AgentStatus.FAILED
    assert "network down" in result.error


async def test_qa_agent_rejects_duplicate_title_even_when_topic_differs():
    script = _make_script(
        topic="người que",
        title="Tự Làm: Vì Sao Bạn Muốn Thay Đổi Những Điều Mình Tự Làm?",
    )
    agent = QAAgent()

    result = await agent.run({
        "script": script,
        "done_topics": ["Tự Làm: Vì Sao Bạn Muốn Thay Đổi Những Điều Mình Tự Làm?"],
    })

    assert result.status == AgentStatus.SUCCESS
    assert result.output["passed"] is False
    assert result.output["violations"][0]["rule"] == "series_dedup"


# ---------------------------------------------------------------------------
# StoryArchitectAgent
# ---------------------------------------------------------------------------

def test_story_architect_can_run_with_all_keys():
    agent = StoryArchitectAgent()
    context = {"topic": "ai", "research": {}, "type_of_vid": "short"}
    assert agent.can_run(context) is True


def test_story_architect_can_run_missing_key():
    agent = StoryArchitectAgent()
    assert agent.can_run({"topic": "ai"}) is False


async def test_story_architect_run_without_claude_returns_placeholder(monkeypatch):
    class _UnavailableLLM:
        def is_available(self): return False
        async def complete(self, prompt, **kw): raise RuntimeError("unavailable")

    monkeypatch.setattr(
        "ytb_pipeline.agents.story_architect_agent.get_llm_provider",
        lambda: _UnavailableLLM(),
    )
    agent = StoryArchitectAgent()
    result = await agent.run({"topic": "ai", "research": {}, "type_of_vid": "short"})

    assert result.status == AgentStatus.SUCCESS
    outline = result.output["outline"]
    assert "acts" in outline
    assert len(outline["acts"]) == 3
    assert outline["acts"][0]["act"] == "problem"


async def test_story_architect_run_subprocess_failure_falls_back(monkeypatch):
    class _FailingLLM:
        def is_available(self): return True
        async def complete(self, prompt, **kw): raise RuntimeError("LLM error")

    monkeypatch.setattr(
        "ytb_pipeline.agents.story_architect_agent.get_llm_provider",
        lambda: _FailingLLM(),
    )
    agent = StoryArchitectAgent()
    result = await agent.run({"topic": "ai", "research": {}, "type_of_vid": "short"})

    assert result.status == AgentStatus.SUCCESS
    assert "mechanism" in result.output["outline"]


async def test_story_architect_run_with_claude_output(monkeypatch):
    class _MockLLM:
        def is_available(self): return True
        async def complete(self, prompt, **kw): return "Hook line\nrest of outline"

    monkeypatch.setattr(
        "ytb_pipeline.agents.story_architect_agent.get_llm_provider",
        lambda: _MockLLM(),
    )
    agent = StoryArchitectAgent()
    result = await agent.run({"topic": "ai", "research": {}, "type_of_vid": "short"})

    assert result.status == AgentStatus.SUCCESS
    assert result.output["outline"]["hook"] == "Hook line"


# ---------------------------------------------------------------------------
# VoiceDirectorAgent
# ---------------------------------------------------------------------------

def test_voice_director_can_run_with_script():
    agent = VoiceDirectorAgent()
    assert agent.can_run({"script": {}}) is True


def test_voice_director_can_run_without_script():
    agent = VoiceDirectorAgent()
    assert agent.can_run({}) is False


async def test_voice_director_with_code_segments_recommends_slower_pace():
    agent = VoiceDirectorAgent()
    script = {
        "segments": [
            {"narration": "n1", "code": "print('hi')"},
            {"narration": "n2", "code": ""},
        ],
        "voice": "vi-VN-NamMinhNeural",
    }

    result = await agent.run({"script": script})

    assert result.status == AgentStatus.SUCCESS
    assert result.output["pause_adjustments"]["pace"] == "slow"
    assert result.output["pause_adjustments"]["rate"] < 1.0


async def test_voice_director_without_code_recommends_edge_provider():
    agent = VoiceDirectorAgent()
    script = {
        "segments": [{"narration": "n1", "code": ""}],
        "voice": "vi-VN-NamMinhNeural",
    }

    result = await agent.run({"script": script})

    assert result.status == AgentStatus.SUCCESS
    assert result.output["provider"] == "edge"
    assert result.output["pause_adjustments"]["pace"] == "normal"


async def test_voice_director_entertainment_recommends_fast_profile():
    agent = VoiceDirectorAgent()
    script = {
        "topic": "giải trí người que",
        "segments": [{"narration": "Người que chạy rồi té cái rầm.", "broll": "người que chạy"}],
        "voice": "vi-VN-NamMinhNeural",
    }

    result = await agent.run({"script": script})

    assert result.output["pause_adjustments"]["pace"] == "fast"
    assert result.output["pause_adjustments"]["profile"] == "entertainment"


async def test_voice_director_knowledge_recommends_inspiring_profile():
    agent = VoiceDirectorAgent()
    script = {
        "topic": "kiến thức tâm lý",
        "segments": [{"narration": "Một cơ chế nhỏ có thể đổi hành vi.", "broll": "psychology"}],
        "voice": "vi-VN-NamMinhNeural",
    }

    result = await agent.run({"script": script})

    assert result.output["pause_adjustments"]["pace"] == "inspiring"
    assert result.output["pause_adjustments"]["profile"] == "knowledge"


async def test_voice_director_voice_clone_required_prefers_f5():
    agent = VoiceDirectorAgent()
    script = {"segments": [{"narration": "n1", "code": ""}], "voice": "custom"}

    result = await agent.run({"script": script, "voice_clone_required": True})

    assert result.output["provider"] == "f5"


# ---------------------------------------------------------------------------
# SEOAgent
# ---------------------------------------------------------------------------

def test_seo_agent_required_keys():
    agent = SEOAgent()
    assert set(agent.required_context_keys) == {"title", "topic", "tags", "platform"}


async def test_seo_agent_truncates_title_to_platform_max_chars():
    agent = SEOAgent()
    long_title = "x" * 300
    context = {
        "title": long_title,
        "topic": "ai",
        "tags": ["ai", "tech"],
        "platform": "youtube_short",
    }

    result = await agent.run(context)

    assert result.status == AgentStatus.SUCCESS
    assert len(result.output["optimized_title"]) <= 100


async def test_seo_agent_all_caps_title_penalizes_score():
    agent = SEOAgent()
    context_normal = {
        "title": "Cách học python",
        "topic": "ai",
        "tags": ["ai"],
        "platform": "youtube_short",
    }
    context_caps = {
        "title": "SHOCKING NEWS TODAY",
        "topic": "ai",
        "tags": ["ai"],
        "platform": "youtube_short",
    }

    normal_result = await agent.run(context_normal)
    caps_result = await agent.run(context_caps)

    assert caps_result.output["seo_score"] < normal_result.output["seo_score"]


async def test_seo_agent_adds_shorts_hashtag_for_youtube_short():
    agent = SEOAgent()
    context = {
        "title": "Video ngắn",
        "topic": "ai",
        "tags": ["ai", "tech"],
        "platform": "youtube_short",
    }

    result = await agent.run(context)

    assert result.output["hashtags"][0] == "#Shorts"


# ---------------------------------------------------------------------------
# QAAgent
# ---------------------------------------------------------------------------

def test_qa_agent_required_keys():
    agent = QAAgent()
    assert agent.required_context_keys == ["script"]


async def test_qa_agent_passing_script_returns_no_violations():
    agent = QAAgent()
    script = _make_script(target_minutes=None)

    result = await agent.run({"script": script})

    assert result.status == AgentStatus.SUCCESS
    assert result.output["passed"] is True
    assert result.output["violations"] == []


async def test_qa_agent_compliance_fail_flags_violation():
    agent = QAAgent()
    script = _make_script(target_minutes=None, compliance_passed=False)

    result = await agent.run({"script": script})

    assert result.output["passed"] is False
    rules = [v["rule"] for v in result.output["violations"]]
    assert "compliance" in rules


async def test_qa_agent_self_help_mantra_detected():
    agent = QAAgent()
    script = _make_script(
        target_minutes=None,
        narration_segments=["Just believe in yourself and everything will work out."],
    )

    result = await agent.run({"script": script})

    assert result.output["passed"] is False
    rules = [v["rule"] for v in result.output["violations"]]
    assert "niche_self_help" in rules


async def test_qa_agent_studies_show_without_source_warns():
    agent = QAAgent()
    script = _make_script(
        target_minutes=None,
        narration_segments=["Studies show that this works well for everyone."],
    )

    result = await agent.run({"script": script})

    assert any(w["rule"] == "sourced_claims" for w in result.output["warnings"])


async def test_qa_agent_studies_show_with_source_no_warning():
    agent = QAAgent()
    script = _make_script(
        target_minutes=None,
        narration_segments=["Studies show this works, nguồn: https://example.com/study"],
    )

    result = await agent.run({"script": script})

    assert not any(w["rule"] == "sourced_claims" for w in result.output["warnings"])


async def test_qa_agent_does_not_apply_legacy_stickman_gate():
    agent = QAAgent()
    script = Script(
        topic="giải trí người que",
        title="Người Que Tự Làm Nhà",
        description="Short giải trí.",
        tags=("người que", "giải trí"),
        compliance=ComplianceCheck(passed=True),
        body="",
        segments=(
            Segment(
                caption="Hook",
                narration=chars_for_minutes(1.0) + " Cơ chế này cho thấy bài học về sự cố gắng.",
                broll="abstract decision making",
                emphasis=("cơ chế",),
            ),
        ),
    )

    result = await agent.run({"script": script})

    assert result.output["passed"] is True
    rules = [v["rule"] for v in result.output["violations"]]
    assert not any(rule.startswith("entertainment_") for rule in rules)


async def test_qa_agent_accepts_stickman_visual_gag_structure():
    agent = QAAgent()
    unit = (
        "Người que mở cửa quá tự tin, nhưng tay nắm rơi xuống sàn ngay trước mặt. "
        "Nó cúi nhặt thì bỗng cái cửa tự chạy lùi lại, càng đuổi càng xa. "
        "Cả hành lang đứng hình, cuối cùng hóa ra cái cửa cũng có chân và cú chốt là nó tự khóa người que bên ngoài. "
    )
    script = Script(
        topic="giải trí người que",
        title="Người Que Và Cánh Cửa Biết Chạy",
        description="Short giải trí.",
        tags=("người que", "giải trí"),
        compliance=ComplianceCheck(passed=True),
        body=unit * 4,
        segments=(
            Segment(
                caption="Cửa chạy",
                narration=unit,
                broll="người que mở cửa rồi trượt tay nắm rơi xuống",
                emphasis=("hook",),
            ),
            Segment(
                caption="Đuổi cửa",
                narration=unit,
                broll="người que chạy đuổi theo cánh cửa trên hành lang",
                emphasis=("bất ngờ",),
            ),
            Segment(
                caption="Càng rối",
                narration=unit,
                broll="người que vấp ngã khi cánh cửa bật ngược lại",
                emphasis=("leo thang",),
            ),
            Segment(
                caption="Punchline",
                narration=unit,
                broll="người que đứng hình khi cánh cửa khóa nó bên ngoài",
                emphasis=("punchline",),
            ),
        ),
    )

    result = await agent.run({"script": script})

    assert result.output["passed"] is True


async def test_qa_agent_series_dedup_flags_done_topic():
    agent = QAAgent()
    script = _make_script(target_minutes=None, topic="Chu De Trung Lap")

    result = await agent.run({
        "script": script,
        "done_topics": ["Chu De Trung Lap"],
    })

    assert result.output["passed"] is False
    rules = [v["rule"] for v in result.output["violations"]]
    assert "series_dedup" in rules


async def test_strict_qa_requires_a_complete_concrete_example():
    agent = QAAgent()
    script = _make_script(
        narration_segments=["Ví dụ, một người trì hoãn việc khó mỗi ngày. " + chars_for_minutes(1.0)],
    )

    result = await agent.run({"script": script, "strict": True})

    rules = [v["rule"] for v in result.output["violations"]]
    assert "concrete_example" in rules
    violation = next(v for v in result.output["violations"] if v["rule"] == "concrete_example")
    assert "suggestion" in violation


async def test_strict_qa_rejects_missing_immediate_action_and_final_payoff():
    agent = QAAgent()
    script = _make_script(
        narration_segments=[
            "Ví dụ, khi Lan mở điện thoại ở bàn làm việc, cô chọn đọc thông báo nên bị trễ việc; "
            "vì vậy lần tới bạn có thể đặt điện thoại ngoài bàn trước khi bắt đầu. " + chars_for_minutes(1.0),
        ],
    )

    result = await agent.run({"script": script, "strict": True})

    rules = [v["rule"] for v in result.output["violations"]]
    assert "immediate_action" in rules
    assert "final_payoff" in rules


async def test_strict_qa_blocks_absolute_health_or_finance_claim():
    agent = QAAgent()
    script = _make_script(
        narration_segments=["Cách này chắc chắn chữa khỏi lo âu cho mọi người. " + chars_for_minutes(1.0)],
    )

    result = await agent.run({"script": script, "strict": True})

    rules = [v["rule"] for v in result.output["violations"]]
    assert "health_finance_claim" in rules
    assert result.output["passed"] is False


async def test_qa_agent_semantic_dedup_flags_near_duplicate_topic():
    agent = QAAgent()
    script = _make_script(
        topic="Mất 100 nghìn đau hơn nhặt được 100 nghìn",
        title="Vì sao mất 100 nghìn đau hơn nhặt được 100 nghìn",
    )

    result = await agent.run({
        "script": script,
        "done_topics": ["Mất một trăm nghìn đau hơn có thêm một trăm nghìn"],
    })

    rules = [v["rule"] for v in result.output["violations"]]
    assert "series_semantic_dedup" in rules


async def test_strict_qa_rejects_multiple_competing_mechanisms():
    agent = QAAgent()
    script = _make_script(
        narration_segments=[
            "Vì sao bạn trì hoãn? Ví dụ, khi Lan mở điện thoại ở bàn làm việc, cô chọn đọc thông báo nên trễ việc; "
            "lần tới bạn có thể đặt điện thoại ngoài bàn. Cơ chế né mơ hồ giải thích điều này, nhưng cơ chế so sánh xã hội "
            "và cơ chế thiên kiến xác nhận cũng là trọng tâm. Hãy đặt điện thoại ngoài bàn ngay hôm nay. " + chars_for_minutes(1.0),
        ],
    )

    result = await agent.run({"script": script, "strict": True})

    assert "central_mechanism" in [v["rule"] for v in result.output["violations"]]


async def test_qa_agent_handles_exception_gracefully():
    agent = QAAgent()

    result = await agent.run({"script": object()})

    assert result.status == AgentStatus.SUCCESS or result.status == AgentStatus.FAILED
