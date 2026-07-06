"""Adapter — visual keyframe generator bằng Pillow.

Provider này là fallback local-first khi không dùng Flux/Wan. Nó không chỉ vẽ
gradient: mỗi prompt tạo một keyframe có nền, mặt sàn, chủ thể, action marks và
stickman scene nếu prompt có người que/stickman. FFmpeg sau đó animate keyframe
bằng Ken Burns trong `render/compose_ai.py`.
"""

import hashlib
import math
from pathlib import Path

from PIL import Image, ImageDraw

DEFAULT_TOP = (13, 17, 23)
DEFAULT_BOTTOM = (22, 27, 34)
CACHE_VERSION = "pillow-scene-v3"

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


def _seed(prompt: str) -> int:
    return int(hashlib.sha256((prompt or "").encode("utf-8")).hexdigest()[:8], 16)


def _is_stickman_prompt(prompt: str) -> bool:
    lowered = (prompt or "").lower()
    return any(word in lowered for word in ("người que", "nguoi que", "stickman"))


def _accent(seed: int) -> tuple[int, int, int]:
    palette = (
        (246, 196, 83),
        (91, 192, 190),
        (238, 108, 77),
        (139, 211, 70),
        (239, 118, 122),
    )
    return palette[seed % len(palette)]


def _draw_scene(img: Image.Image, prompt: str) -> None:
    draw = ImageDraw.Draw(img, "RGBA")
    w, h = img.size
    seed = _seed(prompt)
    accent = _accent(seed)

    horizon = int(h * 0.66)
    draw.rectangle([0, horizon, w, h], fill=(8, 12, 18, 185))
    draw.line([0, horizon, w, horizon], fill=(*accent, 190), width=max(4, w // 180))

    # Background depth: deterministic panels/props so the frame is not a flat card.
    for i in range(4):
        x = int((i + 0.5) * w / 4 + ((seed >> (i * 3)) % 45) - 22)
        top = int(h * (0.16 + 0.04 * (i % 2)))
        panel_w = int(w * (0.11 + 0.02 * ((seed >> i) % 3)))
        draw.rounded_rectangle(
            [x - panel_w, top, x + panel_w, horizon - 24],
            radius=max(8, w // 80),
            fill=(255, 255, 255, 18 + 8 * (i % 2)),
            outline=(255, 255, 255, 35),
            width=max(1, w // 360),
        )

    if _is_stickman_prompt(prompt):
        _draw_stickman_scene(draw, prompt, w, h, accent, seed)
    else:
        _draw_generic_scene(draw, prompt, w, h, accent, seed)


def _draw_generic_scene(draw: ImageDraw.ImageDraw, prompt: str, w: int, h: int,
                        accent: tuple[int, int, int], seed: int) -> None:
    cx, cy = w // 2, int(h * 0.52)
    radius = max(44, min(w, h) // 9)
    draw.ellipse([cx - radius, cy - radius, cx + radius, cy + radius],
                 fill=(*accent, 210), outline=(255, 255, 255, 230), width=max(3, w // 160))
    for i in range(9):
        angle = math.radians((seed + i * 41) % 360)
        x = cx + int((radius * 1.7) * math.cos(angle))
        y = cy + int((radius * 1.1) * math.sin(angle))
        r = max(8, radius // 8)
        draw.ellipse([x - r, y - r, x + r, y + r], fill=(255, 255, 255, 65))
    _draw_motion_burst(draw, (cx, cy), radius * 2, accent, w)


def _draw_stickman_scene(draw: ImageDraw.ImageDraw, prompt: str, w: int, h: int,
                         accent: tuple[int, int, int], seed: int) -> None:
    lowered = prompt.lower()
    floor = int(h * 0.71)
    main_x = int(w * 0.38)
    main_y = floor - int(h * 0.03)
    scale = max(1.45, min(w, h) / 620)
    action = _action_from_prompt(lowered)

    # Props derived from common entertainment prompts.
    if any(word in lowered for word in ("đất", "mảnh đất", "dat", "land")):
        _draw_land_patch(draw, int(w * 0.59), floor, scale, accent)
    if any(word in lowered for word in ("nhà", "nha", "house")):
        _draw_house(draw, int(w * 0.66), floor, scale, accent)
    if any(word in lowered for word in ("cửa", "door")):
        _draw_door(draw, int(w * 0.68), floor, scale, accent)
    if any(word in lowered for word in ("thang máy", "elevator")):
        _draw_elevator(draw, int(w * 0.68), floor, scale, accent)
    if any(word in lowered for word in ("cây", "tree")):
        _draw_tree(draw, int(w * 0.72), floor, scale, accent)
    if any(word in lowered for word in ("cân", "scale")):
        _draw_scale(draw, int(w * 0.62), floor, scale, accent)
    if any(word in lowered for word in ("dao", "rìu", "riu", "chặt", "chop", "knife", "axe")):
        _draw_tool(draw, main_x + int(w * 0.11), main_y - int(h * 0.10), scale, accent)

    _draw_stickman(draw, main_x, main_y, scale, action=action, accent=accent)
    _draw_stickman(draw, int(w * 0.19), floor - int(h * 0.02), scale * 0.72,
                   action="watch", accent=(255, 255, 255))
    _draw_motion_burst(draw, (main_x + int(w * 0.08), main_y - int(h * 0.17)),
                       int(min(w, h) * 0.24), accent, w)
    _draw_impact_marks(draw, main_x + int(w * 0.19), floor - int(h * 0.22), accent, w)


def _action_from_prompt(lowered: str) -> str:
    if any(word in lowered for word in ("ngã", "té", "vấp", "trượt", "rơi")):
        return "fall"
    if any(word in lowered for word in ("chạy", "đuổi", "lao", "né")):
        return "run"
    if any(word in lowered for word in ("hoảng", "đứng hình", "bất ngờ")):
        return "shock"
    if any(word in lowered for word in ("kéo", "đẩy", "mở", "đóng")):
        return "pull"
    return "run"


def _draw_stickman(draw: ImageDraw.ImageDraw, x: int, y: int, scale: float, *,
                   action: str, accent: tuple[int, int, int]) -> None:
    line = max(5, int(7 * scale))
    head = int(24 * scale)
    torso = int(70 * scale)
    arm = int(48 * scale)
    leg = int(56 * scale)
    color = (245, 247, 250, 255)

    if action == "fall":
        head_c = (x + int(22 * scale), y - int(82 * scale))
        body_top = (x, y - int(62 * scale))
        body_bottom = (x + int(74 * scale), y - int(34 * scale))
        draw.ellipse([head_c[0] - head, head_c[1] - head, head_c[0] + head, head_c[1] + head],
                     outline=color, width=line)
        draw.line([body_top, body_bottom], fill=color, width=line)
        draw.line([body_top, (x - arm, y - int(84 * scale))], fill=color, width=line)
        draw.line([body_top, (x + arm, y - int(96 * scale))], fill=color, width=line)
        draw.line([body_bottom, (x + int(110 * scale), y - int(10 * scale))], fill=color, width=line)
        draw.line([body_bottom, (x + int(38 * scale), y + int(10 * scale))], fill=color, width=line)
        return

    head_c = (x, y - torso - head)
    neck = (x, y - torso)
    hip = (x, y - int(22 * scale))
    draw.ellipse([head_c[0] - head, head_c[1] - head, head_c[0] + head, head_c[1] + head],
                 outline=color, width=line)
    draw.line([neck, hip], fill=color, width=line)

    if action == "run":
        arms = [((x - arm, y - int(58 * scale)), (x + arm, y - int(88 * scale)))]
        legs = [((x - leg, y + int(18 * scale)), (x + leg, y + int(14 * scale)))]
    elif action == "shock":
        arms = [((x - arm, y - int(116 * scale)), (x + arm, y - int(116 * scale)))]
        legs = [((x - int(34 * scale), y + int(20 * scale)), (x + int(34 * scale), y + int(20 * scale)))]
        draw.ellipse([x - int(8 * scale), head_c[1] - int(5 * scale),
                      x + int(8 * scale), head_c[1] + int(12 * scale)], fill=(*accent, 230))
    elif action == "pull":
        arms = [((x + arm, y - int(80 * scale)), (x + int(arm * 1.6), y - int(86 * scale)))]
        legs = [((x - leg, y + int(18 * scale)), (x + int(30 * scale), y + int(22 * scale)))]
    else:
        arms = [((x - arm, y - int(70 * scale)), (x + arm, y - int(70 * scale)))]
        legs = [((x - leg, y + int(16 * scale)), (x + leg, y + int(16 * scale)))]

    for a, b in arms:
        draw.line([(x, y - int(74 * scale)), a], fill=color, width=line)
        draw.line([(x, y - int(74 * scale)), b], fill=color, width=line)
    for a, b in legs:
        draw.line([hip, a], fill=color, width=line)
        draw.line([hip, b], fill=color, width=line)


def _draw_motion_burst(draw: ImageDraw.ImageDraw, center: tuple[int, int], radius: int,
                       accent: tuple[int, int, int], width: int) -> None:
    cx, cy = center
    stroke = max(3, width // 260)
    for dx, dy in ((-1, -1), (1, -1), (1, 1), (-1, 1), (0, -1), (1, 0)):
        draw.line([cx + dx * radius // 3, cy + dy * radius // 3,
                   cx + dx * radius, cy + dy * radius],
                  fill=(*accent, 180), width=stroke)


def _draw_impact_marks(draw: ImageDraw.ImageDraw, x: int, y: int,
                       accent: tuple[int, int, int], width: int) -> None:
    stroke = max(3, width // 250)
    draw.line([x - 26, y - 26, x + 26, y + 26], fill=(*accent, 230), width=stroke)
    draw.line([x + 26, y - 26, x - 26, y + 26], fill=(*accent, 230), width=stroke)
    draw.ellipse([x - 44, y - 44, x + 44, y + 44], outline=(*accent, 160), width=stroke)


def _draw_door(draw: ImageDraw.ImageDraw, x: int, floor: int, scale: float,
               accent: tuple[int, int, int]) -> None:
    w, h = int(95 * scale), int(185 * scale)
    draw.rounded_rectangle([x - w // 2, floor - h, x + w // 2, floor],
                           radius=int(10 * scale), fill=(30, 34, 46, 235),
                           outline=(*accent, 230), width=max(3, int(5 * scale)))
    draw.ellipse([x + w // 4, floor - h // 2, x + w // 4 + 10, floor - h // 2 + 10],
                 fill=(*accent, 255))


def _draw_elevator(draw: ImageDraw.ImageDraw, x: int, floor: int, scale: float,
                   accent: tuple[int, int, int]) -> None:
    w, h = int(165 * scale), int(210 * scale)
    draw.rectangle([x - w // 2, floor - h, x + w // 2, floor],
                   fill=(24, 28, 38, 235), outline=(255, 255, 255, 95),
                   width=max(3, int(4 * scale)))
    draw.line([x, floor - h, x, floor], fill=(*accent, 210), width=max(3, int(4 * scale)))
    draw.rectangle([x - 28, floor - h - 34, x + 28, floor - h - 10], fill=(*accent, 220))


def _draw_tree(draw: ImageDraw.ImageDraw, x: int, floor: int, scale: float,
               accent: tuple[int, int, int]) -> None:
    trunk_w, trunk_h = int(24 * scale), int(130 * scale)
    draw.rectangle([x - trunk_w // 2, floor - trunk_h, x + trunk_w // 2, floor],
                   fill=(102, 74, 48, 255))
    for ox, oy, r in ((0, -150, 58), (-42, -116, 46), (45, -112, 48)):
        rr = int(r * scale)
        draw.ellipse([x + int(ox * scale) - rr, floor + int(oy * scale) - rr,
                      x + int(ox * scale) + rr, floor + int(oy * scale) + rr],
                     fill=(*accent, 185))


def _draw_scale(draw: ImageDraw.ImageDraw, x: int, floor: int, scale: float,
                accent: tuple[int, int, int]) -> None:
    w, h = int(120 * scale), int(34 * scale)
    draw.rounded_rectangle([x - w // 2, floor - h, x + w // 2, floor],
                           radius=int(12 * scale), fill=(245, 247, 250, 235))
    draw.rectangle([x - int(26 * scale), floor - h + int(6 * scale),
                    x + int(26 * scale), floor - h + int(20 * scale)],
                   fill=(*accent, 240))


def _draw_land_patch(draw: ImageDraw.ImageDraw, x: int, floor: int, scale: float,
                     accent: tuple[int, int, int]) -> None:
    w, h = int(210 * scale), int(58 * scale)
    draw.ellipse([x - w // 2, floor - h, x + w // 2, floor + h // 3],
                 fill=(85, 63, 42, 210), outline=(*accent, 160), width=max(3, int(4 * scale)))
    for i in range(5):
        px = x - w // 3 + int(i * w / 6)
        draw.line([px, floor - int(10 * scale), px + int(24 * scale), floor - int(25 * scale)],
                  fill=(*accent, 155), width=max(2, int(3 * scale)))


def _draw_house(draw: ImageDraw.ImageDraw, x: int, floor: int, scale: float,
                accent: tuple[int, int, int]) -> None:
    w, h = int(190 * scale), int(135 * scale)
    y0 = floor - h
    draw.rectangle([x - w // 2, y0, x + w // 2, floor],
                   fill=(30, 34, 46, 230), outline=(255, 255, 255, 95),
                   width=max(3, int(4 * scale)))
    roof = [(x - w // 2 - int(18 * scale), y0), (x, y0 - int(78 * scale)),
            (x + w // 2 + int(18 * scale), y0)]
    draw.polygon(roof, fill=(*accent, 195), outline=(255, 255, 255, 120))
    door_w, door_h = int(44 * scale), int(76 * scale)
    draw.rectangle([x - door_w // 2, floor - door_h, x + door_w // 2, floor],
                   fill=(10, 14, 22, 245), outline=(*accent, 220),
                   width=max(2, int(3 * scale)))
    window = int(34 * scale)
    draw.rectangle([x + int(35 * scale), y0 + int(36 * scale),
                    x + int(35 * scale) + window, y0 + int(36 * scale) + window],
                   fill=(245, 247, 250, 210))


def _draw_tool(draw: ImageDraw.ImageDraw, x: int, y: int, scale: float,
               accent: tuple[int, int, int]) -> None:
    stroke = max(5, int(7 * scale))
    length = int(118 * scale)
    draw.line([x - length // 2, y + int(35 * scale), x + length // 2, y - int(35 * scale)],
              fill=(245, 247, 250, 235), width=stroke)
    blade = [
        (x + length // 2, y - int(35 * scale)),
        (x + length // 2 + int(46 * scale), y - int(50 * scale)),
        (x + length // 2 + int(24 * scale), y - int(4 * scale)),
    ]
    draw.polygon(blade, fill=(*accent, 235), outline=(255, 255, 255, 160))


class PillowImageProvider:
    """Deterministic Pillow scene generator — always available, no image model."""

    name = "pillow"
    cache_version = CACHE_VERSION

    def availability_status(self) -> tuple[bool, str]:
        return True, "Pillow scene keyframes + ffmpeg image-motion; không cần model ảnh"

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
        _draw_scene(img, prompt)
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        img.save(output_path)
        return output_path

    def is_available(self) -> bool:
        return True
