"""Настройки Solutions Stories. Всё из .env рядом с main.py.

Общий .env в корне папки ботов намеренно не подхватывается: там токен
другого бота, а один токен — один поллинг.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()


def _ids(raw: str | None) -> set[int]:
    if not raw:
        return set()
    out: set[int] = set()
    for chunk in raw.replace(";", ",").split(","):
        chunk = chunk.strip()
        if chunk.lstrip("-").isdigit():
            out.add(int(chunk))
    return out


#: Кому открыта админка. Свой id узнать у @userinfobot.
ADMIN_IDS = _ids(os.getenv("ADMIN_IDS"))

#: Хостинги отдают под данные отдельный том и называют его в DATA_DIR.
#: Не слушать её нельзя: база ляжет рядом с кодом и сотрётся на первом
#: же передеплое — вместе со списком людей для рассылки и купленными
#: бесплатными нарезками.
DATA_DIR = Path(os.getenv("DATA_DIR") or BASE_DIR / "data")
DB_PATH = Path(os.getenv("DB_PATH") or DATA_DIR / "stories.db")

#: Рамки, присланные админом прямо в бота. Лежат в томе с базой, а не
#: рядом с кодом: папка проекта перезаписывается на каждом деплое из
#: Git, и загруженные рамки исчезали бы после первого же обновления.
FRAMES_DIR = Path(os.getenv("FRAMES_DIR") or DATA_DIR / "frames")

#: Картинки-заставки для /start, инструкции и раздела «для чего это».
#: Лежат файлами, а не file_id: file_id живёт внутри одного бота, и при
#: переезде на другой токен всё оформление отвалится молча.
ASSETS_DIR = Path(os.getenv("ASSETS_DIR") or BASE_DIR / "assets")

#: Звёзды — единственная валюта, которую Telegram разрешает боту без
#: платёжного провайдера и договора с банком.
CURRENCY = "XTR"


def _prices(raw: str | None) -> dict[int, int]:
    """Цены вида «6:20,9:25,12:30,15:35» — сколько звёзд за нарезку."""
    default = {3: 10, 6: 20, 9: 25, 12: 30, 15: 35}
    if not raw:
        return default
    out: dict[int, int] = {}
    for chunk in raw.replace(";", ",").split(","):
        parts, _, stars = chunk.partition(":")
        if parts.strip().isdigit() and stars.strip().isdigit():
            out[int(parts)] = int(stars)
    return out or default


#: Сколько стоит нарезка на N частей. Ключи — единственные варианты,
#: которые бот вообще предложит: колонок в сетке профиля всегда три,
#: поэтому частей может быть только кратно трём.
PRICES = _prices(os.getenv("PRICES"))

#: Рамка для аватарки дешевле нарезки: там одна картинка, а не пятнадцать.
FRAME_PRICE = int(os.getenv("FRAME_PRICE", "15"))

#: Столько активных рефералов даёт одну бесплатную генерацию.
#: «Активный» — тот, кто сделал в боте хоть что-то, кроме /start:
#: иначе накрутка сводится к рассылке ссылки по чатам.
REF_PER_FREE = int(os.getenv("REF_PER_FREE", "3"))

#: Сколько бесплатных генераций выдать новичку. Ноль — как у оригинала,
#: но первая бесплатная резко поднимает конверсию в оплату: человек
#: видит результат раньше, чем счёт.
WELCOME_CREDITS = int(os.getenv("WELCOME_CREDITS", "1"))

#: Чем заполнять верх и низ сторис: превью в профиле занимает только
#: середину кадра, а остальное видно, когда историю открывают целиком.
#: blur — размытое продолжение кадра, black — чёрные поля.
FILL_MODE = (os.getenv("FILL_MODE", "blur").strip().lower() or "blur")

#: Ссылки в оформлении. Пусто — кнопка просто не появится.
EXAMPLE_URL = os.getenv("EXAMPLE_URL", "").strip()
SECOND_BOT_URL = os.getenv("SECOND_BOT_URL", "").strip()
SUPPORT_URL = os.getenv("SUPPORT_URL", "").strip()


def check() -> None:
    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN не задан. Скопируй .env.example в .env и впиши токен от @BotFather."
        )
    bad = [n for n in PRICES if n % 3]
    if bad:
        raise RuntimeError(
            f"PRICES: {bad} не делится на 3. В профиле Telegram три колонки, "
            "стенка из некратного числа частей соберётся кривой."
        )
