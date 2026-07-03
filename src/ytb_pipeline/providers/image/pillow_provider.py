"""Adapter — bọc logic gradient hiện có trong `render/compose.py` thành ImageProvider.

KHÔNG xoá `_gradient()` khỏi compose.py (giữ backward compat) — provider này chỉ
tái lập logic tương đương để dùng qua interface chung `ImageProvider`. Khi
`prompt` chứa từ khoá màu (dark/blue/warm/...), gradient đổi sắc tương ứng;
mặc định giữ tông GitHub dark gốc (13,17,23 → 22,27,34).
"""

from pathlib import Path

from PIL import Image

DEFAULT_TOP = (13, 17, 23)
DEFAULT_BOTTOM = (22, 27, 34)

# Từ khoá màu đơn giản trong prompt → (top, bottom). Khớp gần đúng theo substring.
COLOR_HINTS: dict[str, tuple[tuple[int, int, int], tuple[int, int, int]]] = {
    "dark": ((13, 17, 23), (22, 27, 34)),
    "blue": ((10, 20, 40), (20, 40, 80)),
    "warm": ((40, 20, 10), (80, 45, 20)),
    "red": ((40, 10, 12), (80, 20, 25)),
    "green": ((10, 30, 15), (20, 60, 30)),
    "purple": ((25, 10, 40), (55, 20, 80)),
}


def _pick_gradient_colors(prompt: str) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    lowered = (prompt or "").lower()
    for keyword, colors in COLOR_HINTS.items():
        if keyword in lowered:
            return colors
    return DEFAULT_TOP, DEFAULT_BOTTOM


def _draw_gradient(width: int, height: int,
                   top: tuple[int, int, int], bottom: tuple[int, int, int]) -> Image.Image:
    base = Image.new("RGB", (width, height), top)
    px = base.load()
    for y in range(height):
        t = y / height if height else 0
        row = tuple(int(top[c] + (bottom[c] - top[c]) * t) for c in range(3))
        for x in range(width):
            px[x, y] = row
    return base


class PillowImageProvider:
    """Gradient background sinh bằng Pillow — luôn khả dụng, không cần model."""

    name = "pillow"

    def availability_status(self) -> tuple[bool, str]:
        return True, "Pillow image backgrounds + ffmpeg image-motion; không cần model ảnh"

    def generate(
        self,
        prompt: str,
        width: int,
        height: int,
        output_path: Path,
        *,
        negative_prompt: str = "",
        seed: int | None = None,
    ) -> Path:
        top, bottom = _pick_gradient_colors(prompt)
        img = _draw_gradient(width, height, top, bottom)
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        img.save(output_path)
        return output_path

    def is_available(self) -> bool:
        return True
