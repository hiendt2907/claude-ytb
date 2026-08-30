from __future__ import annotations

import pytest


def test_loader_hydrates_optional_strategy_without_breaking_legacy_scripts(tmp_path):
    from conftest import chars_for_minutes
    from ytb_pipeline.ideation.generator import load_script

    narration = chars_for_minutes(1.2)
    source = tmp_path / "strategy-short.json"
    source.write_text(
        """{
          "title": "Mở laptop rồi cầm điện thoại",
          "video_type": "short",
              "sections": [
                {"voiceover": "Mở laptop nhưng tay lại mở điện thoại.", "purpose": "situation"},
                {"voiceover": "Não đang né sự mơ hồ%s", "purpose": "core_answer"}
              ],
          "strategy": {
            "format_id": "core_answer_first_v1",
            "core_mechanism": "tránh né sự mơ hồ",
            "audience_problem": "mở laptop rồi cầm điện thoại",
            "angle": "trang trắng",
            "long_form_slug": "buoc-dau-mo-ho",
            "playlist": "co-che-tri-hoan",
            "cta_target": "buoc-dau-mo-ho",
            "hook": {
              "situation": "Mở laptop rồi cầm điện thoại",
              "core_answer": "Não đang né sự mơ hồ",
              "open_loop": "Vì sao nó xảy ra?",
              "answer_by_sec": 5
            }
          },
          "compliance": {
            "passed": true, "community": "PASS", "copyright": "PASS",
            "accuracy": "PASS", "advertiser": "PASS", "coppa": "PASS", "notes": "PASS"
          }
        }""" % narration,
        encoding="utf-8",
    )

    script = load_script(source)

    assert script.strategy is not None
    assert script.strategy.format_id == "core_answer_first_v1"
    assert script.segments[1].purpose == "core_answer"


def _short_voiceover(*, answer_duration: float):
    from ytb_pipeline.pkg.models import (
        ContentStrategy,
        HookPlan,
        Segment,
        Voiceover,
    )

    strategy = ContentStrategy(
        format_id="core_answer_first_v1",
        core_mechanism="tránh né sự mơ hồ của bước đầu",
        audience_problem="mở laptop rồi cầm điện thoại",
        angle="trang trắng trước khi viết báo cáo",
        long_form_slug="buoc-dau-mo-ho",
        playlist="co-che-tri-hoan",
        cta_target="buoc-dau-mo-ho",
        hook=HookPlan(
            situation="Mở laptop rồi lại cầm điện thoại",
            core_answer="Não đang né khoảnh khắc chưa biết bắt đầu từ đâu",
            open_loop="Vì sao sự mơ hồ này mạnh hơn ý chí?",
            answer_by_sec=5.0,
        ),
    )
    return Voiceover(
        topic="Trì hoãn",
        title="Mở laptop rồi cầm điện thoại",
        description="",
        video_type="short",
        strategy=strategy,
        segments=(
            Segment(
                caption="MỞ LAPTOP",
                narration="Mở laptop rồi lại cầm điện thoại.",
                purpose="situation",
                duration_sec=1.5,
            ),
            Segment(
                caption="KHÔNG PHẢI LƯỜI",
                narration="Não đang né khoảnh khắc chưa biết bắt đầu từ đâu.",
                purpose="core_answer",
                duration_sec=answer_duration,
            ),
        ),
    )


def test_hook_timing_accepts_a_core_answer_that_starts_within_five_seconds():
    from ytb_pipeline.voiceover.validation import validate_hook_timing

    validate_hook_timing(_short_voiceover(answer_duration=3.4))


def test_hook_timing_rejects_a_core_answer_that_starts_after_the_declared_deadline():
    from ytb_pipeline.voiceover.validation import validate_hook_timing

    voiceover = _short_voiceover(answer_duration=12.0)
    delayed = voiceover.segments[0].__class__(
        caption=voiceover.segments[0].caption,
        narration=voiceover.segments[0].narration,
        purpose=voiceover.segments[0].purpose,
        duration_sec=5.1,
    )
    from dataclasses import replace

    with pytest.raises(ValueError, match="bắt đầu.*5.0s"):
        validate_hook_timing(replace(voiceover, segments=(delayed, voiceover.segments[1])))


def test_loader_rejects_a_short_when_its_answer_cannot_start_by_deadline(write_script):
    from conftest import chars_for_minutes, make_script
    from ytb_pipeline.ideation.generator import load_script

    payload = make_script(
        [
            # Keep the answer deliberately after 5s while the whole Short
            # stays valid for every calibrated TTS provider.
            {"purpose": "situation", "voiceover": chars_for_minutes(0.15)},
            {"purpose": "core_answer", "voiceover": "Đó là câu trả lời. " + chars_for_minutes(1.1)},
        ]
    )
    payload["strategy"] = {
        "format_id": "core_answer_first_v1",
        "core_mechanism": "một cơ chế",
        "audience_problem": "một vấn đề",
        "angle": "một góc",
        "long_form_slug": "long-a",
        "playlist": "series-a",
        "cta_target": "long-a",
        "hook": {
            "situation": "Một tình huống",
            "core_answer": "Đó là câu trả lời.",
            "open_loop": "Vì sao?",
            "answer_by_sec": 5,
        },
    }

    with pytest.raises(ValueError, match="không thể bắt đầu trước 5.0s"):
        load_script(write_script(payload))


def test_strategy_requires_a_complete_short_to_long_funnel():
    from ytb_pipeline.pkg.models import ContentStrategy, HookPlan

    with pytest.raises(ValueError, match="cta_target"):
        ContentStrategy(
            format_id="core_answer_first_v1",
            core_mechanism="tránh né sự mơ hồ",
            audience_problem="mở laptop rồi cầm điện thoại",
            angle="trang trắng",
            long_form_slug="buoc-dau-mo-ho",
            playlist="co-che-tri-hoan",
            hook=HookPlan(
                situation="Mở laptop rồi cầm điện thoại",
                core_answer="Não đang né sự mơ hồ",
                open_loop="Điều gì khiến nó xảy ra?",
            ),
        )


def test_strategy_v1_payload_cannot_be_missing_from_a_new_short():
    from ytb_pipeline.orchestrator.ideation_script_fix import validate_short_strategy_v1

    with pytest.raises(ValueError, match="strategy-v1"):
        validate_short_strategy_v1({"video_type": "short", "sections": []})


async def test_strict_qa_rejects_a_strategy_short_without_a_core_answer_segment():
    from ytb_pipeline.agents.qa_agent import QAAgent
    from ytb_pipeline.pkg.models import ComplianceCheck, ContentStrategy, HookPlan, Script, Segment

    script = Script(
        topic="Trì hoãn",
        title="Mở laptop rồi cầm điện thoại",
        description="",
        video_type="short",
        compliance=ComplianceCheck(True, "PASS", "PASS", "PASS", "PASS", "PASS", "PASS"),
        strategy=ContentStrategy(
            format_id="core_answer_first_v1",
            core_mechanism="tránh né sự mơ hồ",
            audience_problem="mở laptop rồi cầm điện thoại",
            angle="trang trắng",
            long_form_slug="buoc-dau-mo-ho",
            playlist="co-che-tri-hoan",
            cta_target="buoc-dau-mo-ho",
            hook=HookPlan(
                situation="Mở laptop rồi cầm điện thoại",
                core_answer="Não đang né sự mơ hồ",
                open_loop="Vì sao nó xảy ra?",
            ),
        ),
        segments=(Segment(caption="", narration="Một câu mở đầu.", purpose="situation"),),
    )

    result = await QAAgent().run({"script": script, "strict": True})

    assert any(item["rule"] == "hook_contract" for item in result.output["violations"])


def test_script_prompt_requires_the_strategy_v1_hook_contract():
    from ytb_pipeline.orchestrator.ideation_prompts import local_script_prompt

    prompt = local_script_prompt(1, 1, "short", "auto", "")

    assert '"strategy"' in prompt
    assert "core_answer" in prompt
    assert "answer_by_sec" in prompt
    assert "phát triển bản thân thật, không self-help" in prompt.lower()


def test_approval_preview_exposes_the_short_hook_and_long_destination():
    from ytb_pipeline.ideation.approval import _format_full

    preview = _format_full(_short_voiceover(answer_duration=3.4))

    assert "⚡ Hook 0–5s" in preview
    assert "Não đang né khoảnh khắc chưa biết bắt đầu từ đâu" in preview
    assert "↗️ Long đích: buoc-dau-mo-ho" in preview


def test_repair_prompt_preserves_strategy_v1_instead_of_downgrading_to_legacy():
    from ytb_pipeline.orchestrator.ideation_prompts import repair_prompt

    prompt = repair_prompt(
        {
            "video_type": "short",
            "strategy": {
                "format_id": "core_answer_first_v1",
                "hook": {"core_answer": "Não đang né sự mơ hồ"},
            },
        },
        {"violations": [{"rule": "hook_contract"}]},
        None,
    )

    assert '"strategy"' in prompt
    assert "core_answer" in prompt
    assert "purpose" in prompt


def _strategy_short_payload(situation: str) -> dict:
    """A minimal strategy-v1 Short shaped exactly like the production payload."""
    return {
        "video_type": "short",
        "profile_id": "",
        "strategy": {
            "format_id": "core_answer_first_v1",
            "core_mechanism": "tránh né sự mơ hồ",
            "audience_problem": "mở laptop rồi cầm điện thoại",
            "angle": "trang trắng",
            "long_form_slug": "buoc-dau-mo-ho",
            "playlist": "co-che-tri-hoan",
            "cta_target": "buoc-dau-mo-ho",
            "hook": {
                "situation": situation,
                "core_answer": "Não đang né sự mơ hồ",
                "open_loop": "Vì sao nó xảy ra?",
                "answer_by_sec": 5,
            },
        },
        "sections": [
            {"purpose": "situation", "voiceover": situation},
            {"purpose": "core_answer", "voiceover": "Não đang né sự mơ hồ. Rồi tay mở điện thoại."},
        ],
    }


def test_short_situation_gate_accepts_only_the_markers_it_documents():
    """The gate's accepted markers are a closed lexical whitelist, not a concept.

    Production 2026-08-30: an editorially natural opening carrying explicit
    tension but none of these exact tokens is rejected outright, so any prompt
    that only asks for "a concrete tension marker" cannot reliably satisfy it.
    """
    from ytb_pipeline.orchestrator.ideation_script_fix import (
        SHORT_SITUATION_TENSION_MARKERS,
        validate_short_strategy_v1,
    )

    for marker in SHORT_SITUATION_TENSION_MARKERS:
        validate_short_strategy_v1(
            _strategy_short_payload(f"Còn mười phút nữa họp, {marker} dòng vẫn để nguyên.")
        )

    with pytest.raises(ValueError, match="tension marker"):
        validate_short_strategy_v1(
            _strategy_short_payload("Còn mười phút nữa họp, dòng bôi vàng vẫn để nguyên à?")
        )


def test_editorial_rewrite_guard_names_the_markers_the_short_gate_will_check():
    """A cited section 1 must be rewritable into something the gate accepts.

    Production 2026-08-30 (ideation_20260830_082534/083708/085402): the review
    cited section 1, the rewrite came back editorially better but without one of
    the whitelisted tokens, and `Editorial rewrite phá Short strategy-v1` threw
    the whole delta away. The bounded editorial budget was then spent
    re-reviewing byte-identical payloads — three reviews, one payload SHA, the
    same 3/10 — so the engine's only self-repair path never applied once.
    """
    from types import SimpleNamespace

    from ytb_pipeline.orchestrator.ideation_prompts import editorial_rewrite_prompt
    from ytb_pipeline.orchestrator.ideation_script_fix import SHORT_SITUATION_TENSION_MARKERS

    prompt = editorial_rewrite_prompt(
        _strategy_short_payload("Còn mười phút nữa họp, nhưng dòng vẫn để nguyên."),
        SimpleNamespace(
            blocking_findings=["An never speaks or asks a real question."],
            section_refs=[1],
            overall_score=6,
            dimension_scores={"role_fidelity": 4},
            repair_brief="Give An one real spoken question.",
        ),
    )

    for marker in SHORT_SITUATION_TENSION_MARKERS:
        assert marker in prompt


def test_short_generation_instruction_names_the_markers_the_gate_will_check():
    """The first generation attempt must not have to guess the whitelist either.

    Production 2026-08-30 (ideation_20260830_081943): a first-pass candidate was
    rejected for exactly this before any repair budget was even reached.
    """
    from ytb_pipeline.orchestrator.ideation_prompts import local_script_prompt
    from ytb_pipeline.orchestrator.ideation_script_fix import SHORT_SITUATION_TENSION_MARKERS

    prompt = local_script_prompt(
        1,
        1,
        "short",
        "auto",
        "",
    )

    for marker in SHORT_SITUATION_TENSION_MARKERS:
        assert marker in prompt


def test_hook_repair_names_the_markers_for_a_strategy_short():
    """The hook repair rewrites the very section the marker gate polices.

    Production 2026-08-30 (ideation_20260830_084815 and _092129): QA rejected the
    hook, the bounded repair returned a well-anchored opening carrying real
    tension, but without a whitelisted token — so contract validation killed the
    whole run. Two supervised attempts died this way at the third rewrite site.
    """
    from ytb_pipeline.content_profiles import load_content_profile
    from ytb_pipeline.orchestrator.ideation_prompts import hook_repair_prompt
    from ytb_pipeline.orchestrator.ideation_script_fix import SHORT_SITUATION_TENSION_MARKERS

    # The production path is a character_story profile, whose hook directive is
    # STORY_HOOK_CONTRACT — it never carried the marker list that the legacy
    # Long directive happens to mention.
    prompt = hook_repair_prompt(
        _strategy_short_payload("Còn mười phút nữa họp, nhưng dòng vẫn để nguyên."),
        "Cảnh mở đầu chưa neo được khoảnh khắc hoặc chưa có gì để mất.",
        content_profile=load_content_profile("ban-so-6"),
    )

    for marker in SHORT_SITUATION_TENSION_MARKERS:
        assert marker in prompt


def test_hook_repair_stays_silent_about_short_markers_for_a_long():
    """A Long opening is judged by a different contract; do not leak this one."""
    from ytb_pipeline.orchestrator.ideation_prompts import hook_repair_prompt

    prompt = hook_repair_prompt(
        {"video_type": "long", "sections": [{"purpose": "intro", "voiceover": "Mến chào các bạn,"}]},
        "Cảnh mở đầu chưa neo được khoảnh khắc.",
    )

    assert "exact Vietnamese markers" not in prompt


def test_narrator_reflection_repair_states_the_length_floor_for_a_short():
    """The repair rewrites a section whose size decides Short admission.

    Production 2026-08-30 (ideation_20260830_092704): at validation attempt 5 the
    Short was a valid 556 characters. The narrator-reflection repair rewrote the
    final section from 321 to 252 characters, leaving 487 total — 28.4s against a
    30.0s floor — and the run was rejected outright. The prompt never stated the
    budget its own output would be judged against. A prior session fixed the
    mirror case (a repair overflowing the cap); this is the underflow side.
    """
    from ytb_pipeline.content_profiles import load_content_profile
    from ytb_pipeline.orchestrator.ideation_prompts import narrator_reflection_repair_prompt

    payload = _strategy_short_payload("Còn mười phút nữa họp, nhưng dòng vẫn để nguyên.")
    payload["sections"].append(
        {
            "purpose": "payoff",
            "speaker_id": "narrator",
            "voiceover": "Có lẽ bạn cũng từng dừng lại như vậy. Tập sau, mời bạn xem video dài buoc-dau-mo-ho.",
        }
    )

    prompt = narrator_reflection_repair_prompt(
        payload,
        "Lời chốt story cần là phản chiếu trực tiếp, khiêm tốn của narrator.",
        content_profile=load_content_profile("ban-so-6"),
    )

    assert "characters" in prompt
    # Both ends: a floor-only instruction lets the rewrite overshoot instead.
    assert "between" in prompt.lower()


def _repair_sites_for_a_strategy_short():
    """Render every bounded repair prompt that can resize or reopen a Short."""
    from types import SimpleNamespace

    from ytb_pipeline.content_profiles import load_content_profile
    from ytb_pipeline.orchestrator import ideation_prompts as prompts

    profile = load_content_profile("ban-so-6")
    payload = _strategy_short_payload("Còn mười phút nữa họp, nhưng dòng vẫn để nguyên.")
    # A real script declares its profile; without it every site silently quotes
    # the default contract's window instead of the one it will be judged by.
    payload["profile_id"] = "ban-so-6"
    payload["profile_version"] = "2.1.0"
    payload["sections"].append(
        {
            "purpose": "payoff",
            "speaker_id": "narrator",
            "voiceover": "Có lẽ bạn cũng vậy. Tập sau, mời bạn xem video dài buoc-dau-mo-ho.",
        }
    )
    review = SimpleNamespace(
        blocking_findings=["f"], section_refs=[1, 3], overall_score=6,
        dimension_scores={"causal_coherence": 4}, repair_brief="b",
    )
    return {
        "hook_repair": prompts.hook_repair_prompt(payload, "d", content_profile=profile),
        "editorial_rewrite": prompts.editorial_rewrite_prompt(payload, review),
        "generic_repair": prompts.repair_prompt(payload, {"violations": [{"rule": "hook"}]}, None),
        "reflection_repair": prompts.narrator_reflection_repair_prompt(
            payload, "d", content_profile=profile
        ),
    }


def test_every_short_repair_states_BOTH_length_bounds_it_will_be_judged_by():
    """No bounded repair may resize a Short knowing only one end of the gate.

    Four P0s on 2026-08-30 had one shape: a repair prompt was judged by a
    contract nobody told it about. The fourth was self-inflicted — a fix stated
    the floor and dropped the cap it had already computed, so an editorial
    rewrite of all seven sections came back at 70.4s against a 45.0s ceiling.
    The duration gate is two-sided, so every resizing repair must carry both.
    """
    for name, prompt in _repair_sites_for_a_strategy_short().items():
        lowered = prompt.lower()
        has_floor = "at least" in lowered or "between" in lowered or "total narration" in lowered
        has_cap = (
            "between" in lowered
            or "do not overshoot" in lowered
            or "must not exceed" in lowered
            or "ceiling" in lowered
        )
        assert has_floor, f"{name} states no length floor"
        assert has_cap, f"{name} states no length cap"


def test_every_short_repair_that_can_touch_the_opening_names_the_markers():
    from ytb_pipeline.orchestrator.ideation_script_fix import SHORT_SITUATION_TENSION_MARKERS

    sites = _repair_sites_for_a_strategy_short()
    for name in ("hook_repair", "editorial_rewrite", "generic_repair"):
        for marker in SHORT_SITUATION_TENSION_MARKERS:
            assert marker in sites[name], f"{name} missing {marker}"


def test_strategy_short_prompt_offers_the_profile_section_window_not_just_the_minimum():
    """A strategy-v1 Short must be told the shape its own quality gate expects.

    `short_sections` is the profile MINIMUM, and the strategy-v1 branch turned it
    into "Use exactly 4 sections" while the sibling legacy branch already offered
    the profile's expansion window. Production 2026-08-30: every four-section
    candidate was rejected for the same structural reasons — "An gets a question
    but no Minh reply", "the outcome is asserted without showing the choice",
    "the close is a generalized lesson" — all symptoms of too few beats. The one
    artifact that ever cleared the 9/10 bar for this slug used SEVEN sections,
    a shape the prompt forbade.

    The runtime contract is unaffected: the character and duration bounds are
    identical for every section count in the profile window.
    """
    from ytb_pipeline.content_profiles import load_content_profile
    from ytb_pipeline.orchestrator.ideation_prompts import local_script_prompt

    profile = load_content_profile("ban-so-6")
    short_format = profile.format_for("short")
    prompt = local_script_prompt(
        1, 1, "short", "auto", "",
        funnel={
            "long_form_slug": "minh-neu-rui-ro-trong-cuoc-hop",
            "playlist": "Bàn số 6 — Truyện đời thường",
            "cta_target": "minh-neu-rui-ro-trong-cuoc-hop",
        },
        content_profile=profile,
    )

    assert f"Use exactly {short_format.min_sections} sections" not in prompt
    assert str(short_format.max_sections) in prompt


def test_repair_length_budget_satisfies_every_gate_the_short_must_pass():
    """The quoted budget must be the intersection of both duration gates.

    A Short is measured twice with two different rates: the ideation contract
    uses chars_per_min_for_provider (1030 for xkiro) and the QA length rule
    resolves to effective_chars_per_min (947.6 for ban-so-6). Quoting only the
    first gate's window told the writer it could spend 726 characters, which the
    second gate measures as 46.0s against a 45.0s ceiling.

    Production 2026-08-30 (ideation_20260830_102041): the best candidate of the
    session — nine sections, 7/10 with human_truth and useful_restraint at the
    bar — was rejected at 730 characters / 46.2s, four characters past a cap
    that was already too generous.
    """
    from ytb_pipeline.content_contract import (
        chars_per_min_for_provider,
        contract_for,
        effective_chars_per_min,
    )
    from ytb_pipeline.content_profiles import load_content_profile
    from ytb_pipeline.orchestrator.ideation_prompts import _short_total_length_bounds

    profile = load_content_profile("ban-so-6")
    payload = _strategy_short_payload("Còn mười phút nữa họp, nhưng dòng vẫn để nguyên.")
    floor, cap = _short_total_length_bounds(payload, content_profile=profile)

    contract = contract_for("short", profile)
    _lower, upper_sec = contract.audio_runtime_bounds_sec(segment_count=len(payload["sections"]))
    for rate in (
        chars_per_min_for_provider(profile.providers.tts, video_type="short"),
        effective_chars_per_min(profile.providers.tts, video_type="short", content_profile=profile),
    ):
        assert cap / rate * 60 <= upper_sec, f"cap {cap} overruns {upper_sec}s at {rate} chars/min"
    assert floor < cap


def test_every_repair_quotes_the_budget_of_the_scripts_own_profile():
    """A repair must not quote another profile's window.

    Three times this session a fix was shipped that was correct in one place and
    absent or wrong in another. Here the editorial rewrite resolved its profile
    for every other guard but passed none to the length helper, so it quoted the
    default contract's 605-784 instead of ban-so-6's 540-668 — and 784
    characters measures 49.6s against a 45.0s ceiling
    (ideation_20260830_103233, rejected at 898 characters / 52.3s).

    Pin the numbers themselves, not merely that some number is present.
    """
    import re

    from ytb_pipeline.content_profiles import load_content_profile
    from ytb_pipeline.orchestrator.ideation_prompts import _short_total_length_bounds

    profile = load_content_profile("ban-so-6")
    sites = _repair_sites_for_a_strategy_short()
    payload = _strategy_short_payload("Còn mười phút nữa họp, nhưng dòng vẫn để nguyên.")
    payload["sections"].append(
        {
            "purpose": "payoff",
            "speaker_id": "narrator",
            "voiceover": "Có lẽ bạn cũng vậy. Tập sau, mời bạn xem video dài buoc-dau-mo-ho.",
        }
    )
    floor, cap = _short_total_length_bounds(payload, content_profile=profile)

    for name, prompt in sites.items():
        quoted = {int(value) for value in re.findall(r"\b(\d{3})\b", prompt)}
        assert cap in quoted, f"{name} does not quote the profile cap {cap}: {sorted(quoted)}"
        assert floor in quoted, f"{name} does not quote the profile floor {floor}"


def test_normalization_protects_a_bridge_the_qa_gate_would_accept():
    """The guard must recognise every bridge the gate accepts, or it deletes it.

    `_check_funnel_bridge` accepts a final section carrying "video dài" (the slug
    only has to match across the strategy metadata). `required_short_funnel_bridge`
    demanded the literal slug inside the spoken sentence, so a bridge naming the
    Long by its Vietnamese title was invisible to the protection, was trimmed away
    as ordinary trailing text, and the script was then rejected for the missing
    bridge the engine had just removed.

    Production 2026-08-30, ideation_20260830_105004: the model wrote
    "Xem video dài 'Minh nêu rủi ro trong cuộc họp' để hiểu lựa chọn này." at 748
    characters; normalization cut to 650 and the sentence was gone.
    """
    from ytb_pipeline.orchestrator.ideation_script_fix import (
        normalize_short_narration,
        required_short_funnel_bridge,
    )

    slug = "minh-neu-rui-ro-trong-cuoc-hop"
    bridge = "Xem video dài 'Minh nêu rủi ro trong cuộc họp' để hiểu lựa chọn này."
    payload = {
        "video_type": "short",
        "profile_id": "ban-so-6",
        "profile_version": "2.1.0",
        "strategy": {
            "format_id": "core_answer_first_v1",
            "long_form_slug": slug, "cta_target": slug, "source_long_slug": slug,
            "hook": {"core_answer": "CORE."},
        },
        "sections": [
            {"purpose": "situation", "voiceover": "Sáu giờ bốn mươi, nhưng dòng vàng vẫn nguyên."},
            {"purpose": "core_answer", "voiceover": "CORE. " + "Một câu kể dài. " * 30},
            {"purpose": "evidence", "voiceover": "Một câu kể khác. " * 20},
            {"purpose": "payoff", "voiceover": f"Có những lúc bạn nói ra điều chưa chắc. {bridge}"},
        ],
    }

    assert required_short_funnel_bridge(payload) == bridge

    normalized, note = normalize_short_narration(payload, expected_video_type="short")
    assert note, "the fixture must actually be over the cap so trimming runs"
    assert "video dài" in (normalized["sections"][-1].get("voiceover") or "")


def test_editorial_review_tolerates_numeric_section_refs_from_the_judge():
    """A hint field must not abort a production run.

    `section_refs` only tells the repair prompt which sections to rebuild; it is
    not part of the quality gate. A judge returning ["4", "6"] or [4.0, 6.0]
    crashed `_parse_review_response` with an uncaught ValueError, which killed
    the whole supervised run (production 2026-08-30, ideation_20260830_111408 —
    the log ends at QA_RESULT 1 with no review recorded at all).

    Coerce integral values; keep rejecting anything that is not a section
    number. `passed` and `overall_score` stay strict — those ARE the gate.
    """
    import json

    from ytb_pipeline.agents.editorial_review_agent import _parse_review_response

    for refs in (["4", "6"], [4.0, 6.0], [4, "6"]):
        parsed = _parse_review_response(
            json.dumps({"passed": False, "blocking_findings": ["x"], "section_refs": refs})
        )
        assert list(parsed.section_refs) == [4, 6], refs

    for bad in (["four"], [None], [[4]], [True]):
        with pytest.raises(ValueError, match="section_refs"):
            _parse_review_response(
                json.dumps({"passed": False, "blocking_findings": [], "section_refs": bad})
            )


def test_editorial_review_keeps_the_gate_fields_strict():
    """Tolerance must not leak into the fields that decide admission."""
    import json

    from ytb_pipeline.agents.editorial_review_agent import _parse_review_response

    with pytest.raises(ValueError, match="passed"):
        _parse_review_response(json.dumps({"passed": "false", "blocking_findings": []}))
    with pytest.raises(ValueError, match="overall_score"):
        _parse_review_response(
            json.dumps({"passed": False, "blocking_findings": [], "overall_score": "7"})
        )


def test_auto_visual_prompt_states_what_visual_intent_is_judged_on():
    """`visual_intent` is the image prompt AND the pass/fail spec — say so.

    Nothing in the prompt stack told the writer how `visual_intent` is consumed.
    It is sent verbatim to ComfyUI as the generation prompt AND to the Vision
    Judge as the requirement, which then treats every clause as binding.

    Production 2026-08-30 (project minh-neu-rui-ro-trong-cuoc-hop): three of
    three shots escalated to a human for exactly this, while character,
    composition and continuity all scored 1.000:

      scene-000  "màn hình laptop mở trang tài liệu có dòng bôi vàng"
                 -> unreadable_required_text
      scene-001  "An ... tay cầm khay"
                 -> missing_required_object
      scene-002  "Minh chỉ vào dòng bôi vàng trên màn hình, tay còn lại đặt
                  trên mép bàn"
                 -> semantic_contradiction, missing_required_object

    Prose written for a human reader became an unsatisfiable specification.
    """
    from ytb_pipeline.content_profiles import load_content_profile
    from ytb_pipeline.orchestrator.ideation_prompts import local_script_prompt

    prompt = local_script_prompt(
        1, 1, "long", "auto", "", content_profile=load_content_profile("ban-so-6"),
    )

    lowered = prompt.lower()
    assert "visual_intent" in prompt
    # It must say the intent is generated and judged, not just "where action goes".
    assert "judged" in lowered or "chấm" in lowered or "pass/fail" in lowered
    # It must warn off the three things a still frame cannot carry.
    assert "readable text" in lowered or "chữ đọc được" in lowered
