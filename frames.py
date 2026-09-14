"""Рамки для аватарки: венок вокруг фото на цвете профиля.

Почему сначала спрашиваем цвет. Telegram обрезает аватарку по кругу, а
вокруг неё в профиле — фон выбранного человеком акцентного цвета. Если
залить углы картинки чем попало, венок будет висеть на чужом квадрате.
Поэтому рамка рисуется внутри вписанной окружности, а всё за её
пределами заливается тем же цветом, что и профиль, — и стык не виден.

Рамки рисуются кодом, а не лежат картинками. Причина простая: набор из
двух десятков PNG с прозрачностью — это отдельная папка ассетов, которую
надо тащить в каждый деплой и держать в одном стиле. Параметрический
венок даёт тот же результат и бесплатно масштабируется под любой размер.
Если нужны именно нарисованные рамки — положи PNG с альфой в
assets/frames/, они подхватятся поверх процедурных.
"""

from __future__ import annotations

import io
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

import config

#: Итоговая аватарка. 640 — то, что Telegram принимает без пережатия и
#: чего хватает на любой экран.
SIZE = 640

#: Рисуем крупнее и уменьшаем: у ImageDraw нет сглаживания, а венок из
#: сотни мелких фигур без него выглядит рваным.
SS = 3

#: Акцентные цвета профиля Telegram — фон, на котором живёт аватарка.
COLORS: list[tuple[str, str, str]] = [
    ("Красный", "#E15052", "#F9AE63"),
    ("Оранжевый", "#E0802B", "#FAC534"),
    ("Фиолетовый", "#A05FF3", "#C867F0"),
    ("Зелёный", "#27A910", "#A7DC57"),
    ("Бирюзовый", "#27ACCE", "#82E8D6"),
    ("Синий", "#3391D4", "#7DD3F0"),
    ("Розовый", "#DD4371", "#FFBE9F"),
    ("Графит", "#3A3B42", "#6C6E77"),
    ("Ночь", "#1F1D3B", "#4A2E6B"),
    ("Золото", "#8A6A1E", "#E8C56A"),
]

#: Каждая рамка — мотив, число повторов по кругу и своя палитра.
#: Палитра у рамки собственная: золотой венок обязан остаться золотым на
#: любом фоне профиля, иначе выбор цвета превращается в перекраску всего
#: подряд и все двадцать пять вариантов сливаются в один.
FRAMES: list[dict] = [
    {"name": "Жемчуг", "motif": "bead", "count": 36, "ring": "thin", "colors": ("#FFFFFF", "#D8D8E0")},
    {"name": "Шипы", "motif": "spike", "count": 28, "ring": "thin", "colors": ("#C0392B", "#7B1E12")},
    {"name": "Ромбы", "motif": "diamond", "count": 24, "ring": "double", "colors": ("#F1C40F", "#B8860B")},
    {"name": "Лепестки", "motif": "petal", "count": 18, "ring": "none", "colors": ("#FF7EB6", "#D6336C")},
    {"name": "Сердца", "motif": "heart", "count": 16, "ring": "none", "colors": ("#FF4D6D", "#B3123C")},
    {"name": "Звёзды", "motif": "star", "count": 14, "ring": "thin", "colors": ("#FFD166", "#E8A33D")},
    {"name": "Клинки", "motif": "blade", "count": 20, "ring": "thin", "colors": ("#8E44AD", "#4A235A")},
    {"name": "Волна", "motif": "scallop", "count": 26, "ring": "thin", "colors": ("#48C9B0", "#148F77")},
    {"name": "Листья", "motif": "leaf", "count": 22, "ring": "none", "colors": ("#58D68D", "#1E8449")},
    {"name": "Искры", "motif": "sparkle", "count": 12, "ring": "dashed", "colors": ("#FFFFFF", "#9AD0FF")},
    {"name": "Корона", "motif": "spike", "count": 12, "ring": "double", "colors": ("#FFD700", "#8A6D1E")},
    {"name": "Кристаллы", "motif": "diamond", "count": 16, "ring": "none", "colors": ("#7FDBFF", "#2E86C1")},
    {"name": "Роса", "motif": "bead", "count": 52, "ring": "none", "colors": ("#AEE8FF", "#3B8EA5")},
    {"name": "Пламя", "motif": "blade", "count": 30, "ring": "none", "colors": ("#FF8C42", "#C0392B")},
    {"name": "Иней", "motif": "sparkle", "count": 18, "ring": "thin", "colors": ("#DFF6FF", "#7FB3D5")},
    {"name": "Терновник", "motif": "spike", "count": 40, "ring": "double", "colors": ("#4A235A", "#1B1B1B")},
    {"name": "Ромашки", "motif": "petal", "count": 12, "ring": "none", "colors": ("#FFFFFF", "#F4D03F")},
    {"name": "Витраж", "motif": "diamond", "count": 30, "ring": "double", "colors": ("#BB8FCE", "#5B2C6F")},
    {"name": "Монеты", "motif": "bead", "count": 20, "ring": "double", "colors": ("#F5C542", "#9C6B1E")},
    {"name": "Перья", "motif": "leaf", "count": 30, "ring": "thin", "colors": ("#D5DBDB", "#85929E")},
    {"name": "Шторм", "motif": "scallop", "count": 18, "ring": "double", "colors": ("#5DADE2", "#154360")},
    {"name": "Сакура", "motif": "petal", "count": 24, "ring": "thin", "colors": ("#FFC2D1", "#E75480")},
    {"name": "Неон", "motif": "sparkle", "count": 24, "ring": "thin", "colors": ("#39FF14", "#0B6623")},
    {"name": "Рубины", "motif": "heart", "count": 24, "ring": "thin", "colors": ("#E01E5A", "#6E0B28")},
    {"name": "Минимал", "motif": "none", "count": 0, "ring": "double", "colors": ("#FFFFFF", "#B0B0B0")},
]

#: Куда кладут настоящие PNG с альфой, если процедурных мало.
CUSTOM_DIR = config.ASSETS_DIR / "frames"


def _rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def custom_frames() -> list[Path]:
    """PNG из assets/frames — по алфавиту, чтобы номера не прыгали."""
    if not CUSTOM_DIR.is_dir():
        return []
    return sorted(p for p in CUSTOM_DIR.iterdir() if p.suffix.lower() == ".png")


def frame_count() -> int:
    return len(FRAMES) + len(custom_frames())


def frame_name(index: int) -> str:
    files = custom_frames()
    if index < len(FRAMES):
        return FRAMES[index]["name"]
    return files[index - len(FRAMES)].stem


def color_name(index: int) -> str:
    return COLORS[index % len(COLORS)][0]


# --------------------------------------------------------------------------
# Рисование
# --------------------------------------------------------------------------


def _gradient(size: int, top: str, bottom: str) -> Image.Image:
    """Вертикальная растяжка двух цветов — так же, как в профиле."""
    strip = Image.new("RGB", (1, size))
    a, b = _rgb(top), _rgb(bottom)
    px = strip.load()
    for y in range(size):
        t = y / max(size - 1, 1)
        px[0, y] = tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))  # type: ignore[assignment]
    return strip.resize((size, size), Image.BILINEAR)


def _motif(kind: str, radius: float, scale: float) -> list[tuple[float, float]]:
    """Контур одной фигуры вокруг точки (0, 0), носом вверх."""
    r = radius * scale
    if kind == "bead":
        return [(r * math.cos(a), r * math.sin(a)) for a in
                (i * math.tau / 16 for i in range(16))]
    if kind == "spike":
        return [(-r * 0.42, r * 0.7), (0.0, -r * 1.5), (r * 0.42, r * 0.7)]
    if kind == "blade":
        return [(-r * 0.3, r * 0.8), (-r * 0.12, -r * 1.7), (r * 0.12, -r * 1.7), (r * 0.3, r * 0.8)]
    if kind == "diamond":
        return [(0.0, -r * 1.3), (r * 0.7, 0.0), (0.0, r * 1.3), (-r * 0.7, 0.0)]
    if kind == "petal":
        pts = []
        for i in range(20):
            a = i * math.tau / 20
            pts.append((r * 0.62 * math.sin(a), -r * 1.25 * (1 - math.cos(a)) / 2 - r * 0.1))
        return pts
    if kind == "leaf":
        pts = []
        for i in range(21):
            t = i / 20
            pts.append((r * 0.55 * math.sin(t * math.pi), -r * 1.6 * t + r * 0.5))
        for i in range(21):
            t = 1 - i / 20
            pts.append((-r * 0.55 * math.sin(t * math.pi), -r * 1.6 * t + r * 0.5))
        return pts
    if kind == "heart":
        pts = []
        for i in range(30):
            t = i * math.tau / 30
            x = 16 * math.sin(t) ** 3
            y = -(13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t))
            pts.append((x * r / 16, y * r / 16))
        return pts
    if kind == "star":
        pts = []
        for i in range(10):
            rad = r * (1.4 if i % 2 == 0 else 0.6)
            a = -math.pi / 2 + i * math.pi / 5
            pts.append((rad * math.cos(a), rad * math.sin(a)))
        return pts
    if kind == "sparkle":
        pts = []
        for i in range(8):
            rad = r * (1.6 if i % 2 == 0 else 0.28)
            a = -math.pi / 2 + i * math.pi / 4
            pts.append((rad * math.cos(a), rad * math.sin(a)))
        return pts
    if kind == "scallop":
        return [(r * 0.9 * math.cos(a), r * 0.9 * math.sin(a) - r * 0.3)
                for a in (i * math.tau / 14 for i in range(14))]
    return []


def _draw_frame(spec: dict, canvas_size: int) -> Image.Image:
    """Венок с прозрачным центром — его потом кладут поверх аватарки."""
    big = canvas_size * SS
    layer = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)

    centre = big / 2
    #: Радиус подобран так, чтобы самый длинный мотив (клинок, 1.7
    #: радиуса от своей оси) уложился внутрь вписанной окружности:
    #: Telegram обрежет аватарку по ней, и всё, что вылезло, исчезнет.
    ring_r = big * 0.365
    main, dark = _rgb(spec["colors"][0]), _rgb(spec["colors"][1])

    width = max(2, round(big * 0.012))
    if spec["ring"] == "thin":
        draw.ellipse(_box(centre, ring_r), outline=dark + (235,), width=width)
    elif spec["ring"] == "double":
        draw.ellipse(_box(centre, ring_r * 0.955), outline=dark + (235,), width=width)
        draw.ellipse(_box(centre, ring_r * 1.06), outline=main + (200,), width=max(1, width // 2))
    elif spec["ring"] == "dashed":
        step = math.tau / 48
        for i in range(48):
            if i % 2:
                continue
            a0, a1 = math.degrees(i * step), math.degrees(i * step + step * 0.9)
            draw.arc(_box(centre, ring_r), a0, a1, fill=dark + (235,), width=width)

    count = int(spec["count"])
    motif_r = big * (0.05 if count > 20 else 0.072)
    for i in range(count):
        angle = i * math.tau / count - math.pi / 2
        cx = centre + ring_r * math.cos(angle)
        cy = centre + ring_r * math.sin(angle)
        #: Каждую вторую фигуру красим тёмным и делаем чуть мельче —
        #: ровный ряд одинаковых значков читается как рамка из клипарта,
        #: а чередование даёт вид плетения.
        colour = main if i % 2 == 0 else dark
        scale = 1.0 if i % 2 == 0 else 0.78
        shape = _motif(spec["motif"], motif_r, scale)
        if not shape:
            break
        rot = angle + math.pi / 2
        cos_r, sin_r = math.cos(rot), math.sin(rot)
        pts = [
            (cx + x * cos_r - y * sin_r, cy + x * sin_r + y * cos_r) for x, y in shape
        ]
        draw.polygon(pts, fill=colour + (255,))

    return layer.resize((canvas_size, canvas_size), Image.LANCZOS)


def _box(centre: float, radius: float) -> tuple[float, float, float, float]:
    return (centre - radius, centre - radius, centre + radius, centre + radius)


def _frame_layer(index: int, canvas_size: int) -> Image.Image:
    files = custom_frames()
    if index >= len(FRAMES):
        with Image.open(files[index - len(FRAMES)]) as img:
            return img.convert("RGBA").resize((canvas_size, canvas_size), Image.LANCZOS)
    return _draw_frame(FRAMES[index], canvas_size)


def _circle(photo: Image.Image, diameter: int) -> Image.Image:
    """Фото, обрезанное в круг, — так же, как его покажет Telegram."""
    src_ratio = photo.width / photo.height
    if src_ratio > 1:
        new_h, new_w = diameter, round(diameter * src_ratio)
    else:
        new_w, new_h = diameter, round(diameter / src_ratio)
    photo = photo.resize((new_w, new_h), Image.LANCZOS)
    photo = photo.crop(
        ((new_w - diameter) // 2, (new_h - diameter) // 2,
         (new_w - diameter) // 2 + diameter, (new_h - diameter) // 2 + diameter)
    )
    mask = Image.new("L", (diameter * SS, diameter * SS), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, diameter * SS - 1, diameter * SS - 1), fill=255)
    photo.putalpha(mask.resize((diameter, diameter), Image.LANCZOS))
    return photo


def _placeholder(diameter: int) -> Image.Image:
    """Заглушка вместо фото, пока человек только листает рамки."""
    plate = Image.new("RGBA", (diameter, diameter), (0, 0, 0, 0))
    draw = ImageDraw.Draw(plate)
    draw.ellipse((0, 0, diameter - 1, diameter - 1), fill=(255, 255, 255, 38))
    draw.ellipse(
        (diameter * 0.32, diameter * 0.2, diameter * 0.68, diameter * 0.56),
        fill=(255, 255, 255, 90),
    )
    draw.ellipse(
        (diameter * 0.16, diameter * 0.6, diameter * 0.84, diameter * 1.3),
        fill=(255, 255, 255, 90),
    )
    return plate.filter(ImageFilter.SMOOTH)


def _compose(photo: Image.Image | None, color_idx: int, frame_idx: int, size: int) -> Image.Image:
    _, top, bottom = COLORS[color_idx % len(COLORS)]
    canvas = _gradient(size, top, bottom).convert("RGBA")

    avatar_d = round(size * 0.60)
    inner = _circle(photo, avatar_d) if photo is not None else _placeholder(avatar_d)
    offset = (size - avatar_d) // 2
    canvas.alpha_composite(inner, (offset, offset))
    canvas.alpha_composite(_frame_layer(frame_idx, size))
    return canvas


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for name in ("DejaVuSans-Bold.ttf", "arialbd.ttf", "Arial Bold.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def preview(color_idx: int, frame_idx: int | None, title: str) -> bytes:
    """Карточка «как это будет выглядеть в профиле».

    Показываем не голую рамку, а кусок профиля целиком: без имени и
    подписи под ним рамка висит в воздухе, и понять, налезает она на
    аватарку или нет, невозможно.
    """
    card_w, card_h = 720, 720
    _, top, bottom = COLORS[color_idx % len(COLORS)]
    card = _gradient(card_h, top, bottom).resize((card_w, card_h), Image.BILINEAR).convert("RGBA")
    #: Затемняем фон карточки, чтобы сама аватарка читалась как объект,
    #: а не как пятно того же цвета.
    card.alpha_composite(Image.new("RGBA", (card_w, card_h), (0, 0, 0, 70)))

    avatar = _compose(None, color_idx, frame_idx, 420) if frame_idx is not None else None
    if avatar is None:
        avatar = Image.new("RGBA", (420, 420), (0, 0, 0, 0))
        avatar.alpha_composite(_placeholder(round(420 * 0.60)), (84, 84))
    card.alpha_composite(avatar, ((card_w - 420) // 2, 90))

    draw = ImageDraw.Draw(card)
    label = _font(44)
    sub = _font(28)
    draw.text((card_w / 2, 560), title, font=label, fill=(255, 255, 255, 255), anchor="mm")
    draw.text((card_w / 2, 610), "был(а) недавно", font=sub, fill=(255, 255, 255, 170), anchor="mm")

    buf = io.BytesIO()
    card.convert("RGB").save(buf, format="JPEG", quality=92, optimize=True)
    return buf.getvalue()


def apply(photo_data: bytes, color_idx: int, frame_idx: int) -> bytes:
    """Готовая аватарка: фото в круге, венок вокруг, цвет профиля в углах."""
    with Image.open(io.BytesIO(photo_data)) as src:
        photo = src.convert("RGB")
        result = _compose(photo, color_idx, frame_idx, SIZE)
    buf = io.BytesIO()
    #: PNG, а не JPEG: у аватарки видно каждый артефакт по краю венка, а
    #: 640×640 весит немного даже без потерь.
    result.convert("RGB").save(buf, format="PNG", optimize=True)
    return buf.getvalue()
