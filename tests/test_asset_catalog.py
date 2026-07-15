from __future__ import annotations

from pathlib import Path


def test_catalog_records_required_asset_metadata_and_usage(tmp_path: Path):
    from ytb_pipeline.render.asset_catalog import AssetCatalog

    catalog = AssetCatalog(tmp_path / "catalog.json")
    catalog.record_usage(
        source_url="https://videos.pexels.com/clip-a.mp4",
        local_path=tmp_path / "clip-a.mp4",
        query="person putting phone away",
        orientation="portrait",
        video_slug="loss-aversion-short",
        role="hook",
        duration_sec=8.0,
    )

    asset = catalog.assets()[0]
    assert asset["asset_id"]
    assert asset["source"] == "pexels"
    assert asset["license"] == "Pexels License"
    assert asset["orientation"] == "portrait"
    assert asset["duration_sec"] == 8.0
    assert asset["topics"] == ["person putting phone away"]
    assert asset["uses"][0]["video_slug"] == "loss-aversion-short"
    assert asset["uses"][0]["role"] == "hook"


def test_catalog_prioritises_unused_asset_and_avoids_recent_same_role(tmp_path: Path):
    from ytb_pipeline.render.asset_catalog import AssetCatalog

    catalog = AssetCatalog(tmp_path / "catalog.json")
    reused = "https://videos.pexels.com/reused.mp4"
    fresh = "https://videos.pexels.com/fresh.mp4"
    catalog.record_usage(
        source_url=reused, local_path=tmp_path / "reused.mp4", query="phone at desk",
        orientation="portrait", video_slug="older-video", role="hook", duration_sec=7.0,
    )

    assert catalog.select_urls([reused, fresh], role="hook") == [fresh, reused]


def test_catalog_does_not_repeat_an_asset_inside_one_video(tmp_path: Path):
    from ytb_pipeline.render.asset_catalog import AssetCatalog

    catalog = AssetCatalog(tmp_path / "catalog.json")
    links = ["https://videos.pexels.com/a.mp4", "https://videos.pexels.com/b.mp4"]

    assert catalog.select_urls(links, excluded={links[0]}, role="payoff") == [links[1]]
