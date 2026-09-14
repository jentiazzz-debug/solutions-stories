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

INK = (255, 255, 255)
DIM = (198, 226, 232)

#: Бирюзовая диагональ вместо почти-чёрного фона. На тёмной подложке
#: тёмные плашки не читаются, и карточка выглядит пустой: контраст даёт
#: не текст, а перепад между светлым фоном и тёмной плашкой.
BG_STOPS = ((10, 40, 48), (26, 104, 120), (150, 219, 228))

#: Плашки почти непрозрачные: полупрозрачные на градиенте плывут по
#: тону, и один и тот же блок выглядит по-разному сверху и снизу.
PLATE = (17, 33, 43)
PLATE_ALPHA = 232
RADIUS = 34
ACCENT = (126, 230, 245)

BRAND = "Solutions Stories"

#: Чей профиль показываем на витрине. Живой юзернейм вместо названия
#: бота: человек должен увидеть чужой настоящий профиль, а не макет.
OWNER = "@nudick"
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
    """Диагональный бирюзовый градиент: тёмный угол сверху, свет снизу."""
    small = Image.new("RGB", (64, 64))
    px = small.load()
    for y in range(64):
        for x in range(64):
            #: Диагональ, а не вертикаль: свет приходит из угла, и
            #: плашки ложатся на неоднородный фон — так карточка
            #: выглядит снятой, а не залитой.
            t = (x / 63) * 0.42 + (y / 63) * 0.58
            t = min(max(t, 0.0), 1.0) * (len(BG_STOPS) - 1)
            i = min(int(t), len(BG_STOPS) - 2)
            f = t - i
            a, b = BG_STOPS[i], BG_STOPS[i + 1]
            px[x, y] = tuple(round(a[k] + (b[k] - a[k]) * f) for k in range(3))  # type: ignore[index]
    base = small.resize((width, height), Image.BICUBIC)
    glow = Image.new("RGB", (width, height), (0, 0, 0))
    ImageDraw.Draw(glow).ellipse(
        (width * 0.1, height * 0.42, width * 1.1, height * 1.25), fill=(120, 210, 225)
    )
    return Image.blend(base, glow.filter(ImageFilter.GaussianBlur(210)), 0.35)


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


def wall_grid(source: bytes, parts: int, box_w: int, gap: int,
              seam: tuple[int, int, int] = (12, 14, 22)) -> Image.Image:
    """Сетка превью ровно так, как её покажет профиль."""
    rows = slicer.LAYOUTS[parts]
    cell_w = (box_w - gap * (slicer.COLS - 1)) // slicer.COLS
    cell_h = round(cell_w * slicer.CELL_H / slicer.CELL_W)
    with Image.open(io.BytesIO(source)) as src:
        board = slicer._cover(src.convert("RGB"), cell_w * slicer.COLS, cell_h * rows)
    grid = Image.new("RGB", (box_w, cell_h * rows + gap * (rows - 1)), seam)
    for row in range(rows):
        for col in range(slicer.COLS):
            tile = board.crop(
                (col * cell_w, row * cell_h, (col + 1) * cell_w, (row + 1) * cell_h)
            )
            grid.paste(tile, (col * (cell_w + gap), row * (cell_h + gap)))
    return grid


#: Логический экран iPhone 15/16 Pro Max — 430×932 pt. Ровно эти числа,
#: а не «примерно вытянутый прямоугольник»: пропорция 2.167 и есть то,
#: по чему глаз узнаёт айфон, а не марку на корпусе.
SCREEN_W, SCREEN_H = 430, 932

#: Рисуем корпус вдвое крупнее и уменьшаем: радиусы у айфона большие, и
#: без сглаживания углы выходят ступеньками.
PHONE_SS = 2


def phone(inner: Image.Image) -> Image.Image:
    """Корпус iPhone: титановая рамка, Dynamic Island, боковые кнопки."""
    ss = PHONE_SS
    bezel = 11 * ss
    rail = 3 * ss
    screen = inner.resize((inner.width * ss, inner.height * ss), Image.LANCZOS)

    body_w = screen.width + bezel * 2
    body_h = screen.height + bezel * 2
    pad = 14 * ss
    canvas = Image.new("RGBA", (body_w + pad * 2, body_h + pad * 2), (0, 0, 0, 0))

    #: Тень отдельным слоем под корпусом: без неё телефон выглядит
    #: наклейкой на фоне, а не предметом перед ним.
    shadow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle(
        (pad, pad + 6 * ss, pad + body_w, pad + body_h + 6 * ss),
        radius=round(body_w * 0.145), fill=(0, 20, 28, 150),
    )
    canvas.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(9 * ss)))

    draw = ImageDraw.Draw(canvas)
    box = (pad, pad, pad + body_w, pad + body_h)
    radius = round(body_w * 0.145)
    #: Титан: светлая рамка с тёмной внутренней кромкой. Один плоский
    #: серый читается как пластик.
    draw.rounded_rectangle(box, radius=radius, fill=(206, 205, 200, 255))
    draw.rounded_rectangle(
        (box[0] + rail, box[1] + rail, box[2] - rail, box[3] - rail),
        radius=radius - rail, fill=(28, 28, 30, 255),
    )

    mask = Image.new("L", screen.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, screen.width - 1, screen.height - 1),
        radius=round(body_w * 0.145) - bezel, fill=255,
    )
    canvas.paste(screen, (pad + bezel, pad + bezel), mask)

    #: Dynamic Island — 125×36 pt при ширине 430 pt.
    island_w, island_h = round(screen.width * 0.291), round(screen.width * 0.084)
    island_x = pad + bezel + (screen.width - island_w) // 2
    island_y = pad + bezel + round(screen.width * 0.026)
    #: Тонкий тёмно-серый кант: на чёрном интерфейсе чёрная пилюля
    #: исчезает, а это главная деталь, по которой узнают айфон.
    draw.rounded_rectangle(
        (island_x, island_y, island_x + island_w, island_y + island_h),
        radius=island_h // 2, fill=(0, 0, 0, 255), outline=(52, 52, 56, 255), width=ss,
    )

    #: Кнопки выступают за корпус на волосок — так силуэт перестаёт быть
    #: голым прямоугольником.
    btn = (196, 195, 190, 255)
    for top, height in ((0.155, 0.030), (0.225, 0.058), (0.295, 0.058)):
        y0 = pad + round(body_h * top)
        draw.rounded_rectangle(
            (box[0] - rail, y0, box[0] + rail, y0 + round(body_h * height)),
            radius=rail, fill=btn,
        )
    y0 = pad + round(body_h * 0.245)
    draw.rounded_rectangle(
        (box[2] - rail, y0, box[2] + rail, y0 + round(body_h * 0.085)), radius=rail, fill=btn
    )

    return canvas.resize((canvas.width // ss, canvas.height // ss), Image.LANCZOS)


def status_bar(draw: ImageDraw.ImageDraw, width: int, colour=(255, 255, 255)) -> None:
    """Время слева, сеть/Wi-Fi/батарея справа — как на скриншоте."""
    draw.text((width * 0.085, 26), "9:41", font=font(17), fill=colour, anchor="mm")

    x = width - 92
    for i in range(4):
        h = 4 + i * 3
        draw.rounded_rectangle((x + i * 6, 32 - h, x + i * 6 + 4, 32), radius=1, fill=colour)

    wx, wy = width - 62, 31
    for i, r in enumerate((11, 7, 3)):
        draw.arc((wx - r, wy - r, wx + r, wy + r), 215, 325,
                 fill=colour, width=3 - (i == 2))
    draw.ellipse((wx - 1.6, wy - 1.6, wx + 1.6, wy + 1.6), fill=colour)

    bx = width - 40
    draw.rounded_rectangle((bx, 18, bx + 26, 32), radius=5, outline=colour, width=2)
    draw.rounded_rectangle((bx + 2, 20, bx + 19, 30), radius=3, fill=colour)
    draw.rounded_rectangle((bx + 27, 23, bx + 29, 28), radius=1, fill=colour)


#: Цвета тёмной темы Telegram на iOS.
IOS_BG = (0, 0, 0)
IOS_CARD = (28, 28, 30)
IOS_GRAY = (142, 142, 147)
IOS_BLUE = (10, 132, 255)


def _profile_chrome(screen: Image.Image, name: str, avatar: Image.Image | None) -> int:
    """Шапка профиля Telegram: навигация, аватарка, имя, ряд кнопок.

    Возвращает Y, с которого начинается сетка публикаций.
    """
    width = screen.width
    draw = ImageDraw.Draw(screen, "RGBA")
    status_bar(draw, width)

    #: Навигация: «‹ Назад» слева, «…» справа — без них экран не
    #: читается как экран приложения.
    draw.text((22, 78), "‹", font=font(34), fill=IOS_BLUE, anchor="lm")
    draw.text((40, 79), "Назад", font=font(18), fill=IOS_BLUE, anchor="lm")
    for i in range(3):
        draw.ellipse((width - 44 + i * 10, 76, width - 40 + i * 10, 80), fill=IOS_BLUE)

    avatar_d = 104
    top = 110
    if avatar is not None:
        plate = avatar.convert("RGB").resize((avatar_d, avatar_d), Image.LANCZOS)
        mask = Image.new("L", (avatar_d * 4, avatar_d * 4), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, avatar_d * 4 - 1, avatar_d * 4 - 1), fill=255)
        screen.paste(plate, ((width - avatar_d) // 2, top),
                     mask.resize((avatar_d, avatar_d), Image.LANCZOS))
    else:
        draw.ellipse(((width - avatar_d) // 2, top,
                      (width + avatar_d) // 2, top + avatar_d), fill=(58, 58, 60))

    name_y = top + avatar_d + 34
    draw.text((width / 2, name_y), name, font=font(25), fill=INK, anchor="mm")
    draw.text((width / 2, name_y + 28), "был(а) недавно", font=font(15),
              fill=IOS_GRAY, anchor="mm")

    #: Ряд действий — четыре карточки, как в профиле на iOS.
    row_y = name_y + 56
    labels = ("Сообщение", "Позвонить", "Видео", "Ещё")
    pad, gap = 14, 8
    cell = (width - pad * 2 - gap * 3) // 4
    for i, label in enumerate(labels):
        x = pad + i * (cell + gap)
        draw.rounded_rectangle((x, row_y, x + cell, row_y + 62), radius=12, fill=IOS_CARD)
        cx = x + cell / 2
        draw.ellipse((cx - 8, row_y + 14, cx + 8, row_y + 30), outline=IOS_BLUE, width=2)
        draw.text((cx, row_y + 47), label, font=font(11), fill=IOS_BLUE, anchor="mm")

    #: Вкладки. Активны «Публикации» — именно там и живёт стенка.
    tabs_y = row_y + 84
    tabs = ("Публикации", "Медиа", "Файлы", "Ссылки")
    x = 18
    for i, tab in enumerate(tabs):
        w = draw.textlength(tab, font=font(15))
        draw.text((x, tabs_y), tab, font=font(15),
                  fill=INK if i == 0 else IOS_GRAY, anchor="lm")
        if i == 0:
            draw.rounded_rectangle((x, tabs_y + 16, x + w, tabs_y + 19), radius=2, fill=INK)
        x += w + 26
    return tabs_y + 30


def profile_screen(source: bytes, parts: int, width: int, name: str,
                   frame_index: int | None = None, colour_index: int = 4) -> Image.Image:
    """Скриншот профиля со стенкой — как его снял бы владелец."""
    screen = Image.new("RGB", (SCREEN_W, SCREEN_H), IOS_BG)
    avatar = Image.open(io.BytesIO(frames_mod.apply(source, colour_index,
                                                    3 if frame_index is None else frame_index)))
    grid_top = _profile_chrome(screen, name, avatar)

    gap = 2
    grid = wall_grid(source, parts, SCREEN_W, gap, seam=IOS_BG)
    #: Сетка уходит за нижний край — так и выглядит настоящий скриншот,
    #: аккуратно уместившаяся сетка сразу читается как макет.
    screen.paste(grid, (0, grid_top))

    draw = ImageDraw.Draw(screen, "RGBA")
    draw.rounded_rectangle((SCREEN_W / 2 - 70, SCREEN_H - 12, SCREEN_W / 2 + 70, SCREEN_H - 7),
                           radius=3, fill=(255, 255, 255, 190))
    return screen


def blank_screen(name: str = "@nudick") -> Image.Image:
    """Тот же профиль, но с обычной лентой — половина карточки «было/стало»."""
    screen = Image.new("RGB", (SCREEN_W, SCREEN_H), IOS_BG)
    grid_top = _profile_chrome(screen, name, None)
    draw = ImageDraw.Draw(screen)
    gap = 2
    cell = (SCREEN_W - gap * 2) // 3
    cell_h = round(cell * slicer.CELL_H / slicer.CELL_W)
    tones = [(38, 38, 42), (30, 30, 34), (46, 46, 50)]
    for row in range(4):
        for col in range(3):
            x = col * (cell + gap)
            y = grid_top + row * (cell_h + gap)
            draw.rectangle((x, y, x + cell, y + cell_h), fill=tones[(row + col) % 3])
    draw.rounded_rectangle((SCREEN_W / 2 - 70, SCREEN_H - 12, SCREEN_W / 2 + 70, SCREEN_H - 7),
                           radius=3, fill=(255, 255, 255, 190))
    return screen


def footer(card: Image.Image, text: str = HANDLE) -> None:
    ImageDraw.Draw(card).text(
        (W / 2, H - 46), text, font=font(30), fill=(120, 132, 154), anchor="mm"
    )


def chip(draw: ImageDraw.ImageDraw, box, title: str, lines: list[str]) -> None:
    """Скруглённая плашка с заголовком и строками."""
    x0, y0, x1, y1 = box
    draw.rounded_rectangle(box, radius=RADIUS, fill=PLATE + (PLATE_ALPHA,))
    draw.text((x0 + 34, y0 + 28), title, font=font(34), fill=ACCENT)
    y = y0 + 88
    for line in lines:
        draw.text((x0 + 34, y), line, font=font(31), fill=INK)
        y += 46


def title_plate(draw: ImageDraw.ImageDraw, text: str, top: int = 56, size: int = 54) -> int:
    """Заголовок в отдельной тёмной пилюле по центру, как у конкурента.

    Текст прямо на градиенте читается плохо: сверху фон тёмный, снизу
    светлый, и одна и та же белая строка где-то тонет, где-то слепит.
    """
    face = font(size)
    width = draw.textlength(text, font=face)
    pad_x, pad_y = 44, 26
    box = ((W - width) / 2 - pad_x, top, (W + width) / 2 + pad_x, top + size + pad_y * 2)
    draw.rounded_rectangle(box, radius=RADIUS, fill=PLATE + (PLATE_ALPHA,))
    draw.text((W / 2, top + (size + pad_y * 2) / 2), text, font=face, fill=INK, anchor="mm")
    return int(box[3])


# --------------------------------------------------------------------------
# Карточки
# --------------------------------------------------------------------------


def make_manual(source: bytes) -> Image.Image:
    card = backdrop()
    draw = ImageDraw.Draw(card, "RGBA")
    bottom = title_plate(draw, "Как подобрать размер фото")

    ratios = []
    for parts in sorted(slicer.LAYOUTS):
        w, h = slicer.ideal_ratio(parts)
        ratios.append(f"{w}:{h}   →   {parts} сторис")
    top = bottom + 28
    chip(draw, (60, top, W // 2 - 14, top + 292), "Идеальные пропорции", ratios)
    chip(
        draw, (W // 2 + 14, top, W - 60, top + 292), "Почему так",
        ["В профиле три колонки,", "а в превью видно только", "середину кадра —", "окно 4:5."],
    )

    #: Сетку кладём как у конкурента: тонкие белые швы и крупные белые
    #: цифры прямо на снимке, без тёмных кружков — кружки съедают кадр и
    #: превращают демонстрацию в схему.
    grid_w, grid_x = 420, 60
    grid_y = top + 330
    grid = wall_grid(source, 9, grid_w, 6, seam=(255, 255, 255))
    card.paste(grid, (grid_x, grid_y))
    gdraw = ImageDraw.Draw(card, "RGBA")
    cell = (grid_w - 12) // 3
    cell_h = round(cell * slicer.CELL_H / slicer.CELL_W)
    number = 9
    for row in range(3):
        for col in range(3):
            cx = grid_x + col * (cell + 6) + cell / 2
            cy = grid_y + row * (cell_h + 6) + cell_h / 2
            gdraw.text((cx + 2, cy + 2), str(number), font=font(52),
                       fill=(0, 0, 0, 150), anchor="mm")
            gdraw.text((cx, cy), str(number), font=font(52), fill=INK, anchor="mm")
            number -= 1

    grid_bottom = grid_y + cell_h * 3 + 12
    chip(
        ImageDraw.Draw(card, "RGBA"),
        (520, grid_y, W - 60, grid_bottom),
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
    warn_top = grid_bottom + 26
    draw.rounded_rectangle((60, warn_top, W - 60, warn_top + 156), radius=RADIUS,
                           fill=(74, 46, 12, 236))
    draw.text((94, warn_top + 24), "Важно", font=font(34), fill=(255, 196, 92))
    draw.text(
        (94, warn_top + 74),
        f"Фото меньше {slicer.MIN_SIDE} px по короткой стороне\n"
        "на 12–15 частей бот растянет — будет мылить.",
        font=font(31), fill=INK,
    )
    footer(card)
    return card


def make_welcome(source: bytes) -> Image.Image:
    card = backdrop()
    draw = ImageDraw.Draw(card, "RGBA")
    title_plate(draw, "Стенка из сторис", top=44, size=58)

    shell = phone(profile_screen(source, 9, SCREEN_W, OWNER))
    scale = 920 / shell.height
    shell = shell.resize((round(shell.width * scale), round(shell.height * scale)), Image.LANCZOS)
    card.paste(shell, ((W - shell.width) // 2, 182), shell)

    draw = ImageDraw.Draw(card, "RGBA")
    #: Подпись в плашке, а не поверх градиента: внизу фон самый светлый,
    #: и белый текст на нём исчезает.
    face = font(38)
    text = "Одна картинка — целый профиль"
    width = draw.textlength(text, font=face)
    draw.rounded_rectangle(
        ((W - width) / 2 - 38, H - 158, (W + width) / 2 + 38, H - 84),
        radius=RADIUS, fill=PLATE + (PLATE_ALPHA,),
    )
    draw.text((W / 2, H - 121), text, font=face, fill=INK, anchor="mm")
    footer(card)
    return card


def make_about(source: bytes) -> Image.Image:
    card = backdrop()
    draw = ImageDraw.Draw(card, "RGBA")
    title_plate(draw, "Было / стало")

    shells = []
    for inner in (blank_screen(OWNER), profile_screen(source, 9, SCREEN_W, OWNER)):
        shell = phone(inner)
        scale = 740 / shell.height
        shells.append(
            shell.resize((round(shell.width * scale), round(shell.height * scale)), Image.LANCZOS)
        )
    gap = 64
    span = shells[0].width * 2 + gap
    for index, shell in enumerate(shells):
        card.paste(shell, ((W - span) // 2 + index * (shell.width + gap), 214), shell)

    draw = ImageDraw.Draw(card, "RGBA")
    for index, label in enumerate(("обычная лента", "стенка")):
        cx = (W - span) // 2 + index * (shells[0].width + gap) + shells[0].width / 2
        w = draw.textlength(label, font=font(28))
        draw.rounded_rectangle((cx - w / 2 - 22, 966, cx + w / 2 + 22, 1020),
                               radius=26, fill=PLATE + (PLATE_ALPHA,))
        draw.text((cx, 993), label, font=font(28), fill=INK, anchor="mm")

    #: Две строки, а не четыре: плашка кончается на 1216, четвёртая
    #: строка ложилась уже на градиент под ней.
    chip(
        draw, (60, 1046, W - 60, 1216), "Что меняется",
        [
            "Сетка профиля складывает истории в одно",
            "полотно. Порядок публикации бот берёт на себя.",
        ],
    )
    footer(card)
    return card


def profile_card(avatar_src: bytes, frame_index: int, colour_index: int,
                 name: str, width: int, height: int) -> Image.Image:
    """Карточка профиля Telegram: узор, аватарка с рамкой, имя, статус.

    Именно так рамку показывает конкурент — и это честно: человек видит
    не рамку саму по себе, а то, как она сядет в его профиль.
    """
    plate = Image.new("RGB", (width, height))
    px = plate.load()
    for y in range(height):
        for x in range(width):
            t = (x / width) * 0.4 + (y / height) * 0.6
            px[x, y] = (  # type: ignore[index]
                round(74 + 84 * t), round(170 + 46 * t), round(206 + 30 * t),
            )
    pat = ImageDraw.Draw(plate, "RGBA")
    #: Редкие светлые пятна вместо фирменного узора Telegram: рисовать
    #: чужие иконки в собственную рекламу нечестно, а фактура нужна —
    #: на голой заливке карточка выглядит плашкой, а не интерфейсом.
    for i in range(46):
        angle = i * 2.399
        cx = width * (0.5 + 0.46 * math.cos(angle * 3.1) * ((i % 7) / 7 + 0.3))
        cy = height * (0.5 + 0.46 * math.sin(angle * 2.3) * ((i % 5) / 5 + 0.3))
        r = width * 0.018
        pat.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(255, 255, 255, 28))

    avatar_d = round(width * 0.42)
    avatar = Image.open(
        io.BytesIO(frames_mod.apply(avatar_src, colour_index, frame_index))
    ).convert("RGBA").resize((avatar_d, avatar_d), Image.LANCZOS)
    mask = Image.new("L", (avatar_d * 4, avatar_d * 4), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, avatar_d * 4 - 1, avatar_d * 4 - 1), fill=255)
    avatar.putalpha(mask.resize((avatar_d, avatar_d), Image.LANCZOS))
    plate.paste(avatar, ((width - avatar_d) // 2, round(height * 0.14)), avatar)

    draw = ImageDraw.Draw(plate, "RGBA")
    #: Зазор между именем и статусом считаем от кегля имени, а не от
    #: высоты карточки: при 0.085 высоты строки налезали друг на друга.
    name_size = round(width * 0.085)
    name_y = round(height * 0.14) + avatar_d + round(name_size * 0.95)
    draw.text((width / 2, name_y), name, font=font(name_size), fill=INK, anchor="mm")
    draw.text((width / 2, name_y + round(name_size * 1.15)), "был(а) недавно",
              font=font(round(width * 0.05)), fill=(255, 255, 255, 200), anchor="mm")

    rounded = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    rmask = Image.new("L", (width * 2, height * 2), 0)
    ImageDraw.Draw(rmask).rounded_rectangle(
        (0, 0, width * 2 - 1, height * 2 - 1), radius=round(width * 0.12), fill=255
    )
    rounded.paste(plate, (0, 0), rmask.resize((width, height), Image.LANCZOS))
    return rounded


def make_frames(source: bytes) -> Image.Image:
    card = backdrop()
    draw = ImageDraw.Draw(card, "RGBA")
    title_plate(draw, "Рамки для аватарки")

    #: Золотой венок, а не чернильная маска: на тёмной аватарке тёмная
    #: маска сливается с фотографией, и рамки на витрине просто не видно.
    hero = profile_card(source, 0, 7, "@nudick", 620, 500)
    card.paste(hero, ((W - hero.width) // 2, 216), hero)

    picks = [3, 5, 7, 1]
    size, gap = 208, 22
    start_x = (W - (size * len(picks) + gap * (len(picks) - 1))) // 2
    row_y = 800
    for i, index in enumerate(picks):
        shot = Image.open(io.BytesIO(frames_mod.apply(source, i * 2, index))).convert("RGB")
        shot = shot.resize((size, size), Image.LANCZOS)
        card.paste(shot, (start_x + i * (size + gap), row_y))

    chip(
        draw, (60, 1058, W - 60, 1216), "Как это работает",
        [
            f"{frames_mod.frame_count()} рамок × {len(frames_mod.COLORS)} фонов, включая подарочные.",
            "Фон под рамкой — фон твоего профиля,",
            "поэтому она выглядит частью интерфейса.",
        ],
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
    for candidate in (CUSTOM_SOURCE, CUSTOM_SOURCE.with_suffix(".jpg"), OUT / "_nudick.jpg"):
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
