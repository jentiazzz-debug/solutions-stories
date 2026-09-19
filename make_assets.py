"""Сборка картинок-заставок в assets/.

Почему кодом, а не нейронкой. Инструкция — инфографика: в ней пропорции,
номера ячеек и порядок публикации. Ошибись генератор в одной цифре — и
человек соберёт стенку задом наперёд, а проверить это на глаз нельзя.
Здесь числа берутся прямо из slicer.py, поэтому картинка не может
разойтись с тем, что бот реально делает.

    python make_assets.py

Витринные баннеры (welcome, about, frames) нарисованы руками и лежат
готовыми файлами — скрипт их не трогает, см. HANDMADE.

Модуль нужен и в рантайме: handlers зовёт personal_manual(), чтобы
собрать инструкцию на аватарке того, кто её открыл.
"""

from __future__ import annotations

import io
import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

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

#: Серо-белая палитра для инструкции. Бирюза хороша на витрине, но
#: инструкцию человек читает, а не рассматривает: цветной градиент под
#: плотным текстом спорит с ним за внимание и мешает на нём удержаться.
MONO_STOPS = ((9, 9, 11), (26, 26, 30), (92, 94, 100))
MONO_PLATE = (20, 20, 23)
MONO_ACCENT = (228, 230, 236)
MONO_FOOT = (122, 124, 132)
MONO_GLOW = (188, 194, 206)

BRAND = "Solutions Stories"

#: Чей профиль показываем на витрине. Живой юзернейм вместо названия
#: бота: человек должен увидеть чужой настоящий профиль, а не макет.
OWNER = "@nudick"
HANDLE = "@SolutionsStoriesbot"

#: Шрифт ищем сначала в репозитории, потом в системе. Контейнер на
#: хостинге — голый python:3.11, шрифтов там нет вообще: пока карточки
#: собирались только на моей машине, это было незаметно, а личная
#: инструкция рисуется уже в проде и падала на первом же заголовке.
FONTS_DIR = OUT / "fonts"

_FONTS = (
    str(FONTS_DIR / "DejaVuSans-Bold.ttf"),
    str(FONTS_DIR / "DejaVuSans.ttf"),
    "arialbd.ttf", "arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)

NO_FONT = ("Не нашёл шрифт с кириллицей. Положи .ttf в assets/fonts "
           "(DejaVuSans-Bold.ttf) или впиши свой в _FONTS.")


def font(size: int) -> ImageFont.FreeTypeFont:
    for name in _FONTS:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    #: Не SystemExit: раньше эта функция работала только в сборке, где
    #: «выйти с ошибкой» — нормальный исход. Теперь её зовёт бот, а
    #: SystemExit наследуется от BaseException и пролетает мимо
    #: `except Exception` в хендлере — человек получал молчание вместо
    #: инструкции.
    raise RuntimeError(NO_FONT)


# --------------------------------------------------------------------------
# Кисти
# --------------------------------------------------------------------------


def backdrop(width: int = W, height: int = H, stops=None,
             glow_colour=(120, 210, 225)) -> Image.Image:
    """Диагональный градиент: тёмный угол сверху, свет снизу."""
    stops = stops or BG_STOPS
    small = Image.new("RGB", (64, 64))
    px = small.load()
    for y in range(64):
        for x in range(64):
            #: Диагональ, а не вертикаль: свет приходит из угла, и
            #: плашки ложатся на неоднородный фон — так карточка
            #: выглядит снятой, а не залитой.
            t = (x / 63) * 0.42 + (y / 63) * 0.58
            t = min(max(t, 0.0), 1.0) * (len(stops) - 1)
            i = min(int(t), len(stops) - 2)
            f = t - i
            a, b = stops[i], stops[i + 1]
            px[x, y] = tuple(round(a[k] + (b[k] - a[k]) * f) for k in range(3))  # type: ignore[index]
    base = small.resize((width, height), Image.BICUBIC)
    glow = Image.new("RGB", (width, height), (0, 0, 0))
    ImageDraw.Draw(glow).ellipse(
        (width * 0.1, height * 0.42, width * 1.1, height * 1.25), fill=glow_colour
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

    #: Блик по стеклу. Без него экран выглядит напечатанным на корпусе:
    #: у настоящего телефона поверх картинки всегда лежит отражение.
    glass = screen.convert("RGBA")
    glare = Image.new("RGBA", screen.size, (0, 0, 0, 0))
    gw, gh = screen.width, screen.height
    ImageDraw.Draw(glare).polygon(
        [(-gw * 0.15, gh * 0.46), (gw * 0.58, -gh * 0.05),
         (gw * 1.05, -gh * 0.05), (gw * 0.18, gh * 0.72)],
        fill=(255, 255, 255, 26),
    )
    ImageDraw.Draw(glare).polygon(
        [(gw * 0.62, -gh * 0.05), (gw * 1.05, -gh * 0.05),
         (gw * 0.52, gh * 0.55), (gw * 0.34, gh * 0.55)],
        fill=(255, 255, 255, 16),
    )
    glass.alpha_composite(glare.filter(ImageFilter.GaussianBlur(gw * 0.012)))

    mask = Image.new("L", screen.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, screen.width - 1, screen.height - 1),
        radius=round(body_w * 0.145) - bezel, fill=255,
    )
    canvas.paste(glass, (pad + bezel, pad + bezel), mask)

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

    #: Световая кромка по верхне-левой грани: титан ловит свет ребром, и
    #: без этой линии рамка остаётся серой заливкой.
    rim = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    ImageDraw.Draw(rim).rounded_rectangle(
        (box[0] + 1, box[1] + 1, box[2] - 1, box[3] - 1), radius=radius,
        outline=(255, 255, 255, 190), width=max(1, rail // 2),
    )
    #: Оставляем только верх и левый край — блик по всему периметру
    #: выглядит как обводка в редакторе.
    keep = Image.new("L", canvas.size, 0)
    ImageDraw.Draw(keep).polygon(
        [(0, 0), (canvas.width, 0), (0, canvas.height)], fill=255
    )
    canvas.alpha_composite(Image.composite(rim, Image.new("RGBA", canvas.size, (0, 0, 0, 0)), keep))

    return canvas.resize((canvas.width // ss, canvas.height // ss), Image.LANCZOS)


def tilt(shell: Image.Image, angle: float) -> Image.Image:
    """Наклонить корпус. Фронтальный телефон в упор — самая скучная подача."""
    return shell.rotate(angle, resample=Image.BICUBIC, expand=True)


def halo(card: Image.Image, cx: int, cy: int, radius: int, colour, strength: float = 0.55) -> None:
    """Свечение за корпусом — телефон перестаёт лежать на плоскости.

    Свет подмешивается ТОЛЬКО там, где он есть: маской служит само пятно.
    Смешивать свечение со всей карточкой нельзя — тогда вместе с фоном
    выцветает и заголовок, и подписи.
    """
    spot = Image.new("L", card.size, 0)
    ImageDraw.Draw(spot).ellipse(
        (cx - radius, cy - radius * 1.15, cx + radius, cy + radius * 1.15), fill=255
    )
    spot = spot.filter(ImageFilter.GaussianBlur(radius * 0.45))
    spot = spot.point(lambda v: int(v * strength))
    card.paste(Image.new("RGB", card.size, colour).convert(card.mode), (0, 0), spot)


def floating_chip(card: Image.Image, xy, lines, size: int = 30) -> None:
    """Плавающая подпись — приём из витрины конкурента.

    Принимает несколько строк: две отдельные пилюли под одну фразу
    читаются как обрывки, а не как подпись.
    """
    if isinstance(lines, str):
        lines = [lines]
    draw = ImageDraw.Draw(card, "RGBA")
    face = font(size)
    width = max(draw.textlength(line, font=face) for line in lines)
    step = size + 12
    x, y = xy
    box = (x, y, x + width + 52, y + step * len(lines) + 24)
    shadow = Image.new("RGBA", card.size, (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle(
        (box[0] + 4, box[1] + 9, box[2] + 4, box[3] + 9), radius=28, fill=(0, 16, 24, 150)
    )
    card.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(11)))
    draw = ImageDraw.Draw(card, "RGBA")
    draw.rounded_rectangle(box, radius=28, fill=(255, 255, 255, 242))
    cy = box[1] + 12 + step / 2
    for line in lines:
        draw.text(((box[0] + box[2]) / 2, cy), line, font=face, fill=(16, 32, 42), anchor="mm")
        cy += step


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
        #: Кадрируем по центру, а не растягиваем: аватарка почти никогда
        #: не квадратная, и resize превращал лицо в блин.
        plate = slicer._cover(avatar.convert("RGB"), avatar_d, avatar_d)
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
                   frame_index: int | None = None, colour_index: int = 4,
                   numbers: bool = False) -> Image.Image:
    """Скриншот профиля со стенкой — как его снял бы владелец."""
    screen = Image.new("RGB", (SCREEN_W, SCREEN_H), IOS_BG)
    #: Номер рамки не фиксируем: их число зависит от того, сколько файлов
    #: лежит в папке, и жёсткая тройка роняла сборку на любой правке набора.
    total = frames_mod.frame_count()
    if total == 0:
        avatar = None
    else:
        pick = (frame_index if frame_index is not None else 0) % total
        avatar = Image.open(io.BytesIO(frames_mod.apply(source, colour_index, pick)))
    grid_top = _profile_chrome(screen, name, avatar)

    gap = 2
    grid = wall_grid(source, parts, SCREEN_W, gap, seam=IOS_BG)
    #: Витринную стенку осветляем: исходник — ночной кадр, и на превью
    #: девять почти чёрных плиток не показывают ровным счётом ничего.
    #: Это экспозиция демонстрации, сама нарезка исходник не трогает.
    grid = ImageEnhance.Contrast(ImageEnhance.Brightness(grid).enhance(1.42)).enhance(1.12)
    #: Сетка уходит за нижний край — так и выглядит настоящий скриншот,
    #: аккуратно уместившаяся сетка сразу читается как макет.
    screen.paste(grid, (0, grid_top))

    draw = ImageDraw.Draw(screen, "RGBA")
    if numbers:
        #: Номера кладём на сам профиль, а не на отдельную схему рядом.
        #: Инструкция про порядок публикации, и порядок понятнее всего
        #: там, где человек его и увидит, — в своей же сетке.
        cell = (SCREEN_W - gap * 2) // slicer.COLS
        cell_h = round(cell * slicer.CELL_H / slicer.CELL_W)
        left = parts
        for row in range(slicer.LAYOUTS[parts]):
            for col in range(slicer.COLS):
                cx = col * (cell + gap) + cell / 2
                cy = grid_top + row * (cell_h + gap) + cell_h / 2
                if cy > SCREEN_H - 20:
                    continue
                draw.text((cx + 2, cy + 2), str(left), font=font(40),
                          fill=(0, 0, 0, 170), anchor="mm")
                draw.text((cx, cy), str(left), font=font(40),
                          fill=(255, 255, 255), anchor="mm")
                left -= 1
    draw.rounded_rectangle((SCREEN_W / 2 - 70, SCREEN_H - 12, SCREEN_W / 2 + 70, SCREEN_H - 7),
                           radius=3, fill=(255, 255, 255, 190))
    return screen


def blank_screen(name: str = "@nudick", avatar: Image.Image | None = None) -> Image.Image:
    """Тот же профиль, но с обычной лентой — половина карточки «было/стало».

    Аватарка тут его настоящая, без рамки: половинки должны отличаться
    ровно тем, о чём раздел, — лентой, а не подменённым лицом.
    """
    screen = Image.new("RGB", (SCREEN_W, SCREEN_H), IOS_BG)
    grid_top = _profile_chrome(screen, name, avatar)
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


def footer(card: Image.Image, text: str = HANDLE, colour=(120, 132, 154)) -> None:
    ImageDraw.Draw(card).text(
        (W / 2, H - 46), text, font=font(30), fill=colour, anchor="mm"
    )


def wrap(draw: ImageDraw.ImageDraw, text: str, face, width: float) -> list[str]:
    """Разбить строку по словам так, чтобы влезла в заданную ширину."""
    if not text or draw.textlength(text, font=face) <= width:
        return [text]
    out, line = [], ""
    for word in text.split(" "):
        probe = f"{line} {word}".strip()
        if line and draw.textlength(probe, font=face) > width:
            out.append(line)
            line = word
        else:
            line = probe
    if line:
        out.append(line)
    return out


def chip(draw: ImageDraw.ImageDraw, box, title: str, lines: list[str],
         accent=None, plate=None, size: int = 31, step: int = 46) -> int:
    """Скруглённая плашка с заголовком и строками.

    Высота считается от содержимого, а не задаётся руками: заданная
    руками уже дважды оказывалась короче текста, и последние строки
    уезжали на градиент под плашкой. Четвёртый элемент box теперь
    только минимум высоты.

    Длинные строки переносятся по словам. Раньше перенос был расставлен
    руками — и держался ровно до смены шрифта: DejaVu шире ариала, и
    те же строки полезли за край плашки. Пустая строка по-прежнему
    означает отбивку между абзацами.
    """
    x0, y0, x1, y1 = box
    top_pad, line_step, bottom_pad = 88, step, 30
    body = font(size)
    lines = [part for line in lines for part in wrap(draw, line, body, x1 - x0 - 68)]
    needed = top_pad + line_step * len(lines) + bottom_pad
    bottom = max(y1, y0 + needed)
    draw.rounded_rectangle((x0, y0, x1, bottom), radius=RADIUS,
                           fill=(plate or PLATE) + (PLATE_ALPHA,))
    draw.text((x0 + 34, y0 + 28), title, font=font(34), fill=accent or ACCENT)
    y = y0 + top_pad
    for line in lines:
        draw.text((x0 + 34, y), line, font=body, fill=INK)
        y += line_step
    return int(bottom)


def title_plate(draw: ImageDraw.ImageDraw, text: str, top: int = 56, size: int = 54,
                plate=None) -> int:
    """Заголовок в отдельной тёмной пилюле по центру, как у конкурента.

    Текст прямо на градиенте читается плохо: сверху фон тёмный, снизу
    светлый, и одна и та же белая строка где-то тонет, где-то слепит.
    """
    face = font(size)
    width = draw.textlength(text, font=face)
    pad_x, pad_y = 44, 26
    box = ((W - width) / 2 - pad_x, top, (W + width) / 2 + pad_x, top + size + pad_y * 2)
    draw.rounded_rectangle(box, radius=RADIUS, fill=(plate or PLATE) + (PLATE_ALPHA,))
    draw.text((W / 2, top + (size + pad_y * 2) / 2), text, font=face, fill=INK, anchor="mm")
    return int(box[3])


# --------------------------------------------------------------------------
# Карточки
# --------------------------------------------------------------------------


def manual_card(source: bytes, name: str = OWNER) -> Image.Image:
    """Инструкция: слева профиль с пронумерованной стенкой, справа — правила.

    Карточка собирается под конкретного человека: `source` — его же
    аватарка, `name` — его юзернейм. Инструкция про «нарежь свой
    профиль» на чужом демо-кадре читается как реклама; на своём лице
    видно, что именно получится, и порядок публикации запоминается
    вместе с картинкой.
    """
    card = backdrop(stops=MONO_STOPS, glow_colour=MONO_GLOW)
    draw = ImageDraw.Draw(card, "RGBA")
    title_plate(draw, "Как собрать стенку", top=48, size=52, plate=MONO_PLATE)

    #: Телефон с его собственным профилем: 9 частей — та сетка, на
    #: которой видно и три колонки, и порядок сверху вниз.
    #: Фон рамки на аве — «Чёрный»: цветная рамка в серо-белой карточке
    #: тянет взгляд на себя, а смотреть тут надо на номера.
    inner = profile_screen(source, 9, SCREEN_W, name, colour_index=0, numbers=True)
    shell = phone(inner)
    scale = 840 / shell.height
    shell = tilt(
        shell.resize((round(shell.width * scale), round(shell.height * scale)), Image.LANCZOS),
        -4,
    )
    halo(card, 270, 690, 300, MONO_GLOW, 0.28)
    card.paste(shell, (26, 232), shell)

    draw = ImageDraw.Draw(card, "RGBA")
    #: Кегль в плашках мельче основного: колонка узкая, а текста тут
    #: втрое больше, чем на витринных карточках.
    col_x, col_r, small = 520, W - 60, dict(size=28, step=42)

    ratios = [f"{w}:{h}   →   {parts} сторис"
              for parts in sorted(slicer.LAYOUTS)
              for w, h in [slicer.ideal_ratio(parts)]]
    bottom = chip(draw, (col_x, 200, col_r, 200), "Идеальные пропорции", ratios,
                  accent=MONO_ACCENT, plate=MONO_PLATE, **small)

    bottom = chip(
        draw, (col_x, bottom + 28, col_r, bottom + 28), "Порядок публикации",
        [
            "Публикуй файлы подряд, сверху вниз, по одному.",
            "",
            "Первый — правый нижний угол. Последний — левый верхний.",
        ],
        accent=MONO_ACCENT, plate=MONO_PLATE, **small,
    )

    chip(
        draw, (col_x, bottom + 28, col_r, bottom + 28), "Важно",
        [f"Фото меньше {slicer.MIN_SIDE} px по короткой стороне "
         "на 12–15 частей бот растянет."],
        accent=MONO_ACCENT, plate=MONO_PLATE, **small,
    )

    footer(card, colour=MONO_FOOT)
    return card


def make_manual(source: bytes) -> Image.Image:
    """Запасная инструкция в файле — на случай, если у человека нет авы."""
    return manual_card(source)


def _jpeg(card: Image.Image) -> bytes:
    buf = io.BytesIO()
    card.convert("RGB").save(buf, format="JPEG", quality=90, optimize=True)
    return buf.getvalue()


def personal_manual(photo: bytes, name: str) -> bytes:
    """Та же карточка, но собранная под конкретного человека, в JPEG."""
    return _jpeg(manual_card(photo, name))


def make_welcome(source: bytes) -> Image.Image:
    card = backdrop()
    draw = ImageDraw.Draw(card, "RGBA")
    title_plate(draw, "Стенка из сторис", top=44, size=58)

    shell = phone(profile_screen(source, 9, SCREEN_W, OWNER))
    scale = 840 / shell.height
    shell = shell.resize((round(shell.width * scale), round(shell.height * scale)), Image.LANCZOS)
    shell = tilt(shell, -7)

    #: Свет за телефоном ставим до самого телефона, иначе он ляжет
    #: поверх корпуса и получится туман.
    halo(card, 330, 640, 300, (86, 220, 236), 0.42)
    card = card.convert("RGBA")
    card.alpha_composite(shell, (34, 210))

    #: Плашки справа перекрывают корпус — из-за этого композиция
    #: перестаёт быть «телефон по центру и подпись снизу».
    floating_chip(card, (500, 296), "Красивое оформление")
    floating_chip(card, (556, 600), ["Одна картинка —", "весь профиль"])
    floating_chip(card, (518, 986), "Выделись среди других", 27)

    footer(card)
    return card


def about_card(source: bytes, name: str = OWNER) -> Image.Image:
    """«Было / стало» на профиле конкретного человека.

    Раздел отвечает на вопрос «а зачем мне это»; ответ убедительнее
    всего выглядит на его собственной аватарке: слева его обычная лента,
    справа она же, собранная в одно полотно.
    """
    card = backdrop(stops=MONO_STOPS, glow_colour=MONO_GLOW)
    draw = ImageDraw.Draw(card, "RGBA")
    title_plate(draw, "Было / стало", plate=MONO_PLATE)

    #: Наклон навстречу друг другу: два одинаково стоящих корпуса
    #: читаются как таблица, развёрнутые — как сравнение.
    shells = []
    with Image.open(io.BytesIO(source)) as raw:
        face = raw.convert("RGB").copy()
    screens = (
        blank_screen(name, face),
        profile_screen(source, 9, SCREEN_W, name, colour_index=0),
    )
    for inner, angle in zip(screens, (6, -6)):
        shell = phone(inner)
        scale = 700 / shell.height
        shell = shell.resize((round(shell.width * scale), round(shell.height * scale)),
                             Image.LANCZOS)
        shells.append(tilt(shell, angle))

    halo(card, 700, 560, 250, MONO_GLOW, 0.26)
    gap = 26
    span = shells[0].width + shells[1].width + gap
    x = (W - span) // 2
    for shell in shells:
        card.paste(shell, (x, 214), shell)
        x += shell.width + gap

    draw = ImageDraw.Draw(card, "RGBA")
    for index, label in enumerate(("обычная лента", "стенка")):
        cx = (W - span) // 2 + index * (shells[0].width + gap) + shells[0].width / 2
        w = draw.textlength(label, font=font(28))
        draw.rounded_rectangle((cx - w / 2 - 22, 966, cx + w / 2 + 22, 1020),
                               radius=26, fill=MONO_PLATE + (PLATE_ALPHA,))
        draw.text((cx, 993), label, font=font(28), fill=INK, anchor="mm")

    chip(
        draw, (60, 1046, W - 60, 1046), "Что меняется",
        ["Сетка профиля складывает истории в одно полотно. "
         "Порядок публикации бот берёт на себя."],
        accent=MONO_ACCENT, plate=MONO_PLATE, size=29, step=44,
    )
    footer(card, colour=MONO_FOOT)
    return card


def make_about(source: bytes) -> Image.Image:
    """Запасная витрина в файле — на случай, если у человека нет авы."""
    return about_card(source)


def personal_about(photo: bytes, name: str) -> bytes:
    """«Было / стало» под конкретного человека, в JPEG."""
    return _jpeg(about_card(photo, name))


def profile_card(avatar_src: bytes, frame_index: int, colour_index: int,
                 name: str, width: int, height: int, tint: bool = True) -> Image.Image:
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
        io.BytesIO(frames_mod.apply(avatar_src, colour_index, frame_index, tint))
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

    #: На витрину — самая нарядная из загруженных: витрина продаёт
    #: рамки, а не движок, и рисованная продаёт лучше процедурной.
    #: На витрине рамки показываем родными цветами: подгонка под фон
    #: хороша в профиле, но здесь она гасит именно то, что продаётся.
    #: Номера рамок больше не фиксированы — их число зависит от того,
    #: сколько файлов в папке. Берём по кругу, иначе витрина падает на
    #: любой правке набора.
    total = max(1, frames_mod.frame_count())
    hero = profile_card(source, 0 % total, 7, "@nudick", 620, 500, tint=False)
    card.paste(hero, ((W - hero.width) // 2, 216), hero)

    picks = [i % total for i in (1, 2, 3, 0)]
    size, gap = 208, 22
    start_x = (W - (size * len(picks) + gap * (len(picks) - 1))) // 2
    row_y = 772
    for i, index in enumerate(picks):
        shot = Image.open(io.BytesIO(frames_mod.apply(source, i * 2, index, False))).convert("RGB")
        shot = shot.resize((size, size), Image.LANCZOS)
        card.paste(shot, (start_x + i * (size + gap), row_y))

    chip(
        draw, (60, 996, W - 60, 996), "Как это работает",
        [
            f"{frames_mod.frame_count()} рамок × {len(frames_mod.COLORS)} фонов, включая подарочные.",
            "Фон под рамкой — тот, что стоит у тебя в профиле.",
            "Рамка умеет перекрашиваться под него одной кнопкой.",
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


#: Карточки, которые нарисованы руками. Скрипт их не воспроизведёт —
#: у него нет ни исходников, ни шрифтов, — поэтому даже --force их не
#: трогает. Один раз я так уже затёр готовые баннеры; проверка стоит
#: строчки, а восстановление стоило вечера.
HANDMADE = {"welcome.jpg", "frames.jpg"}


def main() -> int:
    #: Готовые карточки не перезаписываем: молча затереть чужую работу
    #: скрипт может запросто. --force перерисовывает процедурные,
    #: --force-all — вообще всё, включая нарисованное руками.
    argv = [a for a in sys.argv if a not in ("--force", "--force-all")]
    force_all = "--force-all" in sys.argv
    force = force_all or "--force" in sys.argv

    OUT.mkdir(parents=True, exist_ok=True)
    try:
        font(20)
    except RuntimeError as err:
        print(err)
        return 1
    source = pick_source(argv)
    (OUT / "_demo_source.jpg").write_bytes(source)

    kept = []
    for name, build in (
        ("welcome", make_welcome),
        ("about", make_about),
        ("manual", make_manual),
        ("frames", make_frames),
    ):
        path = OUT / f"{name}.jpg"
        handmade = path.name in HANDMADE and not force_all
        if path.is_file() and (handmade or not force):
            kept.append(path.name + (" (рисованная)" if handmade else ""))
            continue
        card = build(source).convert("RGB")
        card.save(path, format="JPEG", quality=92, optimize=True)
        print(f"{path.name:<14} {card.size[0]}×{card.size[1]}  {path.stat().st_size // 1024} КБ")

    if kept:
        print(f"оставил как есть: {', '.join(kept)}")
        print("перерисовать процедурные: python make_assets.py --force")
        print("затереть и рисованные:    python make_assets.py --force-all")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
