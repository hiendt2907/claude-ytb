"""Resolve ffmpeg/ffprobe commands for dev and packaged desktop builds."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _candidate_dirs() -> tuple[Path, ...]:
    dirs: list[Path] = []

    env_dir = os.environ.get("VIDEO_RENDER_FFMPEG_DIR")
    if env_dir:
        dirs.append(Path(env_dir))

    pyinstaller_root = getattr(sys, "_MEIPASS", None)
    if pyinstaller_root:
        root = Path(pyinstaller_root)
        dirs.extend((root / "ffmpeg", root / "vendor" / "ffmpeg"))

    executable_dir = Path(sys.executable).resolve().parent
    dirs.extend((executable_dir / "ffmpeg", executable_dir / "vendor" / "ffmpeg"))

    return tuple(dirs)


def ffmpeg_executable(name: str) -> str:
    suffix = ".exe" if sys.platform == "win32" else ""
    executable_name = f"{name}{suffix}"
    for directory in _candidate_dirs():
        candidate = directory / executable_name
        if candidate.is_file():
            return str(candidate)
    return name


def ffmpeg_cmd() -> str:
    return ffmpeg_executable("ffmpeg")


def ffprobe_cmd() -> str:
    return ffmpeg_executable("ffprobe")

