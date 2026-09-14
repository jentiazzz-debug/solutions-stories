"""Рамки для аватарки: венок вокруг фото на фоне твоего профиля.

Почему фон выбирается отдельно. Telegram обрезает аватарку по кругу, а
вокруг неё в профиле — либо акцентный цвет, либо фон коллекционного
подарка (Black, Chill Flame, Vice Cream…). Прозрачность в аватарке не
живёт: Telegram сводит её на чёрное. Значит углы картинки надо залить
ровно тем, что стоит у человека в профиле, — тогда рамка выглядит частью
интерфейса, а не наклейкой поверх.

Фоны подарков — радиальные: центр светлее краёв. Обычный линейный
градиент на их месте сразу выдаёт подделку, поэтому здесь тоже радиал.

Почему рамки нарисованы, а не разложены по кругу. Двадцать одинаковых
значков через равные углы читаются как клипарт — это и была главная
беда прошлой версии. Дорого выглядит другое: разный размер элементов,
несимметричные сгущения, тень под элементом и блик сверху. Здесь каждая
рамка — отдельная функция рисования, а не строчка в таблице.
"""

from __future__ import annotations

import io
import math
import random
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

import config

#: Итоговая аватарка. 512 — то, что Telegram принимает без пережатия.
SIZE = 512

#: Рисуем крупнее и уменьшаем: без этого лепестки и блики рвутся.
SS = 3

#: Фоны. Первым — подарочный Black, о нём спрашивают чаще всего.
#: (имя, центр, край) — радиальный градиент, как у подарков Telegram.
BACKDROPS: list[tuple[str, str, str]] = [
    ("Чёрный", "#3A3A40", "#0B0B0D"),
    ("Ночь", "#3B2F6B", "#120B22"),
    ("Графит", "#5A5D66", "#232529"),
    ("Красный", "#F08A6A", "#B0342E"),
    ("Оранжевый", "#F7C04A", "#C25E12"),
    ("Золото", "#F0D080", "#7A5A12"),
    ("Зелёный", "#8FDC6A", "#1F7A2E"),
    ("Бирюзовый", "#7FE3DC", "#136C7E"),
    ("Синий", "#7FC4F0", "#17508F"),
    ("Фиолетовый", "#C79BF5", "#4B2280"),
    ("Розовый", "#FFB0C8", "#A82458"),
    ("Белый", "#FFFFFF", "#C8CDD6"),
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
    _, centre_hex, edge_hex = BACKDROPS[index % len(BACKDROPS)]
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


# --------------------------------------------------------------------------
# Кисти
# --------------------------------------------------------------------------


def _poly(draw: ImageDraw.ImageDraw, pts, fill) -> None:
    draw.polygon([(float(x), float(y)) for x, y in pts], fill=fill)


def _rotate(pts, angle: float, cx: float, cy: float):
    cos_a, sin_a = math.cos(angle), math.sin(angle)
    return [(cx + x * cos_a - y * sin_a, cy + x * sin_a + y * cos_a) for x, y in pts]


def _leaf_shape(length: float, width: float, tilt: float = 0.0):
    """Лист: две дуги, сходящиеся в остриё. Ассиметричный — так живее."""
    pts = []
    steps = 22
    for i in range(steps + 1):
        t = i / steps
        pts.append((width * math.sin(t * math.pi) * (1 - 0.25 * t), -length * t))
    for i in range(steps + 1):
        t = 1 - i / steps
        pts.append((-width * math.sin(t * math.pi) * (1 + tilt * t), -length * t))
    return pts


def _petal_shape(length: float, width: float):
    pts = []
    for i in range(26):
        t = i / 25
        pts.append((width * math.sin(t * math.pi), -length * t))
    for i in range(26):
        t = 1 - i / 25
        pts.append((-width * math.sin(t * math.pi), -length * t))
    return pts


def _star_shape(outer: float, inner: float, points: int = 4):
    pts = []
    for i in range(points * 2):
        r = outer if i % 2 == 0 else inner
        a = -math.pi / 2 + i * math.pi / points
        pts.append((r * math.cos(a), r * math.sin(a)))
    return pts


def _heart_shape(r: float):
    pts = []
    for i in range(34):
        t = i * math.tau / 34
        x = 16 * math.sin(t) ** 3
        y = -(13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t))
        pts.append((x * r / 16, y * r / 16))
    return pts


def _shard_shape(length: float, width: float):
    return [(0, -length), (width, -length * 0.35), (width * 0.55, length * 0.3),
            (0, length * 0.5), (-width * 0.55, length * 0.3), (-width, -length * 0.35)]


class Wreath:
    """Холст одной рамки: тень снизу, элемент, блик сверху, свечение."""

    def __init__(self, size: int) -> None:
        self.big = size * SS
        self.centre = self.big / 2
        self.ring = self.big * 0.372
        self.layer = Image.new("RGBA", (self.big, self.big), (0, 0, 0, 0))
        self.shadow = Image.new("RGBA", (self.big, self.big), (0, 0, 0, 0))
        self.glow = Image.new("RGBA", (self.big, self.big), (0, 0, 0, 0))
        self.draw = ImageDraw.Draw(self.layer)
        self.sdraw = ImageDraw.Draw(self.shadow)
        self.gdraw = ImageDraw.Draw(self.glow)

    def at(self, angle: float, radius: float | None = None) -> tuple[float, float]:
        r = self.ring if radius is None else radius
        return self.centre + r * math.cos(angle), self.centre + r * math.sin(angle)

    def piece(self, pts, angle: float, cx: float, cy: float, fill,
              shade=None, shine=None, glow=None) -> None:
        """Один элемент со всей обвязкой.

        Тень кладётся со смещением вниз-вправо, блик — уменьшенной
        копией вверх-влево. Без этой пары фигура остаётся плоской
        заливкой, сколько её ни раскрашивай.
        """
        body = _rotate(pts, angle, cx, cy)
        if shade is not None:
            off = self.big * 0.006
            _poly(self.sdraw, [(x + off, y + off) for x, y in body], shade)
        if glow is not None:
            _poly(self.gdraw, body, glow)
        _poly(self.draw, body, fill)
        if shine is not None:
            small = [(x * 0.55, y * 0.55 - self.big * 0.004) for x, y in pts]
            _poly(self.draw, _rotate(small, angle, cx, cy), shine)

    def finish(self) -> Image.Image:
        out = Image.new("RGBA", (self.big, self.big), (0, 0, 0, 0))
        out.alpha_composite(self.shadow.filter(ImageFilter.GaussianBlur(self.big * 0.012)))
        out.alpha_composite(self.glow.filter(ImageFilter.GaussianBlur(self.big * 0.030)))
        out.alpha_composite(self.glow.filter(ImageFilter.GaussianBlur(self.big * 0.009)))
        out.alpha_composite(self.layer)
        return out.resize((self.big // SS, self.big // SS), Image.LANCZOS)


# --------------------------------------------------------------------------
# Рамки
# --------------------------------------------------------------------------
#
# У каждой — своя логика раскладки. Равномерный шаг используется только
# там, где он оправдан (жемчуг, цепь); остальные собраны сгущениями.

SHADE = (0, 0, 0, 120)


def _laurel(w: Wreath) -> Image.Image:
    """Лавр: сплошная лента листьев в два слоя.

    Плотность здесь важнее рисунка отдельного листа. Пока между
    элементами есть зазор, глаз видит ряд значков; как только соседи
    перекрываются, лента читается одним предметом — венком.
    """
    gold, dark, shine = (240, 206, 126), (128, 94, 30), (255, 242, 200)
    count = 46
    for layer in (0, 1):
        back = layer == 0
        radius = w.ring * (1.055 if back else 0.985)
        scale = 0.86 if back else 1.0
        #: Задний слой сдвинут на полшага — стыки переднего ряда
        #: закрываются, и просветов в ленте не остаётся.
        shift = math.pi / count if back else 0.0
        for i in range(count):
            angle = i * math.tau / count + shift
            cx, cy = w.at(angle, radius)
            length = w.big * 0.098 * scale
            leaf = _leaf_shape(length, length * 0.27, tilt=0.16)
            colour = _mix(gold, dark, 0.62 if back else 0.10)
            w.piece(leaf, angle + math.pi / 2 + 0.46, cx, cy, colour + (255,),
                    shade=None if back else SHADE,
                    shine=None if back else shine + (95,))
    return w.finish()


def _neon(w: Wreath) -> Image.Image:
    """Неон: широкое свечение, тонкое ядро, разрыв сверху."""
    tint = (90, 240, 255)
    box = (w.centre - w.ring, w.centre - w.ring, w.centre + w.ring, w.centre + w.ring)
    w.gdraw.arc(box, 108, 72, fill=tint + (255,), width=round(w.big * 0.030))
    w.draw.arc(box, 108, 72, fill=tint + (235,), width=round(w.big * 0.016))
    w.draw.arc(box, 108, 72, fill=(255, 255, 255, 240), width=round(w.big * 0.005))
    for angle in (108 * math.pi / 180, 72 * math.pi / 180):
        cx, cy = w.at(angle)
        r = w.big * 0.012
        w.draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(255, 255, 255, 240))
        w.gdraw.ellipse((cx - r * 2, cy - r * 2, cx + r * 2, cy + r * 2), fill=tint + (255,))
    return w.finish()


def _chain(w: Wreath) -> Image.Image:
    """Цепь: звенья-трубки, соседние развёрнуты и заходят друг на друга.

    Звено рисуется не контуром эллипса, а цепочкой кружков по его
    траектории: контур даёт плоское кольцо, а кружки с меняющейся
    яркостью читаются как круглый металлический пруток.
    """
    steel, dark = (232, 236, 246), (92, 98, 114)
    #: 16 звеньев при этом радиусе стояли с просветами — цепь
    #: рассыпалась на отдельные колечки.
    count = 26
    tube = w.big * 0.0080
    for i in range(count):
        angle = i * math.tau / count
        #: Нечётные звенья чуть ближе к центру — тогда соседние
        #: перекрываются, и цепь перестаёт быть рядом отдельных колец.
        cx, cy = w.at(angle, w.ring * (1.0 if i % 2 == 0 else 0.972))
        flat = i % 2 == 0
        rx = w.big * (0.046 if flat else 0.027)
        ry = w.big * (0.027 if flat else 0.046)
        spin = angle + math.pi / 2
        cos_s, sin_s = math.cos(spin), math.sin(spin)
        for k in range(40):
            a = k * math.tau / 40
            lx, ly = rx * math.cos(a), ry * math.sin(a)
            px = cx + lx * cos_s - ly * sin_s
            py = cy + lx * sin_s + ly * cos_s
            #: Свет сверху-слева: по верхней дуге пруток светлее.
            lit = 0.5 - 0.5 * math.cos(a - spin - math.pi / 4)
            colour = _mix(dark, steel, lit)
            w.sdraw.ellipse((px - tube + w.big * 0.004, py - tube + w.big * 0.004,
                             px + tube + w.big * 0.004, py + tube + w.big * 0.004), fill=SHADE)
            w.draw.ellipse((px - tube, py - tube, px + tube, py + tube), fill=colour + (255,))
    return w.finish()


def _flame(w: Wreath) -> Image.Image:
    """Пламя: языки снизу, выше — короче и бледнее, всё в свечении."""
    rng = random.Random(3)
    for i in range(52):
        t = i / 51
        #: Языки гуще внизу: пламя не окружает голову равномерно.
        angle = math.pi / 2 + (t - 0.5) * math.tau * 0.88
        spread = abs(math.sin(angle))
        cx, cy = w.at(angle, w.ring * (0.97 + 0.05 * rng.random()))
        length = w.big * (0.050 + 0.095 * spread) * rng.uniform(0.72, 1.28)
        #: Кончик уводим вбок случайной стороной: симметричный язычок —
        #: это лепесток, а пламя кривое.
        bend = rng.uniform(-0.42, 0.42) * length
        tongue = [(bend, -length), (w.big * 0.019, -length * 0.42),
                  (w.big * 0.012, length * 0.20), (0, length * 0.30),
                  (-w.big * 0.012, length * 0.20), (-w.big * 0.019, -length * 0.42)]
        hot = _mix((255, 236, 150), (222, 58, 20), (1 - spread) * rng.uniform(0.6, 1.1))
        w.piece(tongue, angle + math.pi / 2 + rng.uniform(-0.12, 0.12), cx, cy, hot + (245,),
                glow=(255, 130, 40, 150),
                shine=(255, 248, 210, 130))
    return w.finish()


def _sakura(w: Wreath) -> Image.Image:
    """Сакура: три грозди разного размера, между ними — редкие цветки."""
    pink, deep, heart = (255, 216, 228), (222, 100, 146), (255, 226, 130)
    rng = random.Random(7)
    #: Сомкнутая лента цветов: 22 штуки при таком размере лепестка
    #: перекрываются, и венок становится венком. Размер всё равно гуляет
    #: — ровные одинаковые цветы выглядят штампом.
    count = 22
    for layer in (0, 1):
        back = layer == 0
        for i in range(count):
            angle = (i + (0.5 if back else 0.0)) * math.tau / count
            cx, cy = w.at(angle, w.ring * (1.055 if back else 0.98))
            petal_len = w.big * (0.044 if back else 0.056) * rng.uniform(0.86, 1.14)
            for k in range(5):
                spin = angle + k * math.tau / 5 + rng.uniform(-0.1, 0.1)
                w.piece(_petal_shape(petal_len, petal_len * 0.48), spin, cx, cy,
                        _mix(pink, deep, (0.55 if back else 0.12) + 0.3 * rng.random()) + (250,),
                        shade=None if back else SHADE)
            if not back:
                r = petal_len * 0.22
                w.draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=heart + (255,))
    return w.finish()


def _stardust(w: Wreath) -> Image.Image:
    """Звёздная пыль: крупные искры сгущаются к правому верху."""
    rng = random.Random(21)
    #: Сомкнутое кольцо из трёх рядов, а не россыпь по площади. Россыпь
    #: и была тем самым «накиданными символами»: у неё нет края, поэтому
    #: она не читается как рамка.
    for radius_mul, count, lo, hi in ((1.075, 26, 0.020, 0.034),
                                      (1.0, 22, 0.038, 0.062),
                                      (0.935, 26, 0.018, 0.030)):
        for i in range(count):
            angle = i * math.tau / count + rng.uniform(-0.04, 0.04)
            cx, cy = w.at(angle, w.ring * radius_mul * rng.uniform(0.985, 1.015))
            outer = w.big * rng.uniform(lo, hi)
            w.piece(_star_shape(outer, outer * 0.15), rng.uniform(0, 1.5), cx, cy,
                    (255, 255, 255, 250), glow=(150, 220, 255, 170))
    return w.finish()


def _thorns(w: Wreath) -> Image.Image:
    """Терновник: изогнутые шипы, каждый со светлой кромкой."""
    dark, edge = (38, 22, 48), (150, 96, 190)
    #: Плотный частокол: шипы должны касаться основаниями.
    count = 66
    for i in range(count):
        angle = i * math.tau / count
        cx, cy = w.at(angle, w.ring * (1.03 if i % 2 else 0.97))
        long_one = i % 3 == 0
        length = w.big * (0.105 if long_one else 0.062)
        bend = 0.30 if i % 2 else -0.30
        spike = [(0, -length), (w.big * 0.021, -length * 0.25),
                 (w.big * 0.010 + bend * w.big * 0.02, length * 0.16),
                 (-w.big * 0.010 + bend * w.big * 0.02, length * 0.16),
                 (-w.big * 0.021, -length * 0.25)]
        w.piece(spike, angle + math.pi / 2 + bend * 0.5, cx, cy, dark + (255,),
                shade=SHADE, shine=edge + (120,))
    return w.finish()


def _pearls(w: Wreath) -> Image.Image:
    """Жемчуг: крупные и мелкие вперемешку, у каждой бусины блик."""
    base, deep = (255, 252, 248), (168, 162, 180)
    #: Два сомкнутых ряда: нижний виден в просветах верхнего, поэтому
    #: нитка выглядит нитью, а не пунктиром из точек.
    for radius_mul, r_mul, count, shift in ((1.050, 0.020, 34, 0.5), (0.985, 0.027, 30, 0.0)):
        for i in range(count):
            angle = (i + shift) * math.tau / count
            r = w.big * r_mul
            cx, cy = w.at(angle, w.ring * radius_mul)
            w.sdraw.ellipse((cx - r + w.big * 0.005, cy - r + w.big * 0.005,
                             cx + r + w.big * 0.005, cy + r + w.big * 0.005), fill=SHADE)
            w.draw.ellipse((cx - r, cy - r, cx + r, cy + r),
                           fill=_mix(base, deep, 0.50 if r_mul < 0.024 else 0.18) + (255,))
            #: Блик смещён в одну сторону у всех бусин — иначе свет
            #: выглядит приходящим отовсюду, и объём пропадает.
            hr = r * 0.34
            hx, hy = cx - r * 0.34, cy - r * 0.36
            w.draw.ellipse((hx - hr, hy - hr, hx + hr, hy + hr), fill=(255, 255, 255, 230))
    return w.finish()


def _ice(w: Wreath) -> Image.Image:
    """Лёд: осколки разной длины, полупрозрачные, с белой кромкой."""
    rng = random.Random(4)
    tint = (196, 238, 255)
    for i in range(34):
        angle = i * math.tau / 34 + rng.uniform(-0.05, 0.05)
        cx, cy = w.at(angle, w.ring * 0.99)
        length = w.big * rng.uniform(0.055, 0.115)
        shard = _shard_shape(length, w.big * 0.022)
        w.piece(shard, angle + math.pi / 2, cx, cy, tint + (185,),
                glow=(120, 210, 255, 110), shine=(255, 255, 255, 210))
    return w.finish()


def _hearts(w: Wreath) -> Image.Image:
    """Сердца: гроздь слева внизу и редкая россыпь по остальному кругу."""
    rng = random.Random(11)
    warm, deep = (255, 126, 162), (188, 24, 80)
    for layer in (0, 1):
        back = layer == 0
        count = 26
        for i in range(count):
            angle = (i + (0.5 if back else 0.0)) * math.tau / count
            cx, cy = w.at(angle, w.ring * (1.055 if back else 0.98))
            r = w.big * (0.036 if back else 0.048) * rng.uniform(0.88, 1.12)
            w.piece(_heart_shape(r), angle + math.pi / 2 + rng.uniform(-0.18, 0.18), cx, cy,
                    _mix(warm, deep, (0.62 if back else 0.10) + 0.25 * rng.random()) + (250,),
                    shade=None if back else SHADE,
                    shine=None if back else (255, 220, 232, 130),
                    glow=(255, 90, 140, 70))
    return w.finish()


def _crown(w: Wreath) -> Image.Image:
    """Корона: обод и зубцы на одной верхней дуге, камни в основаниях.

    Обод и зубцы обязаны жить на одном участке круга. В прошлой версии
    дуга рисовалась снизу, а зубцы ставились сверху — корона разъезжалась
    на улыбку и отдельно висящие треугольники.
    """
    gold, dark, gem = (245, 208, 110), (152, 108, 30), (120, 200, 255)
    start, end = math.radians(203), math.radians(337)
    box = (w.centre - w.ring, w.centre - w.ring, w.centre + w.ring, w.centre + w.ring)
    w.draw.arc(box, 203, 337, fill=_mix(gold, dark, 0.30) + (255,), width=round(w.big * 0.014))
    for i in range(7):
        t = i / 6
        angle = start + t * (end - start)
        cx, cy = w.at(angle)
        #: Центральный зубец выше боковых — иначе это забор, а не корона.
        tall = w.big * (0.120 if i == 3 else (0.090 if i in (2, 4) else 0.062))
        spike = [(0, -tall), (w.big * 0.027, 0), (-w.big * 0.027, 0)]
        w.piece(spike, angle + math.pi / 2, cx, cy, gold + (255,),
                shade=SHADE, shine=(255, 244, 200, 150))
        gx, gy = w.at(angle, w.ring - w.big * 0.004)
        r = w.big * 0.014
        w.draw.ellipse((gx - r, gy - r, gx + r, gy + r), fill=gem + (250,))
        w.gdraw.ellipse((gx - r * 2, gy - r * 2, gx + r * 2, gy + r * 2), fill=gem + (130,))
    return w.finish()


#: Порядок = порядок в карусели. Первыми — самые понятные.
FRAMES: list[tuple[str, object]] = [
    ("Лавр", _laurel),
    ("Жемчуг", _pearls),
    ("Сакура", _sakura),
    ("Неон", _neon),
    ("Пламя", _flame),
    ("Звёздная пыль", _stardust),
    ("Сердца", _hearts),
    ("Корона", _crown),
    ("Терновник", _thorns),
    ("Цепь", _chain),
    ("Лёд", _ice),
]


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
    return len(FRAMES) + len(custom_frames())


def frame_name(index: int) -> str:
    if index < len(FRAMES):
        return FRAMES[index][0]
    return custom_frames()[index - len(FRAMES)].stem


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
    if index >= len(FRAMES):
        return _load_custom(custom_frames()[index - len(FRAMES)], size)[0]
    return FRAMES[index][1](Wreath(size))  # type: ignore[operator]


def _avatar_fraction(index: int, size: int) -> float:
    """Какую долю холста занимает фото под этой рамкой."""
    if index < len(FRAMES):
        #: Нарисованные рамки считаны под 60 % — у них кольцо на 0.372.
        return 0.60
    hole = _load_custom(custom_frames()[index - len(FRAMES)], size)[1]
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
             size: int, with_backdrop: bool = True) -> Image.Image:
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
    canvas.alpha_composite(_frame_layer(frame_idx, size))
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


def preview(backdrop_idx: int, frame_idx: int | None, title: str) -> bytes:
    """Карточка «как это сядет в профиль»: фон, аватарка, имя, статус."""
    card_w, card_h = 720, 720
    card = backdrop(backdrop_idx, card_h).resize((card_w, card_h), Image.BICUBIC).convert("RGBA")

    avatar = Image.new("RGBA", (420, 420), (0, 0, 0, 0))
    if frame_idx is None:
        blank = _placeholder(round(420 * 0.60))
        blank.putalpha(_circle_mask(blank.width))
        avatar.alpha_composite(blank, (84, 84))
    else:
        avatar = _compose(None, backdrop_idx, frame_idx, 420, with_backdrop=False)
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


def apply(photo_data: bytes, backdrop_idx: int, frame_idx: int) -> bytes:
    """Готовая аватарка: фото в круге, венок вокруг, фон профиля в углах."""
    with Image.open(io.BytesIO(photo_data)) as src:
        result = _compose(src.convert("RGB"), backdrop_idx, frame_idx, SIZE)
    buf = io.BytesIO()
    #: PNG: у аватарки видно каждый артефакт по краю венка.
    result.convert("RGB").save(buf, format="PNG", optimize=True)
    return buf.getvalue()
