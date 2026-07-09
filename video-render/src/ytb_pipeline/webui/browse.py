"""Liệt kê thư mục trên đĩa cho file browser trong UI — thay thế nhập path tay."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

_MEDIA_SUFFIXES = {
    ".mp4", ".mov", ".mkv", ".avi", ".webm", ".wav", ".mp3", ".m4a", ".aac",
    ".png", ".jpg", ".jpeg", ".webp", ".srt",
}


@dataclass(frozen=True)
class DirEntry:
    name: str
    path: str
    is_dir: bool


@dataclass(frozen=True)
class DirListing:
    current_path: str
    parent_path: str | None
    entries: tuple[DirEntry, ...]


def list_directory(path: Path, *, only_dirs: bool = False) -> DirListing:
    """Liệt kê nội dung `path`. Nếu `only_dirs`, ẩn hết file (dùng khi chọn scenes_dir)."""
    if not path.is_dir():
        raise NotADirectoryError(f"Không phải thư mục: {path}")

    entries: list[DirEntry] = []
    for child in sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
        if child.is_dir():
            entries.append(DirEntry(name=child.name, path=str(child), is_dir=True))
        elif not only_dirs and child.suffix.lower() in _MEDIA_SUFFIXES:
            entries.append(DirEntry(name=child.name, path=str(child), is_dir=False))

    parent = path.parent
    parent_path = str(parent) if parent != path else None
    return DirListing(current_path=str(path), parent_path=parent_path, entries=tuple(entries))


def make_directory(parent: Path, name: str) -> Path:
    """Tạo thư mục con `name` trong `parent`. Chặn path traversal qua tên (VD '../x')."""
    name = name.strip()
    if not name or "/" in name or "\\" in name or name in {".", ".."}:
        raise ValueError(f"Tên thư mục không hợp lệ: {name!r}")
    if not parent.is_dir():
        raise NotADirectoryError(f"Không phải thư mục: {parent}")

    new_dir = parent / name
    new_dir.mkdir(exist_ok=True)
    return new_dir
