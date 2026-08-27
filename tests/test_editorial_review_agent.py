"""Profile-scoped LLM editorial review — a quality gate deterministic
`script_contract` cannot express (dialogue quality, narrator discipline,
causal-turn sense, timeline consistency).

Compatibility is the load-bearing rule here: a profile that never declares
`editorial_review` (every real profile today — ban-so-6, one-cup-cafe-6h)
must never trigger an LLM call from this module. No unit test may call a
real LLM/HTTP provider (CLAUDE.md testing rule) — every provider here is a
fake in-process object.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ytb_pipeline.content_profiles import load_content_profile


def _write_profile(
    root: Path, profile_id: str, *, editorial_review: dict | None = None,
) -> Path:
    folder = root / profile_id
    (folder / "prompts").mkdir(parents=True)
    (folder / "assets").mkdir()
    (folder / "prompts" / "editorial.md").write_text("Editorial rules.", encoding="utf-8")
    (folder / "prompts" / "review-rubric.md").write_text(
        "Narrator must narrate, never speak as a character.", encoding="utf-8"
    )
    prompts = {"editorial": "prompts/editorial.md"}
    if editorial_review is not None:
        prompts["review_rubric"] = "prompts/review-rubric.md"
    payload = {
        "schema_version": 1,
        "profile_id": profile_id,
        "version": "1.0.0",
        "display_name": profile_id,
        "topic": "Topic",
        "narrative_mode": "character_story",
        "prompts": prompts,
        "formats": {
            "short": {"viewer_min_sec": 30, "viewer_max_sec": 45, "min_sections": 4},
            "long": {"viewer_min_sec": 300, "viewer_max_sec": 420, "min_sections": 10},
        },
        "providers": {
            "llm": "xkiro", "tts": "xkiro", "render": "story",
            "broll_strategy": "none", "broll_allow_downloads": False,
        },
        "voice_cast": {"narrator": "standard-female-vietnamese"},
        "content_rules": {"require_pexels_query": False, "require_short_source_trace": False},
        "render": {
            "assets_dir": "assets", "show_captions": True,
            "inter_segment_gap_sec": 0.2, "transition_overlap_sec": 0.0,
        },
    }
    if editorial_review is not None:
        payload["editorial_review"] = editorial_review
    (folder / "profile.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return folder


class _FakeProvider:
    def __init__(self, response: str):
        self.response = response
        self.calls = 0

    async def complete(self, prompt, *, system, max_tokens, temperature, json_output):
        self.calls += 1
        self.last_prompt = prompt
        return self.response


def _valid_review_gate_payload(profile) -> dict:
    """A Short that passes `validate_script_payload` for `_write_profile`'s
    fixture shape (min_sections=4, character_story, no auto_visuals/turns)."""
    from ytb_pipeline.content_contract import CONTRACT_VERSION

    return {
        "ruleset_id": CONTRACT_VERSION,
        "profile_id": profile.profile_id,
        "profile_version": profile.version,
        "slug": "s", "topic": "t", "title": "ti", "description": "d", "tags": [],
        "video_type": "short", "voice_profile": "knowledge",
        "thumbnail_brief": {
            "visual_contradiction": "x", "subject": "y", "emotion": "z", "headline": "h",
        },
        "sections": [
            {
                "purpose": purpose, "time_goal": 0.3,
                "voiceover": f"Doan {i} noi dung day du de vuot qua nguong thoi luong toi thieu cua short nay. " * 3,
                "visual_intent": "vi", "speaker_id": "narrator", "visual_asset": "opening.png",
                "caption": None, "hook": None, "transition": None, "payoff": None, "emphasis": None,
            }
            for i, purpose in enumerate(["situation", "core_answer", "application", "payoff"])
        ],
        "compliance": {"passed": True},
    }


def _script_payload(profile) -> dict:
    return {
        "profile_id": profile.profile_id, "profile_version": profile.version,
        "slug": "s", "title": "t", "sections": [{"purpose": "situation", "voiceover": "abc"}],
    }


def test_profile_without_editorial_review_never_calls_the_llm(tmp_path):
    from ytb_pipeline.agents.editorial_review_agent import run_editorial_review
    import asyncio

    _write_profile(tmp_path, "no-review-fixture")
    profile = load_content_profile("no-review-fixture", profiles_dir=tmp_path)
    provider = _FakeProvider("{}")

    result = asyncio.run(run_editorial_review(
        profile, _script_payload(profile), provider=provider, cache_dir=tmp_path / "cache",
    ))

    assert result is None
    assert provider.calls == 0


def test_profile_with_review_enabled_calls_the_llm_and_parses_the_verdict(tmp_path):
    from ytb_pipeline.agents.editorial_review_agent import run_editorial_review
    import asyncio

    _write_profile(
        tmp_path, "review-fixture",
        editorial_review={"enabled": True, "rubric_prompt_name": "review_rubric"},
    )
    profile = load_content_profile("review-fixture", profiles_dir=tmp_path)
    provider = _FakeProvider(json.dumps({
        "passed": False,
        "blocking_findings": ["Narrator speaks Minh's line directly in section 2."],
        "section_refs": [2],
        "repair_brief": "Move the direct address into a character-owned section.",
    }))

    result = asyncio.run(run_editorial_review(
        profile, _script_payload(profile), provider=provider, cache_dir=tmp_path / "cache",
    ))

    assert result is not None
    assert result.passed is False
    assert result.blocking_findings == ("Narrator speaks Minh's line directly in section 2.",)
    assert result.section_refs == (2,)
    assert provider.calls == 1
    assert "Narrator must narrate" in provider.last_prompt


def test_review_rejects_a_self_approved_score_below_the_profile_bar(tmp_path):
    """A model cannot approve its own weak draft by setting passed=true.

    The product bar is profile-owned: a script only clears editorial review
    when the independent score reaches that profile's declared threshold.
    """
    from ytb_pipeline.agents.editorial_review_agent import run_editorial_review
    import asyncio

    _write_profile(
        tmp_path, "scored-review-fixture",
        editorial_review={
            "enabled": True,
            "rubric_prompt_name": "review_rubric",
            "minimum_score": 9,
            "max_rewrites": 1,
        },
    )
    profile = load_content_profile("scored-review-fixture", profiles_dir=tmp_path)
    provider = _FakeProvider(json.dumps({
        "passed": True,
        "overall_score": 8,
        "dimension_scores": {
            "human_truth": 9,
            "spoken_naturalness": 8,
            "causal_coherence": 9,
            "role_fidelity": 9,
            "useful_restraint": 9,
        },
        "blocking_findings": [],
        "section_refs": [],
        "repair_brief": "",
    }))

    result = asyncio.run(run_editorial_review(
        profile, _script_payload(profile), provider=provider, cache_dir=tmp_path / "cache",
    ))

    assert result is not None
    assert result.overall_score == 8
    assert result.passed is False
    assert any("8/10" in finding for finding in result.blocking_findings)


@pytest.mark.parametrize("dimension_scores", [
    {},
    {
        "human_truth": 9,
        "spoken_naturalness": 9,
        "causal_coherence": 9,
        "role_fidelity": 8,
        "useful_restraint": 9,
    },
])
def test_review_requires_every_declared_dimension_to_clear_the_profile_bar(tmp_path, dimension_scores):
    """An overall 9 cannot hide a missing or weak essential dimension."""
    from ytb_pipeline.agents.editorial_review_agent import run_editorial_review
    import asyncio

    _write_profile(
        tmp_path, "dimension-review-fixture",
        editorial_review={
            "enabled": True,
            "rubric_prompt_name": "review_rubric",
            "minimum_score": 9,
            "max_rewrites": 1,
        },
    )
    profile = load_content_profile("dimension-review-fixture", profiles_dir=tmp_path)
    provider = _FakeProvider(json.dumps({
        "passed": True,
        "overall_score": 9,
        "dimension_scores": dimension_scores,
        "blocking_findings": [],
        "section_refs": [],
        "repair_brief": "",
    }))

    if not dimension_scores:
        with pytest.raises(ValueError, match="dimension_scores"):
            asyncio.run(run_editorial_review(
                profile, _script_payload(profile), provider=provider, cache_dir=tmp_path / "cache",
            ))
    else:
        result = asyncio.run(run_editorial_review(
            profile, _script_payload(profile), provider=provider, cache_dir=tmp_path / "cache",
        ))
        assert result is not None
        assert result.passed is False
        assert any("role_fidelity" in finding for finding in result.blocking_findings)


def test_review_is_cached_by_profile_fingerprint_and_script_content(tmp_path):
    from ytb_pipeline.agents.editorial_review_agent import run_editorial_review
    import asyncio

    _write_profile(
        tmp_path, "review-fixture",
        editorial_review={"enabled": True, "rubric_prompt_name": "review_rubric"},
    )
    profile = load_content_profile("review-fixture", profiles_dir=tmp_path)
    provider = _FakeProvider(json.dumps({
        "passed": True, "blocking_findings": [], "section_refs": [], "repair_brief": "",
    }))
    cache_dir = tmp_path / "cache"
    payload = _script_payload(profile)

    first = asyncio.run(run_editorial_review(profile, payload, provider=provider, cache_dir=cache_dir))
    second = asyncio.run(run_editorial_review(profile, payload, provider=provider, cache_dir=cache_dir))

    assert first.passed is True
    assert second.passed is True
    assert provider.calls == 1, "unchanged script must not trigger a second LLM call"


def test_persisted_editorial_evidence_is_excluded_from_review_prompt_and_cache(tmp_path):
    """An audit receipt must never become self-referential reviewer input."""
    from ytb_pipeline.agents.editorial_review_agent import run_editorial_review
    import asyncio

    _write_profile(
        tmp_path, "evidence-isolation-fixture",
        editorial_review={"enabled": True, "rubric_prompt_name": "review_rubric"},
    )
    profile = load_content_profile("evidence-isolation-fixture", profiles_dir=tmp_path)
    payload = _script_payload(profile)

    class CapturingProvider:
        def __init__(self):
            self.calls = 0
            self.prompts: list[str] = []

        async def complete(self, prompt, **_kwargs):
            self.calls += 1
            self.prompts.append(prompt)
            return json.dumps({
                "passed": True, "blocking_findings": [], "section_refs": [], "repair_brief": "",
            })

    provider = CapturingProvider()
    cache_dir = tmp_path / "cache"
    first = asyncio.run(run_editorial_review(profile, payload, provider=provider, cache_dir=cache_dir))
    with_evidence = {
        **payload,
        "_editorial_review": {"passed": True, "overall_score": 10, "dimension_scores": {}},
    }
    second = asyncio.run(run_editorial_review(
        profile, with_evidence, provider=provider, cache_dir=cache_dir,
    ))

    assert first is not None and second is not None
    assert provider.calls == 1
    assert "_editorial_review" not in provider.prompts[0]


def test_cached_review_is_rechecked_against_the_current_score_contract(tmp_path):
    """A cache written before score dimensions existed cannot approve a draft."""
    from ytb_pipeline.agents import editorial_review_agent as review_agent
    from ytb_pipeline.agents.editorial_review_agent import run_editorial_review
    import asyncio

    _write_profile(
        tmp_path, "stale-cache-review-fixture",
        editorial_review={
            "enabled": True,
            "rubric_prompt_name": "review_rubric",
            "minimum_score": 9,
            "max_rewrites": 1,
        },
    )
    profile = load_content_profile("stale-cache-review-fixture", profiles_dir=tmp_path)
    payload = _script_payload(profile)
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    cache_path = cache_dir / f"{review_agent._cache_key(profile, payload)}.json"
    cache_path.write_text(json.dumps({
        "passed": True,
        "overall_score": 9,
        "dimension_scores": {},
        "blocking_findings": [],
        "section_refs": [],
        "repair_brief": "",
    }), encoding="utf-8")

    with pytest.raises(ValueError, match="dimension_scores"):
        asyncio.run(run_editorial_review(
            profile, payload, provider=_FakeProvider("should not be called"), cache_dir=cache_dir,
        ))


def test_editorial_review_rejects_a_malformed_llm_response(tmp_path):
    from ytb_pipeline.agents.editorial_review_agent import run_editorial_review
    import asyncio

    _write_profile(
        tmp_path, "review-fixture",
        editorial_review={"enabled": True, "rubric_prompt_name": "review_rubric"},
    )
    profile = load_content_profile("review-fixture", profiles_dir=tmp_path)
    provider = _FakeProvider("not json")

    with pytest.raises(ValueError):
        asyncio.run(run_editorial_review(
            profile, _script_payload(profile), provider=provider, cache_dir=tmp_path / "cache",
        ))


def test_loader_rejects_enabled_review_with_unknown_rubric_prompt_name(tmp_path):
    from ytb_pipeline.content_profiles import ContentProfileError

    _write_profile(
        tmp_path, "bad-review-fixture",
        editorial_review={"enabled": True, "rubric_prompt_name": "does_not_exist"},
    )
    with pytest.raises(ContentProfileError):
        load_content_profile("bad-review-fixture", profiles_dir=tmp_path)


def test_real_profiles_declare_a_nine_of_ten_editorial_review_bar():
    """The production profiles must use the same content gate as test runs."""
    for profile_id in ("ban-so-6", "one-cup-cafe-6h"):
        profile = load_content_profile(profile_id)
        assert profile.editorial_review is not None
        assert profile.editorial_review.enabled is True
        assert profile.editorial_review.minimum_score == 9
        assert profile.editorial_review.max_rewrites == 2


def test_validate_or_repair_script_blocks_release_when_review_fails(tmp_path, monkeypatch):
    """Integration seam: validate_or_repair_script must consult editorial
    review before accepting a QA-passed script, for a profile that opts in.

    QAAgent itself has its own extensive test suite; here it is stubbed to a
    fixed SUCCESS/passed=True so this test isolates the NEW review gate."""
    import asyncio
    from ytb_pipeline.agents.base import AgentResult, AgentStatus
    from ytb_pipeline.orchestrator.ideation_script_fix import (
        IdeationQualityFailure,
        validate_or_repair_script,
    )
    from ytb_pipeline.config.settings import settings
    import ytb_pipeline.orchestrator.ideation_script_fix as fix_module

    _write_profile(
        tmp_path, "review-gate-fixture",
        editorial_review={"enabled": True, "rubric_prompt_name": "review_rubric"},
    )
    monkeypatch.setattr(settings, "content_profiles_dir", tmp_path, raising=False)
    monkeypatch.setattr(settings, "assets_dir", tmp_path / "assets_root", raising=False)
    profile = load_content_profile("review-gate-fixture", profiles_dir=tmp_path)

    async def _fake_qa_run(self, context):
        return AgentResult(agent_name="qa", status=AgentStatus.SUCCESS, output={"passed": True})

    monkeypatch.setattr(fix_module.QAAgent, "run", _fake_qa_run)

    payload = _valid_review_gate_payload(profile)

    class _RejectingReviewProvider:
        async def complete(self, prompt, **kwargs):
            return json.dumps({
                "passed": False,
                "blocking_findings": ["Narrator speaks a character line directly."],
                "section_refs": [1],
                "repair_brief": "Split section 1 into narrator + character turns.",
            })

    with pytest.raises(IdeationQualityFailure) as excinfo:
        asyncio.run(validate_or_repair_script(
            _RejectingReviewProvider(), payload, tmp_path / "s.json", "", max_attempts=1,
        ))
    assert "editorial_review" in str(excinfo.value)


def test_validate_or_repair_script_returns_when_review_passes(tmp_path, monkeypatch):
    import asyncio
    from ytb_pipeline.agents.base import AgentResult, AgentStatus
    from ytb_pipeline.orchestrator.ideation_script_fix import validate_or_repair_script
    from ytb_pipeline.config.settings import settings
    import ytb_pipeline.orchestrator.ideation_script_fix as fix_module

    _write_profile(
        tmp_path, "review-gate-fixture",
        editorial_review={"enabled": True, "rubric_prompt_name": "review_rubric"},
    )
    monkeypatch.setattr(settings, "content_profiles_dir", tmp_path, raising=False)
    monkeypatch.setattr(settings, "assets_dir", tmp_path / "assets_root", raising=False)
    profile = load_content_profile("review-gate-fixture", profiles_dir=tmp_path)

    async def _fake_qa_run(self, context):
        return AgentResult(agent_name="qa", status=AgentStatus.SUCCESS, output={"passed": True})

    monkeypatch.setattr(fix_module.QAAgent, "run", _fake_qa_run)

    payload = _valid_review_gate_payload(profile)

    class _PassingReviewProvider:
        async def complete(self, prompt, **kwargs):
            return json.dumps({
                "passed": True,
                "overall_score": 9,
                "dimension_scores": {
                    "human_truth": 9,
                    "spoken_naturalness": 9,
                    "causal_coherence": 9,
                    "role_fidelity": 9,
                    "useful_restraint": 9,
                },
                "blocking_findings": [],
                "section_refs": [],
                "repair_brief": "",
            })

    log_path = tmp_path / "ideation.log"
    result = asyncio.run(validate_or_repair_script(
        _PassingReviewProvider(), payload, tmp_path / "s.json", "", max_attempts=1,
        log_path=log_path,
    ))
    assert result["profile_id"] == profile.profile_id
    assert result["_editorial_review"]["passed"] is True
    assert result["_editorial_review"]["overall_score"] == 9
    assert 'EDITORIAL_REVIEW_RESULT 1' in log_path.read_text(encoding="utf-8")


def test_editorial_rejection_rewrites_then_re_reviews_until_the_profile_bar(tmp_path, monkeypatch):
    """A weak but schema-valid draft gets one profile-authorized rewrite.

    This is deliberately an integration test: deterministic QA passes both
    versions, so only the editorial score can keep the first draft from
    leaking into the queue.
    """
    import asyncio
    from ytb_pipeline.agents.base import AgentResult, AgentStatus
    from ytb_pipeline.orchestrator.ideation_script_fix import validate_or_repair_script
    from ytb_pipeline.config.settings import settings
    import ytb_pipeline.orchestrator.ideation_script_fix as fix_module

    _write_profile(
        tmp_path, "rewrite-review-fixture",
        editorial_review={
            "enabled": True,
            "rubric_prompt_name": "review_rubric",
            "minimum_score": 9,
            "max_rewrites": 1,
        },
    )
    monkeypatch.setattr(settings, "content_profiles_dir", tmp_path, raising=False)
    monkeypatch.setattr(settings, "assets_dir", tmp_path / "assets_root", raising=False)
    profile = load_content_profile("rewrite-review-fixture", profiles_dir=tmp_path)

    async def _fake_qa_run(self, context):
        return AgentResult(agent_name="qa", status=AgentStatus.SUCCESS, output={"passed": True})

    monkeypatch.setattr(fix_module.QAAgent, "run", _fake_qa_run)
    original = _valid_review_gate_payload(profile)
    rewritten_opening = "Đoạn mở đã được viết lại thành lời kể cụ thể, không còn giọng thuyết minh."

    class _ReviewThenRewriteProvider:
        def __init__(self):
            self.review_calls = 0
            self.rewrite_calls = 0

        async def complete(self, prompt, **kwargs):
            if prompt.startswith("Review this Vietnamese YouTube script JSON"):
                self.review_calls += 1
                if self.review_calls == 1:
                    return json.dumps({
                        "passed": False,
                        "overall_score": 6,
                        "dimension_scores": {
                            "human_truth": 6, "spoken_naturalness": 6,
                            "causal_coherence": 8, "role_fidelity": 8,
                            "useful_restraint": 7,
                        },
                        "blocking_findings": ["Đoạn mở nghe như một bản thuyết minh."],
                        "section_refs": [1],
                        "repair_brief": "Viết lại toàn bộ transcript thành văn nói cụ thể.",
                    })
                return json.dumps({
                    "passed": True,
                    "overall_score": 9,
                    "dimension_scores": {
                        "human_truth": 9, "spoken_naturalness": 9,
                        "causal_coherence": 9, "role_fidelity": 9,
                        "useful_restraint": 9,
                    },
                    "blocking_findings": [], "section_refs": [], "repair_brief": "",
                })
            assert "Editorial review findings" in prompt
            assert "do not rewrite the entire script" in prompt.casefold()
            self.rewrite_calls += 1
            return json.dumps({"sections": [{"section_index": 1, "voiceover": rewritten_opening}]})

    provider = _ReviewThenRewriteProvider()
    result = asyncio.run(validate_or_repair_script(
        # A profile-authorized editorial rewrite must remain available even
        # when the deterministic attempt budget has just been exhausted.
        provider, original, tmp_path / "s.json", "", max_attempts=1,
    ))

    # Bounded: only the cited section's spoken text was asked to change, title
    # is untouched, and section structure/order/count survives — a full
    # rewrite is not what this LLM response shape can do.
    assert result["title"] == original["title"]
    assert rewritten_opening in result["sections"][0]["voiceover"]
    assert [s["purpose"] for s in result["sections"]] == [s["purpose"] for s in original["sections"]]
    assert len(result["sections"]) == len(original["sections"])
    assert provider.rewrite_calls == 1
    assert provider.review_calls == 2


def test_editorial_only_retry_never_spends_a_contract_repair_call(tmp_path, monkeypatch):
    """A bad editorial rewrite fails closed instead of borrowing a hook retry."""
    import asyncio
    from ytb_pipeline.agents.base import AgentResult, AgentStatus
    from ytb_pipeline.orchestrator.ideation_script_fix import IdeationQualityFailure, validate_or_repair_script
    from ytb_pipeline.config.settings import settings
    import ytb_pipeline.orchestrator.ideation_script_fix as fix_module

    _write_profile(
        tmp_path, "editorial-budget-fixture",
        editorial_review={
            "enabled": True, "rubric_prompt_name": "review_rubric",
            "minimum_score": 9, "max_rewrites": 1,
        },
    )
    monkeypatch.setattr(settings, "content_profiles_dir", tmp_path, raising=False)
    monkeypatch.setattr(settings, "assets_dir", tmp_path / "assets_root", raising=False)
    profile = load_content_profile("editorial-budget-fixture", profiles_dir=tmp_path)
    calls = 0

    async def _qa_pass_then_hook(self, _context):
        nonlocal calls
        calls += 1
        if calls == 1:
            return AgentResult(agent_name="qa", status=AgentStatus.SUCCESS, output={"passed": True})
        return AgentResult(
            agent_name="qa", status=AgentStatus.SUCCESS,
            output={"passed": False, "violations": [{"rule": "hook", "detail": "opening weak"}]},
        )

    monkeypatch.setattr(fix_module.QAAgent, "run", _qa_pass_then_hook)
    original = _valid_review_gate_payload(profile)

    class Provider:
        def __init__(self):
            self.prompts: list[str] = []

        async def complete(self, prompt, **_kwargs):
            self.prompts.append(prompt)
            if prompt.startswith("Review this Vietnamese YouTube script JSON"):
                return json.dumps({
                    "passed": False, "overall_score": 8,
                    "dimension_scores": {
                        "human_truth": 9, "spoken_naturalness": 8,
                        "causal_coherence": 9, "role_fidelity": 9, "useful_restraint": 9,
                    },
                    "blocking_findings": ["Văn nói còn gượng."], "section_refs": [1],
                    "repair_brief": "Viết lại tự nhiên hơn.",
                })
            assert "Editorial review findings" in prompt
            # A "bad" rewrite: the bounded delta is well-formed but returns
            # the same opening text unchanged, so the hook violation persists.
            return json.dumps({
                "sections": [{"section_index": 1, "voiceover": original["sections"][0]["voiceover"]}],
            })

    provider = Provider()
    with pytest.raises(IdeationQualityFailure):
        asyncio.run(validate_or_repair_script(
            provider, original, tmp_path / "s.json", "", max_attempts=1,
        ))
    assert not any(prompt.startswith("Rewrite ONLY the opening narration") for prompt in provider.prompts)


def _editorial_rewrite_payload():
    return {
        "slug": "fixture", "topic": "Một tình huống công việc", "profile_id": "one-cup-cafe-6h",
        "profile_version": "1.1.0", "video_type": "long", "target_minutes": 5,
        "_editorial_review": {"passed": True, "overall_score": 10},
        "sections": [
            {"purpose": "situation", "voiceover": "Section 1 giữ nguyên."},
            {"purpose": "evidence", "voiceover": "Section 2 giữ nguyên."},
            {"purpose": "evidence", "voiceover": "Section 3 bị liệt kê như dàn bài."},
            {"purpose": "application", "voiceover": "Section 4 cũng bị liệt kê như dàn bài."},
            {"purpose": "payoff", "voiceover": "Section 5 giữ nguyên."},
        ],
    }


def _editorial_rewrite_review():
    from types import SimpleNamespace

    return SimpleNamespace(
        overall_score=8,
        dimension_scores={
            "human_truth": 9, "spoken_naturalness": 7,
            "causal_coherence": 9, "role_fidelity": 9, "useful_restraint": 9,
        },
        section_refs=(3, 4),
        blocking_findings=("Phần 3-4 liệt kê như dàn bài.",),
        repair_brief="Bỏ đánh số góc nhìn, chuyển thành lời kể liền mạch.",
    )


def test_editorial_rewrite_prompt_gives_xkiro_dimension_level_feedback():
    """A rejected writer gets actionable evidence, not a vague retry order."""
    from ytb_pipeline.orchestrator.ideation_prompts import editorial_rewrite_prompt

    prompt = editorial_rewrite_prompt(_editorial_rewrite_payload(), _editorial_rewrite_review())

    assert "target bar: every dimension and overall score must reach 9/10" in prompt
    assert '"spoken_naturalness": 7' in prompt
    assert "sections: [3, 4]" in prompt
    assert "Bỏ đánh số góc nhìn" in prompt
    assert "_editorial_review" not in prompt


def test_editorial_rewrite_prompt_is_bounded_to_the_cited_sections_only():
    """A full-transcript rewrite risks regressing a section the reviewer
    never flagged (production 2026-08-27: an editorial rewrite silently
    broke the opening hook, burning the whole repair budget on a violation
    nobody asked it to touch). The prompt must give full context but demand
    output for ONLY the cited section indices, in a bounded, mergeable shape
    — the same discipline `apply_hook_repair`/`apply_short_expansion` already
    use for their own narrow repairs.
    """
    from ytb_pipeline.orchestrator.ideation_prompts import editorial_rewrite_prompt

    prompt = editorial_rewrite_prompt(_editorial_rewrite_payload(), _editorial_rewrite_review())

    assert "do not rewrite the entire script" in prompt.casefold()
    assert '"section_index"' in prompt
    assert "Section 3 bị liệt kê như dàn bài." in prompt  # full context still supplied
    assert "Section 1 giữ nguyên." in prompt  # untouched sections still visible as context
