"""Tự động tải B-roll Pexels cho từng cảnh, đổ đúng vào cấu trúc `scene_XX/`
mà `assembler/scanning.py` đọc — không cần sửa gì ở assembler.

Mỗi đoạn kịch bản (segment) → 1 thư mục cảnh (`scene_00/`, `scene_01/`...),
mỗi thư mục chứa nhiều clip candidate (`1.1.mp4`, `1.2.mp4`...) để giữ nguyên
cơ chế chọn/ghép N-variant sẵn có của `assembler/assignment.py`.

Chỉ dùng stdlib (urllib) — không thêm dependency, cùng cách làm với
`claude-ytb/render/stock.py`.
"""

from __future__ import annotations

import hashlib
import http.client
import json
import shutil
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from .config import load_content_settings
from .models import Script

SEARCH_URL = "https://api.pexels.com/videos/search"
CACHE_DIR = Path("assets/broll")
_HTTP_TIMEOUT = 60
DEFAULT_CANDIDATES_PER_SCENE = 3
PORTRAIT_WH = (1080, 1920)
LANDSCAPE_WH = (1920, 1080)


def fetch_scenes(
    script: Script,
    output_dir: Path,
    *,
    candidates_per_scene: int = DEFAULT_CANDIDATES_PER_SCENE,
    landscape: bool = False,
) -> list[Path]:
    """Tải candidate cho MỌI segment của `script`, trả về list thư mục cảnh đã tạo.

    Ném RuntimeError ngay (fail fast) nếu thiếu PEXELS_API_KEY — không âm thầm
    bỏ qua cảnh nào.
    """
    settings = load_content_settings()
    if not settings.pexels_api_key:
        raise RuntimeError(
            "Thiếu PEXELS_API_KEY — không thể tự động tải B-roll. "
            "Lấy key free tại https://www.pexels.com/api/"
        )

    scene_dirs: list[Path] = []
    for i, segment in enumerate(script.segments):
        query = " ".join(segment.visual_keywords) or segment.narration
        scene_dir = output_dir / f"scene_{i:02d}"
        scene_dir.mkdir(parents=True, exist_ok=True)
        links = _search_links(
            query, settings.pexels_api_key, count=candidates_per_scene, landscape=landscape
        )
        for j, link in enumerate(links, start=1):
            cached = _download_cached(link)
            dest = scene_dir / f"{i + 1}.{j}.mp4"
            shutil.copyfile(cached, dest)
        scene_dirs.append(scene_dir)
    return scene_dirs


def _search_links(query: str, key: str, *, count: int, landscape: bool) -> list[str]:
    orientation = "landscape" if landscape else "portrait"
    params = urllib.parse.urlencode(
        {"query": query, "orientation": orientation, "size": "medium",
         "per_page": min(80, max(15, count))}
    )
    req = urllib.request.Request(
        f"{SEARCH_URL}?{params}",
        headers={"Authorization": key, "User-Agent": "video-render/1.0"},
    )
    with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT) as resp:
        data = json.loads(resp.read().decode())

    links = _rank_links(data.get("videos", []), landscape)
    if not links:
        raise RuntimeError(f"Pexels không có B-roll dùng được cho từ khoá: '{query}'")
    return links[:count]


def _rank_links(videos: list[dict], landscape: bool) -> list[str]:
    """Giữ nguyên thứ tự relevance Pexels trả về, mỗi video lấy 1 file đúng hướng."""
    seen: set[str] = set()
    links: list[str] = []
    for v in videos:
        f = _best_file(v.get("video_files", []), landscape)
        if f and f["link"] not in seen:
            seen.add(f["link"])
            links.append(f["link"])
    return links


def _best_file(files: list[dict], landscape: bool) -> dict | None:
    def correct(f: dict) -> bool:
        w, h = f.get("width", 0), f.get("height", 0)
        return (w >= h) if landscape else (h >= w)

    mp4 = [f for f in files if f.get("file_type") == "video/mp4"]
    pool = [f for f in mp4 if correct(f)] or mp4
    if not pool:
        return None
    return min(pool, key=lambda f: _score(f, landscape))


def _score(f: dict, landscape: bool) -> float:
    tw, th = LANDSCAPE_WH if landscape else PORTRAIT_WH
    return abs(f.get("height", 0) - th) + abs(f.get("width", 0) - tw)


def _download_cached(url: str) -> Path:
    """Cache theo hash của link — link giống nhau không tải lại."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_key = hashlib.sha256(url.encode()).hexdigest()[:16]
    cached = CACHE_DIR / f"{cache_key}.mp4"
    if not (cached.exists() and cached.stat().st_size > 0):
        _download(url, cached)
    return cached


def _download(url: str, dest: Path, *, retries: int = 3) -> None:
    """Tải atomic (qua .part) + retry khi mạng đứt giữa chừng."""
    req = urllib.request.Request(url, headers={"User-Agent": "video-render/1.0"})
    last_err: Exception | None = None
    for attempt in range(1, retries + 1):
        tmp = dest.with_suffix(dest.suffix + ".part")
        try:
            with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT) as resp:
                data = resp.read()
                expected = resp.headers.get("Content-Length")
                if expected is not None and len(data) != int(expected):
                    raise OSError(f"tải thiếu: {len(data)}/{expected} bytes")
            tmp.write_bytes(data)
            tmp.replace(dest)
            return
        except (urllib.error.URLError, OSError, http.client.IncompleteRead) as exc:
            last_err = exc
            tmp.unlink(missing_ok=True)
            if attempt == retries:
                break
    raise OSError(f"không tải được {url} sau {retries} lần thử: {last_err}")
