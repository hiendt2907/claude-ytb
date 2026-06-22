"""Sinh bộ nhận diện kênh '1 Cốc Café 6h': avatar (800x800) + banner (2560x1440).

Tông ấm bình minh + cà phê (ưu tiên sáng sớm / động lực / lifestyle), đủ rộng cho
kênh tổng hợp. Banner giữ nội dung trong 'safe area' giữa (1546x423) để không bị
cắt trên TV/mobile.
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

OUT = Path("assets/branding")

# bảng màu bình minh ấm
SKY_TOP = (34, 26, 46)       # tím đêm còn sót
SKY_MID = (158, 78, 62)      # cam đất
SKY_BOT = (244, 173, 96)     # nắng sớm
CREAM = (247, 239, 227)
COFFEE = (59, 36, 21)
CUP = (232, 213, 181)
AMBER = (242, 166, 90)
MUTED = (214, 198, 178)

FONT = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
MONO = "/System/Library/Fonts/Menlo.ttc"

NAME = "1 Cốc Café 6h"
HANDLE = "@1coccafe6h"
TAGLINE = "Mỗi sáng một chút — động lực • lifestyle • điều hay ho"


def _f(path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size)


def _sunrise(w: int, h: int) -> Image.Image:
    """Gradient 3 chặng: tím đêm -> cam đất -> nắng sớm."""
    img = Image.new("RGB", (w, h))
    px = img.load()
    for y in range(h):
        t = y / h
        if t < 0.5:
            u = t / 0.5
            a, b = SKY_TOP, SKY_MID
        else:
            u = (t - 0.5) / 0.5
            a, b = SKY_MID, SKY_BOT
        row = tuple(int(a[c] + (b[c] - a[c]) * u) for c in range(3))
        for x in range(w):
            px[x, y] = row
    return img


def _sun(img: Image.Image, cx: int, cy: int, r: int) -> None:
    """Vầng sáng mặt trời mọc (nhiều vòng mờ dần)."""
    draw = ImageDraw.Draw(img, "RGBA")
    for i in range(r, 0, -6):
        a = int(70 * (1 - i / r))
        draw.ellipse([cx - i, cy - i, cx + i, cy + i], fill=(255, 214, 140, a))


def _text_outline(draw: ImageDraw.ImageDraw, xy, text, font, fill,
                  outline=(40, 24, 18), ow: int = 6, anchor: str = "mm") -> None:
    """Vẽ chữ có viền để nổi rõ trên nền nắng (đọc được cả ở avatar nhỏ)."""
    x, y = xy
    for dx in range(-ow, ow + 1, 2):
        for dy in range(-ow, ow + 1, 2):
            if dx * dx + dy * dy <= ow * ow:
                draw.text((x + dx, y + dy), text, font=font, fill=outline, anchor=anchor)
    draw.text((x, y), text, font=font, fill=fill, anchor=anchor)


def _cup(draw: ImageDraw.ImageDraw, cx: int, top: int, scale: float) -> None:
    """Ly cà phê tối giản: bóng đổ + đĩa + thân + viền sáng + cà phê + quai."""
    bw = int(150 * scale)      # nửa bề ngang thân
    bh = int(150 * scale)      # cao thân
    # bóng đổ mềm dưới đĩa
    draw.ellipse([cx - bw - 30 * scale, top + bh + 18 * scale,
                  cx + bw + 30 * scale, top + bh + 48 * scale], fill=(30, 18, 12, 90))
    # đĩa lót (viền nâu mảnh cho nét)
    draw.ellipse([cx - bw - 40 * scale, top + bh - 8, cx + bw + 40 * scale, top + bh + 34 * scale],
                 fill=CREAM, outline=COFFEE, width=max(1, int(3 * scale)))
    # quai (vẽ trước thân để thân đè mép trong)
    draw.arc([cx + bw - 24 * scale, top + 28 * scale, cx + bw + 90 * scale, top + 124 * scale],
             start=-72, end=72, fill=CUP, width=int(24 * scale))
    # thân ly (hình thang bo) + viền nâu
    draw.rounded_rectangle([cx - bw, top, cx + bw, top + bh], radius=int(30 * scale),
                           fill=CUP, outline=COFFEE, width=max(1, int(3 * scale)))
    # viền sáng bên trái thân (khối hình)
    draw.line([(cx - bw + 14 * scale, top + 30 * scale), (cx - bw + 14 * scale, top + bh - 24 * scale)],
              fill=(255, 248, 236, 150), width=int(8 * scale))
    # mặt cà phê
    draw.ellipse([cx - bw + 16 * scale, top + 8 * scale, cx + bw - 16 * scale, top + 48 * scale],
                 fill=COFFEE)
    # ánh phản trên mặt cà phê
    draw.ellipse([cx - 30 * scale, top + 16 * scale, cx + 20 * scale, top + 30 * scale],
                 fill=(120, 78, 50, 120))


def _steam(draw: ImageDraw.ImageDraw, cx: int, base: int, scale: float) -> None:
    """Hai làn khói lượn sóng."""
    for dx in (-int(38 * scale), int(38 * scale)):
        pts = []
        for k in range(0, 140):
            y = base - k * scale
            x = cx + dx + math.sin(k / 16) * 18 * scale
            pts.append((x, y))
        draw.line(pts, fill=(255, 245, 230, 120), width=int(7 * scale), joint="curve")


def make_avatar() -> Path:
    """Avatar dạng badge: ly café nắng sớm + '6h' lớn có viền, đọc rõ ở cỡ nhỏ."""
    s = 800
    img = _sunrise(s, s)
    _sun(img, s // 2, int(s * 0.46), 330)
    draw = ImageDraw.Draw(img, "RGBA")
    # ly + khói ở nửa trên
    _steam(draw, s // 2, int(s * 0.30), 1.3)
    _cup(draw, s // 2, int(s * 0.30), 1.45)
    # "6h" lớn, viền nổi rõ ở nửa dưới (hero của avatar nhỏ)
    f = _f(FONT, 188)
    _text_outline(draw, (s / 2, s * 0.80), "6h", f, CREAM, outline=COFFEE, ow=9, anchor="mm")
    # vignette mượt (blur để khỏi vân tròn) + vành badge mảnh
    vg = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    vgd = ImageDraw.Draw(vg)
    vgd.ellipse([-s * 0.25, -s * 0.25, s * 1.25, s * 1.25], fill=(0, 0, 0, 0))
    vgd.ellipse([s * 0.04, s * 0.04, s * 0.96, s * 0.96], outline=(18, 10, 16, 130), width=90)
    vg = vg.filter(ImageFilter.GaussianBlur(60))
    img = Image.alpha_composite(img.convert("RGBA"), vg)
    ImageDraw.Draw(img, "RGBA").ellipse([10, 10, s - 10, s - 10],
                                        outline=(255, 233, 196, 180), width=8)
    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / "avatar.png"
    img.convert("RGB").save(p)
    return p


def make_banner() -> Path:
    w, h = 2560, 1440
    img = _sunrise(w, h)
    # mặt trời dịch sang TRÁI, sau ly — không rửa trôi chữ bên phải
    _sun(img, 760, int(h * 0.44), 460)
    img = img.convert("RGBA")
    cy = h // 2

    # lớp tối gradient phía phải (sau chữ) để tăng tương phản, tách chữ khỏi nắng
    panel = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    pd = ImageDraw.Draw(panel)
    for x in range(960, w):
        t = min(1.0, (x - 960) / 700)
        pd.line([(x, cy - 250), (x, cy + 220)], fill=(22, 14, 12, int(110 * t)))
    img = Image.alpha_composite(img, panel)

    draw = ImageDraw.Draw(img, "RGBA")
    # ly + khói bên TRÁI, trong safe area
    cup_x = 740
    _steam(draw, cup_x, cy + 10, 1.05)
    _cup(draw, cup_x, cy - 60, 1.15)

    # cụm chữ căn trái, có viền nhẹ cho nét
    tx = 1040
    big = _f(FONT, 142)
    _text_outline(draw, (tx, cy - 96), NAME, big, CREAM, outline=(34, 20, 14), ow=5, anchor="lm")
    # accent underline dưới tên
    draw.line([(tx + 4, cy - 6), (tx + 560, cy - 6)], fill=AMBER, width=7)
    tag = _f(FONT, 52)
    draw.text((tx + 4, cy + 58), TAGLINE, font=tag, fill=(250, 222, 188), anchor="lm")
    sub = _f(FONT, 40)  # Arial -> có dấu tiếng Việt (Menlo thiếu glyph)
    draw.text((tx + 4, cy + 140), f"{HANDLE}   •   video mới mỗi sáng", font=sub,
              fill=MUTED, anchor="lm")

    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / "banner.png"
    img.convert("RGB").save(p, quality=92)
    return p


if __name__ == "__main__":
    print("avatar:", make_avatar())
    print("banner:", make_banner())
