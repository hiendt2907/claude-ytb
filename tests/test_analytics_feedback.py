from __future__ import annotations


def test_feedback_labels_scale_for_strong_retention_and_subscribers(tmp_path):
    from ytb_pipeline.analytics.feedback import AnalyticsStore

    store = AnalyticsStore(tmp_path / "analytics.json")
    label = store.record("loss-aversion", {
        "views": 12000, "retention_3s": 0.78, "average_percentage_viewed": 0.72,
        "subscribers_gained": 35, "comments": 12, "short_to_long_clicks": 40,
    })

    assert label == "scale"
    assert store.get("loss-aversion")["decision"] == "scale"


def test_feedback_labels_revise_hook_and_waits_before_48_hours(tmp_path):
    from ytb_pipeline.analytics.feedback import AnalyticsStore

    store = AnalyticsStore(tmp_path / "analytics.json")
    assert store.record("fresh", {"age_hours": 24, "views": 100}) == "needs_more_data"
    assert store.record("weak-hook", {"age_hours": 72, "retention_3s": 0.25}) == "revise_hook"


def test_ideation_prompt_includes_mature_feedback():
    from ytb_pipeline.orchestrator.ideation_prompts import local_script_prompt

    prompt = local_script_prompt(1, 1, "short", "auto", "", analytics_feedback=["old: revise_hook"])

    assert "old: revise_hook" in prompt
    assert "drop_format" in prompt


def test_collect_youtube_metrics_records_api_report_with_video_age(tmp_path):
    from ytb_pipeline.analytics.feedback import AnalyticsStore, collect_youtube_metrics

    class Request:
        def execute(self):
            return {"rows": [[1200, 37.5, 62.0, 4, 9]]}

    class Reports:
        def query(self, **kwargs):
            assert kwargs["filters"] == "video==abc123"
            assert "averageViewPercentage" in kwargs["metrics"]
            return Request()

    class Client:
        def reports(self):
            return Reports()

    store = AnalyticsStore(tmp_path / "analytics.json")
    decision = collect_youtube_metrics(
        "video-a", "abc123", analytics_client=Client(), store=store,
        published_at="2026-07-10T00:00:00+00:00", now="2026-07-13T00:00:00+00:00",
    )

    saved = store.get("video-a")
    assert saved["views"] == 1200
    assert saved["average_percentage_viewed"] == 62.0
    assert saved["age_hours"] == 72.0
    assert decision in {"scale", "revise_value", "needs_more_data"}


def test_collect_youtube_metrics_without_rows_waits_for_data(tmp_path):
    from ytb_pipeline.analytics.feedback import AnalyticsStore, collect_youtube_metrics

    class Request:
        def execute(self):
            return {"rows": []}

    class Client:
        def reports(self):
            return type("Reports", (), {"query": lambda _self, **_kwargs: Request()})()

    assert collect_youtube_metrics(
        "scheduled", "id", analytics_client=Client(), store=AnalyticsStore(tmp_path / "a.json"),
    ) == "needs_more_data"
