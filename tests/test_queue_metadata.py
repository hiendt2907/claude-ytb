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
