"""Acceptance tests for LOCAL_FIRST_AI_MIGRATION_PLAN.md."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from ytb_pipeline.config.settings import settings
from ytb_pipeline.content_contract import CONTRACT_VERSION
from ytb_pipeline.ideation.generator import CHARS_PER_MIN
from ytb_pipeline.pkg.models import PublishResult, RenderedVideo

SHORT_BATCH_KEY = "shorts_funnel_batch_test"
SHORT_LONG_SLUG = "long-test"


def _seed_strategy_short_batch(path: Path) -> None:
    path.write_text(
        json.dumps({
            SHORT_BATCH_KEY: {
                "status": "active",
                "long_videos": [{"slug": SHORT_LONG_SLUG}],
                "short_videos": [],
            }
        }),
        encoding="utf-8",
    )
    # A Short now derives its open-loop context from its funnel Long
    # (ideation_cmd.load_short_source_long_context), so the Long's own
    # script.json must already exist on disk under scripts/.
    scripts_dir = path.parent / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    (scripts_dir / f"{SHORT_LONG_SLUG}.json").write_text(
        json.dumps({
            "slug": SHORT_LONG_SLUG,
            "title": "Long nguồn test",
            "sections": [
                {"purpose": "mở đầu", "voiceover": "Mến chào các bạn, hôm nay ta nói về cơ chế trì hoãn."},
                {
                    "purpose": "giải thích cơ chế",
                    "voiceover": "Não né sự mơ hồ của bước đầu tiên nên ta trì hoãn.",
                },
                {
                    "purpose": "bằng chứng",
                    "voiceover": "Nghiên cứu hành vi cho thấy sự mơ hồ làm tăng cảm giác tốn công sức.",
                },
                {
                    "purpose": "ví dụ thực hành",
                    "voiceover": "Khi Lan chia việc mơ hồ thành một bước cụ thể đầu tiên, cô bắt tay làm ngay.",
                },
                {"purpose": "cầu nối", "voiceover": "Hẹn gặp lại ở tập sau."},
            ],
        }),
        encoding="utf-8",
    )


def _strategy_short_args(**overrides) -> argparse.Namespace:
    values = {
        "num_of_vid": 1,
        "type_of_vid": "short",
        "type_of_rules": "auto",
        "resume": False,
        "local": False,
        "cloud": False,
        "batch_key": SHORT_BATCH_KEY,
        "long_form_slug": SHORT_LONG_SLUG,
        "playlist": "co-che-test",
        "cta_target": SHORT_LONG_SLUG,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def _valid_short_script() -> dict:
    chunk = (
        "Vì sao ta trì hoãn? Ví dụ, khi Lan mở điện thoại ở bàn làm việc, cô chọn đọc "
        "thông báo nên trễ việc. Lần tới bạn có thể đặt điện thoại ngoài bàn. "
    )
    narration = (chunk * (-(-int(CHARS_PER_MIN * 1.2) // len(chunk)))).strip()
    # content_contract's Short minimum is 6 sections (contract_for("short").minimum_sections).
    section_size = -(-len(narration) // 6)
    sections = [
        {
            "caption": f"Ý {i}",
            "narration": narration[i * section_size:(i + 1) * section_size],
            "broll": "abstract decision making",
            "visual_intent": "abstract decision making",
            "pexels_query": "abstract decision making",
            "time_goal": 0.2,
            "emphasis": ["cơ chế"],
            "payoff": "Bạn nhìn ra tín hiệu nào đang kéo lựa chọn của mình.",
        }
        for i in range(6)
    ]
    first_detail = sections[0]["narration"]
    sections[0]["purpose"] = "situation"
    sections[0]["narration"] = (
        "Mở laptop để làm việc, nhưng tay bạn lại cầm điện thoại trước khi gõ dòng đầu tiên."
    )
    sections[1]["purpose"] = "core_answer"
    sections[1]["narration"] = "Não đang né khoảnh khắc chưa biết bắt đầu từ đâu. " + sections[1]["narration"]
    sections[2]["purpose"] = "evidence"
    sections[2]["narration"] = first_detail + " " + sections[2]["narration"]
    sections[3]["purpose"] = "evidence"
    sections[4]["purpose"] = "application"
    # The release gate requires a payoff section, so a fixture claiming to be a
    # runnable Short must carry one.
    sections[5]["purpose"] = "payoff"
    sections[-1]["narration"] += " Hãy đặt điện thoại ngoài bàn trong 10 phút tới."
    return {
        "ruleset_id": CONTRACT_VERSION,
        "slug": "co-che-test-local",
        "topic": "Cơ chế test local",
        "title": "Cơ Chế Test Local",
        "description": "Một kịch bản test local-first.",
        "tags": ["tam ly", "hanh vi"],
        "video_type": "short",
        "thumbnail_brief": {
            "visual_contradiction": "Tay cầm điện thoại thay vì gõ phím",
            "subject": "Người trẻ trước laptop",
            "emotion": "Bối rối",
            "headline": "Vì sao trì hoãn",
        },
        "strategy": {
            "format_id": "core_answer_first_v1",
            "core_mechanism": "tránh né sự mơ hồ của bước đầu",
            "audience_problem": "mở laptop rồi cầm điện thoại",
            "angle": "trang trắng trước khi bắt đầu",
            "long_form_slug": SHORT_LONG_SLUG,
            "playlist": "co-che-test",
            "cta_target": SHORT_LONG_SLUG,
            "source_long_slug": SHORT_LONG_SLUG,
            "source_section_index": 1,
            "source_excerpt": "Não né sự mơ hồ của bước đầu tiên nên ta trì hoãn.",
            "hook": {
                "situation": "Mở laptop rồi lại cầm điện thoại",
                "core_answer": "Não đang né khoảnh khắc chưa biết bắt đầu từ đâu",
                "open_loop": "Vì sao sự mơ hồ thắng ý chí?",
                "answer_by_sec": 5,
            },
        },
        "sections": sections,
        "compliance": {
            "passed": True,
            "community": "ok",
            "copyright": "ok",
            "accuracy": "ok",
            "advertiser": "ok",
            "coppa": "not for kids",
            "notes": "test",
        },
    }


def test_settings_default_to_local_first_stack():
    # llm_provider mặc định "xkiro". Amendment 2026-08-26 pin ideation vào
    # DeepSeek V4 Pro qua xKiro, không fallback provider. Image/video vẫn
    # cố định local-first.
    assert settings.image_provider == "pillow"
    assert settings.video_provider == "pexels"
    assert settings.broll_strategy == "pexels"
    assert settings.llm_provider == "xkiro"


def test_ai_render_provider_local_only_available_without_pexels_key(monkeypatch):
    """Rollback 2026-08-24 (xem docs/TOOL_UPGRADE_PLAN.md): local-only mode
    (BROLL_ALLOW_DOWNLOADS=false, mặc định) KHÔNG được báo unavailable chỉ vì
    thiếu PEXELS_API_KEY — renderer phụ thuộc asset catalog/cache local, không
    phụ thuộc network."""
    from ytb_pipeline.providers.render.ai_provider import AiRenderProvider

    original = {
        "broll_strategy": settings.broll_strategy,
        "broll_allow_downloads": settings.broll_allow_downloads,
        "pexels_api_key": settings.pexels_api_key,
    }
    try:
        settings.broll_strategy = "pexels"
        settings.broll_allow_downloads = False
        settings.pexels_api_key = ""
        assert AiRenderProvider().is_available() is True
    finally:
        for key, value in original.items():
            setattr(settings, key, value)


def test_ai_render_provider_requires_pexels_key_only_when_downloads_enabled(monkeypatch):
    from ytb_pipeline.providers.render.ai_provider import AiRenderProvider

    original = {
        "broll_strategy": settings.broll_strategy,
        "broll_allow_downloads": settings.broll_allow_downloads,
        "pexels_api_key": settings.pexels_api_key,
    }
    try:
        settings.broll_strategy = "pexels"
        settings.broll_allow_downloads = True
        settings.pexels_api_key = ""
        assert AiRenderProvider().is_available() is False

        settings.pexels_api_key = "test-key"
        assert AiRenderProvider().is_available() is True
    finally:
        for key, value in original.items():
            setattr(settings, key, value)


def test_ai_render_provider_unavailable_when_broll_strategy_not_pexels(monkeypatch):
    from ytb_pipeline.providers.render.ai_provider import AiRenderProvider

    original = settings.broll_strategy
    try:
        settings.broll_strategy = "local_video"
        assert AiRenderProvider().is_available() is False
    finally:
        settings.broll_strategy = original


def test_local_doctor_reports_local_ai_readiness(monkeypatch):
    from ytb_pipeline.orchestrator.doctor import run_local_doctor_checks

    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/" + name if name == "ffmpeg" else None)

    checks = run_local_doctor_checks()
    names = {name for name, _ok, _detail in checks}

    assert "LLM provider (xkiro)" in names
    assert "Local image provider" in names
    assert "Vietnamese TTS provider" in names
    assert "ffprobe" in names


def test_batch_start_local_uses_llm_provider_without_claude(tmp_path, monkeypatch):
    from ytb_pipeline.orchestrator import batch_cli as cli
    from ytb_pipeline.orchestrator import ideation_cmd
    from ytb_pipeline.orchestrator.ideation_prompts import SCRIPT_GENERATION_SYSTEM_PROMPT

    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    auto_state = tmp_path / "auto_state.json"
    _seed_strategy_short_batch(auto_state)
    ledger = tmp_path / "ledger.md"
    ledger.write_text(
        "# Ledger\n| Ngày | Slug | Tiêu đề | Stage | Status | URL / ghi chú |\n",
        encoding="utf-8",
    )

    class FakeLLM:
        name = "ollama"

        async def complete(self, *args, **kwargs):
            self.systems.append(kwargs["system"])
            return json.dumps(_valid_short_script(), ensure_ascii=False)

        def __init__(self):
            self.systems: list[str] = []

        def is_available(self):
            return True

        def model_name(self):
            return "qwen-test"

    def fail_popen(*_args, **_kwargs):
        raise AssertionError("Claude subprocess must not be used in local start")

    monkeypatch.setattr(cli, "ROOT", tmp_path)
    monkeypatch.setattr(cli, "AUTO_STATE_PATH", auto_state)
    monkeypatch.setattr(cli, "LEDGER_PATH", ledger)
    provider = FakeLLM()
    monkeypatch.setattr(ideation_cmd, "get_llm_provider", lambda *_a, **_kw: provider)
    monkeypatch.setattr(cli.subprocess, "Popen", fail_popen)

    args = _strategy_short_args()
    ideation_cmd.cmd_start(args)

    script_path = scripts_dir / "co-che-test-local.json"
    assert script_path.exists()
    assert "co-che-test-local" in auto_state.read_text(encoding="utf-8")
    assert "co-che-test-local" in ledger.read_text(encoding="utf-8")
    assert provider.systems == [SCRIPT_GENERATION_SYSTEM_PROMPT]

    # Rollback 2026-08-24: metadata mặc định của video mới trong auto_state.json
    # phải là "ai" (B-roll local-only), không phải "motion" — batch runner
    # không được vô tình chọn provider khác production default.
    def _find_slug_entry(node):
        if isinstance(node, dict):
            if node.get("slug") == "co-che-test-local" and "render_provider" in node:
                return node
            for value in node.values():
                found = _find_slug_entry(value)
                if found is not None:
                    return found
        elif isinstance(node, list):
            for item in node:
                found = _find_slug_entry(item)
                if found is not None:
                    return found
        return None

    entry = _find_slug_entry(json.loads(auto_state.read_text(encoding="utf-8")))
    assert entry is not None, "không tìm thấy metadata video mới trong auto_state.json"
    assert entry["render_provider"] == "ai"


def test_batch_start_local_prints_steps_and_writes_trace_log(tmp_path, monkeypatch, capsys):
    from ytb_pipeline.orchestrator import batch_cli as cli
    from ytb_pipeline.orchestrator import ideation_cmd

    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    auto_state = tmp_path / "auto_state.json"
    _seed_strategy_short_batch(auto_state)
    ledger = tmp_path / "ledger.md"
    ledger.write_text(
        "# Ledger\n| Ngày | Slug | Tiêu đề | Stage | Status | URL / ghi chú |\n",
        encoding="utf-8",
    )
    log_dir = tmp_path / "batch_logs"

    payload = _valid_short_script()
    payload["sections"][0]["emphasis"] = True

    class FakeLLM:
        name = "ollama"

        async def complete(self, *args, **kwargs):
            return json.dumps(payload, ensure_ascii=False)

        def is_available(self):
            return True

        def model_name(self):
            return "qwen-test"

    monkeypatch.setattr(cli, "ROOT", tmp_path)
    monkeypatch.setattr(cli, "AUTO_STATE_PATH", auto_state)
    monkeypatch.setattr(cli, "LEDGER_PATH", ledger)
    monkeypatch.setattr(ideation_cmd, "PIPELINE_LOG_DIR", log_dir)
    monkeypatch.setattr(ideation_cmd, "get_llm_provider", lambda *_a, **_kw: FakeLLM())

    ideation_cmd.cmd_start(_strategy_short_args())

    out = capsys.readouterr().out
    assert "ý tưởng: auto" in out
    assert "[1/1] prompt" in out
    assert "[1/1] LLM" in out
    assert "[1/1] validate" in out
    assert "log chi tiết:" in out
    logs = list(log_dir.glob("ideation_*.log"))
    assert len(logs) == 1
    log_text = logs[0].read_text(encoding="utf-8")
    assert "PROMPT" in log_text
    assert "RAW_LLM_RESPONSE" in log_text
    assert "VALIDATION_ATTEMPT 1" in log_text


def test_batch_start_local_can_clear_old_ledger_for_user_idea(tmp_path, monkeypatch, capsys):
    from ytb_pipeline.orchestrator import batch_cli as cli
    from ytb_pipeline.orchestrator import ideation_cmd

    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    auto_state = tmp_path / "auto_state.json"
    _seed_strategy_short_batch(auto_state)
    ledger = tmp_path / "ledger.md"
    ledger.write_text(
        "# Ledger\n"
        "| Ngày | Slug | Tiêu đề | Stage | Status | URL / ghi chú |\n"
        "| 2026-01-01 | old | Chủ đề cũ không được nhắc lại | done | ok | old |\n",
        encoding="utf-8",
    )

    captured_prompts: list[str] = []

    class FakeLLM:
        name = "ollama"

        async def complete(self, prompt, *args, **kwargs):
            captured_prompts.append(prompt)
            payload = _valid_short_script()
            payload["topic"] = "Cơ chế xấu hổ"
            payload["title"] = "Cơ Chế Xấu Hổ"
            payload["slug"] = "co-che-xau-ho"
            return json.dumps(payload, ensure_ascii=False)

        def is_available(self):
            return True

        def model_name(self):
            return "qwen-test"

    monkeypatch.setattr(cli, "ROOT", tmp_path)
    monkeypatch.setattr(cli, "AUTO_STATE_PATH", auto_state)
    monkeypatch.setattr(cli, "LEDGER_PATH", ledger)
    monkeypatch.setattr(ideation_cmd, "get_llm_provider", lambda *_a, **_kw: FakeLLM())

    ideation_cmd.cmd_start(_strategy_short_args(
        type_of_rules="cơ chế xấu hổ",
        clear_ledger=True,
    ))

    out = capsys.readouterr().out
    assert "Đã clear ledger cũ" in out
    assert "cơ chế xấu hổ" in captured_prompts[0]
    assert "Chủ đề cũ không được nhắc lại" not in captured_prompts[0]
    assert "co-che-xau-ho" in ledger.read_text(encoding="utf-8")
    assert "Chủ đề cũ không được nhắc lại" not in ledger.read_text(encoding="utf-8")
    backups = list(tmp_path.glob("ledger.backup.*.md"))
    assert len(backups) == 1
    assert "Chủ đề cũ không được nhắc lại" in backups[0].read_text(encoding="utf-8")


def test_local_prompt_blocks_entertainment_for_current_channel_scope():
    from ytb_pipeline.orchestrator import ideation_cmd

    prompt = ideation_cmd._local_script_prompt(
        1,
        1,
        "short",
        "làm nội dung giải trí, người que, kéo view",
        "",
    )

    assert "not entertainment" in prompt
    assert "Do NOT write comedy" in prompt
    assert "stickman/người que" not in prompt
    assert "real stock footage" in prompt


def test_script_generation_system_prompt_enforces_title_topic_and_length_contract():
    from ytb_pipeline.orchestrator.ideation_prompts import (
        LONG_MAX_CHARS,
        LONG_MAX_MINUTES,
        LONG_MIN_CHARS,
        LONG_MIN_MINUTES,
        SCRIPT_GENERATION_SYSTEM_PROMPT,
        SHORT_MAX_CHARS,
        SHORT_MAX_MINUTES,
        SHORT_MIN_CHARS,
        SHORT_MIN_MINUTES,
    )

    assert f"{SHORT_MIN_CHARS}-{SHORT_MAX_CHARS}" in SCRIPT_GENERATION_SYSTEM_PROMPT
    assert f"{LONG_MIN_CHARS}-{LONG_MAX_CHARS}" in SCRIPT_GENERATION_SYSTEM_PROMPT
    # Derived, not literal: the Short window is operator-configurable, so a
    # pinned "1.0-1.5" only asserted that nobody had retuned the channel yet.
    assert f"{SHORT_MIN_MINUTES:.2f}-{SHORT_MAX_MINUTES:.2f} minutes" in SCRIPT_GENERATION_SYSTEM_PROMPT
    assert f"{LONG_MIN_MINUTES}-{LONG_MAX_MINUTES} minute" in SCRIPT_GENERATION_SYSTEM_PROMPT
    assert "Every spoken sentence must directly serve the declared title and topic" in SCRIPT_GENERATION_SYSTEM_PROMPT
    assert "never stretch runtime with repeated phrasing" in SCRIPT_GENERATION_SYSTEM_PROMPT
    assert "one mechanism" in SCRIPT_GENERATION_SYSTEM_PROMPT
    assert "verify every factual, numerical, medical, financial, legal, or research claim" in SCRIPT_GENERATION_SYSTEM_PROMPT.lower()


def test_batch_start_local_rejects_and_archives_a_qa_failed_candidate_fail_fast(tmp_path, monkeypatch):
    """A rejected candidate now fails fast instead of spending a second LLM call.

    ideation_cmd._cmd_start_local sets `max_rejected_candidates = 1` and
    documents why: automatic repair/candidate loops must not spend cloud
    tokens silently — a QA-terminal rejection is archived for an intentional
    editorial retry instead of an automatic one.
    """
    from ytb_pipeline.orchestrator import batch_cli as cli
    from ytb_pipeline.orchestrator import ideation_cmd

    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    auto_state = tmp_path / "auto_state.json"
    _seed_strategy_short_batch(auto_state)
    ledger = tmp_path / "ledger.md"
    ledger.write_text(
        "# Ledger\n| Ngày | Slug | Tiêu đề | Stage | Status | URL / ghi chú |\n",
        encoding="utf-8",
    )

    bad = _valid_short_script()
    bad["compliance"] = {**bad["compliance"], "passed": False}

    class RejectingLLM:
        name = "ollama"

        def __init__(self):
            self.calls = 0

        async def complete(self, *args, **kwargs):
            self.calls += 1
            return json.dumps(bad, ensure_ascii=False)

        def is_available(self):
            return True

        def model_name(self):
            return "qwen-test"

    provider = RejectingLLM()
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    monkeypatch.setattr(cli, "AUTO_STATE_PATH", auto_state)
    monkeypatch.setattr(cli, "LEDGER_PATH", ledger)
    monkeypatch.setattr(ideation_cmd, "get_llm_provider", lambda *_a, **_kw: provider)
    monkeypatch.setattr(cli.subprocess, "Popen", lambda *_args, **_kwargs: pytest.fail("Claude must not run"))

    args = _strategy_short_args()
    with pytest.raises(SystemExit, match="1 candidate bị QA từ chối"):
        ideation_cmd.cmd_start(args)

    assert provider.calls == 1
    assert not (scripts_dir / "co-che-test-local.json").exists()
    archived = list((tmp_path / "assets" / "script_revisions" / "failed_ideation").glob("co-che-test-local_*.json"))
    assert len(archived) == 1
    assert json.loads(archived[0].read_text(encoding="utf-8"))["compliance"]["passed"] is False
    assert "co-che-test-local" not in ledger.read_text(encoding="utf-8")


def test_batch_start_local_rejects_a_duplicate_second_candidate_without_overwriting_the_first(
    tmp_path, monkeypatch, capsys
):
    """The first Short in a batch is preserved even when the second candidate

    reuses its content. Under the fail-fast policy (`max_rejected_candidates
    = 1`, see the sibling `..._fail_fast` test above) that reuse now aborts
    the whole `cmd_start` call instead of silently retrying — but the already
    -queued first Short must not be discarded or overwritten by the failure.
    """
    from ytb_pipeline.orchestrator import batch_cli as cli
    from ytb_pipeline.orchestrator import ideation_cmd

    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    auto_state = tmp_path / "auto_state.json"
    _seed_strategy_short_batch(auto_state)
    ledger = tmp_path / "ledger.md"
    ledger.write_text(
        "# Ledger\n| Ngày | Slug | Tiêu đề | Stage | Status | URL / ghi chú |\n",
        encoding="utf-8",
    )

    duplicate = _valid_short_script()
    # Provenance is selected by the workflow before each request.  This fake
    # model must not claim the first candidate's selection again for the second
    # request; absence lets the preassignment layer attach the right one.
    for field in ("source_long_slug", "source_section_index", "source_excerpt"):
        duplicate["strategy"].pop(field, None)

    class DuplicateLLM:
        name = "ollama"

        def __init__(self):
            self.calls = 0

        async def complete(self, *args, **kwargs):
            self.calls += 1
            return json.dumps(duplicate, ensure_ascii=False)

        def is_available(self):
            return True

        def model_name(self):
            return "qwen-test"

    provider = DuplicateLLM()
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    monkeypatch.setattr(cli, "AUTO_STATE_PATH", auto_state)
    monkeypatch.setattr(cli, "LEDGER_PATH", ledger)
    monkeypatch.setattr(ideation_cmd, "get_llm_provider", lambda *_a, **_kw: provider)

    with pytest.raises(SystemExit, match="1 candidate bị QA từ chối"):
        ideation_cmd.cmd_start(_strategy_short_args(
            num_of_vid=2,
            type_of_rules="một cơ chế hành vi mới",
            _strict_qa=False,
        ))

    out = capsys.readouterr().out
    assert "slug: adjusted duplicate `co-che-test-local` -> `co-che-test-local-2`" in out
    # A quality-repair request is permitted after the second candidate; this
    # test protects queue preservation, not an incidental call count.
    assert provider.calls >= 2
    first = json.loads((scripts_dir / "co-che-test-local.json").read_text(encoding="utf-8"))
    assert first["title"] == "Cơ Chế Test Local"
    assert not (scripts_dir / "co-che-test-local-2.json").exists()
    state = json.loads(auto_state.read_text(encoding="utf-8"))
    slugs = [item["slug"] for item in state[SHORT_BATCH_KEY]["short_videos"]]
    assert slugs == ["co-che-test-local"]


def test_local_short_normalizer_shrinks_overlong_repair():
    from ytb_pipeline.orchestrator.ideation_cmd import (
        SHORT_MAX_CHARS,
        SHORT_MIN_CHARS,
        _normalize_short_narration,
        _short_narration_chars,
    )

    payload = _valid_short_script()
    per_section = SHORT_MIN_CHARS // 4 + 20
    long_sentence = (
        "Người que chạy qua hành lang, trượt chân, bật dậy và cố tỏ ra bình thường "
        "trong khi mọi người xung quanh nhìn theo vì cú va chạm bất ngờ này làm câu "
        "chuyện càng rối hơn, nhưng nó vẫn cố tiếp tục bước đi như chưa có gì xảy ra."
    )
    long_sentence = (long_sentence * (-(-per_section // len(long_sentence))))[:per_section - 1] + "."
    payload["sections"] = [
        {
            "caption": f"Cảnh {i}",
            "narration": ("Chào mừng các bạn đến với video mới của chúng tôi. " if i == 0 else "")
            + long_sentence * 4,
            "broll": "người que chạy và ngã",
            "emphasis": ["punchline"],
        }
        for i in range(4)
    ]

    fixed, note = _normalize_short_narration(payload)

    assert note is not None
    assert SHORT_MIN_CHARS < _short_narration_chars(fixed) < SHORT_MAX_CHARS
    assert "Chào mừng các bạn" not in fixed["sections"][0]["narration"]


def test_local_short_normalizer_never_pads_too_short_script_with_template_text():
    from ytb_pipeline.orchestrator.ideation_cmd import (
        SHORT_MAX_CHARS,
        SHORT_MIN_CHARS,
        _normalize_short_narration,
        _short_narration_chars,
    )

    payload = _valid_short_script()
    payload["sections"] = [
        {
            "caption": "Hook",
            "narration": "Người que mở cửa, thấy sếp, đóng cửa lại.",
            "broll": "người que đóng cửa",
            "emphasis": ["hook"],
        },
        {
            "caption": "Punchline",
            "narration": "Cánh cửa tự mở lại, sếp cũng là người que.",
            "broll": "hai người que nhìn nhau",
            "emphasis": ["punchline"],
        },
    ]

    original_narration = [section["narration"] for section in payload["sections"]]

    fixed, note = _normalize_short_narration(payload)

    assert note is None
    assert _short_narration_chars(fixed) < SHORT_MIN_CHARS
    assert [section["narration"] for section in fixed["sections"]] == original_narration
    assert "mở laptop để làm việc" not in " ".join(original_narration)


@pytest.mark.asyncio
async def test_undersized_short_is_rewritten_by_llm_instead_of_padded(tmp_path):
    from ytb_pipeline.orchestrator.ideation_script_fix import validate_or_repair_script
    from ytb_pipeline.orchestrator.ideation_prompts import SCRIPT_GENERATION_SYSTEM_PROMPT, SHORT_MIN_CHARS

    undersized = _valid_short_script()
    # Structurally valid (>= 6 sections, every required field present) but
    # far under SHORT_MIN_CHARS in total narration, so `validate_or_repair_script`
    # reaches load_script's audio-runtime "quá ngắn" gate instead of failing
    # earlier on script_contract's structural checks.
    undersized_purposes = ["situation", "core_answer", "evidence", "evidence", "application", "payoff"]
    undersized["sections"] = [
        {
            "caption": f"Beat {i}",
            "narration": text,
            "broll": "person writing in notebook at desk",
            "visual_intent": "person writing in notebook at desk",
            "pexels_query": "person writing in notebook at desk",
            "time_goal": 0.1,
            "purpose": purpose,
            "emphasis": ["quyết định"],
            "payoff": "Nhìn lại quyết định rõ hơn.",
        }
        for i, (purpose, text) in enumerate(zip(undersized_purposes, [
            # situation/core_answer must satisfy validate_short_strategy_v1's
            # hook contract: a tension marker (≤120 chars) then a core_answer
            # voiceover that starts with strategy.hook.core_answer verbatim.
            "Mở laptop để làm việc, nhưng tay bạn lại cầm điện thoại trước khi gõ dòng đầu tiên.",
            "Não đang né khoảnh khắc chưa biết bắt đầu từ đâu.",
            "Cô chưa biết bắt đầu từ đâu.",
            "Một dòng ngắn cũng đủ để bắt đầu.",
            "Nhìn lại sổ tay sau một tuần.",
            "Hãy viết một dòng vào sổ ngay hôm nay.",
        ]))
    ]
    # apply_short_expansion (ideation_script_fix.py) now only accepts a
    # bounded `section_updates` delta appended to an existing middle
    # section — a full script rewrite is explicitly rejected ("without
    # allowing a full script rewrite"). Push section index 2 well past
    # SHORT_MIN_CHARS on its own so the merged total clears the gate.
    addition = "Một bước nhỏ mỗi ngày giúp giảm sự mơ hồ khi bắt đầu. " * 40
    expansion = {"section_updates": [{"index": 2, "append_voiceover": addition}]}

    class RepairingLLM:
        calls = 0

        def __init__(self):
            self.systems: list[str] = []

        async def complete(self, *_args, **_kwargs):
            self.calls += 1
            self.systems.append(_kwargs["system"])
            return json.dumps(expansion, ensure_ascii=False)

    provider = RepairingLLM()
    script_path = tmp_path / "co-che-test-local.json"

    result = await validate_or_repair_script(
        provider,
        undersized,
        script_path,
        ledger_text="",
        max_attempts=2,
        strict=False,
        expected_video_type="short",
    )

    assert provider.calls == 1
    assert provider.systems == [SCRIPT_GENERATION_SYSTEM_PROMPT]
    assert sum(len(section["narration"]) for section in result["sections"]) >= SHORT_MIN_CHARS
    assert "mở laptop để làm việc" not in script_path.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_undersized_short_retries_invalid_expansion_with_one_allowed_middle_index(tmp_path):
    """A mixed/CTA delta must be rejected, then corrected without rewriting the CTA."""
    from ytb_pipeline.orchestrator.ideation_script_fix import validate_or_repair_script

    undersized = _valid_short_script()
    for section in undersized["sections"]:
        section["narration"] = "Một nhịp ngắn để kiểm tra lỗi."
    undersized["sections"][0]["narration"] = "Mở laptop, nhưng tay lại cầm điện thoại."
    undersized["sections"][1]["narration"] = "Não đang né khoảnh khắc chưa biết bắt đầu từ đâu."
    original_payoff = undersized["sections"][-1]["narration"]
    addition = "Một bước nhỏ mỗi ngày giúp giảm sự mơ hồ khi bắt đầu. " * 40

    class RetryingLLM:
        def __init__(self):
            self.calls = 0

        async def complete(self, *_args, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                # Index 5 is the payoff/CTA and must never be applied.
                return json.dumps({"section_updates": [{"index": 5, "append_voiceover": addition}]})
            return json.dumps({"section_updates": [{"index": 2, "append_voiceover": addition}]})

    provider = RetryingLLM()
    result = await validate_or_repair_script(
        provider,
        undersized,
        tmp_path / "retry-short.json",
        ledger_text="",
        max_attempts=3,
        strict=False,
        expected_video_type="short",
    )

    assert provider.calls == 2
    assert result["sections"][-1]["narration"] == original_payoff
    assert result["sections"][2]["narration"].endswith(addition.strip())


@pytest.mark.asyncio
async def test_manual_export_provider_creates_queue_package(tmp_path, monkeypatch):
    from ytb_pipeline.platform.profiles import Platform, get_profile
    from ytb_pipeline.providers.registry import get_publish_provider

    profile = get_profile("facebook_reel")
    assert profile.platform == Platform.FACEBOOK_REEL

    video_file = tmp_path / "video.mp4"
    video_file.write_bytes(b"mp4")
    video = RenderedVideo(
        topic="topic",
        title="Title",
        description="Desc",
        tags=("tag",),
        video_path=video_file,
        duration_sec=12,
    )
    monkeypatch.setattr(settings, "manual_publish_dir", tmp_path / "manual")

    provider = get_publish_provider("facebook_reel")
    result = await provider.publish(video)

    assert result.uploaded is False
    assert result.url is not None
    manifest = Path(result.url)
    assert manifest.exists()
    assert json.loads(manifest.read_text(encoding="utf-8"))["platform"] == "facebook_reel"


@pytest.mark.asyncio
async def test_multiplatform_publish_validates_manual_export_manifest(tmp_path, monkeypatch):
    from dataclasses import replace

    from ytb_pipeline.pkg.models import PublishResult
    from ytb_pipeline.publish import multiplatform

    video_file = tmp_path / "video.mp4"
    video_file.write_bytes(b"mp4")
    video = RenderedVideo(
        topic="topic",
        title="Title",
        description="Mô tả đủ dài để qua kiểm tra nội dung gốc trước khi test riêng lỗi manifest của manual export.",
        tags=("tag",),
        video_path=video_file,
        duration_sec=12,
    )

    class BrokenProvider:
        async def publish(self, video):
            return replace(PublishResult(**vars(video)), uploaded=False, url=str(tmp_path / "missing.json"))

        def is_available(self):
            return True

    monkeypatch.setattr(multiplatform, "get_publish_provider", lambda _name: BrokenProvider())

    with pytest.raises(FileNotFoundError):
        await multiplatform.publish_to_platforms(video, ["manual_export"])


def test_run_project_resume_publish_rehydrates_rendered_video(tmp_path, monkeypatch):
    from ytb_pipeline import pipeline
    from ytb_pipeline.project.checkpoint import CheckpointManager
    from ytb_pipeline.project.models import Project

    script_path = tmp_path / "scripts" / "co-che-test-local.json"
    script_path.parent.mkdir()
    script_path.write_text(json.dumps(_valid_short_script(), ensure_ascii=False), encoding="utf-8")
    video_path = tmp_path / "assets" / "output" / "co-che-test-local.mp4"
    video_path.parent.mkdir(parents=True)
    video_path.write_bytes(b"mp4")

    checkpoint = CheckpointManager(tmp_path / "projects")
    # publish_fn re-hashes script_path and cross-checks it, plus the "input"
    # node's own ruleset_id/script_sha256/qa_decision, against Project
    # metadata (pipeline.py's "Release manifest" guards) before releasing —
    # a hand-built Project/checkpoint must satisfy all of it. The DAG's first
    # node is "input" (not "ideation"), and "audio_quality"/"render_quality"
    # are separate checkpointed nodes between voiceover/render and publish.
    script_sha256 = hashlib.sha256(script_path.read_bytes()).hexdigest()
    project = Project(
        project_id="co-che-test-local",
        script_path=str(script_path),
        metadata={"script_sha256": script_sha256, "ruleset_id": CONTRACT_VERSION},
    )
    project = checkpoint.mark_done(
        project,
        "input",
        str(script_path),
        {
            "title": "Cơ Chế Test Local",
            "segments": 6,
            "ruleset_id": CONTRACT_VERSION,
            "script_sha256": script_sha256,
            "qa_decision": "pass",
        },
    )
    project = checkpoint.mark_done(
        project,
        "voiceover",
        str(tmp_path / "assets/audio/co-che-test-local.mp3"),
        {
            "duration_sec": 42.0,
            "segments": [
                {"index": index, "audio_path": str(tmp_path / f"seg{index}.mp3"), "duration_sec": 10.5}
                for index in range(4)
            ],
        },
    )
    project = checkpoint.mark_done(
        project,
        "audio_quality",
        str(tmp_path / "assets/audio/co-che-test-local.mp3"),
        {"quality_status": "pass"},
    )
    project = checkpoint.mark_done(
        project,
        "render",
        str(video_path),
        {"video_path": str(video_path), "duration_sec": 42.0, "thumbnail_path": None},
    )
    project = checkpoint.mark_done(
        project,
        "render_quality",
        str(video_path),
        {"quality_status": "pass"},
    )

    seen: list[RenderedVideo] = []

    async def fake_publish_to_platforms(video, *, project_id=None):
        assert project_id == "co-che-test-local"
        seen.append(video)
        return {"youtube_short": replace(PublishResult(**vars(video)), uploaded=False, url="manual://queued")}

    monkeypatch.setattr(pipeline, "publish_to_platforms", fake_publish_to_platforms)
    monkeypatch.setattr(pipeline, "validate_final_video", lambda _video: None)

    result = asyncio.run(pipeline.run_project(project, checkpoint))

    assert seen
    assert seen[0].video_path == video_path
    assert seen[0].duration_sec == 42.0
    assert seen[0].segments[0].duration_sec == 10.5
    assert result.nodes["publish"].output_ref == "manual://queued"
    assert result.nodes["publish"].output_data["platforms"]["youtube_short"]["url"] == "manual://queued"
