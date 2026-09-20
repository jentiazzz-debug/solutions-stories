"""Обязательная подписка: стена перед ботом и её проверка.

Проверка стоит middleware, а не вызовом в каждом хендлере. Хендлеров в
боте два десятка, и стоит забыть один — через него откроется вся
механика: нарезка, рамки, рефералка. Middleware закрывает вход целиком,
а исключения перечислены здесь же, в одном списке, где их видно.

Отдельно про отказы Telegram. Если бота выкинули из канала,
get_chat_member начинает падать на всех подряд. Считать такой отказ
«не подписан» нельзя: одна ошибка в настройке закрывает бота вообще
для всех, и админ узнаёт об этом от пользователей. Поэтому ошибка API
здесь трактуется в пользу человека, а сломанный канал видно в панели —
там он помечен ⚠️.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware, Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, TelegramObject

import config
import db
import handlers
import keyboards as kb
import texts

router = Router(name="subscribe")

logger = logging.getLogger("stories.gate")

#: Сколько секунд помним, что человек подписан. Без кеша каждый клик по
#: карусели рамок — это ещё один запрос get_chat_member на канал.
CACHE_TTL = 300

#: Статусы, при которых человек в канале не состоит.
OUT = ("left", "kicked", "banned")

_ok: dict[int, float] = {}


def forget(user_id: int | None = None) -> None:
    """Сбросить кеш: целиком или по одному человеку.

    Нужен после правки списка каналов — иначе добавленный канал начнёт
    требоваться только через пять минут, и админ решит, что не работает.
    """
    if user_id is None:
        _ok.clear()
    else:
        _ok.pop(user_id, None)


async def missing(bot: Bot, user_id: int, rows: list) -> list:
    """Каналы, в которых человека нет. Недоступные каналы пропускаем."""
    out = []
    for row in rows:
        try:
            member = await bot.get_chat_member(chat_id=row["id"], user_id=user_id)
        except TelegramAPIError as err:
            logger.warning("канал %s недоступен боту: %s", row["id"], err)
            continue
        if member.status in OUT:
            out.append(row)
    return out


async def status(bot: Bot, chat_id: str) -> bool:
    """Может ли бот читать участников канала. Для отметки ⚠️ в панели."""
    try:
        member = await bot.get_chat_member(chat_id=chat_id, user_id=bot.id)
    except TelegramAPIError:
        return False
    return member.status in ("administrator", "creator")


async def passed(bot: Bot, user_id: int) -> bool:
    """Пускать ли человека дальше. Заодно обновляет кеш."""
    if user_id in config.ADMIN_IDS:
        return True
    if not await db.gate_on():
        return True
    rows = await db.channels()
    if not rows:
        return True
    seen = _ok.get(user_id)
    if seen is not None and time.monotonic() - seen < CACHE_TTL:
        return True
    if await missing(bot, user_id, rows):
        _ok.pop(user_id, None)
        return False
    _ok[user_id] = time.monotonic()
    return True


async def wall(target: Message | CallbackQuery, bot: Bot) -> None:
    """Показать стену с каналами."""
    rows = await db.channels()
    gone = await missing(bot, target.from_user.id, rows)
    markup = kb.subscribe(gone or rows)
    if isinstance(target, CallbackQuery):
        await target.answer()
        await target.message.answer(texts.gate(), reply_markup=markup)
    else:
        await target.answer(texts.gate(), reply_markup=markup)


class Gate(BaseMiddleware):
    """Пропускает внутрь только подписанных.

    Исключение одно — кнопка проверки: без неё из стены не выйти.

    /start не исключение, стена встречает и его. Но реферальный код
    приезжает именно в /start, и если человек пришёл по ссылке друга и
    упёрся в стену, код нужно сохранить до проверки — иначе друг не
    засчитается никогда.
    """

    EXEMPT_DATA = ("sub:check", "sub:none")

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = getattr(event, "from_user", None)
        bot: Bot = data["bot"]
        if user is None:
            return await handler(event, data)
        if isinstance(event, CallbackQuery) and (event.data or "").startswith(
            self.EXEMPT_DATA
        ):
            return await handler(event, data)
        if await passed(bot, user.id):
            return await handler(event, data)
        await _remember_ref(event, data.get("state"))
        await wall(event, bot)
        return None


async def _remember_ref(event: TelegramObject, state: FSMContext | None) -> None:
    """Отложить реферальный код до прохода стены."""
    if state is None or not isinstance(event, Message):
        return
    text = (event.text or "").strip()
    if not text.startswith("/start "):
        return
    payload = text.split(maxsplit=1)[1].strip()
    if payload:
        await state.update_data(gate_ref=payload)


@router.callback_query(F.data == "sub:none")
async def cb_no_link(callback: CallbackQuery) -> None:
    """У канала нет ссылки — кнопка обязана хоть что-то ответить.

    Без хендлера Telegram крутит на ней часики, пока не отвалится по
    таймауту: выглядит как зависший бот, а виновата пустая настройка.
    """
    await callback.answer("У этого канала нет открытой ссылки — попроси её у админа.",
                          show_alert=True)


@router.callback_query(F.data == "sub:check")
async def cb_check(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    rows = await db.channels()
    gone = await missing(bot, callback.from_user.id, rows)
    if gone:
        #: Отвечаем алертом, а не новой стеной: человек и так на ней
        #: стоит, второй такой же экран выглядит как зависший бот.
        await callback.answer(texts.GATE_STILL, show_alert=True)
        return
    forget(callback.from_user.id)
    data = await state.get_data()
    payload = str(data.get("gate_ref") or "")
    await callback.answer(texts.GATE_OK)
    await handlers.start_flow(callback.message, callback.from_user, payload, state)
