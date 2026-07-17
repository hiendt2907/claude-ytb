from __future__ import annotations

import json


def test_reconcile_batch_state_records_script_and_verified_ledger_state(tmp_path, monkeypatch):
    from ytb_pipeline.orchestrator import batch_cli as cli

    state_path = tmp_path / "auto_state.json"
    ledger_path = tmp_path / "ledger.md"
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "short-a.json").write_text('{"slug":"short-a"}', encoding="utf-8")
    state_path.write_text(json.dumps({
        "shorts_funnel_batch_2026-07-17": {
            "long_videos": [],
            "short_videos": [{"day": 1, "slug": "short-a", "status": "ok"}],
        },
    }), encoding="utf-8")
    ledger_path.write_text(
        "# Ledger\n"
        "| Ngày | Slug | Tiêu đề | Stage | Status | URL / ghi chú |\n"
        "|---|---|---|---|---|---|\n"
        "| 2026-07-17 | short-a | Một short | done | ok | https://youtu.be/abcDEF12345 — verified qua YouTube API |\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(cli, "AUTO_STATE_PATH", state_path)
    monkeypatch.setattr(cli, "LEDGER_PATH", ledger_path)
    monkeypatch.setattr(cli, "ROOT", tmp_path)

    summary = cli.reconcile_batch_state("shorts_funnel_batch_2026-07-17")

    data = json.loads(state_path.read_text(encoding="utf-8"))
    item = data["shorts_funnel_batch_2026-07-17"]["short_videos"][0]
    assert summary == {"done": 1, "pending": 0, "error": 0}
    assert item["status"] == "done"
    assert item["publish_verified"] is True
    assert item["youtube_id"] == "abcDEF12345"
    assert item["provenance"]["script_sha256"]
    assert item["provenance"]["ledger"]["stage"] == "done"
