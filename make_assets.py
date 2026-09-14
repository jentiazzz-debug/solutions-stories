"""Сборка картинок-заставок в assets/.

Почему кодом, а не нейронкой. Три из четырёх карточек — инфографика: в
них есть пропорции, номера ячеек и порядок публикации. Ошибись генератор
в одной цифре — и человек соберёт стенку задом наперёд, а проверить это
на глаз нельзя. Здесь же числа берутся прямо из slicer.py, поэтому
картинка не может разойтись с тем, что бот реально делает.

    python make_assets.py

Шрифт нужен только на этом шаге: в репозиторий уезжают уже готовые JPEG.
"""

from __future__ import annotations

import io
import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

import frames as frames_mod
import slicer

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

OUT = Path(__file__).resolve().parent / "assets"

W, H = 1080, 1350

INK = (236, 240, 248)
DIM = (150, 162, 184)
BG_TOP, BG_BOTTOM = (18, 22, 34), (10, 13, 22)
ACCENT = (64, 190, 255)

BRAND = "Solutions Stories"
HANDLE = "@SolutionsStoriesbot"

_FONTS = (
    "arialbd.ttf", "arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)


def font(size: int) -> ImageFont.FreeTypeFont:
    for name in _FONTS:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    raise SystemExit(
        "Не нашёл шрифт с кириллицей. Положи .ttf рядом и впиши его в _FONTS."
    )


# --------------------------------------------------------------------------
# Кисти
# --------------------------------------------------------------------------


def backdrop(width: int = W, height: int = H) -> Image.Image:
    """Тёмный фон с парой цветных пятен — чтобы карточка не была плоской."""
    base = Image.new("RGB", (width, height), BG_BOTTOM)
    px = base.load()
    for y in range(height):
        t = y / (height - 1)
        row = tuple(round(BG_TOP[i] + (BG_BOTTOM[i] - BG_TOP[i]) * t) for i in range(3))
        for x in range(width):
            px[x, y] = row  # type: ignore[index]
    glow = Image.new("RGB", (width, height), (0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse((-width * 0.3, -height * 0.15, width * 0.55, height * 0.35), fill=(20, 70, 120))
    gd.ellipse((width * 0.55, height * 0.66, width * 1.35, height * 1.2), fill=(80, 30, 110))
    return Image.blend(base, glow.filter(ImageFilter.GaussianBlur(190)), 0.55)


def demo_source(width: int = 1400, height: int = 1750) -> bytes:
    """Яркая абстракция, которую режем в демонстрационную стенку.

    Своя картинка, а не фотография: заставки уезжают в публичный репозиторий
    и в рекламу, и чужой снимок там — чужие права.
    """
    img = Image.new("RGB", (width, height), (12, 14, 26))
    draw = ImageDraw.Draw(img, "RGBA")
    for i in range(110):
        t = i / 110
        radius = width * (0.06 + 0.5 * (1 - t))
        cx = width * (0.5 + 0.34 * math.sin(t * 7.5))
        cy = height * (0.5 + 0.40 * math.cos(t * 5.1))
        colour = (
            round(60 + 190 * abs(math.sin(t * 3.0))),
            round(40 + 120 * abs(math.sin(t * 4.6 + 1.1))),
            round(120 + 130 * abs(math.cos(t * 2.2))),
            26,
        )
        draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill=colour)
    img = img.filter(ImageFilter.GaussianBlur(14))

    draw = ImageDraw.Draw(img, "RGBA")
    #: Сетка поверх размытия: без жёстких деталей нарезка выглядит
    #: одинаково при любом числе частей, и демонстрировать нечего.
    for i in range(46):
        t = i / 46
        x = width * t
        draw.line((x, 0, x * 0.4 + width * 0.3, height), fill=(255, 255, 255, 14), width=3)
    for ring in range(7):
        r = width * (0.12 + ring * 0.075)
        draw.ellipse(
            (width / 2 - r, height / 2 - r, width / 2 + r, height / 2 + r),
            outline=(120, 230, 255, 40), width=5,
        )
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=95)
    return buf.getvalue()


def wall_grid(source: bytes, parts: int, box_w: int, gap: int) -> Image.Image:
    """Сетка превью ровно так, как её покажет профиль."""
    rows = slicer.LAYOUTS[parts]
    cell_w = (box_w - gap * (slicer.COLS - 1)) // slicer.COLS
    cell_h = round(cell_w * slicer.CELL_H / slicer.CELL_W)
    with Image.open(io.BytesIO(source)) as src:
        board = slicer._cover(src.convert("RGB"), cell_w * slicer.COLS, cell_h * rows)
    grid = Image.new("RGB", (box_w, cell_h * rows + gap * (rows - 1)), (12, 14, 22))
    for row in range(rows):
        for col in range(slicer.COLS):
            tile = board.crop(
                (col * cell_w, row * cell_h, (col + 1) * cell_w, (row + 1) * cell_h)
            )
            grid.paste(tile, (col * (cell_w + gap), row * (cell_h + gap)))
    return grid


def phone(inner: Image.Image, scale: float = 1.0) -> Image.Image:
    """Рамка телефона вокруг готового экрана."""
    pad = round(22 * scale)
    radius = round(70 * scale)
    body = Image.new("RGBA", (inner.width + pad * 2, inner.height + pad * 2), (0, 0, 0, 0))
    draw = ImageDraw.Draw(body)
    draw.rounded_rectangle(
        (0, 0, body.width - 1, body.height - 1), radius=radius, fill=(26, 29, 38, 255),
        outline=(70, 78, 96, 255), width=max(2, round(3 * scale)),
    )
    mask = Image.new("L", inner.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, inner.width - 1, inner.height - 1), radius=round(radius * 0.75), fill=255
    )
    body.paste(inner, (pad, pad), mask)
    notch_w, notch_h = round(inner.width * 0.34), round(26 * scale)
    draw.rounded_rectangle(
        (body.width / 2 - notch_w / 2, pad - round(2 * scale),
         body.width / 2 + notch_w / 2, pad + notch_h),
        radius=notch_h // 2, fill=(18, 20, 27, 255),
    )
    return body


def profile_screen(source: bytes, parts: int, width: int, name: str,
                   frame_index: int | None = None, colour_index: int = 4) -> Image.Image:
    """Экран профиля: аватарка, имя и стенка под ними."""
    height = round(width * 2.06)
    screen = Image.new("RGB", (width, height), (14, 16, 24))
    draw = ImageDraw.Draw(screen)

    avatar_d = round(width * 0.30)
    if frame_index is None:
        avatar = Image.open(io.BytesIO(frames_mod.apply(source, colour_index, 24)))
    else:
        avatar = Image.open(io.BytesIO(frames_mod.apply(source, colour_index, frame_index)))
    avatar = avatar.convert("RGB").resize((avatar_d, avatar_d), Image.LANCZOS)
    circle = Image.new("L", (avatar_d, avatar_d), 0)
    ImageDraw.Draw(circle).ellipse((0, 0, avatar_d - 1, avatar_d - 1), fill=255)
    screen.paste(avatar, ((width - avatar_d) // 2, round(width * 0.12)), circle)

    name_y = round(width * 0.12) + avatar_d + round(width * 0.075)
    draw.text((width / 2, name_y), name, font=font(round(width * 0.072)), fill=INK, anchor="mm")
    draw.text((width / 2, name_y + round(width * 0.075)), "был(а) недавно",
              font=font(round(width * 0.045)), fill=DIM, anchor="mm")

    gap = max(2, round(width * 0.012))
    box_w = width - gap * 2
    grid = wall_grid(source, parts, box_w, gap)
    screen.paste(grid, (gap, name_y + round(width * 0.14)))
    return screen


def footer(card: Image.Image, text: str = HANDLE) -> None:
    ImageDraw.Draw(card).text(
        (W / 2, H - 46), text, font=font(30), fill=(120, 132, 154), anchor="mm"
    )


def chip(draw: ImageDraw.ImageDraw, box, title: str, lines: list[str]) -> None:
    """Скруглённая плашка с заголовком и строками."""
    x0, y0, x1, y1 = box
    draw.rounded_rectangle(box, radius=28, fill=(255, 255, 255, 16))
    draw.text((x0 + 30, y0 + 26), title, font=font(34), fill=ACCENT)
    y = y0 + 84
    for line in lines:
        draw.text((x0 + 30, y), line, font=font(31), fill=INK)
        y += 46


# --------------------------------------------------------------------------
# Карточки
# --------------------------------------------------------------------------


def make_manual(source: bytes) -> Image.Image:
    card = backdrop()
    draw = ImageDraw.Draw(card, "RGBA")
    draw.text((W / 2, 92), "Как подобрать размер фото", font=font(56), fill=INK, anchor="mm")

    ratios = []
    for parts in sorted(slicer.LAYOUTS):
        w, h = slicer.ideal_ratio(parts)
        ratios.append(f"{w}:{h}   →   {parts} сторис")
    chip(draw, (60, 150, W // 2 - 16, 440), "Идеальные пропорции", ratios)
    chip(
        draw, (W // 2 + 16, 150, W - 60, 440), "Почему так",
        ["В профиле три колонки,", "а в превью видно только", "середину кадра —", "окно 4:5."],
    )

    #: Ширина сетки подобрана так, чтобы три ряда 4:5 закончились выше
    #: плашки «Важно»: при 470 px последний ряд налезал на неё.
    grid_w, grid_x, grid_y = 420, 60, 492
    grid = wall_grid(source, 9, grid_w, 10)
    card.paste(grid, (grid_x, grid_y))
    gdraw = ImageDraw.Draw(card, "RGBA")
    cell = (grid_w - 20) // 3
    cell_h = round(cell * slicer.CELL_H / slicer.CELL_W)
    number = 9
    for row in range(3):
        for col in range(3):
            cx = grid_x + col * (cell + 10) + cell / 2
            cy = grid_y + row * (cell_h + 10) + cell_h / 2
            gdraw.ellipse((cx - 36, cy - 36, cx + 36, cy + 36), fill=(0, 0, 0, 175))
            gdraw.text((cx, cy), str(number), font=font(44), fill=INK, anchor="mm")
            number -= 1

    chip(
        ImageDraw.Draw(card, "RGBA"),
        (520, 500, W - 60, 1000),
        "Последовательность",
        [
            "Публикуй файлы подряд,",
            "сверху вниз — бот уже",
            "отдал их в нужном",
            "порядке.",
            "",
            "Первый файл — правый",
            "нижний угол.",
            "Последний — левый",
            "верхний.",
        ],
    )
    draw = ImageDraw.Draw(card, "RGBA")
    draw.rounded_rectangle((60, 1040, W - 60, 1215), radius=28, fill=(255, 180, 60, 30))
    draw.text((90, 1068), "Важно", font=font(34), fill=(255, 196, 92))
    draw.text(
        (90, 1118),
        f"Фото меньше {slicer.MIN_SIDE} px по короткой стороне\n"
        "на 12–15 частей бот растянет — будет мылить.",
        font=font(31), fill=INK,
    )
    footer(card)
    return card


def make_welcome(source: bytes) -> Image.Image:
    card = backdrop()
    screen = profile_screen(source, 9, 430, BRAND)
    shell = phone(screen)
    shell = shell.resize((round(shell.width * 0.96), round(shell.height * 0.96)), Image.LANCZOS)
    card.paste(shell, ((W - shell.width) // 2, 150), shell)

    draw = ImageDraw.Draw(card, "RGBA")
    draw.text((W / 2, 76), "Стенка из сторис", font=font(62), fill=INK, anchor="mm")
    draw.text(
        (W / 2, H - 108), "Одна картинка — целый профиль",
        font=font(38), fill=DIM, anchor="mm",
    )
    footer(card)
    return card


def make_about(source: bytes) -> Image.Image:
    card = backdrop()
    draw = ImageDraw.Draw(card, "RGBA")
    draw.text((W / 2, 84), "Было / стало", font=font(56), fill=INK, anchor="mm")

    plain = Image.new("RGB", (430, round(430 * 2.06)), (14, 16, 24))
    pdraw = ImageDraw.Draw(plain)
    avatar_d = round(430 * 0.30)
    pdraw.ellipse(
        ((430 - avatar_d) // 2, round(430 * 0.12),
         (430 - avatar_d) // 2 + avatar_d, round(430 * 0.12) + avatar_d),
        fill=(46, 52, 66),
    )
    pdraw.text((215, round(430 * 0.12) + avatar_d + 32), "обычный профиль",
               font=font(30), fill=DIM, anchor="mm")
    gap, box = 5, 420
    cell = (box - gap * 2) // 3
    cell_h = round(cell * slicer.CELL_H / slicer.CELL_W)
    top = round(430 * 0.12) + avatar_d + 60
    tones = [(38, 42, 54), (30, 34, 46), (46, 50, 62)]
    for row in range(3):
        for col in range(3):
            pdraw.rectangle(
                (gap + col * (cell + gap), top + row * (cell_h + gap),
                 gap + col * (cell + gap) + cell, top + row * (cell_h + gap) + cell_h),
                fill=tones[(row + col) % 3],
            )

    shells = []
    for inner in (plain, profile_screen(source, 9, 430, BRAND)):
        shell = phone(inner)
        shells.append(
            shell.resize((round(shell.width * 0.78), round(shell.height * 0.78)), Image.LANCZOS)
        )
    span = shells[0].width * 2 + 80
    for index, shell in enumerate(shells):
        card.paste(shell, ((W - span) // 2 + index * (shell.width + 80), 190), shell)

    draw.text(
        (W / 2, 1010),
        "Сетка профиля складывает истории\nв одно полотно — если нарезать правильно",
        font=font(38), fill=INK, anchor="mm", align="center",
    )
    draw.text(
        (W / 2, 1130),
        "Порядок публикации бот берёт на себя",
        font=font(32), fill=DIM, anchor="mm",
    )
    footer(card)
    return card


def make_frames(source: bytes) -> Image.Image:
    card = backdrop()
    draw = ImageDraw.Draw(card, "RGBA")
    draw.text((W / 2, 88), "Рамки для аватарки", font=font(56), fill=INK, anchor="mm")
    draw.text(
        (W / 2, 152), f"{frames_mod.frame_count()} рамок × {len(frames_mod.COLORS)} цветов профиля",
        font=font(34), fill=DIM, anchor="mm",
    )

    #: Первый ряд — венки, второй — маски, третий — смешанный: так на
    #: одной картинке видно, что рамки бывают двух разных сортов.
    picks = [3, 5, 10, 26, 28, 30, 32, 33, 19]
    size, gap = 268, 20
    start_x = (W - (size * 3 + gap * 2)) // 2
    for i, index in enumerate(picks[:9]):
        shot = Image.open(io.BytesIO(frames_mod.apply(source, i, index))).convert("RGB")
        shot = shot.resize((size, size), Image.LANCZOS)
        card.paste(shot, (start_x + (i % 3) * (size + gap), 226 + (i // 3) * (size + gap)))

    draw.text(
        (W / 2, H - 150),
        "Фон под рамкой — цвет твоего профиля,\nпоэтому она выглядит частью интерфейса",
        font=font(36), fill=INK, anchor="mm", align="center",
    )
    footer(card)
    return card


#: Своя картинка для витрины. Положи сюда что угодно — нейросетевой
#: постер, фотографию, арт — и заставки пересоберутся на ней. Нет файла
#: — рисуем абстракцию кодом, чтобы сборка не падала на чистом клоне.
CUSTOM_SOURCE = OUT / "_ai_source.png"


def pick_source(argv: list[str]) -> bytes:
    if len(argv) > 1:
        return Path(argv[1]).read_bytes()
    for candidate in (CUSTOM_SOURCE, CUSTOM_SOURCE.with_suffix(".jpg")):
        if candidate.is_file():
            print(f"витрина: {candidate.name}")
            return candidate.read_bytes()
    print("витрина: процедурная абстракция (своего файла нет)")
    return demo_source()


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    source = pick_source(sys.argv)
    (OUT / "_demo_source.jpg").write_bytes(source)

    for name, build in (
        ("welcome", make_welcome),
        ("about", make_about),
        ("manual", make_manual),
        ("frames", make_frames),
    ):
        card = build(source).convert("RGB")
        path = OUT / f"{name}.jpg"
        card.save(path, format="JPEG", quality=92, optimize=True)
        print(f"{path.name:<14} {card.size[0]}×{card.size[1]}  {path.stat().st_size // 1024} КБ")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
