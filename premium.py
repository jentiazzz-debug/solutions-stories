"""Премиум-эмодзи в текстах бота.

Подмена делается на выходе, а не в текстах. Текстов в боте под сотню,
и проставить `<tg-emoji>` руками в каждом — значит развести две версии
одной строки и навсегда следить, чтобы они не разошлись. Здесь же
обычные эмодзи остаются в исходниках как были, а в сообщение уходят
уже премиальными.

Про ограничение Telegram. Кастомные эмодзи разрешены не каждому боту:
API отвечает отказом, если у бота нет на это права. Проверять заранее
нечем — документированного способа спросить «а мне можно» нет, — и
гадать не нужно: первый же отказ выключает подмену на весь процесс, а
сообщение уходит повторно с обычными эмодзи. Человек видит ответ, а не
пустоту, и в логах остаётся одна понятная строка вместо потока ошибок.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Awaitable, Callable

from aiogram import Bot
from aiogram.client.session.middlewares.base import NextRequestMiddlewareType
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import TelegramMethod
from aiogram.methods.base import TelegramType

import config

logger = logging.getLogger("stories.premium")

#: Файл с паком: {"🎁": "5368324170671202286", ...}. Собирается
#: скриптом fetch_emoji.py из самого набора, руками не правится.
PACK = config.ASSETS_DIR / "emoji.json"

#: Поля методов Bot API, в которых едет видимый текст.
FIELDS = ("text", "caption")

#: Только те методы, чей текст Telegram разбирает как HTML. Список, а не
#: исключения: поле `text` есть и у answerCallbackQuery, но всплывашка
#: разметку не понимает и показала бы человеку сырой тег.
HTML_METHODS = frozenset({
    "SendMessage",
    "EditMessageText",
    "SendPhoto",
    "SendDocument",
    "SendVideo",
    "SendAnimation",
    "SendAudio",
    "EditMessageCaption",
    "EditMessageMedia",
    "CopyMessage",
})

#: Разрезаем строку по HTML-тегам: внутрь тега подмена лезть не должна,
#: иначе эмодзи в атрибуте превратится в сломанную разметку.
_TAG = re.compile(r"(<[^>]*>)")

#: Внутри моноширинных блоков вложенные сущности запрещены: Telegram
#: отвечает «can't parse entities» и роняет отправку целиком. Ссылки и
#: id мы показываем именно так, поэтому такие куски пропускаем.
_VERBATIM = ("code", "pre")
_TAG_NAME = re.compile(r"</?\s*([a-zA-Z0-9-]+)")

#: Чего в наборе нет — подставляем ближайшее по смыслу из него же.
#: Обычный символ при этом остаётся внутри тега: клиент, который не
#: умеет кастомные эмодзи, покажет именно его, так что ножницы никуда
#: не денутся — просто у всех остальных на их месте будет иконка набора.
#:
#: Первая половина — замены, где смысл не меняется совсем. Вторая —
#: где точного соответствия в наборе нет и выбрано близкое: набор
#: конечный, а обычный цветной эмодзи посреди линейных иконок виден
#: сразу и выглядит промахом вёрстки.
ALIAS = {
    "🔁": "🔄",
    "👇": "⬇️",
    "✖️": "❌",
    "👀": "👁",
    "🔴": "⛔",
    "🟢": "✅",
    "💸": "💰",
    "🧾": "📋",
    "📨": "📣",
    #: ↓ точного нет, взято близкое
    "✂️": "🪄",
    "💫": "⭐",
    "📘": "📄",
    "🎉": "🎈",
    "👋": "✨",
    "🤝": "❤️",
    "🖼️": "🖼",
    "🗑️": "🗑",
    "⭐️": "⭐",
}

_map: dict[str, str] = {}
_pattern: re.Pattern[str] | None = None
_enabled = True


def load() -> int:
    """Прочитать пак. Возвращает, сколько эмодзи подхватилось."""
    global _map, _pattern
    if not PACK.is_file():
        _map, _pattern = {}, None
        return 0
    raw = json.loads(PACK.read_text(encoding="utf-8"))
    _map = {k: str(v) for k, v in raw.items() if k and v}
    for plain, twin in ALIAS.items():
        if plain not in _map and twin in _map:
            _map[plain] = _map[twin]
    #: Длинные последовательности вперёд: составные эмодзи (с модификатором
    #: цвета кожи, с ZWJ) начинаются с обычного, и без сортировки набор
    #: подменял бы первый символ, оставляя хвост висеть отдельно.
    _pattern = (
        re.compile("|".join(re.escape(k) for k in sorted(_map, key=len, reverse=True)))
        if _map else None
    )
    return len(_map)


def decorate(text: str) -> str:
    """Обернуть известные эмодзи в <tg-emoji>."""
    if not _enabled or _pattern is None or not text:
        return text
    out = []
    depth = 0
    for chunk in _TAG.split(text):
        if chunk.startswith("<"):
            name = _TAG_NAME.match(chunk)
            if name and name.group(1).lower() in _VERBATIM:
                depth += -1 if chunk.startswith("</") else 1
                depth = max(depth, 0)
            out.append(chunk)
            continue
        if depth:
            out.append(chunk)
            continue
        out.append(_pattern.sub(
            lambda m: f'<tg-emoji emoji-id="{_map[m.group(0)]}">{m.group(0)}</tg-emoji>',
            chunk,
        ))
    return "".join(out)


def _looks_like_emoji_refusal(err: TelegramBadRequest) -> bool:
    return "emoji" in str(err).lower()


class Premium:
    """Session middleware: подменяет эмодзи в исходящих текстах."""

    async def __call__(
        self,
        make_request: NextRequestMiddlewareType[TelegramType],
        bot: Bot,
        method: TelegramMethod[TelegramType],
    ) -> Any:
        global _enabled
        if not _enabled or _pattern is None:
            return await make_request(bot, method)
        if type(method).__name__ not in HTML_METHODS:
            return await make_request(bot, method)

        before: list[tuple[str, Any]] = []
        for field in FIELDS:
            value = getattr(method, field, None)
            if isinstance(value, str) and value:
                decorated = decorate(value)
                if decorated != value:
                    before.append((field, value))
                    setattr(method, field, decorated)

        #: У editMessageMedia подпись лежит не в самом методе, а внутри
        #: media — именно ею подписана карусель рамок и фонов. Сам
        #: InputMedia заморожен, поэтому не правим, а подменяем копией.
        media = getattr(method, "media", None)
        caption = getattr(media, "caption", None)
        if isinstance(caption, str) and caption:
            decorated = decorate(caption)
            if decorated != caption:
                before.append(("media", media))
                method.media = media.model_copy(update={"caption": decorated})

        if not before:
            return await make_request(bot, method)

        try:
            return await make_request(bot, method)
        except TelegramBadRequest as err:
            if not _looks_like_emoji_refusal(err):
                raise
            #: Права на кастомные эмодзи у бота нет. Выключаем подмену на
            #: весь процесс и отправляем то же сообщение обычным текстом:
            #: иначе каждый ответ бота будет падать с этой же ошибкой.
            _enabled = False
            logger.warning(
                "Telegram не принял премиум-эмодзи (%s) — дальше шлём обычные", err
            )
            for field, value in before:
                setattr(method, field, value)
            return await make_request(bot, method)
