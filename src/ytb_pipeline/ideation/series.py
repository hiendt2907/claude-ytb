"""Khâu -0.5/B+C — Dựng series 30 ngày từ kết quả research.

Phân chia trách nhiệm rõ:

- **Claude (sáng tạo):** chọn ngách thắng, sinh 30 chủ đề con KHÁC NHAU hợp ngách,
  chấm điểm 4 tiêu chí cho từng ứng viên ngách. Đây là phần ngôn ngữ/đánh giá.
- **Code (xác định, ở file này):** chuẩn hoá slug, chấm tổng & xếp hạng ngách theo
  điểm đã cho, tính lịch publish 06:00 (+1 ngày/tập), loại tập trùng slug có sẵn
  trong ledger, lắp khối `series` và ghi vào `auto_state.json` (atomic, không mutate).

Tất cả hàm thuần để test offline; `write_series` là tác dụng phụ duy nhất (ghi file).
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date, timedelta
from pathlib import Path

from ..orchestrator.state_io import locked_json_update

DAYS_TOTAL = 30
PUBLISH_HOUR = 6           # giờ vàng brand "1 Cốc Café 6h"
PUBLISH_TZ = "+0700"
# 4 tiêu chí chấm ngách (mục B của skill). Trọng số bằng nhau, thang 1–5.
NICHE_CRITERIA = ("search", "competition", "ypp", "brand")


# ---------------------------------------------------------------------------
# Slug & lịch publish (thuần, xác định)
# ---------------------------------------------------------------------------

def slugify(text: str) -> str:
    """Chuẩn hoá tiêu đề -> slug ascii: bỏ dấu tiếng Việt, hạ thường, nối '-'."""
    text = text.replace("đ", "d").replace("Đ", "D")
    normalized = unicodedata.normalize("NFD", text)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    ascii_text = ascii_text.lower()
    ascii_text = re.sub(r"[^a-z0-9]+", "-", ascii_text)
    return ascii_text.strip("-")


def publish_at(started_at: str, day: int, *, hour: int = PUBLISH_HOUR) -> str:
    """RFC3339 cho tập `day` (1-indexed): started_at + day ngày, lúc `hour`:00 +07:00.

    Tập 1 publish vào NGÀY HÔM SAU started_at (ngày làm = started_at, ra mắt +1).
    """
    start = date.fromisoformat(started_at)
    publish_day = start + timedelta(days=day)
    return f"{publish_day.isoformat()}T{hour:02d}:00:00{PUBLISH_TZ}"


# ---------------------------------------------------------------------------
# Chấm & chọn ngách (thuần)
# ---------------------------------------------------------------------------

def derive_search_score(views: int, trend: str) -> int:
    """Quy đổi lượt xem + đà tăng -> điểm search 1–5 (gợi ý cho tiêu chí 1)."""
    if views >= 1_000_000:
        base = 5
    elif views >= 300_000:
        base = 4
    elif views >= 50_000:
        base = 3
    elif views >= 5_000:
        base = 2
    else:
        base = 1
    if trend == "up":
        base = min(5, base + 1)
    elif trend == "down":
        base = max(1, base - 1)
    return base


def rank_niches(candidates: list[dict]) -> list[dict]:
    """Xếp hạng ứng viên ngách theo tổng 4 tiêu chí (desc), tie-break theo tên.

    Mỗi candidate: {"niche": str, "scores": {search, competition, ypp, brand}}.
    Trả bản sao có thêm `total`; KHÔNG mutate input.
    """
    scored = [
        {**c, "total": sum(c["scores"].get(k, 0) for k in NICHE_CRITERIA)}
        for c in candidates
    ]
    return sorted(scored, key=lambda c: (-c["total"], c["niche"]))


def pick_niche(candidates: list[dict]) -> dict:
    """Chọn ngách điểm cao nhất. Rỗng -> fail fast."""
    if not candidates:
        raise ValueError("Không có ứng viên ngách nào để chọn (research rỗng?).")
    return rank_niches(candidates)[0]


# ---------------------------------------------------------------------------
# Dựng episodes + dedup theo ledger (thuần)
# ---------------------------------------------------------------------------

def dedup_topics(topics: list[str], ledger_text: str) -> list[str]:
    """Loại chủ đề mà slug đã xuất hiện trong ledger (chống trùng cấp slug).

    Đây là lưới AN TOÀN cấp slug — chống-trùng ngữ nghĩa vẫn do Claude phán đoán
    (xem Bước -2 skill). Giữ thứ tự, loại trùng nội bộ danh sách luôn.
    """
    seen: set[str] = set()
    kept: list[str] = []
    for topic in topics:
        slug = slugify(topic)
        if slug and slug not in seen and slug not in ledger_text:
            seen.add(slug)
            kept.append(topic)
    return kept


def build_episodes(topics: list[str], started_at: str, *,
                   hour: int = PUBLISH_HOUR) -> list[dict]:
    """Gắn day/slug/publish_at/status='queued' cho từng chủ đề (1 tập/ngày)."""
    return [
        {
            "day": i,
            "slug": slugify(topic),
            "topic": topic,
            "publish_at": publish_at(started_at, i, hour=hour),
            "status": "queued",
        }
        for i, topic in enumerate(topics, start=1)
    ]


def build_series(*, niche: str, reason: str, research: dict, topics: list[str],
                 started_at: str, days_total: int = DAYS_TOTAL,
                 hour: int = PUBLISH_HOUR, slot: str = "morning") -> dict:
    """Lắp khối `series` hoàn chỉnh cho auto_state.json.

    `research` là output của research_trending ({"research":[...], "seo_pool":{...}}).
    `topics` là 30 chủ đề con Claude đã sinh + ĐÃ qua dedup. Trả dict mới (immutable).
    `slot` gắn nhãn khung giờ ("morning" 06:00 / "evening" 20:00) để chạy nhiều series
    song song; `hour` quyết định giờ publish thực tế của lịch.
    """
    return {
        "status": "active",
        "slot": slot,
        "niche": niche,
        "reason": reason,
        "research": research.get("research", []),
        "seo_pool": research.get("seo_pool", {"hashtags": [], "keywords": []}),
        "started_at": started_at,
        "days_total": days_total,
        "episodes": build_episodes(topics, started_at, hour=hour),
    }


# ---------------------------------------------------------------------------
# Lấy tập kế tiếp & đánh dấu hoàn thành (thuần, immutable)
# ---------------------------------------------------------------------------

def next_episode(series_block: dict) -> dict | None:
    """Tập `queued` sớm nhất (theo `day`) của series đang active; None nếu hết/đã done.

    Đây là điểm vào mỗi vòng sản xuất: lấy chủ đề tập kế tiếp nạp vào ideation.
    """
    if series_block.get("status") != "active":
        return None
    queued = [e for e in series_block.get("episodes", ()) if e.get("status") == "queued"]
    if not queued:
        return None
    return min(queued, key=lambda e: e.get("day", 0))


def mark_episode_done(series_block: dict, slug: str) -> dict:
    """Trả series MỚI với tập `slug` -> status='done'; KHÔNG mutate bản gốc.

    Khi mọi tập đã done -> đặt `series.status='done'`. Slug không tồn tại -> fail fast.
    """
    episodes = series_block.get("episodes", [])
    if not any(e.get("slug") == slug for e in episodes):
        raise ValueError(f"Series không có tập slug={slug!r} để đánh dấu done.")

    new_episodes = [
        {**e, "status": "done"} if e.get("slug") == slug else e
        for e in episodes
    ]
    all_done = all(e.get("status") == "done" for e in new_episodes)
    return {
        **series_block,
        "episodes": new_episodes,
        "status": "done" if all_done else series_block.get("status", "active"),
    }


# ---------------------------------------------------------------------------
# Ghi state (tác dụng phụ duy nhất, atomic, không mutate khối cũ)
# ---------------------------------------------------------------------------

def write_series(series_block: dict, state_path: str | Path,
                 *, key: str = "series") -> None:
    """Merge khối series vào auto_state.json mà KHÔNG đụng các khối khác.

    `key` chọn vị trí lưu: `"series"` (mặc định, series sáng) hoặc một key riêng như
    `"series_evening"` để chạy nhiều series song song. Đọc state hiện tại (nếu có) ->
    tạo dict MỚI gắn series -> ghi atomic qua file tạm.
    """
    path = Path(state_path)
    with locked_json_update(path) as existing:
        existing[key] = series_block
