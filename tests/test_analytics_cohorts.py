from __future__ import annotations

import pytest


def test_cohort_waits_for_four_mature_shorts_before_a_scale_decision():
    from ytb_pipeline.analytics.cohorts import classify_cohort

    decision = classify_cohort([
        {"age_hours": 72, "stayed_to_watch": 0.45, "short_to_long_clicks": 3,
         "subscribers_gained": 1}
        for _ in range(3)
    ], baseline_stayed_to_watch=0.22)

    assert decision == "needs_more_data"


def test_cohort_scales_only_when_hook_and_funnel_both_improve():
    from ytb_pipeline.analytics.cohorts import classify_cohort

    decision = classify_cohort([
        {"age_hours": 72, "stayed_to_watch": 0.42, "short_to_long_clicks": 4,
         "subscribers_gained": 1}
        for _ in range(4)
    ], baseline_stayed_to_watch=0.22)

    assert decision == "scale"


def test_analytics_store_keeps_snapshots_and_summarizes_each_format(tmp_path):
    from ytb_pipeline.analytics.feedback import AnalyticsStore

    store = AnalyticsStore(tmp_path / "analytics.json")
    for slug in ("a", "b", "c", "d"):
        store.record_snapshot(slug, {
            "age_hours": 72,
            "format_id": "core_answer_first_v1",
            "stayed_to_watch": 0.42,
            "short_to_long_clicks": 3,
            "subscribers_gained": 1,
        })

    assert len(store.get("a")["snapshots"]) == 1
    store.record_channel_baseline(stayed_to_watch=0.22)
    assert store.format_feedback(baseline_stayed_to_watch=0.22) == [
        "format=core_answer_first_v1: scale"
    ]
    assert "format=core_answer_first_v1: scale" in store.feedback_summary()


def test_analytics_snapshot_rejects_impossible_manual_short_metrics(tmp_path):
    from ytb_pipeline.analytics.feedback import AnalyticsStore

    with pytest.raises(ValueError, match="stayed_to_watch"):
        AnalyticsStore(tmp_path / "analytics.json").record_snapshot(
            "short-a", {"stayed_to_watch": 1.1}
        )


def test_batch_analytics_command_records_manual_baseline_and_short_snapshot(monkeypatch, capsys):
    from argparse import Namespace
    from ytb_pipeline.orchestrator import batch_cli as cli

    calls = []

    class FakeStore:
        def record_channel_baseline(self, *, stayed_to_watch):
            calls.append(("baseline", stayed_to_watch))

        def record_snapshot(self, slug, metrics):
            calls.append(("snapshot", slug, metrics))

        def feedback_summary(self):
            return ["format=core_answer_first_v1: needs_more_data"]

    monkeypatch.setattr(cli, "AnalyticsStore", FakeStore)

    cli.cmd_analytics(Namespace(action="baseline", stayed_to_watch=0.22))
    cli.cmd_analytics(
        Namespace(
            action="snapshot",
            slug="short-mo-laptop",
            format_id="core_answer_first_v1",
            age_hours=48,
            stayed_to_watch=0.31,
            short_to_long_clicks=2,
            subscribers_gained=1,
        )
    )
    cli.cmd_analytics(Namespace(action="summary"))

    assert calls == [
        ("baseline", 0.22),
        (
            "snapshot",
            "short-mo-laptop",
            {
                "format_id": "core_answer_first_v1",
                "age_hours": 48,
                "stayed_to_watch": 0.31,
                "short_to_long_clicks": 2,
                "subscribers_gained": 1,
            },
        ),
    ]
    assert "needs_more_data" in capsys.readouterr().out


def test_batch_analytics_parser_accepts_a_manual_snapshot(monkeypatch):
    from ytb_pipeline.orchestrator import batch_cli as cli

    captured = []
    monkeypatch.setattr(cli, "cmd_analytics", lambda args: captured.append(args))

    cli.main(
        [
            "analytics",
            "snapshot",
            "--slug",
            "short-mo-laptop",
            "--format-id",
            "core_answer_first_v1",
            "--age-hours",
            "48",
            "--stayed-to-watch",
            "0.31",
            "--short-to-long-clicks",
            "2",
            "--subscribers-gained",
            "1",
        ]
    )

    assert captured[0].action == "snapshot"
    assert captured[0].slug == "short-mo-laptop"
