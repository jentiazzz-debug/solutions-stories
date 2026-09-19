"""Рамки для аватарки: венок вокруг фото на фоне твоего профиля.

Почему фон выбирается отдельно. Telegram обрезает аватарку по кругу, а
вокруг неё в профиле — либо акцентный цвет, либо фон коллекционного
подарка (Black, Chill Flame, Vice Cream…). Прозрачность в аватарке не
живёт: Telegram сводит её на чёрное. Значит углы картинки надо залить
ровно тем, что стоит у человека в профиле, — тогда рамка выглядит частью
интерфейса, а не наклейкой поверх.

Фоны подарков — радиальные: центр светлее краёв. Обычный линейный
градиент на их месте сразу выдаёт подделку, поэтому здесь тоже радиал.

Сами рамки — файлы, а не код. Процедурные венки читались как ряд
одинаковых значков по кругу и рядом с рисованными проигрывали, поэтому
их убрали целиком. Модуль теперь занят другим: вырезает фон у картинок
без прозрачности, меряет просвет в середине, чтобы подогнать под него
фото, и перекрашивает рамку под фон профиля.
"""

from __future__ import annotations

import io
import math
import re
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageOps

import config

#: Итоговая аватарка. 512 — то, что Telegram принимает без пережатия.
SIZE = 512

#: Маски круга считаем крупнее и уменьшаем: без этого край рвётся.
SS = 3

#: Фоны. Первым — подарочный Black, о нём спрашивают чаще всего.
#: (имя, центр, край, акцент) — центр и край дают радиальный градиент,
#: как у подарков Telegram; акцент — цвет, в который перекрашивается
#: рамка под этот фон.
#:
#: Акцент не «светлая версия фона», а цвет, который на этом фоне ВИДНО.
#: На тёмных он светлый, на белом — наоборот тёмный: перекрась рамку в
#: светлое на белом фоне, и она исчезнет.
BACKDROPS: list[tuple[str, str, str, str]] = [
    ("Чёрный", "#3A3A40", "#0B0B0D", "#D6D8E2"),
    ("Ночь", "#3B2F6B", "#120B22", "#B49CFF"),
    ("Графит", "#5A5D66", "#232529", "#DDE1EA"),
    ("Красный", "#F08A6A", "#B0342E", "#FFC6B0"),
    ("Оранжевый", "#F7C04A", "#C25E12", "#FFDE9A"),
    ("Золото", "#F0D080", "#7A5A12", "#FFE9AE"),
    ("Зелёный", "#8FDC6A", "#1F7A2E", "#CBF5A4"),
    ("Бирюзовый", "#7FE3DC", "#136C7E", "#B6F5EE"),
    ("Синий", "#7FC4F0", "#17508F", "#B9E2FF"),
    ("Фиолетовый", "#C79BF5", "#4B2280", "#E2CCFF"),
    ("Розовый", "#FFB0C8", "#A82458", "#FFD6E2"),
    ("Белый", "#FFFFFF", "#C8CDD6", "#5C6478"),
]

#: Старое имя. Хендлеры и сборщик заставок обращаются к COLORS.
COLORS = BACKDROPS

#: Куда кладут купленные или нарисованные PNG с альфой.
CUSTOM_DIR = config.ASSETS_DIR / "frames"


def _rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def _mix(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    t = min(max(t, 0.0), 1.0)
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))  # type: ignore[return-value]


# --------------------------------------------------------------------------
# Фон
# --------------------------------------------------------------------------


def backdrop(index: int, size: int) -> Image.Image:
    """Радиальный градиент подарочного фона."""
    _, centre_hex, edge_hex, _accent = BACKDROPS[index % len(BACKDROPS)]
    centre, edge = _rgb(centre_hex), _rgb(edge_hex)
    #: Считаем на маленьком холсте и растягиваем: попиксельный радиал на
    #: 512×512 — это четверть миллиона вызовов на каждую аватарку.
    small = 96
    plate = Image.new("RGB", (small, small))
    px = plate.load()
    half = (small - 1) / 2
    for y in range(small):
        for x in range(small):
            d = math.hypot(x - half, y - half) / (half * 1.18)
            px[x, y] = _mix(centre, edge, d ** 1.25)  # type: ignore[index]
    return plate.resize((size, size), Image.BICUBIC)


def backdrop_name(index: int) -> str:
    return BACKDROPS[index % len(BACKDROPS)][0]


#: Прежнее имя для хендлеров.
color_name = backdrop_name


def _is_light(index: int) -> bool:
    """Светлый ли фон — от этого зависит цвет теней и подписей."""
    centre = _rgb(BACKDROPS[index % len(BACKDROPS)][1])
    return sum(centre) / 3 > 168


#: Насколько сильно рамка уходит в цвет фона. Не единица: при полной
#: перекраске майнкрафт-венок теряет и зелень, и фиолет, и от рисунка
#: остаётся одноцветный барельеф. 0.72 сохраняет фактуру и материал,
#: но палитра уже читается как общая с фоном.
TINT_STRENGTH = 0.72


def tint_layer(layer: Image.Image, backdrop_idx: int,
               strength: float = TINT_STRENGTH) -> Image.Image:
    """Перекрасить рамку в палитру фона, сохранив светотень.

    Работает по яркости, а не по цвету: тёмные места рисунка уходят в
    тень акцента, средние — в сам акцент, блики — почти в белый. Поэтому
    объём, тени и блики, ради которых всё и рисовалось, остаются на
    месте — меняется только палитра.
    """
    if strength <= 0:
        return layer
    accent = _rgb(BACKDROPS[backdrop_idx % len(BACKDROPS)][3])
    shadow = _mix(accent, (0, 0, 0), 0.68)
    highlight = _mix(accent, (255, 255, 255), 0.62)

    rgb = layer.convert("RGB")
    #: colorize с тремя точками: без средней тёмная и светлая половины
    #: сходятся линейно, и рамка становится плоской.
    painted = ImageOps.colorize(
        rgb.convert("L"), black=shadow, white=highlight, mid=accent
    )
    out = Image.blend(rgb, painted, strength).convert("RGBA")
    out.putalpha(layer.split()[-1])
    return out


#: Рамок, нарисованных кодом, больше нет — в карусели только файлы из
#: assets/frames и из тома с загруженными. Процедурные читались как
#: набор одинаковых значков по кругу и рядом с рисованными проигрывали
#: настолько, что держать их смысла не было.
FRAMES: list[tuple[str, object]] = []



def custom_frames() -> list[Path]:
    """Свои PNG: из репозитория и из тома с загруженными.

    Сортируем по имени, а не по папке: номер рамки в карусели не должен
    меняться от того, откуда она приехала.
    """
    found: list[Path] = []
    for folder in (CUSTOM_DIR, config.FRAMES_DIR):
        if folder.is_dir():
            found += [p for p in folder.iterdir() if p.suffix.lower() == ".png"]
    return sorted(found, key=lambda p: p.name.lower())


def frame_count() -> int:
    return len(custom_frames())


def frame_name(index: int) -> str:
    """Подпись в карусели = имя файла без служебных частей.

    Ведущие «10_» — способ задать порядок: карусель сортирует по имени,
    и без такого префикса новую рамку не поставить в конец, не
    переименовав соседние. В подписи префикс, понятно, не нужен.
    """
    stem = custom_frames()[index].stem
    stem = re.sub(r"^\d+[_\-\s]+", "", stem)
    return stem.replace("_", " ")


#: Разобранные PNG держим в памяти: иначе каждая аватарка заново читает
#: файл, вырезает фон и меряет дырку — а это десятки миллисекунд на
#: каждый показ карусели.
_custom_cache: dict[tuple[str, float, int], tuple[Image.Image, float]] = {}


def _key_out_background(img: Image.Image) -> Image.Image:
    """Убрать однотонный фон у картинки без прозрачности.

    Генераторы почти всегда отдают рамку на белом. Положить такую в
    папку как есть — значит закрыть аватарку белым квадратом, поэтому
    фон вырезаем сами.

    Цвет берём из углов, а не «белый по умолчанию»: та же рамка часто
    приходит и на чёрном. Вырезаем по всему полю, а не заливкой от края:
    у рамки прозрачной должна стать ещё и дырка в середине, а заливка
    от края внутрь кольца не попадёт.
    """
    rgb = img.convert("RGB")
    w, h = rgb.size
    corners = [rgb.getpixel(p) for p in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1))]
    spread = max(max(c) - min(c) for c in zip(*corners))
    if spread > 24:
        #: Углы разного цвета — фон не однотонный, вырезать нечего.
        return img
    bg = tuple(sum(c[i] for c in corners) // 4 for i in range(3))

    #: Порог с запасом: у пережатой картинки «белый» гуляет на пару
    #: десятков единиц, и по точному совпадению остаётся кайма.
    tolerance, band = 38, 26
    #: Считаем разницу средствами Pillow, а не циклом по пикселям:
    #: на 1024×1024 это миллион итераций на питоне против одного
    #: прохода на си.
    diff = ImageChops.difference(rgb, Image.new("RGB", (w, h), bg))
    red, green, blue = diff.split()
    distance = ImageChops.lighter(ImageChops.lighter(red, green), blue)

    def curve(value: int) -> int:
        if value <= tolerance:
            return 0
        if value >= tolerance + band:
            return 255
        #: Мягкий переход по краю: жёсткий порог оставляет пиксельную
        #: лесенку по всему контуру.
        return round(255 * (value - tolerance) / band)

    out = img.convert("RGBA")
    out.putalpha(distance.point(curve))
    return out


def _hole_radius(layer: Image.Image) -> float:
    """Доля радиуса, которую занимает прозрачная середина рамки.

    Нужна, чтобы фото не налезало на рисунок: у купленных рамок дырка
    бывает и на 40 % ширины, и на 60 %, а аватарка у нас одна на всех.
    """
    size = layer.width
    alpha = layer.split()[-1]
    px = alpha.load()
    centre = size / 2
    found: list[float] = []
    for i in range(24):
        angle = i * math.tau / 24
        dx, dy = math.cos(angle), math.sin(angle)
        for step in range(4, int(centre)):
            x, y = int(centre + dx * step), int(centre + dy * step)
            if px[x, y] > 120:
                found.append(step / centre)
                break
        else:
            found.append(1.0)
    found.sort()
    #: Медиана, а не минимум: одинокий шип, торчащий внутрь, не должен
    #: ужимать фото на всю рамку.
    return found[len(found) // 2]


def _load_custom(path: Path, size: int) -> tuple[Image.Image, float]:
    key = (str(path), path.stat().st_mtime, size)
    cached = _custom_cache.get(key)
    if cached is not None:
        return cached

    with Image.open(path) as img:
        layer = img.convert("RGBA")
        #: Если альфа везде непрозрачная, значит её просто нет.
        if layer.split()[-1].getextrema()[0] > 250:
            layer = _key_out_background(layer)
        layer = layer.resize((size, size), Image.LANCZOS)
    value = (layer, _hole_radius(layer))
    _custom_cache[key] = value
    return value


def _frame_layer(index: int, size: int) -> Image.Image:
    return _load_custom(custom_frames()[index], size)[0]


def _avatar_fraction(index: int, size: int) -> float:
    """Какую долю холста занимает фото под этой рамкой."""
    hole = _load_custom(custom_frames()[index], size)[1]
    #: _hole_radius меряет радиус в долях полуширины, а доля холста —
    #: это диаметр в долях ширины. Множитель ровно один: hole = (r / (size/2))
    #: и (2r) / size — одно и то же число.
    #: 1.06 — лёгкий нахлёст, иначе между фото и рисунком видна щель
    #: подложки. Потолок — чтобы фото не вылезло за круг Telegram.
    #: Пол — на случай декоративного колечка у самого центра: под него
    #: фото ужалось бы до марки, а лёгкий нахлёст на рисунок терпимее.
    return min(0.94, max(0.46, hole * 1.06))


# --------------------------------------------------------------------------
# Сборка
# --------------------------------------------------------------------------


def _square(photo: Image.Image, side: int) -> Image.Image:
    ratio = photo.width / photo.height
    if ratio > 1:
        new_h, new_w = side, round(side * ratio)
    else:
        new_w, new_h = side, round(side / ratio)
    photo = photo.resize((new_w, new_h), Image.LANCZOS)
    left, top = (new_w - side) // 2, (new_h - side) // 2
    return photo.crop((left, top, left + side, top + side)).convert("RGBA")


def _circle_mask(diameter: int) -> Image.Image:
    mask = Image.new("L", (diameter * SS, diameter * SS), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, diameter * SS - 1, diameter * SS - 1), fill=255)
    return mask.resize((diameter, diameter), Image.LANCZOS)


def _placeholder(side: int) -> Image.Image:
    """Силуэт вместо фото, пока человек только листает рамки."""
    plate = Image.new("RGBA", (side, side), (255, 255, 255, 34))
    draw = ImageDraw.Draw(plate)
    draw.ellipse((side * 0.32, side * 0.19, side * 0.68, side * 0.55), fill=(255, 255, 255, 96))
    draw.ellipse((side * 0.15, side * 0.61, side * 0.85, side * 1.33), fill=(255, 255, 255, 96))
    return plate.filter(ImageFilter.SMOOTH)


def _compose(photo: Image.Image | None, backdrop_idx: int, frame_idx: int,
             size: int, with_backdrop: bool = True, tint: bool = True) -> Image.Image:
    #: with_backdrop=False нужен превью: там аватарка ложится на фон
    #: самой карточки. Со своим квадратом фона её радиальный градиент не
    #: совпадает с градиентом карточки, и по краю квадрата виден шов.
    canvas = (
        backdrop(backdrop_idx, size).convert("RGBA") if with_backdrop
        else Image.new("RGBA", (size, size), (0, 0, 0, 0))
    )

    #: Размер фото подгоняется под дырку рамки. У нарисованных он 60 %,
    #: у купленных PNG считается по прозрачной середине: иначе одна
    #: рамка налезает на лицо, а вокруг другой зияет подложка.
    avatar_d = round(size * _avatar_fraction(frame_idx, size))
    inner = _square(photo, avatar_d) if photo is not None else _placeholder(avatar_d)
    inner.putalpha(_circle_mask(avatar_d))
    offset = (size - avatar_d) // 2
    canvas.alpha_composite(inner, (offset, offset))
    ring = _frame_layer(frame_idx, size)
    if tint:
        ring = tint_layer(ring, backdrop_idx)
    canvas.alpha_composite(ring)
    return canvas


def _font(size: int) -> tuple[ImageFont.FreeTypeFont | ImageFont.ImageFont, bool]:
    """Шрифт и признак «это настоящий TTF».

    Признак нужен не для красоты: встроенный запасной шрифт Pillow не
    знает кириллицы и рисует её квадратами.
    """
    font_dir = config.ASSETS_DIR / "fonts"
    if font_dir.is_dir():
        for path in sorted(font_dir.glob("*.ttf")) + sorted(font_dir.glob("*.otf")):
            try:
                return ImageFont.truetype(str(path), size), True
            except OSError:
                continue
    for name in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "DejaVuSans-Bold.ttf",
        "arialbd.ttf",
    ):
        try:
            return ImageFont.truetype(name, size), True
        except OSError:
            continue
    try:
        return ImageFont.load_default(size), False
    except TypeError:
        return ImageFont.load_default(), False


def preview(backdrop_idx: int, frame_idx: int | None, title: str,
            tint: bool = True) -> bytes:
    """Карточка «как это сядет в профиль»: фон, аватарка, имя, статус."""
    card_w, card_h = 720, 720
    card = backdrop(backdrop_idx, card_h).resize((card_w, card_h), Image.BICUBIC).convert("RGBA")

    avatar = Image.new("RGBA", (420, 420), (0, 0, 0, 0))
    if frame_idx is None:
        blank = _placeholder(round(420 * 0.60))
        blank.putalpha(_circle_mask(blank.width))
        avatar.alpha_composite(blank, (84, 84))
    else:
        avatar = _compose(None, backdrop_idx, frame_idx, 420,
                          with_backdrop=False, tint=tint)
    card.alpha_composite(avatar, ((card_w - 420) // 2, 84))

    draw = ImageDraw.Draw(card)
    light = _is_light(backdrop_idx)
    ink = (20, 22, 28) if light else (255, 255, 255)
    label, real = _font(46)
    draw.text((card_w / 2, 566), title, font=label, fill=ink + (255,), anchor="mm")
    if real:
        sub, _ = _font(28)
        draw.text((card_w / 2, 614), "был(а) недавно", font=sub,
                  fill=ink + (170,), anchor="mm")

    buf = io.BytesIO()
    card.convert("RGB").save(buf, format="JPEG", quality=92, optimize=True)
    return buf.getvalue()


def apply(photo_data: bytes, backdrop_idx: int, frame_idx: int,
          tint: bool = True) -> bytes:
    """Готовая аватарка: фото в круге, венок вокруг, фон профиля в углах."""
    with Image.open(io.BytesIO(photo_data)) as src:
        result = _compose(src.convert("RGB"), backdrop_idx, frame_idx, SIZE, tint=tint)
    buf = io.BytesIO()
    #: PNG: у аватарки видно каждый артефакт по краю венка.
    result.convert("RGB").save(buf, format="PNG", optimize=True)
    return buf.getvalue()
