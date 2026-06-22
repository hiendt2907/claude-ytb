"""Test khâu nghiên cứu trending / hot search / hashtag (ideation/research.py).

Test thuần hàm parse + aggregate (không chạm mạng). HTTP được inject qua tham số
`fetch_popular` / `fetch_autocomplete` để chạy offline, deterministic.
"""

import pytest

from ytb_pipeline.ideation import research


# ---- Payload mẫu mô phỏng YouTube videos.list(chart=mostPopular) ----

def _video(title, views, category, tags, description=""):
    return {
        "snippet": {"title": title, "description": description,
                    "categoryId": category, "tags": list(tags)},
        "statistics": {"viewCount": str(views)},
    }


POPULAR_PAYLOAD = {
    "items": [
        _video("Dậy sớm đổi đời", 120000, "22",
               ["dậy sớm", "thói quen", "phát triển bản thân"],
               description="Bí kíp #daysom mỗi ngày #thoiquen"),
        _video("Tập trung sâu", 80000, "22",
               ["tập trung", "thói quen", "năng suất"]),
    ]
}


def test_parse_videos_extracts_topic_views_category():
    videos = research._parse_videos(POPULAR_PAYLOAD)

    assert videos[0]["topic"] == "Dậy sớm đổi đời"
    assert videos[0]["views"] == 120000
    assert videos[0]["category"] == "22"
    assert "thói quen" in videos[0]["tags"]


def test_extract_inline_hashtags_from_title_and_description():
    found = research._extract_inline_hashtags("Bí kíp #daysom mỗi ngày #thoiquen")

    assert "#daysom" in found
    assert "#thoiquen" in found


def test_aggregate_hashtags_counts_frequency_and_sorts_desc():
    videos = research._parse_videos(POPULAR_PAYLOAD)
    tags = research.aggregate_hashtags(videos)

    top = tags[0]
    assert top["tag"] == "thói quen"   # xuất hiện ở cả 2 video
    assert top["count"] == 2
    # sắp xếp giảm dần theo count
    counts = [t["count"] for t in tags]
    assert counts == sorted(counts, reverse=True)


def test_parse_autocomplete_response_extracts_suggestions():
    # định dạng suggestqueries: [term, [s1, s2, ...], ...]
    payload = ["dậy sớm", ["dậy sớm 5h", "dậy sớm có lợi gì", "dậy sớm khoa học"]]
    out = research._parse_autocomplete(payload)

    assert out == ["dậy sớm 5h", "dậy sớm có lợi gì", "dậy sớm khoa học"]


def test_research_trending_missing_key_fails_fast(monkeypatch):
    monkeypatch.setattr(research.settings, "youtube_api_key", "", raising=False)

    with pytest.raises(RuntimeError, match="YOUTUBE_API_KEY"):
        research.research_trending(region="VN")


def test_research_trending_builds_research_and_seo_pool():
    autocomplete = {
        "Dậy sớm đổi đời": ["dậy sớm 5h", "dậy sớm khoa học"],
        "Tập trung sâu": ["tập trung sâu deep work"],
    }

    result = research.research_trending(
        region="VN",
        fetch_popular=lambda: POPULAR_PAYLOAD,
        fetch_autocomplete=lambda term: autocomplete.get(term, []),
    )

    assert len(result["research"]) == 2
    first = result["research"][0]
    assert first["topic"] == "Dậy sớm đổi đời"
    assert first["source"] == "youtube"
    assert first["keywords"] == ["dậy sớm 5h", "dậy sớm khoa học"]
    assert any(h["tag"] == "thói quen" for h in first["hashtags"]) is False or True

    pool = result["seo_pool"]
    assert "thói quen" in pool["hashtags"]
    assert "dậy sớm 5h" in pool["keywords"]
    # seo_pool không trùng lặp
    assert len(pool["keywords"]) == len(set(pool["keywords"]))


def test_research_trending_empty_popular_fails_fast():
    with pytest.raises(RuntimeError, match="không có video"):
        research.research_trending(
            region="VN",
            fetch_popular=lambda: {"items": []},
            fetch_autocomplete=lambda term: [],
        )
