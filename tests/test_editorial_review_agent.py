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


def test_short_strategy_editorial_review_treats_cold_open_contract_as_invariant(tmp_path):
    from ytb_pipeline.agents.editorial_review_agent import run_editorial_review
    import asyncio

    _write_profile(
        tmp_path, "short-strategy-review-fixture",
        editorial_review={"enabled": True, "rubric_prompt_name": "review_rubric"},
    )
    profile = load_content_profile("short-strategy-review-fixture", profiles_dir=tmp_path)
    payload = _script_payload(profile)
    payload.update({
        "video_type": "short",
        "strategy": {
            "format_id": "core_answer_first_v1",
            "hook": {
                "situation": "Còn 48 phút, nhưng Minh vẫn chưa biết nên im hay nói.",
                "core_answer": "Im lặng sẽ làm mất chỗ để người khác xác nhận lại.",
                "open_loop": "Minh sẽ chọn gì?",
                "answer_by_sec": 4,
            },
        },
    })
    provider = _FakeProvider(json.dumps({
        "passed": True, "blocking_findings": [], "section_refs": [], "repair_brief": "",
    }))

    asyncio.run(run_editorial_review(
        profile, payload, provider=provider, cache_dir=tmp_path / "cache",
    ))

    assert "mandatory cold-open contract" in provider.last_prompt
    assert "must not recommend removing" in provider.last_prompt
    assert payload["strategy"]["hook"]["core_answer"] in provider.last_prompt


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


def test_hook_repair_can_run_again_after_an_editorial_rewrite_touches_the_opening(tmp_path, monkeypatch):
    """`hook_repair_attempted` is single-shot per QA violation, but an editorial
    rewrite that legitimately re-touches the cited opening section can
    reintroduce a hook violation on brand-new text.

    Production 2026-08-27: exactly this happened — hook_repair fixed the
    opening once, an editorial rewrite (correctly bounded to its own cited
    sections, including section 1) then rewrote that same opening again for
    a role_fidelity/spoken_naturalness fix, and the new opening no longer
    satisfied the hook gate. With a global single-shot flag, the candidate
    was rejected with a leftover repair budget unused. Re-arming hook repair
    specifically when an editorial rewrite touches section 1 fixes this
    without ever looping unboundedly — editorial rewrites are themselves
    capped by `max_rewrites`.
    """
    import asyncio
    from ytb_pipeline.agents.base import AgentResult, AgentStatus
    from ytb_pipeline.orchestrator.ideation_script_fix import validate_or_repair_script
    from ytb_pipeline.config.settings import settings
    import ytb_pipeline.orchestrator.ideation_script_fix as fix_module

    _write_profile(
        tmp_path, "hook-then-editorial-fixture",
        editorial_review={
            "enabled": True, "rubric_prompt_name": "review_rubric",
            "minimum_score": 9, "max_rewrites": 1,
        },
    )
    monkeypatch.setattr(settings, "content_profiles_dir", tmp_path, raising=False)
    monkeypatch.setattr(settings, "assets_dir", tmp_path / "assets_root", raising=False)
    profile = load_content_profile("hook-then-editorial-fixture", profiles_dir=tmp_path)
    # Sized so the total stays inside this profile's Short duration window
    # ([504, 762] chars, measured directly against `_repair_character_bounds`)
    # even after section 0 shrinks to a short canned repair string twice —
    # a smaller total previously fell below the floor after normalization
    # trimmed it, derailing the attempt sequence this test drives.
    original = _valid_review_gate_payload(profile)
    for tag, section in zip(("Hai", "Ba", "Bốn"), original["sections"][1:]):
        section["voiceover"] = (
            f"{tag}, đây là nội dung đệm đủ dài cho section này để không "
            "chạm ngưỡng thời lượng khi phần mở đầu bị thay ngắn lại, hoàn "
            "toàn không liên quan tới nội dung repair đang được xác nhận."
        )
    original["sections"][0]["voiceover"] = (
        "Sáu giờ tối, quán vắng khách, Lan đứng lau quầy nhìn ra cửa."
    )

    qa_calls = 0

    async def _qa_sequence(self, _context):
        nonlocal qa_calls
        qa_calls += 1
        # 1: hook violation (first opening). 2: passes structurally (post
        # hook-repair) -> editorial review runs and fails, citing section 1.
        # 3: hook violation AGAIN (the editorial-rewritten opening). 4: passes
        # structurally -> editorial review runs and passes.
        if qa_calls in (1, 3):
            return AgentResult(
                agent_name="qa", status=AgentStatus.SUCCESS,
                output={"passed": False, "violations": [{"rule": "hook", "detail": "opening weak"}]},
            )
        return AgentResult(agent_name="qa", status=AgentStatus.SUCCESS, output={"passed": True})

    monkeypatch.setattr(fix_module.QAAgent, "run", _qa_sequence)

    review_calls = 0

    class Provider:
        def __init__(self):
            self.hook_repair_calls = 0

        async def complete(self, prompt, **_kwargs):
            nonlocal review_calls
            if prompt.startswith("Rewrite ONLY the opening narration"):
                self.hook_repair_calls += 1
                return json.dumps({"voiceover": f"Opening fixed, lần {self.hook_repair_calls}."})
            if prompt.startswith("Review this Vietnamese YouTube script JSON"):
                review_calls += 1
                if review_calls == 1:
                    return json.dumps({
                        "passed": False, "overall_score": 6,
                        "dimension_scores": {
                            "human_truth": 9, "spoken_naturalness": 6,
                            "causal_coherence": 9, "role_fidelity": 6, "useful_restraint": 9,
                        },
                        "blocking_findings": ["Đoạn mở nghe như thuyết minh."],
                        "section_refs": [1], "repair_brief": "Viết lại tự nhiên hơn.",
                    })
                return json.dumps({
                    "passed": True, "overall_score": 9,
                    "dimension_scores": {
                        "human_truth": 9, "spoken_naturalness": 9,
                        "causal_coherence": 9, "role_fidelity": 9, "useful_restraint": 9,
                    },
                    "blocking_findings": [], "section_refs": [], "repair_brief": "",
                })
            assert "Editorial review findings" in prompt
            return json.dumps({
                "sections": [{"section_index": 1, "voiceover": "Đoạn mở đã viết lại theo rubric."}],
            })

    provider = Provider()
    result = asyncio.run(validate_or_repair_script(
        provider, original, tmp_path / "s.json", "", max_attempts=3,
    ))

    assert provider.hook_repair_calls == 2
    assert result["sections"][0]["voiceover"] == "Opening fixed, lần 2."


def test_narrator_reflection_repair_can_run_after_reserved_editorial_rewrite(
    tmp_path, monkeypatch,
):
    """An editorial rewrite of the payoff may regress a repaired reflection.

    Production Gate 1 exhausted its ordinary QA attempts repairing the final
    narrator reflection, then used the profile-reserved editorial rewrite.
    That rewrite touched the final section and reintroduced the same QA
    violation.  The reserved validation attempt must be allowed one bounded
    reflection repair plus one final validation; otherwise a correct earlier
    repair is impossible to preserve through the independent review stage.
    """
    import asyncio

    from ytb_pipeline.agents.base import AgentResult, AgentStatus
    from ytb_pipeline.config.settings import settings
    from ytb_pipeline.orchestrator.ideation_script_fix import validate_or_repair_script
    import ytb_pipeline.orchestrator.ideation_script_fix as fix_module

    _write_profile(
        tmp_path, "reflection-after-editorial-fixture",
        editorial_review={
            "enabled": True, "rubric_prompt_name": "review_rubric",
            "minimum_score": 9, "max_rewrites": 1,
        },
    )
    monkeypatch.setattr(settings, "content_profiles_dir", tmp_path, raising=False)
    monkeypatch.setattr(settings, "assets_dir", tmp_path / "assets_root", raising=False)
    profile = load_content_profile("reflection-after-editorial-fixture", profiles_dir=tmp_path)
    original = _valid_review_gate_payload(profile)

    qa_calls = 0

    async def _qa_sequence(self, _context):
        nonlocal qa_calls
        qa_calls += 1
        if qa_calls in (1, 3):
            return AgentResult(
                agent_name="qa", status=AgentStatus.SUCCESS,
                output={
                    "passed": False,
                    "violations": [{
                        "rule": "narrator_reflection", "detail": "closing is not direct",
                    }],
                },
            )
        return AgentResult(agent_name="qa", status=AgentStatus.SUCCESS, output={"passed": True})

    monkeypatch.setattr(fix_module.QAAgent, "run", _qa_sequence)

    review_calls = 0

    class Provider:
        def __init__(self):
            self.reflection_repair_calls = 0

        async def complete(self, prompt, **_kwargs):
            nonlocal review_calls
            if prompt.startswith("Rewrite ONLY the final narrator reflection"):
                self.reflection_repair_calls += 1
                return json.dumps({
                    "voiceover": (
                        "Nếu bạn từng giữ một cảnh báo vì sợ bị hỏi ngược, có lẽ "
                        f"sự im lặng ấy cũng có một cái giá, lần {self.reflection_repair_calls}."
                    ),
                })
            if prompt.startswith("Review this Vietnamese YouTube script JSON"):
                review_calls += 1
                if review_calls == 1:
                    return json.dumps({
                        "passed": False, "overall_score": 8,
                        "dimension_scores": {
                            "human_truth": 9, "spoken_naturalness": 8,
                            "causal_coherence": 9, "role_fidelity": 9,
                            "useful_restraint": 9,
                        },
                        "blocking_findings": ["Payoff còn giống lời giải thích."],
                        "section_refs": [4],
                        "repair_brief": "Viết lại payoff tự nhiên hơn.",
                    })
                return json.dumps({
                    "passed": True, "overall_score": 9,
                    "dimension_scores": {
                        "human_truth": 9, "spoken_naturalness": 9,
                        "causal_coherence": 9, "role_fidelity": 9,
                        "useful_restraint": 9,
                    },
                    "blocking_findings": [], "section_refs": [], "repair_brief": "",
                })
            assert "Editorial review findings" in prompt
            return json.dumps({
                "sections": [{
                    "section_index": 4,
                    "voiceover": "Câu chuyện kết thúc ở đây, nhưng chưa nói trực tiếp với bạn.",
                }],
            })

    provider = Provider()
    result = asyncio.run(validate_or_repair_script(
        provider, original, tmp_path / "s.json", "", max_attempts=1,
    ))

    assert provider.reflection_repair_calls == 2
    assert qa_calls == 4
    assert "lần 2" in result["sections"][-1]["voiceover"]


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


def _short_strategy_rewrite_payload() -> dict:
    return {
        "profile_id": "ban-so-6",
        "profile_version": "2.1.0",
        "video_type": "short",
        "strategy": {
            "format_id": "core_answer_first_v1",
            "core_mechanism": "Giữ chỗ để người khác kiểm tra.",
            "audience_problem": "Sợ nói khi chưa chắc.",
            "angle": "Một lựa chọn trong cuộc họp.",
            "long_form_slug": "long-a",
            "playlist": "Bàn số 6",
            "cta_target": "long-a",
            "hook": {
                "situation": "Còn 48 phút, nhưng Minh vẫn chưa biết nên im hay nói.",
                "core_answer": "Im lặng sẽ làm mất chỗ để người khác xác nhận lại.",
                "open_loop": "Minh sẽ chọn gì?",
                "answer_by_sec": 4,
            },
        },
        "sections": [
            {"purpose": "situation", "voiceover": "Còn 48 phút, nhưng Minh vẫn chưa biết nên im hay nói."},
            {"purpose": "core_answer", "voiceover": "Im lặng sẽ làm mất chỗ để người khác xác nhận lại. Đây là chỗ cần kiểm tra."},
            {"purpose": "application", "voiceover": "Minh nói ra điều chưa chắc."},
            {"purpose": "payoff", "voiceover": "Câu trả lời vẫn chưa về."},
        ],
    }


def test_short_strategy_editorial_rewrite_prompt_preserves_required_cold_open():
    from types import SimpleNamespace
    from ytb_pipeline.orchestrator.ideation_prompts import editorial_rewrite_prompt

    review = SimpleNamespace(
        overall_score=7,
        dimension_scores={},
        section_refs=(1, 2, 3),
        blocking_findings=("Cảnh chưa đủ cụ thể.",),
        repair_brief="Làm cảnh tự nhiên hơn.",
    )
    payload = _short_strategy_rewrite_payload()

    prompt = editorial_rewrite_prompt(payload, review)

    assert "MANDATORY SHORT COLD-OPEN CONTRACT" in prompt
    assert payload["strategy"]["hook"]["core_answer"] in prompt
    assert "must start section 2 voiceover exactly" in prompt


def test_short_strategy_editorial_rewrite_prompt_preserves_spoken_funnel_bridge():
    from types import SimpleNamespace
    from ytb_pipeline.orchestrator.ideation_prompts import editorial_rewrite_prompt

    review = SimpleNamespace(
        overall_score=7,
        dimension_scores={},
        section_refs=(4,),
        blocking_findings=("Payoff needs a more grounded consequence.",),
        repair_brief="Rewrite only the payoff.",
    )

    prompt = editorial_rewrite_prompt(_short_strategy_rewrite_payload(), review)

    assert "MANDATORY SHORT FUNNEL BRIDGE" in prompt
    assert "long-a" in prompt
    assert "final spoken section" in prompt


def test_short_strategy_editorial_delta_cannot_break_required_core_answer_prefix():
    from ytb_pipeline.orchestrator.ideation_script_fix import apply_editorial_rewrite

    payload = _short_strategy_rewrite_payload()

    with pytest.raises(ValueError, match="Short strategy-v1"):
        apply_editorial_rewrite(payload, {
            "sections": [{"section_index": 2, "voiceover": "Trang bốn vẫn bôi vàng."}],
        })
