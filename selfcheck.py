"""Проверка без Telegram: собрать нарезку и рамку из тестовой картинки.

Смысл в том, чтобы ловить поломки картиночной части до деплоя. Всё
остальное — токен, платежи, рассылка — проверяется только живым ботом,
а вот геометрия сетки и венок ломаются от любой правки и молча отдают
кривой результат: в чате это видно, в тестах — нет.

    python selfcheck.py [путь_к_картинке]

Результат кладётся в _selfcheck/ рядом с кодом.
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

from PIL import Image, ImageDraw

import frames
import slicer

OUT = Path(__file__).resolve().parent / "_selfcheck"

#: Консоль Windows по умолчанию cp1251, и отчёт с «→» падает на выводе,
#: не дойдя до самих проверок. Переключаем поток, а не правим текст:
#: иначе то же самое повторится на любой новой строке с юникодом.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def _sample() -> bytes:
    """Шахматка с номерами: по ней сразу видно, если куски перепутаны."""
    width, height = 1200, 1500
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    step = 100
    for y in range(0, height, step):
        for x in range(0, width, step):
            if (x // step + y // step) % 2:
                draw.rectangle((x, y, x + step, y + step), fill=(40, 90, 200))
    draw.ellipse((width * 0.25, height * 0.25, width * 0.75, height * 0.75),
                 outline=(255, 60, 60), width=18)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=95)
    return buf.getvalue()


def main() -> int:
    data = Path(sys.argv[1]).read_bytes() if len(sys.argv) > 1 else _sample()
    OUT.mkdir(exist_ok=True)

    for parts in sorted(slicer.LAYOUTS):
        pieces = slicer.cut(data, parts)
        assert len(pieces) == parts, f"{parts}: получили {len(pieces)} кусков"
        for i, chunk in enumerate(pieces, start=1):
            with Image.open(io.BytesIO(chunk)) as img:
                assert img.size == (slicer.STORY_W, slicer.STORY_H), f"{parts}/{i}: {img.size}"
        (OUT / f"cut_{parts}_first.jpg").write_bytes(pieces[0])
        (OUT / f"cut_{parts}_last.jpg").write_bytes(pieces[-1])
        (OUT / f"grid_{parts}.jpg").write_bytes(slicer.preview(data, parts))
        w, h = slicer.ideal_ratio(parts)
        print(f"нарезка {parts:>2} → сетка 3×{slicer.LAYOUTS[parts]}, идеал {w}:{h} — ок")

    total = frames.frame_count()
    for index in range(total):
        result = frames.apply(data, index % len(frames.COLORS), index)
        with Image.open(io.BytesIO(result)) as img:
            assert img.size == (frames.SIZE, frames.SIZE), f"рамка {index}: {img.size}"
        if index < 3:
            (OUT / f"frame_{index}_{frames.frame_name(index)}.png").write_bytes(result)
    (OUT / "frame_preview.jpg").write_bytes(frames.preview(0, 0, "Solutions"))
    print(f"рамок собрано: {total} — ок")
    print(f"\nсмотреть: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
