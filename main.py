"""Точка входа: long polling.

Запуск:  python main.py   (нужен .env с BOT_TOKEN)
"""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand

import admin
import config
import db
import frames
import handlers
import subscribe

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
logger = logging.getLogger("stories")


async def main() -> None:
    config.check()
    await db.connect()
    logger.info("база: %s", config.DB_PATH)

    bot = Bot(
        token=config.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dispatcher = Dispatcher()
    #: Админка идёт первой: её хендлеры ждут любое сообщение в личке
    #: (там собирается рассылка), и встань она после общей — текст поста
    #: перехватывался бы обычным меню.
    dispatcher.include_router(admin.router)
    dispatcher.include_router(subscribe.router)
    dispatcher.include_router(handlers.router)

    #: Стена обязательной подписки. Middleware, а не проверка в каждом
    #: хендлере: забытый хендлер — это дыра, через которую открыта вся
    #: механика. Вешаем на внутренний слой, чтобы в data уже лежал FSM:
    #: реферальный код из /start приходится сохранять до прохода стены.
    gate = subscribe.Gate()
    dispatcher.message.middleware(gate)
    dispatcher.callback_query.middleware(gate)

    me = await bot.get_me()
    #: Юзернейм нужен для реферальных ссылок в каждом ответе, а дёргать
    #: get_me на каждое сообщение — лишний запрос к API.
    dispatcher["bot_username"] = me.username

    #: Команды в меню Telegram, а не только в тексте: у оригинала их нет
    #: вовсе, и человек, потерявший reply-клавиатуру, остаётся без
    #: единого способа вернуться в начало.
    await bot.set_my_commands(
        [
            BotCommand(command="start", description="Начать заново"),
            BotCommand(command="help", description="Как собрать стенку"),
        ]
    )

    logger.info(
        "запущен как @%s (рамок: %d, цен: %s, админов: %d)",
        me.username, frames.frame_count(), config.PRICES, len(config.ADMIN_IDS),
    )
    if not config.ADMIN_IDS:
        logger.warning("ADMIN_IDS пуст — панель /admin никому не откроется")

    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dispatcher.start_polling(bot)
    finally:
        await db.close()
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("остановлен")
