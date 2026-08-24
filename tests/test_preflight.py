"""Preflight must reject bad queue input before any paid or networked stage."""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path
from types import SimpleNamespace

from ytb_pipeline.content_contract import CONTRACT_VERSION


def _payload() -> dict:
    narration = "Một bước nhỏ và rõ ràng giúp bạn bắt đầu công việc đang bị trì hoãn. " * 4
    sections = [
        {
            "purpose": "situation" if index == 0 else ("core_answer" if index == 1 else "application"),
            "voiceover": narration,
            "visual_intent": "Nhân viên văn phòng nhìn danh sách việc.",
            "pexels_query": "office task list",
            "time_goal": 0.2,
        }
        for index in range(6)
    ]
    sections[0]["voiceover"] = "Bạn mở danh sách việc rồi lại trì hoãn."
    sections[1]["voiceover"] = "Hãy chọn một bước nhỏ có thể nhìn thấy. " + narration
    return {
        "ruleset_id": CONTRACT_VERSION,
        "video_type": "short",
        "title": "Bắt đầu một việc rõ ràng",
        "topic": "Công việc",
        "description": "Một hướng dẫn ngắn để bắt đầu việc khó.",
        "tags": ["công việc", "tập trung", "bắt đầu"],
        "compliance": {
            "passed": True,
            "community": "PASS",
            "copyright": "PASS",
            "accuracy": "PASS",
            "advertiser": "PASS",
            "coppa": "PASS",
            "notes": "Nội dung minh hoạ.",
        },
        "thumbnail_brief": {
            "visual_contradiction": "Danh sách dài, một việc được chọn.",
            "subject": "Nhân viên văn phòng.",
            "emotion": "Nhẹ nhõm.",
            "headline": "Chọn một việc",
        },
        "strategy": {
            "format_id": "mechanism_short_v1",
            "core_mechanism": "giảm mơ hồ",
            "audience_problem": "khó bắt đầu việc",
            "angle": "bước đầu cụ thể",
            "long_form_slug": "long-a",
            "playlist": "series",
            "cta_target": "long-a",
            "source_long_slug": "long-a",
            "source_excerpt": "Một bước rõ ràng giảm do dự.",
            "source_section_index": 0,
            "hook": {
                "situation": "Bạn mở danh sách việc rồi lại trì hoãn.",
                "core_answer": "Hãy chọn một bước nhỏ có thể nhìn thấy.",
                "open_loop": "Điều này thay đổi gì?",
            },
        },
        "sections": sections,
    }


def _write_catalog(path: Path, video_path: Path) -> None:
    path.write_text(json.dumps({"assets": {"office": {
        "asset_id": "office",
        "source": "pexels",
        "license": "Pexels License",
        "source_url": "https://example.test/office",
        "local_path": str(video_path),
        "topics": ["office task list"],
        "orientation": "portrait",
        "duration_sec": 3,
        "uses": [],
    }}}), encoding="utf-8")


def test_preflight_passes_a_runnable_local_only_short_without_network(tmp_path, monkeypatch):
    from ytb_pipeline.config.settings import settings
    from ytb_pipeline.orchestrator.preflight import preflight_script

    script_path = tmp_path / "short.json"
    script_path.write_text(json.dumps(_payload()), encoding="utf-8")
    asset = tmp_path / "office.mp4"
    asset.write_bytes(b"local-video")
    catalog = tmp_path / "catalog.json"
    _write_catalog(catalog, asset)
    monkeypatch.setattr(settings, "asset_catalog_path", catalog)
    monkeypatch.setattr(settings, "orientation", "portrait")

    def forbidden(*_args, **_kwargs):
        raise AssertionError("preflight must not call network")

    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
    result = preflight_script(script_path)

    assert result.passed is True
    assert result.failures == ()


def test_preflight_reports_multiple_failures_in_one_run(tmp_path, monkeypatch):
    from ytb_pipeline.config.settings import settings
    from ytb_pipeline.orchestrator.preflight import preflight_script

    payload = _payload()
    payload.pop("ruleset_id")
    payload["thumbnail_brief"]["headline"] = ""
    payload["sections"][0]["pexels_query"] = "missing local scene"
    script_path = tmp_path / "bad.json"
    script_path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(settings, "asset_catalog_path", tmp_path / "empty.json")

    result = preflight_script(script_path)
    codes = {failure.code for failure in result.failures}

    assert result.passed is False
    assert "ruleset_id.current" in codes
    assert "thumbnail_brief.incomplete" in codes
    assert "asset.local_missing" in codes


def test_process_next_records_preflight_error_before_running_pipeline(tmp_path, monkeypatch):
    from ytb_pipeline.orchestrator import batch_cli as cli

    root = tmp_path
    (root / "scripts").mkdir()
    (root / "scripts" / "bad.json").write_text("{}", encoding="utf-8")
    state = root / "state.json"
    state.write_text(json.dumps({"shorts_funnel_batch_test": {"long_videos": [
        {"day": 1, "slug": "bad", "publish_at": ""},
    ]}}), encoding="utf-8")
    ledger = root / "ledger.md"
    ledger.write_text("# Ledger\n", encoding="utf-8")
    monkeypatch.setattr(cli, "ROOT", root)
    monkeypatch.setattr(cli, "run_with_retry", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not run")))

    assert cli.process_next(queue_path=state, ledger_path=ledger, publish=False) is True
    assert "preflight | error" in ledger.read_text(encoding="utf-8")


def test_cmd_run_defaults_to_dry_run_and_never_finalizes_upload(monkeypatch):
    from ytb_pipeline.orchestrator import batch_cli as cli

    calls: list[dict] = []
    monkeypatch.setattr(cli, "process_next", lambda **kwargs: calls.append(kwargs) or False)
    cli.cmd_run(SimpleNamespace(loop=False, workers=1, schedule=False, batch_key="", through="publish", publish=False))

    assert calls[0]["publish"] is False


def test_retry_rejects_a_failed_preflight_before_running_pipeline(monkeypatch):
    from ytb_pipeline.orchestrator import batch_cli as cli

    item = cli.QueueItem(day=1, slug="bad", publish_at="", shorts_status="queued")
    monkeypatch.setattr(cli, "load_queue", lambda: [item])
    monkeypatch.setattr(cli, "preflight_script", lambda _path: SimpleNamespace(
        passed=False,
        failures=(SimpleNamespace(code="ruleset_id.current", message="stale"),),
    ))
    monkeypatch.setattr(cli, "run_with_retry", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not run")))

    cli.cmd_retry(SimpleNamespace(slug="bad", publish=True))
