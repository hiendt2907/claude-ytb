"""Fetch static ffmpeg/ffprobe for the current platform and copy them for PyInstaller."""

from __future__ import annotations

import shutil
import stat
from pathlib import Path

from static_ffmpeg import run


def main() -> None:
    ffmpeg, ffprobe = run.get_or_fetch_platform_executables_else_raise()
    target = Path(".build-assets") / "ffmpeg"
    target.mkdir(parents=True, exist_ok=True)

    for source in (Path(ffmpeg), Path(ffprobe)):
        destination = target / source.name
        if destination.exists():
            destination.chmod(destination.stat().st_mode | stat.S_IWUSR)
            destination.unlink()
        shutil.copy2(source, destination)
        destination.chmod(destination.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        print(destination)


if __name__ == "__main__":
    main()
