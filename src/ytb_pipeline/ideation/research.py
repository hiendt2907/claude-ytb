"""Khâu -0.5/A — Nghiên cứu trending / hot search / hashtag (region VN).

Thu thập tín hiệu xu hướng để chốt ngách + dựng series 30 ngày:

1. **Trending video + hashtag/tags hot** — YouTube Data API
   `videos.list(chart=mostPopular, regionCode=VN)`: lấy video đang hot, gom tần suất
   `snippet.tags` và trích `#hashtag` trong title/description. Tái dùng đúng 1 response
   này cho cả topic lẫn hashtag để khỏi tốn quota.
2. **Related / autocomplete (cụm dài đuôi)** — endpoint suggestqueries (`ds=yt`), KHÔNG
   cần API key, ra keyword cluster cho mỗi chủ đề nóng.

Trả về dict khớp khối `series.research` + `series.seo_pool` trong `assets/auto_state.json`.
Chỉ dùng stdlib (urllib). Fail fast nếu thiếu key hoặc không có video hot — KHÔNG bịa.

HTTP được tách thành `fetch_popular` / `fetch_autocomplete` để test offline và
deterministic; production dùng default đọc từ `settings`.
"""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from collections import Counter
from typing import Callable

from ..config.settings import settings

_HTTP_TIMEOUT = 30
_POPULAR_URL = "https://www.googleapis.com/youtube/v3/videos"
_AUTOCOMPLETE_URL = "https://suggestqueries.google.com/complete/search"

# Số chủ đề/keyword tối đa giữ lại để series không bị nhiễu.
DEFAULT_MAX_RESULTS = 20
SEO_POOL_HASHTAGS = 15
SEO_POOL_KEYWORDS = 30

# #hashtag: dấu # + chữ/số (re.UNICODE mặc định ở py3 nên bắt cả chữ có dấu tiếng Việt).
_HASHTAG_RE = re.compile(r"#\w+")


# ---------------------------------------------------------------------------
# Hàm thuần — parse & aggregate (test trực tiếp, không chạm mạng)
# ---------------------------------------------------------------------------

def _parse_videos(payload: dict) -> list[dict]:
    """Chuẩn hoá response videos.list thành list dict gọn cho downstream."""
    videos: list[dict] = []
    for item in payload.get("items", ()):
        snippet = item.get("snippet", {})
        stats = item.get("statistics", {})
        title = snippet.get("title", "").strip()
        if not title:
            continue
        description = snippet.get("description", "")
        videos.append({
            "topic": title,
            "views": _safe_int(stats.get("viewCount")),
            "category": snippet.get("categoryId", ""),
            "tags": tuple(snippet.get("tags", ())),
            "inline_hashtags": tuple(
                _extract_inline_hashtags(f"{title}\n{description}")
            ),
        })
    return videos


def _extract_inline_hashtags(text: str) -> list[str]:
    """Trích các #hashtag (lowercase) xuất hiện trong text."""
    return [m.lower() for m in _HASHTAG_RE.findall(text)]


def aggregate_hashtags(videos: list[dict]) -> list[dict]:
    """Gom tần suất tag/hashtag trên toàn bộ video hot, sort giảm dần theo count.

    Gộp `snippet.tags` (chuẩn hoá lowercase) với `#hashtag` inline (bỏ dấu # để
    đối sánh cùng pool). Trả [{tag, count}] — `tag` giữ nguyên dạng đọc được.
    """
    counter: Counter[str] = Counter()
    for video in videos:
        for tag in video.get("tags", ()):  # tags dạng cụm từ, giữ nguyên
            normalized = tag.strip().lower()
            if normalized:
                counter[normalized] += 1
        for hashtag in video.get("inline_hashtags", ()):  # '#abc' -> 'abc'
            counter[hashtag.lstrip("#")] += 1
    # sort: count desc, rồi alphabet để deterministic khi hoà
    ordered = sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))
    return [{"tag": tag, "count": count} for tag, count in ordered]


def _parse_autocomplete(payload) -> list[str]:
    """Trích danh sách gợi ý từ response suggestqueries: [term, [s1, s2, ...], ...]."""
    if not isinstance(payload, list) or len(payload) < 2:
        return []
    suggestions = payload[1]
    if not isinstance(suggestions, list):
        return []
    return [s for s in suggestions if isinstance(s, str) and s.strip()]


def _safe_int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


# ---------------------------------------------------------------------------
# Điều phối — research_trending
# ---------------------------------------------------------------------------

def research_trending(
    region: str = "VN",
    *,
    max_results: int = DEFAULT_MAX_RESULTS,
    hl: str = "vi",
    fetch_popular: Callable[[], dict] | None = None,
    fetch_autocomplete: Callable[[str], list[str]] | None = None,
) -> dict:
    """Nghiên cứu trending + hashtag + keyword cho region, trả khối research/seo_pool.

    Inject `fetch_popular`/`fetch_autocomplete` để test offline. Production để None ->
    dùng default đọc YouTube Data API + suggestqueries. Fail fast: thiếu key hoặc
    không có video hot nào.
    """
    fetch_popular = fetch_popular or (
        lambda: _http_get_json(_popular_url(region, max_results))
    )
    fetch_autocomplete = fetch_autocomplete or (
        lambda term: _parse_autocomplete(
            _http_get_json(_autocomplete_url(term, hl, region))
        )
    )

    payload = fetch_popular()
    videos = _parse_videos(payload)
    if not videos:
        raise RuntimeError(
            "YouTube mostPopular không có video nào cho region "
            f"{region!r} — không thể nghiên cứu trending. KHÔNG bịa số liệu; "
            "kiểm tra YOUTUBE_API_KEY / regionCode rồi chạy lại."
        )

    research: list[dict] = []
    for video in videos:
        keywords = list(fetch_autocomplete(video["topic"]))
        research.append({
            "topic": video["topic"],
            "views": video["views"],
            "trend": "up",
            "source": "youtube",
            "category": video["category"],
            "hashtags": aggregate_hashtags([video]),
            "keywords": keywords,
        })

    seo_pool = _build_seo_pool(videos, research)
    return {"research": research, "seo_pool": seo_pool}


def _build_seo_pool(videos: list[dict], research: list[dict]) -> dict:
    """Pool SEO toàn ngách (dedup) để khâu monetization tái dùng làm tag."""
    hashtags = [h["tag"] for h in aggregate_hashtags(videos)][:SEO_POOL_HASHTAGS]

    seen: set[str] = set()
    keywords: list[str] = []
    for item in research:
        for kw in item["keywords"]:
            if kw not in seen:
                seen.add(kw)
                keywords.append(kw)
    return {"hashtags": hashtags, "keywords": keywords[:SEO_POOL_KEYWORDS]}


# ---------------------------------------------------------------------------
# HTTP default (production) — chỉ stdlib
# ---------------------------------------------------------------------------

def _popular_url(region: str, max_results: int) -> str:
    key = settings.youtube_api_key
    if not key:
        raise RuntimeError(
            "Thiếu YOUTUBE_API_KEY trong .env — không thể nghiên cứu trending "
            "(videos.list mostPopular). Lấy key free ở Google Cloud Console."
        )
    params = urllib.parse.urlencode({
        "part": "snippet,statistics",
        "chart": "mostPopular",
        "regionCode": region,
        "maxResults": max_results,
        "key": key,
    })
    return f"{_POPULAR_URL}?{params}"


def _autocomplete_url(term: str, hl: str, region: str) -> str:
    params = urllib.parse.urlencode({
        "client": "firefox",  # trả JSON array thuần
        "ds": "yt",            # ds=yt -> gợi ý YouTube
        "hl": hl,
        "gl": region,
        "q": term,
    })
    return f"{_AUTOCOMPLETE_URL}?{params}"


def _http_get_json(url: str):
    """GET URL -> parse JSON. Raise RuntimeError nếu mạng/giải mã lỗi (không bịa)."""
    req = urllib.request.Request(url, headers={"User-Agent": "claude-ytb/research"})
    try:
        with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001 — gom mọi lỗi mạng thành thông báo rõ
        raise RuntimeError(f"Lỗi gọi {url.split('?')[0]}: {exc}") from exc
    return json.loads(raw)
