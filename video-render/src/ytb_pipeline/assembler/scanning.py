"""Scan thư mục cảnh trên đĩa thành SceneFolder/Clip domain objects."""

from __future__ import annotations

import re
from pathlib import Path

from ytb_pipeline.assembler.models import Clip, SceneFolder

_VIDEO_SUFFIXES = {".mp4", ".mov", ".mkv", ".avi", ".webm"}
_NUMERIC_TOKEN = re.compile(r"\d+")


def parse_sub_index(stem: str) -> tuple[int, ...]:
    """Suy ra khoá sort từ tên file, VD '1.2' -> (1, 2). Không có số -> (,) rỗng."""
    tokens = _NUMERIC_TOKEN.findall(stem)
    return tuple(int(token) for token in tokens)


def scan_scene_folder(scene_index: int, folder: Path) -> SceneFolder:
    """Scan 1 thư mục cảnh, trả về clip đã sort theo sub_index rồi theo tên file."""
    files = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in _VIDEO_SUFFIXES]
    clips = [
        Clip(path=p, scene_index=scene_index, sub_index=parse_sub_index(p.stem)) for p in files
    ]
    clips.sort(key=lambda c: (c.sub_index, c.path.name))
    return SceneFolder(scene_index=scene_index, path=folder, clips=tuple(clips))


def scan_scene_folders(base_dir: Path) -> tuple[SceneFolder, ...]:
    """Scan các thư mục con của base_dir, mỗi thư mục = 1 cảnh.

    Sort theo số trong tên thư mục (natural sort) chứ không phải chuỗi —
    sort chuỗi thuần sẽ xếp 'scene_10' trước 'scene_2' khi có > 10 cảnh và
    tên không được đệm số 0.
    """
    subdirs = sorted(
        (p for p in base_dir.iterdir() if p.is_dir()),
        key=lambda p: (parse_sub_index(p.name), p.name),
    )
    return tuple(
        scan_scene_folder(scene_index=i, folder=folder) for i, folder in enumerate(subdirs)
    )
