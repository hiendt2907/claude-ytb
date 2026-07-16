"""Tải B-roll miễn phí từ Pexels cho khâu render-ai.

Cho 1 từ khoá tiếng Anh -> tìm video hợp nhất (dọc cho Short, ngang cho clip dài)
-> tải về cache. Cache theo SHA-256 của (query + kích thước mong muốn) nên không
tải trùng — Short và clip dùng cache riêng.

Chỉ dùng stdlib (urllib) — không thêm dependency. Key đọc từ settings.pexels_api_key
(lấy free tại https://www.pexels.com/api/). Fail fast nếu thiếu key.
"""

from __future__ import annotations

import hashlib
import http.client
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ..config.settings import settings
from .asset_catalog import AssetCatalog

CACHE_DIR = Path("assets/broll")
SEARCH_URL = "https://api.pexels.com/videos/search"
_HTTP_TIMEOUT = 60
# Socket timeout alone does not cap a response that keeps trickling bytes.  A
# total deadline releases the batch worker so pipeline_runner can use its
# existing bounded retry/checkpoint path.
_DOWNLOAD_DEADLINE_SEC = 180
_DOWNLOAD_CHUNK_BYTES = 64 * 1024
_POOL_SIZE = 80  # pool link/query để dedup xuyên video (per_page tối đa của Pexels)
PORTRAIT_WH = (1080, 1920)
LANDSCAPE_WH = (1920, 1080)


def fetch_broll(query: str, *, min_duration: float = 0.0,
                landscape: bool = False) -> Path:
    """Trả về đường dẫn file B-roll cho `query` (tải nếu chưa có trong cache).

    landscape=False -> video dọc (Short); landscape=True -> video ngang (clip dài).
    Raise RuntimeError nếu thiếu key hoặc Pexels không trả kết quả nào.
    """
    key = settings.pexels_api_key
    if not key:
        raise RuntimeError(
            "Thiếu PEXELS_API_KEY trong .env — không thể tải B-roll cho render-ai. "
            "Lấy key free tại https://www.pexels.com/api/"
        )
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tw, th = LANDSCAPE_WH if landscape else PORTRAIT_WH
    cache_key = hashlib.sha256(f"{query}|{tw}x{th}".encode()).hexdigest()[:16]
    cached = CACHE_DIR / f"{cache_key}.mp4"
    if cached.exists() and cached.stat().st_size > 0:
        return cached

    video_url = _search(query, key, min_duration=min_duration, landscape=landscape)
    _download(video_url, cached)
    return cached


def fetch_broll_variants(query: str, count: int, *, min_duration: float = 0.0,
                         landscape: bool = False,
                         exclude: set[str] | None = None,
                         video_slug: str = "",
                         role: str = "body") -> list[Path]:
    """Trả về tối đa `count` cảnh B-roll KHÁC NHAU cho cùng `query`.

    Dùng cho render-ai cắt cảnh trong một segment: mỗi beat một shot khác nhau
    (đỡ đơn điệu) nhưng cùng chủ đề. Nếu Pexels trả ít hơn `count` shot, danh
    sách ngắn hơn — caller tự lặp lại (round-robin). Fail fast nếu thiếu key.

    `exclude`: tập link ĐÃ DÙNG ở nơi khác trong video. Ưu tiên chọn link chưa
    nằm trong tập này -> chống lặp clip xuyên suốt video (nhiều segment trùng từ
    khoá vẫn ra cảnh khác nhau). Link đã chọn được THÊM VÀO `exclude` (accumulator
    cấp-video). Chỉ khi hết link mới mới quay lại dùng link đã xuất hiện.
    Cache theo hash của LINK: link giống nhau -> cùng file (không tải lại),
    link khác nhau -> file khác (đủ đa dạng).
    """
    key = settings.pexels_api_key
    if not key:
        raise RuntimeError(
            "Thiếu PEXELS_API_KEY trong .env — không thể tải B-roll cho render-ai. "
            "Lấy key free tại https://www.pexels.com/api/"
        )
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    # Đào pool sâu (per_page tối đa Pexels = 80) để có đủ link KHÁC NHAU mà dedup.
    links = _search_links(query, key, count=_POOL_SIZE,
                          min_duration=min_duration, landscape=landscape)

    used = exclude if exclude is not None else set()
    catalog = AssetCatalog()
    # Catalog ranks new/low-use footage first; the existing per-video set remains
    # a hard preference so one render does not repeat a shot before exhausting pool.
    fresh = catalog.select_urls(links, excluded=used, role=role)
    reused = catalog.select_urls([l for l in links if l in used], role=role)
    chosen = (fresh + reused)[:count]  # hết link mới mới tái dùng

    # Chọn link xong mới tải: mỗi link → 1 file cache riêng (hash của link) nên
    # tải SONG SONG an toàn, không tranh chấp file. Thứ tự output giữ theo `chosen`.
    targets = [(link, CACHE_DIR / f"{hashlib.sha256(link.encode()).hexdigest()[:16]}.mp4")
               for link in chosen]
    missing = [(link, path) for link, path in targets
               if not (path.exists() and path.stat().st_size > 0)]
    if missing:
        workers = max(1, min(settings.broll_download_workers, len(missing)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(lambda t: _download(t[0], t[1]), missing))

    orientation = "landscape" if landscape else "portrait"
    for link, path in targets:
        used.add(link)
        catalog.record_usage(
            source_url=link,
            local_path=path,
            query=query,
            orientation=orientation,
            video_slug=video_slug,
            role=role,
            duration_sec=min_duration,
        )
    return [path for _, path in targets]


def _search(query: str, key: str, *, min_duration: float, landscape: bool) -> str:
    """Gọi Pexels search, chọn file đúng hướng gần kích thước mục tiêu nhất."""
    return _search_links(query, key, count=1, min_duration=min_duration,
                         landscape=landscape)[0]


def _search_links(query: str, key: str, *, count: int, min_duration: float,
                  landscape: bool) -> list[str]:
    """Danh sách link (mỗi video một shot riêng) xếp theo độ khớp kích thước."""
    orientation = "landscape" if landscape else "portrait"
    params = urllib.parse.urlencode(
        {"query": query, "orientation": orientation, "size": "medium",
         "per_page": min(80, max(15, count))}
    )
    req = urllib.request.Request(
        f"{SEARCH_URL}?{params}",
        headers={"Authorization": key, "User-Agent": "ytb-pipeline/1.0"},
    )
    with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT) as resp:
        data = json.loads(resp.read().decode())

    videos = [v for v in data.get("videos", []) if v.get("duration", 0) >= min_duration] \
        or data.get("videos", [])

    links = _rank_links(videos, landscape)
    if not links:
        raise RuntimeError(f"Pexels không có B-roll dùng được cho từ khoá: '{query}'")
    return links


def _rank_links(videos: list[dict], landscape: bool) -> list[str]:
    """Giữ NGUYÊN thứ tự relevance Pexels trả về (video đầu = khớp từ khoá nhất),
    mỗi video lấy file đúng hướng & gần độ phân giải mục tiêu nhất. Dedup link.

    Đây là điểm cốt lõi để 'video bám sát voice': KHÔNG sắp lại theo độ phân giải
    (sẽ phá thứ tự liên quan), chỉ dùng độ phân giải để chọn file TRONG một video.
    """
    seen: set[str] = set()
    links: list[str] = []
    for v in videos:
        f = _best_file(v.get("video_files", []), landscape)
        if f and f["link"] not in seen:
            seen.add(f["link"])
            links.append(f["link"])
    return links


def _best_file(files: list[dict], landscape: bool) -> dict | None:
    """File đúng hướng có độ phân giải gần mục tiêu nhất; ưu tiên .mp4."""
    def correct(f: dict) -> bool:
        w, h = f.get("width", 0), f.get("height", 0)
        return (w >= h) if landscape else (h >= w)

    mp4 = [f for f in files if f.get("file_type") == "video/mp4"]
    pool = [f for f in mp4 if correct(f)] or mp4
    if not pool:
        return None
    return min(pool, key=lambda f: _score(f, landscape))


def _score(f: dict, landscape: bool) -> float:
    """Càng nhỏ càng tốt: lệch độ phân giải so với mục tiêu."""
    tw, th = LANDSCAPE_WH if landscape else PORTRAIT_WH
    return abs(f.get("height", 0) - th) + abs(f.get("width", 0) - tw)


def _download(url: str, dest: Path, *, retries: int = 3) -> None:
    """Tải về atomic (qua .part) + retry khi mạng đứt giữa chừng.

    Pexels CDN thi thoảng cắt kết nối -> http.client.IncompleteRead. Ghi vào
    file tạm rồi rename để không bao giờ để lại cache lỗi một nửa.
    """
    req = urllib.request.Request(url, headers={"User-Agent": "ytb-pipeline/1.0"})
    last_err: Exception | None = None
    for attempt in range(1, retries + 1):
        tmp = dest.with_suffix(dest.suffix + ".part")
        try:
            with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT) as resp:
                expected = resp.headers.get("Content-Length")
                downloaded = 0
                started_at = time.monotonic()
                with tmp.open("wb") as output:
                    while True:
                        if time.monotonic() - started_at > _DOWNLOAD_DEADLINE_SEC:
                            raise TimeoutError(
                                f"tải B-roll quá {_DOWNLOAD_DEADLINE_SEC}s"
                            )
                        chunk = resp.read(_DOWNLOAD_CHUNK_BYTES)
                        if not chunk:
                            break
                        output.write(chunk)
                        downloaded += len(chunk)
                        if time.monotonic() - started_at > _DOWNLOAD_DEADLINE_SEC:
                            raise TimeoutError(
                                f"tải B-roll quá {_DOWNLOAD_DEADLINE_SEC}s"
                            )
                if expected is not None and downloaded != int(expected):
                    raise OSError(
                        f"tải thiếu: {downloaded}/{expected} bytes"
                    )
            tmp.replace(dest)
            return
        except (urllib.error.URLError, OSError, http.client.IncompleteRead) as exc:
            last_err = exc
            tmp.unlink(missing_ok=True)
            if attempt == retries:
                break
    raise OSError(f"không tải được {url} sau {retries} lần thử: {last_err}")
