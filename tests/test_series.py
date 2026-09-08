"""Test dựng series 30 ngày từ kết quả research (ideation/series.py).

Phần sáng tạo (30 chủ đề con) do Claude sinh và truyền vào; code lo phần xác định:
slug, chấm/chọn ngách, lịch publish 06:00, dedup theo ledger, ghi state atomic.
"""

import json

import pytest

from ytb_pipeline.ideation import series


def test_slugify_strips_vietnamese_accents_and_spaces():
    assert series.slugify("Dậy sớm đổi đời") == "day-som-doi-doi"
    assert series.slugify("Deep Work — tập trung") == "deep-work-tap-trung"


def test_publish_at_advances_one_day_per_episode_at_6am():
    assert series.publish_at("2026-06-17", 1) == "2026-06-18T06:00:00+0700"
    assert series.publish_at("2026-06-17", 3) == "2026-06-20T06:00:00+0700"


def test_derive_search_score_buckets_by_views_and_trend():
    high = series.derive_search_score(2_000_000, "up")
    low = series.derive_search_score(100, "flat")
    assert 1 <= low <= high <= 5
    assert high == 5


def test_rank_niches_sorts_by_total_score_desc():
    candidates = [
        {"niche": "A", "scores": {"search": 5, "competition": 2, "ypp": 3, "brand": 3}},
        {"niche": "B", "scores": {"search": 4, "competition": 5, "ypp": 5, "brand": 5}},
    ]
    ranked = series.rank_niches(candidates)
    assert ranked[0]["niche"] == "B"  # tổng 19 > 13
    assert "total" in ranked[0]


def test_build_episodes_assigns_day_slug_publish_and_queued():
    eps = series.build_episodes(
        ["Dậy sớm đổi đời", "Tập trung sâu"], started_at="2026-06-17"
    )
    assert eps[0] == {
        "day": 1, "slug": "day-som-doi-doi", "topic": "Dậy sớm đổi đời",
        "publish_at": "2026-06-18T06:00:00+0700", "status": "queued",
    }
    assert eps[1]["day"] == 2
    assert eps[1]["publish_at"] == "2026-06-19T06:00:00+0700"


def test_dedup_topics_removes_slug_already_in_ledger():
    ledger = "| day-som-doi-doi | Dậy sớm | done |\n"
    kept = series.dedup_topics(["Dậy sớm đổi đời", "Tập trung sâu"], ledger)
    assert kept == ["Tập trung sâu"]


def test_build_series_assembles_full_block():
    research = {"research": [{"topic": "x"}], "seo_pool": {"hashtags": ["#a"], "keywords": ["k"]}}
    block = series.build_series(
        niche="Phát triển bản thân thật",
        reason="search 5, ít kênh lớn",
        research=research,
        topics=["Dậy sớm đổi đời", "Tập trung sâu"],
        started_at="2026-06-17",
    )
    assert block["status"] == "active"
    assert block["niche"] == "Phát triển bản thân thật"
    assert block["days_total"] == 30
    assert block["seo_pool"] == research["seo_pool"]
    assert len(block["episodes"]) == 2


def test_write_series_merges_atomically_without_dropping_existing(tmp_path):
    state_path = tmp_path / "auto_state.json"
    state_path.write_text(json.dumps({"config": {"a": 1}, "items": [{"b": 2}]}),
                          encoding="utf-8")

    block = {"status": "active", "episodes": []}
    series.write_series(block, state_path)

    saved = json.loads(state_path.read_text(encoding="utf-8"))
    assert saved["config"] == {"a": 1}      # giữ nguyên khối cũ
    assert saved["items"] == [{"b": 2}]
    assert saved["series"] == block


def test_write_series_creates_file_when_absent(tmp_path):
    state_path = tmp_path / "auto_state.json"
    series.write_series({"status": "active"}, state_path)
    saved = json.loads(state_path.read_text(encoding="utf-8"))
    assert saved["series"]["status"] == "active"


def test_write_series_to_custom_key_keeps_other_series(tmp_path):
    """Hai series song song: ghi vào key riêng không đụng series sáng có sẵn."""
    state_path = tmp_path / "auto_state.json"
    morning = {"status": "active", "slot": "morning", "episodes": []}
    state_path.write_text(json.dumps({"series": morning}), encoding="utf-8")

    evening = {"status": "active", "slot": "evening", "episodes": []}
    series.write_series(evening, state_path, key="series_evening")

    saved = json.loads(state_path.read_text(encoding="utf-8"))
    assert saved["series"] == morning          # series sáng giữ nguyên
    assert saved["series_evening"] == evening


def test_build_series_tags_slot_and_publish_hour():
    """build_series với hour=20 + slot='evening' cho lịch 20:00 và gắn nhãn slot."""
    research = {"research": [], "seo_pool": {"hashtags": [], "keywords": []}}
    block = series.build_series(
        niche="Cơ chế tài chính cá nhân",
        reason="CPM cao, advertiser-safe",
        research=research,
        topics=["Lãi kép", "Lạm phát"],
        started_at="2026-06-18",
        hour=20,
        slot="evening",
    )
    assert block["slot"] == "evening"
    assert block["episodes"][0]["publish_at"].endswith("T20:00:00+0700")


def _block(*statuses):
    eps = [
        {"day": i, "slug": f"s{i}", "topic": f"t{i}",
         "publish_at": "2026-06-18T06:00:00+0700", "status": st}
        for i, st in enumerate(statuses, start=1)
    ]
    return {"status": "active", "episodes": eps}


def test_next_episode_returns_earliest_queued():
    block = _block("done", "queued", "queued")
    ep = series.next_episode(block)
    assert ep["day"] == 2
    assert ep["slug"] == "s2"


def test_next_episode_none_when_all_done():
    assert series.next_episode(_block("done", "done")) is None


def test_next_episode_none_when_series_not_active():
    block = _block("queued")
    block["status"] = "done"
    assert series.next_episode(block) is None


def test_mark_episode_done_sets_status_without_mutating_original():
    block = _block("queued", "queued")
    updated = series.mark_episode_done(block, "s1")

    assert updated["episodes"][0]["status"] == "done"
    assert updated["status"] == "active"          # còn tập queued
    assert block["episodes"][0]["status"] == "queued"  # bản gốc bất biến


def test_mark_episode_done_flips_series_to_done_when_last():
    block = _block("done", "queued")
    updated = series.mark_episode_done(block, "s2")
    assert updated["episodes"][1]["status"] == "done"
    assert updated["status"] == "done"


def test_mark_episode_done_unknown_slug_fails_fast():
    with pytest.raises(ValueError, match="không có tập"):
        series.mark_episode_done(_block("queued"), "nope")


# ---------------------------------------------------------------------------
# Funnel clusters: CHANNEL_GROWTH_PLAN.md ships 1 Long + 2 Shorts per day, with
# each Short pointing back at that day's Long. A flat one-video-per-day series
# cannot express that dependency.
# ---------------------------------------------------------------------------

def _clusters() -> list[dict]:
    return [
        {"long": "Thiên kiến xác nhận", "shorts": ["Đọc review sau khi mua", "Nghe phần đồng ý"]},
        {"long": "Chiết khấu hiện tại", "shorts": ["Tiêu tiền thưởng ngay", "Hoãn tập luyện"]},
    ]


def test_funnel_cluster_emits_one_long_then_its_shorts_each_day():
    from ytb_pipeline.ideation.series import build_funnel_episodes, slugify

    episodes = build_funnel_episodes(_clusters(), "2026-08-25")

    assert len(episodes) == 6  # 2 ngày x (1 Long + 2 Short)
    day1 = [e for e in episodes if e["day"] == 1]
    assert [e["video_type"] for e in day1] == ["long", "short", "short"]

    long_slug = slugify("Thiên kiến xác nhận")
    assert day1[0]["slug"] == long_slug
    assert day1[0].get("long_form_slug") in (None, "")
    for short in day1[1:]:
        assert short["long_form_slug"] == long_slug
        assert short["cta_target"] == long_slug


def test_funnel_cluster_schedules_long_and_shorts_at_their_own_hours():
    from ytb_pipeline.ideation.series import build_funnel_episodes

    episodes = build_funnel_episodes(
        _clusters(), "2026-08-25", long_hour=6, short_hours=(11, 20),
    )
    day1 = [e for e in episodes if e["day"] == 1]

    assert day1[0]["publish_at"].startswith("2026-08-26T06:00")
    assert day1[1]["publish_at"].startswith("2026-08-26T11:00")
    assert day1[2]["publish_at"].startswith("2026-08-26T20:00")
    # Day 2 rolls forward one calendar day, keeping each slot's hour.
    assert [e for e in episodes if e["day"] == 2][0]["publish_at"].startswith("2026-08-27T06:00")


def test_next_episode_holds_a_short_until_its_long_is_done():
    """Mirrors `process_next`, which refuses a Short whose Long has not published."""
    from ytb_pipeline.ideation.series import (
        build_funnel_episodes, mark_episode_done, next_episode, slugify,
    )

    block = {"status": "active", "episodes": build_funnel_episodes(_clusters(), "2026-08-25")}
    long_slug = slugify("Thiên kiến xác nhận")

    assert next_episode(block)["slug"] == long_slug  # Long đi trước

    block = mark_episode_done(block, long_slug)
    following = next_episode(block)

    assert following["video_type"] == "short"
    assert following["long_form_slug"] == long_slug


def test_next_episode_skips_to_the_following_long_when_shorts_are_blocked():
    """A cluster whose Long failed must not stall the whole series."""
    from ytb_pipeline.ideation.series import build_funnel_episodes, next_episode, slugify

    episodes = build_funnel_episodes(_clusters(), "2026-08-25")
    # Day 1's Long is neither queued nor done (e.g. permanently rejected by QA).
    episodes = [e for e in episodes if not (e["day"] == 1 and e["video_type"] == "long")]
    block = {"status": "active", "episodes": episodes}

    following = next_episode(block)

    assert following["slug"] == slugify("Chiết khấu hiện tại")
