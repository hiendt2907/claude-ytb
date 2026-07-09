"""Domain objects cho assembler (render-only tool). Immutable, frozen dataclasses."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Clip:
    """Một clip source ứng viên cho một cảnh."""

    path: Path
    scene_index: int
    sub_index: tuple[int, ...]
    duration_sec: float | None = None


@dataclass(frozen=True)
class ClipSegment:
    """Một đoạn được chọn bên trong clip source để render."""

    clip: Clip
    start_sec: float
    end_sec: float
    score: float

    @property
    def duration_sec(self) -> float:
        return max(0.0, self.end_sec - self.start_sec)


@dataclass(frozen=True)
class SceneFolder:
    """Một thư mục cảnh, đã sort clip theo sub_index."""

    scene_index: int
    path: Path
    clips: tuple[Clip, ...]


@dataclass(frozen=True)
class ClipGroup:
    """1 hoặc nhiều clip liên tiếp (theo sub_index) được chọn cho 1 cảnh/1 output."""

    scene_index: int
    clips: tuple[Clip, ...]
    segments: tuple[ClipSegment, ...] = ()


@dataclass(frozen=True)
class Assignment:
    """Tổ hợp clip group cho toàn bộ các cảnh của MỘT output video."""

    output_index: int
    groups: tuple[ClipGroup, ...]


@dataclass(frozen=True)
class AssemblyPlan:
    """Toàn bộ N assignment, đảm bảo coverage 100% clip nguồn."""

    assignments: tuple[Assignment, ...]
