from __future__ import annotations

import json

from ytb_pipeline.orchestrator.queue_manager import load_queue


def test_queue_preserves_series_and_funnel_metadata(tmp_path):
    state = tmp_path / "auto_state.json"
    state.write_text(json.dumps({
        "shorts_funnel_batch_test": {
            "short_videos": [{
                "day": 1, "slug": "loss-aversion", "shorts_status": "queued",
                "series": "Quyết định đời thường", "content_pillar": "tiền bạc",
                "core_mechanism": "loss aversion", "audience_problem": "chi tiêu bốc đồng",
                "long_form_slug": "loss-aversion-long", "playlist": "Tâm lý tiền bạc",
                "cta_target": "loss-aversion-long",
            }],
        },
    }), encoding="utf-8")

    item = load_queue(state)

    assert item[0].series == "Quyết định đời thường"
    assert item[0].core_mechanism == "loss aversion"
    assert item[0].cta_target == "loss-aversion-long"


def test_strategy_v1_batch_rejects_missing_metadata_and_more_than_two_shorts_per_day():
    from ytb_pipeline.analytics.funnel import audit_batch

    batch = {
        "status": "queued",
        "content_strategy_version": "v1",
        "long_videos": [{"slug": "long-a"}],
        "short_videos": [
            {
                "slug": f"short-{number}", "publish_at": "2026-08-10T06:00:00+07:00",
                "long_form_slug": "long-a", "playlist": "series", "cta_target": "long-a",
            }
            for number in range(3)
        ],
    }

    audit = audit_batch(batch)

    assert "strategy_metadata_missing" in audit.issues
    assert "shorts_per_day_exceeded" in audit.issues
