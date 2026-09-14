"""Аватарка бота: сетка 3×3, собранная в одну картинку.

Почему именно сетка. Аватарку видно в списке чатов размером с ноготь, и
там читается ровно одна форма. Маскот, буквы и мелкие детали на 40 px
превращаются в кашу, а три колонки светящихся плиток остаются тремя
колонками — это и есть то, что бот делает.

    python make_avatar.py

Кладёт assets/avatar.png (512×512) и assets/avatar_preview.png —
раскладку в тех размерах, в которых Telegram её показывает.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

import slicer

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

OUT = Path(__file__).resolve().parent / "assets"

SIZE = 512

#: Рисуем крупнее и уменьшаем: скруглённые углы плиток без сглаживания
#: выглядят рвано, а плиток здесь девять.
SS = 4

BG_TOP = (18, 20, 34)
BG_BOTTOM = (28, 18, 52)

#: Диагональный градиент по полотну: плитки берут цвет из него, поэтому
#: девять кусков читаются как одна разрезанная картинка, а не как девять
#: разноцветных квадратов.
RAMP = ((64, 226, 232), (122, 108, 255), (255, 92, 190), (255, 168, 92))


def _lerp(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))  # type: ignore[return-value]


def _ramp(t: float) -> tuple[int, int, int]:
    t = min(max(t, 0.0), 1.0) * (len(RAMP) - 1)
    i = min(int(t), len(RAMP) - 2)
    return _lerp(RAMP[i], RAMP[i + 1], t - i)


def _canvas(size: int) -> Image.Image:
    base = Image.new("RGB", (size, size))
    px = base.load()
    for y in range(size):
        row = _lerp(BG_TOP, BG_BOTTOM, y / (size - 1))
        for x in range(size):
            px[x, y] = row  # type: ignore[index]
    return base


def _wall(width: int, height: int) -> Image.Image:
    """Полотно, из которого нарезаются плитки."""
    art = Image.new("RGB", (width, height))
    px = art.load()
    for y in range(height):
        for x in range(width):
            #: Диагональ плюс мягкая волна — иначе градиент выглядит
            #: заливкой из графического редактора, а не картинкой.
            t = (x / width) * 0.55 + (y / height) * 0.45
            t += 0.07 * math.sin((x / width) * 5.2 + (y / height) * 3.1)
            px[x, y] = _ramp(t)  # type: ignore[index]
    glow = Image.new("RGB", (width, height), (0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse((width * 0.1, height * 0.08, width * 0.75, height * 0.55), fill=(90, 70, 160))
    return Image.blend(art, glow.filter(ImageFilter.GaussianBlur(width // 6)), 0.22)


def build(size: int = SIZE) -> Image.Image:
    big = size * SS
    card = _canvas(big)

    #: Поля вокруг сетки: Telegram обрежет аватарку по кругу, и плитки,
    #: доведённые до края квадрата, потеряют углы.
    pad = round(big * 0.145)
    #: Зазор считаем от того, что останется на 40 px: при 0.018 швы
    #: схлопываются в полпикселя, и сетка превращается в пятно.
    gap = round(big * 0.030)
    radius = round(big * 0.030)

    cols, rows = slicer.COLS, 3
    cell_w = (big - pad * 2 - gap * (cols - 1)) // cols
    cell_h = round(cell_w * slicer.CELL_H / slicer.CELL_W)
    grid_h = cell_h * rows + gap * (rows - 1)
    top = (big - grid_h) // 2

    wall = _wall(cell_w * cols, cell_h * rows)

    #: Свечение под сеткой — чтобы на тёмном фоне аватарка не выглядела
    #: дырой, и чтобы края плиток не сливались с подложкой.
    halo = Image.new("RGB", (big, big), (0, 0, 0))
    ImageDraw.Draw(halo).rounded_rectangle(
        (pad - gap, top - gap, big - pad + gap, top + grid_h + gap),
        radius=radius * 3, fill=(120, 90, 220),
    )
    #: Свечение приглушённое: яркая подложка подсвечивает швы, и три
    #: колонки перестают читаться именно там, где это важнее всего.
    card = Image.blend(card, halo.filter(ImageFilter.GaussianBlur(big // 22)), 0.32)

    for row in range(rows):
        for col in range(cols):
            tile = wall.crop(
                (col * cell_w, row * cell_h, (col + 1) * cell_w, (row + 1) * cell_h)
            )
            mask = Image.new("L", tile.size, 0)
            ImageDraw.Draw(mask).rounded_rectangle(
                (0, 0, tile.width - 1, tile.height - 1), radius=radius, fill=255
            )
            card.paste(
                tile,
                (pad + col * (cell_w + gap), top + row * (cell_h + gap)),
                mask,
            )

    return card.resize((size, size), Image.LANCZOS)


def preview(avatar: Image.Image) -> Image.Image:
    """Аватарка в тех размерах, в которых её реально видно."""
    sizes = (160, 96, 54, 40)
    pad, gap = 28, 26
    width = pad * 2 + sum(sizes) + gap * (len(sizes) - 1)
    card = Image.new("RGB", (width, 160 + pad * 2), (245, 246, 249))
    x = pad
    for size in sizes:
        shot = avatar.resize((size, size), Image.LANCZOS).convert("RGBA")
        mask = Image.new("L", (size * 4, size * 4), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, size * 4 - 1, size * 4 - 1), fill=255)
        shot.putalpha(mask.resize((size, size), Image.LANCZOS))
        card.paste(shot, (x, pad + (160 - size) // 2), shot)
        x += size + gap
    return card


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    avatar = build()
    path = OUT / "avatar.png"
    avatar.save(path, format="PNG", optimize=True)
    shot = OUT / "avatar_preview.png"
    preview(avatar).save(shot, format="PNG", optimize=True)
    print(f"{path.name:<20} {avatar.size[0]}×{avatar.size[1]}  {path.stat().st_size // 1024} КБ")
    print(f"{shot.name:<20} раскладка 160/96/54/40 px")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
