"""CacheManager — content-hash cache cho output đắt (TTS audio, render video).

Key = SHA-256(JSON sorted của kwargs đầu vào: prompt + model + params...).
Tránh tính lại khi cùng input chạy lại (resume/replay).
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path


class CacheManager:
    """Content-hash based cache. Key = SHA-256(prompt + model + params JSON)."""

    def __init__(self, cache_dir: Path) -> None:
        self.cache_dir = Path(cache_dir)
        self._hits = 0
        self._misses = 0

    def key(self, **kwargs) -> str:
        """Tính SHA-256 hash của JSON (sorted keys) các kwargs."""
        payload = json.dumps(kwargs, sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _cache_path(self, cache_key: str, ext: str) -> Path:
        ext = ext if ext.startswith(".") else f".{ext}"
        return self.cache_dir / f"{cache_key}{ext}"

    def get(self, cache_key: str, ext: str) -> Path | None:
        """Trả path nếu file cache tồn tại, ngược lại None. Cập nhật hit/miss."""
        path = self._cache_path(cache_key, ext)
        if path.exists():
            self._hits += 1
            return path
        self._misses += 1
        return None

    def has(self, cache_key: str, ext: str) -> bool:
        return self._cache_path(cache_key, ext).exists()

    def put(self, cache_key: str, ext: str, source: Path) -> Path:
        """Copy source vào cache/<key>.<ext>, trả cache path."""
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        dest = self._cache_path(cache_key, ext)
        shutil.copyfile(source, dest)
        return dest

    def stats(self) -> dict:
        """Trả {total_files, total_bytes, hit_rate_this_session}."""
        total_files = 0
        total_bytes = 0
        if self.cache_dir.exists():
            for entry in self.cache_dir.iterdir():
                if entry.is_file():
                    total_files += 1
                    total_bytes += entry.stat().st_size

        total_lookups = self._hits + self._misses
        hit_rate = (self._hits / total_lookups) if total_lookups else 0.0

        return {
            "total_files": total_files,
            "total_bytes": total_bytes,
            "hit_rate_this_session": hit_rate,
        }
