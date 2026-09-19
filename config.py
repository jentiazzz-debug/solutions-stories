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


#: Нарезка стоит одинаково, на сколько бы частей ни резали. Лесенка
#: «3 части — 10, 15 частей — 35» выглядела логично со стороны бота
#: (работы-то больше), но со стороны человека наказывала за то, что он
#: хочет стенку покрасивее. Одна цена снимает выбор «а не взять ли
#: подешевле» — остаётся только вопрос, какая сетка ему идёт.
CUT_PRICE = int(os.getenv("CUT_PRICE", "10"))

#: Варианты сетки, которые бот вообще предложит. Колонок в профиле
#: всегда три, поэтому частей может быть только кратно трём.
CUT_OPTIONS = (3, 6, 9, 12, 15)


def _prices(raw: str | None) -> dict[int, int]:
    """Цены вида «6:20,9:25» — если нужно отойти от единой CUT_PRICE."""
    #: Начинаем с полного набора и переопределяем разобранным, а не
    #: заменяем целиком. На хостинге стояло «6:20,9:25,12:30,15:35» без
    #: тройки — бот предлагал «3 части» и падал с KeyError, когда её
    #: выбирали. Частичный список теперь просто уточняет часть цен.
    out = {n: CUT_PRICE for n in CUT_OPTIONS}
    if not raw:
        return out
    for chunk in raw.replace(";", ",").split(","):
        parts, _, stars = chunk.partition(":")
        if parts.strip().isdigit() and stars.strip().isdigit():
            out[int(parts)] = int(stars)
    return out


#: Сколько стоит нарезка на N частей. По умолчанию везде CUT_PRICE;
#: переменная PRICES оставлена на случай, если цены всё-таки разведут.
PRICES = _prices(os.getenv("PRICES"))

#: Рамка дороже нарезки: нарезку человек делает один раз под конкретную
#: картинку, а рамку ставит на аватарку и носит постоянно.
FRAME_PRICE = int(os.getenv("FRAME_PRICE", "15"))


def flat_cut_price() -> int | None:
    """Единая цена нарезки, если она и правда единая.

    Нужна интерфейсу: когда все варианты стоят одинаково, звёзды на
    каждой кнопке — пять раз повторённое «10⭐» и ничего больше.
    """
    values = set(PRICES.values())
    return values.pop() if len(values) == 1 else None

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
