"""Quy ước đặt tên output: output/<product_name>/variant_01.mp4 ..."""

from __future__ import annotations

from pathlib import Path


def output_path(output_dir: Path, product_name: str, output_index: int, n_outputs: int) -> Path:
    """output_index 0-based; tên file 1-based, zero-pad theo độ dài N."""
    width = len(str(n_outputs))
    variant_name = f"variant_{output_index + 1:0{width}d}.mp4"
    return output_dir / product_name / variant_name
