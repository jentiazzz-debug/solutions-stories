"""Нарезка картинки на стенку из сторис.

Почему размеры именно такие. Сторис в Telegram — это кадр 9:16, но в
сетке профиля от него видно не всё: превью обрезается по центру до
пропорции 4:5. Значит, чтобы куски сошлись в единое полотно, стыковать
надо не кадры целиком, а как раз эти центральные окна — их и режем.
Остальное кадра в стенке не участвует и служит полями.

    ┌──────────┐  1080×1920 — сам кадр сторис
    │  поля    │
    ├──────────┤  ← 285 px сверху
    │  1080×   │
    │   1350   │  ← это окно видно в сетке профиля
    ├──────────┤
    │  поля    │
    └──────────┘

Порядок выдачи — порядок публикации. Сетка профиля заполняется свежими
историями слева направо и сверху вниз, поэтому самый первый
опубликованный кусок оказывается в правом нижнем углу, а последний — в
левом верхнем. Бот отдаёт файлы уже в этом порядке: publish как есть,
сверху вниз по списку.
"""

from __future__ import annotations

import io

from PIL import Image, ImageEnhance, ImageFilter

#: Окно, которое попадает в превью профиля.
CELL_W, CELL_H = 1080, 1350

#: Сам кадр сторис.
STORY_W, STORY_H = 1080, 1920

#: Колонок в сетке профиля всегда три — это не настройка, а вёрстка
#: Telegram. Отсюда и требование кратности трём для числа частей.
COLS = 3

#: Сколько рядов получится из N частей.
LAYOUTS = {6: 2, 9: 3, 12: 4, 15: 5}

#: Ниже этого по короткой стороне исходник заметно мылит: каждый кусок
#: растягивается до 1080×1350, и апскейл видно на глаз.
MIN_SIDE = 900

JPEG_QUALITY = 95


def ideal_ratio(parts: int) -> tuple[int, int]:
    """Пропорция исходника, при которой ничего не обрежется.

    Полотно — COLS×rows окон 4:5, значит идеальное соотношение сторон
    равно (3·4) : (rows·5). Для 9 частей это ровно 4:5, для 6 — 4:3.
    """
    rows = LAYOUTS[parts]
    w, h = CELL_W * COLS, CELL_H * rows
    from math import gcd

    g = gcd(w, h)
    return w // g, h // g


def too_small(data: bytes, parts: int) -> bool:
    """Предупредить заранее, а не показывать мыло постфактум."""
    with Image.open(io.BytesIO(data)) as img:
        return min(img.size) < MIN_SIDE and parts >= 12


def _cover(img: Image.Image, width: int, height: int) -> Image.Image:
    """Вписать «по большей стороне» и обрезать лишнее по центру.

    Именно обрезать, а не вписать с полями: полотно должно быть залито
    целиком, иначе в стенке появятся пустые куски.
    """
    src_ratio = img.width / img.height
    dst_ratio = width / height
    if src_ratio > dst_ratio:
        new_h = height
        new_w = max(width, round(height * src_ratio))
    else:
        new_w = width
        new_h = max(height, round(width / src_ratio))
    img = img.resize((new_w, new_h), Image.LANCZOS)
    left = (new_w - width) // 2
    top = (new_h - height) // 2
    return img.crop((left, top, left + width, top + height))


def _story(cell: Image.Image, fill: str) -> Image.Image:
    """Уложить окно в кадр сторис и чем-то занять поля."""
    canvas = Image.new("RGB", (STORY_W, STORY_H), "black")
    if fill == "blur":
        #: Размытая растяжка того же куска: поля перестают читаться как
        #: дефект, а стык с окном остаётся незаметным, потому что цвета
        #: на границе совпадают.
        bg = _cover(cell, STORY_W, STORY_H).filter(ImageFilter.GaussianBlur(48))
        bg = ImageEnhance.Brightness(bg).enhance(0.55)
        canvas.paste(bg, (0, 0))
    canvas.paste(cell, (0, (STORY_H - CELL_H) // 2))
    return canvas


def _encode(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=JPEG_QUALITY, optimize=True, subsampling=0)
    return buf.getvalue()


def cut(data: bytes, parts: int, fill: str = "blur") -> list[bytes]:
    """Нарезать картинку. Список идёт в порядке публикации."""
    if parts not in LAYOUTS:
        raise ValueError(f"частей может быть только {sorted(LAYOUTS)}, а не {parts}")
    rows = LAYOUTS[parts]

    with Image.open(io.BytesIO(data)) as src:
        #: Прозрачность на JPEG превращается в чёрные разводы, поэтому
        #: сводим на белый до всякого ресайза.
        if src.mode in ("RGBA", "LA", "P"):
            src = src.convert("RGBA")
            flat = Image.new("RGB", src.size, "white")
            flat.paste(src, mask=src.split()[-1])
            src = flat
        else:
            src = src.convert("RGB")
        board = _cover(src, CELL_W * COLS, CELL_H * rows)

    cells: list[Image.Image] = []
    for row in range(rows):
        for col in range(COLS):
            box = (col * CELL_W, row * CELL_H, (col + 1) * CELL_W, (row + 1) * CELL_H)
            cells.append(board.crop(box))

    #: Снизу вверх, справа налево — так сетка профиля соберёт полотно
    #: обратно, если публиковать файлы подряд.
    out: list[bytes] = []
    for row in range(rows - 1, -1, -1):
        for col in range(COLS - 1, -1, -1):
            out.append(_encode(_story(cells[row * COLS + col], fill)))
    return out


def preview(data: bytes, parts: int) -> bytes:
    """Как стенка будет выглядеть в профиле: сетка с белыми швами.

    Человеку важно увидеть раскладку до оплаты — на превью сразу видно,
    что лицо разрезано пополам, и он поменяет число частей, а не пойдёт
    в поддержку после списания звёзд.
    """
    rows = LAYOUTS[parts]
    gap = 12
    thumb_w, thumb_h = 240, 300

    with Image.open(io.BytesIO(data)) as src:
        board = _cover(src.convert("RGB"), thumb_w * COLS, thumb_h * rows)

    width = thumb_w * COLS + gap * (COLS + 1)
    height = thumb_h * rows + gap * (rows + 1)
    canvas = Image.new("RGB", (width, height), (16, 18, 22))
    for row in range(rows):
        for col in range(COLS):
            box = (col * thumb_w, row * thumb_h, (col + 1) * thumb_w, (row + 1) * thumb_h)
            canvas.paste(
                board.crop(box),
                (gap + col * (thumb_w + gap), gap + row * (thumb_h + gap)),
            )
    buf = io.BytesIO()
    canvas.save(buf, format="JPEG", quality=90, optimize=True)
    return buf.getvalue()
