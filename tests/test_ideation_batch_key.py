from __future__ import annotations

import argparse
import json


def test_write_local_batch_item_honors_explicit_batch_key(tmp_path, monkeypatch):
    from ytb_pipeline.orchestrator import ideation_state

    state = tmp_path / "auto_state.json"
    state.write_text(json.dumps({
        "shorts_funnel_batch_week1": {
            "status": "active",
            "long_videos": [{"slug": "week1-long"}],
            "short_videos": [],
        },
    }), encoding="utf-8")
    ledger = tmp_path / "ledger.md"
    ledger.write_text("# Ledger\n", encoding="utf-8")

    class CLI:
        AUTO_STATE_PATH = state

        @staticmethod
        def update_ledger(*_args, **_kwargs):
            return None

        class settings:
            dry_run = True
            youtube_publish_at = ""

    monkeypatch.setattr(ideation_state, "_cli", lambda: CLI)

    script = tmp_path / "week1-short.json"
    ideation_state.write_local_batch_item(
        script,
        {"title": "Week 1 Short", "topic": "cơ chế"},
        argparse.Namespace(
            type_of_vid="short",
            batch_key="shorts_funnel_batch_week1",
            long_form_slug="week1-long",
            playlist="week1-playlist",
            cta_target="week1-long",
        ),
    )

    data = json.loads(state.read_text(encoding="utf-8"))
    assert "shorts_funnel_batch_week1" in data
    assert data["shorts_funnel_batch_week1"]["short_videos"][0]["slug"] == "week1-short"
    assert data["shorts_funnel_batch_week1"]["short_videos"][0]["cta_target"] == "week1-long"


def test_short_batch_item_requires_a_complete_long_form_funnel(tmp_path, monkeypatch):
    """A Short must not be persisted until its funnel contract is complete."""
    from ytb_pipeline.orchestrator import ideation_state

    state = tmp_path / "auto_state.json"
    state.write_text("{}", encoding="utf-8")

    class CLI:
        AUTO_STATE_PATH = state

        @staticmethod
        def update_ledger(*_args, **_kwargs):
            raise AssertionError("rejected Short must not reach the ledger")

        class settings:
            dry_run = True
            youtube_publish_at = ""

    monkeypatch.setattr(ideation_state, "_cli", lambda: CLI)

    import pytest

    with pytest.raises(SystemExit, match="long_form_slug.*playlist.*cta_target"):
        ideation_state.write_local_batch_item(
            tmp_path / "orphan-short.json",
            {"title": "Orphan Short", "topic": "cơ chế"},
            argparse.Namespace(type_of_vid="short", batch_key="shorts_funnel_batch_week2"),
        )

    assert json.loads(state.read_text(encoding="utf-8")) == {}
