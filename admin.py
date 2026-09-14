"""Админка: статистика, топы, рассылка.

Роутер подключается ПЕРЕД основным: шаг сбора рассылки ждёт любое
сообщение в личке, и встань он после общего хендлера — текст поста
перехватывался бы как «пришли фото или выбери пункт меню».
"""

from __future__ import annotations

import asyncio
import html
import logging
from datetime import datetime, timedelta, timezone

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

import config
import db
import keyboards as kb

router = Router(name="admin")
logger = logging.getLogger("stories.admin")

#: Telegram пропускает около 30 сообщений в секунду на бота. Держим
#: заметно ниже потолка: рассылка не горит, а вот флуд-бан посреди неё
#: стоит половины аудитории.
RATE = 20


class Cast(StatesGroup):
    post = State()


router.message.filter(F.from_user.id.in_(config.ADMIN_IDS))
router.callback_query.filter(F.from_user.id.in_(config.ADMIN_IDS))


@router.message(Command("admin"))
async def on_admin(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("⚙️ Панель управления", reply_markup=kb.admin())


@router.callback_query(F.data == "adm:main")
async def cb_main(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.edit_text("⚙️ Панель управления", reply_markup=kb.admin())
    await callback.answer()


def _stats_text(data: dict) -> str:
    parts = data.get("parts", {})
    grid = " · ".join(
        f"{n}: <b>{parts.get(f'p{n}', 0)}</b>" for n in (6, 9, 12, 15)
    )
    return (
        "📊 <b>Статистика</b>\n\n"
        f"Людей всего: <b>{data['users']}</b>\n"
        f"Открыли бота: <b>{data['started']}</b> · заблокировали: <b>{data['blocked']}</b>\n"
        f"Новых сегодня: <b>{data['new_today']}</b> · за неделю: <b>{data['new_week']}</b>\n"
        f"Активных сегодня: <b>{data['active_today']}</b> · за месяц: <b>{data['active_month']}</b>\n\n"
        f"✂️ Генераций: <b>{data['cuts']}</b>\n"
        f"Сегодня: <b>{data['cuts_today']}</b> · вчера: <b>{data['cuts_yesterday']}</b> · "
        f"за неделю: <b>{data['cuts_week']}</b>\n"
        f"Бесплатных из них: <b>{data['free']}</b>\n"
        f"Сетки — {grid} · рамок: <b>{parts.get('frames', 0)}</b>\n\n"
        f"⭐ Звёзд всего: <b>{data['stars']}</b>\n"
        f"Сегодня: <b>{data['stars_today']}</b> · за неделю: <b>{data['stars_week']}</b>\n"
        f"Платили: <b>{data['buyers']}</b> человек\n\n"
        f"👥 Пришло по рефералкам: <b>{data['referred']}</b>, "
        f"из них активных: <b>{data['referred_active']}</b>"
    )


@router.callback_query(F.data == "adm:stats")
async def cb_stats(callback: CallbackQuery) -> None:
    await callback.message.edit_text(
        _stats_text(await db.overview()), reply_markup=kb.admin_refresh("stats")
    )
    await callback.answer()


def _who(row) -> str:
    if row["username"]:
        return f"@{html.escape(row['username'])}"
    return html.escape(row["first_name"] or "без имени")


@router.callback_query(F.data == "adm:tops")
async def cb_tops(callback: CallbackQuery) -> None:
    users = await db.top_users(10)
    inviters = await db.top_inviters(10)
    lines = ["🏆 <b>Топ по звёздам</b>", ""]
    lines += [
        f"{i}. {_who(r)} — {r['stars']}⭐ / {r['cuts']} генераций"
        for i, r in enumerate(users, start=1)
    ] or ["пока пусто"]
    lines += ["", "👥 <b>Топ пригласивших</b>", ""]
    lines += [
        f"{i}. {_who(r)} — {r['active'] or 0} активных из {r['total']}"
        for i, r in enumerate(inviters, start=1)
    ] or ["пока пусто"]
    await callback.message.edit_text("\n".join(lines), reply_markup=kb.admin_refresh("tops"))
    await callback.answer()


@router.callback_query(F.data == "adm:history")
async def cb_history(callback: CallbackQuery) -> None:
    rows = await db.last_broadcasts(10)
    if not rows:
        text = "🧾 Рассылок ещё не было."
    else:
        lines = ["🧾 <b>История рассылок</b>", ""]
        for row in rows:
            when = datetime.fromtimestamp(row["at"], timezone(timedelta(hours=3)))
            lines.append(
                f"{when:%d.%m %H:%M} — дошло {row['sent']}/{row['total']}, "
                f"заблокировали {row['blocked']}, ошибок {row['failed']}"
            )
        text = "\n".join(lines)
    await callback.message.edit_text(text, reply_markup=kb.admin_refresh("history"))
    await callback.answer()


# --------------------------------------------------------------------------
# Рассылка
# --------------------------------------------------------------------------


@router.callback_query(F.data == "adm:cast")
async def cb_cast(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(Cast.post)
    await callback.message.edit_text(
        "📣 Пришли сообщение, которое разослать.\n\n"
        "Можно текст, фото или видео с подписью — уйдёт копией, "
        "без пометки «переслано».",
        reply_markup=kb.admin_cancel(),
    )
    await callback.answer()


@router.callback_query(F.data == "adm:cancel")
async def cb_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.edit_text("⚙️ Панель управления", reply_markup=kb.admin())
    await callback.answer("Отменено")


@router.message(Cast.post)
async def on_post(message: Message, state: FSMContext) -> None:
    await state.update_data(chat_id=message.chat.id, message_id=message.message_id)
    everyone = len(await db.audience())
    active = len(await db.audience(30))
    await message.answer(
        "Кому отправляем?", reply_markup=kb.cast_confirm(everyone, active)
    )


@router.callback_query(F.data.startswith("adm:send:"))
async def cb_send(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    source_chat = data.get("chat_id")
    source_id = data.get("message_id")
    if not source_chat or not source_id:
        await callback.answer("Пост потерялся, собери заново", show_alert=True)
        return
    await state.clear()

    only_active = callback.data.endswith(":active")
    targets = await db.audience(30 if only_active else None)
    await callback.message.edit_text(f"📣 Отправляю {len(targets)}…")
    await callback.answer()

    sent, blocked, failed = await _broadcast(
        callback.bot, targets, int(source_chat), int(source_id)
    )
    await db.save_broadcast(callback.from_user.id, len(targets), sent, blocked, failed)
    await callback.message.answer(
        f"✅ Готово.\nДошло: <b>{sent}</b>\nЗаблокировали: <b>{blocked}</b>\n"
        f"Ошибок: <b>{failed}</b>",
        reply_markup=kb.admin(),
    )


async def _broadcast(bot: Bot, targets: list[int], chat_id: int, message_id: int):
    sent = blocked = failed = 0
    for i, user_id in enumerate(targets, start=1):
        try:
            await bot.copy_message(user_id, chat_id, message_id)
            sent += 1
        except TelegramForbiddenError:
            #: Единственная ошибка, по которой точно ясно: писать больше
            #: некуда. Помечаем, чтобы следующая рассылка не тратила на
            #: человека попытку.
            await db.mark_blocked(user_id)
            blocked += 1
        except TelegramRetryAfter as exc:
            #: Telegram прямо говорит, сколько ждать. Ждём и повторяем —
            #: пропустить человека здесь было бы обиднее всего.
            await asyncio.sleep(exc.retry_after + 1)
            try:
                await bot.copy_message(user_id, chat_id, message_id)
                sent += 1
            except Exception:
                failed += 1
        except Exception:
            logger.exception("рассылка: %s", user_id)
            failed += 1
        if i % RATE == 0:
            await asyncio.sleep(1)
    return sent, blocked, failed
