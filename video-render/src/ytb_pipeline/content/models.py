"""Domain objects cho content pipeline. Immutable, frozen dataclasses."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ScriptSegment:
    """Một đoạn narration + từ khoá hình ảnh dùng để tìm clip Pexels khớp nghĩa."""

    narration: str
    visual_keywords: tuple[str, ...]


@dataclass(frozen=True)
class Script:
    """Kịch bản hoàn chỉnh — do Claude sinh hoặc user nhập tay."""

    title: str
    description: str
    segments: tuple[ScriptSegment, ...]
