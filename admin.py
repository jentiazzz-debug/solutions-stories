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
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramRetryAfter,
)
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

import config
import db
import keyboards as kb
import texts

router = Router(name="admin")
logger = logging.getLogger("stories.admin")

#: Telegram пропускает около 30 сообщений в секунду на бота. Держим
#: заметно ниже потолка: рассылка не горит, а вот флуд-бан посреди неё
#: стоит половины аудитории.
RATE = 20


class Cast(StatesGroup):
    post = State()


class Lookup(StatesGroup):
    query = State()


class Grant(StatesGroup):
    query = State()


async def _apply_grant(bot: Bot, admin_id: int, user_id: int, amount: int,
                       exact: bool = False) -> int:
    """Начислить или выставить генерации и сказать об этом человеку.

    Молча менять баланс нельзя: человек видит только «бесплатных: N» в
    меню и решит, что бот сам себе прибавил.
    """
    balance = (
        await db.set_credits(user_id, amount) if exact
        else await db.add_credits(user_id, amount)
    )
    await db.log_grant(admin_id, user_id, amount, balance)
    if not exact and amount > 0:
        #: «Начислили генераций: 3» вместо «начислили 3 бесплатных
        #: генерации»: прилагательное пришлось бы склонять отдельно от
        #: существительного, а двоеточие снимает вопрос целиком.
        note = f"🎁 Тебе начислили бесплатных генераций: <b>{amount}</b>."
    elif not exact:
        note = None
    else:
        note = f"🎁 Твой баланс бесплатных генераций: <b>{balance}</b>."
    if note:
        word = texts.plural(balance, "генерация", "генерации", "генераций")
        try:
            await bot.send_message(user_id, f"{note}\nВсего: <b>{balance}</b> {word}.")
        except (TelegramForbiddenError, TelegramBadRequest):
            #: Человек заблокировал бота. Баланс всё равно начислен —
            #: увидит, когда вернётся.
            logger.info("выдачу не доставили: %s", user_id)
    return balance


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


def _pct(part: int, whole: int) -> str:
    return f"{part / whole * 100:.1f}%" if whole else "—"


def _stats_text(data: dict) -> str:
    parts = data.get("parts", {})
    grid = " · ".join(
        f"{n}: <b>{parts.get(f'p{n}', 0)}</b>" for n in (6, 9, 12, 15)
    )
    paid_cuts = data["cuts"] - data["free"]
    check = f"{data['stars'] / data['buyers']:.0f}" if data["buyers"] else "—"
    arpu = f"{data['stars'] / data['started']:.2f}" if data["started"] else "—"
    #: Три числа, по которым и принимают решения: доля платящих, средний
    #: чек и выручка на человека. Без них «всего звёзд» ни о чём не
    #: говорит — непонятно, много это или мало.
    return "\n".join((
        "📊 <b>Статистика</b>",
        "",
        f"👥 Людей всего: <b>{data['users']}</b>",
        f"Открыли бота: <b>{data['started']}</b> · заблокировали: <b>{data['blocked']}</b>",
        f"Новых сегодня: <b>{data['new_today']}</b> · за неделю: <b>{data['new_week']}</b>",
        f"Активных сегодня: <b>{data['active_today']}</b> · "
        f"за месяц: <b>{data['active_month']}</b>",
        "",
        f"✂️ Генераций: <b>{data['cuts']}</b> "
        f"(платных <b>{paid_cuts}</b>, бесплатных <b>{data['free']}</b>)",
        f"Сегодня: <b>{data['cuts_today']}</b> · вчера: <b>{data['cuts_yesterday']}</b> · "
        f"за неделю: <b>{data['cuts_week']}</b>",
        f"Сетки — {grid} · рамок: <b>{parts.get('frames', 0)}</b>",
        "",
        f"⭐ Звёзд всего: <b>{data['stars']}</b>",
        f"Сегодня: <b>{data['stars_today']}</b> · за неделю: <b>{data['stars_week']}</b>",
        "",
        "💡 <b>Деньги</b>",
        f"Платили: <b>{data['buyers']}</b> из {data['started']} "
        f"(<b>{_pct(data['buyers'], data['started'])}</b>)",
        f"Средний чек: <b>{check}</b> ⭐ · на человека: <b>{arpu}</b> ⭐",
        f"Выдано руками: <b>{data['granted']}</b> · на балансах лежит: "
        f"<b>{data['credits_left']}</b>",
        "",
        f"🔗 По рефералкам: <b>{data['referred']}</b>, "
        f"активных <b>{data['referred_active']}</b> "
        f"(<b>{_pct(data['referred_active'], data['referred'])}</b>)",
    ))


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


@router.callback_query(F.data == "adm:daily")
async def cb_daily(callback: CallbackQuery) -> None:
    rows = await db.daily(14)
    #: Моноширинная таблица в <pre>: в Telegram это единственный способ
    #: выровнять колонки — обычный текст съезжает на каждом шрифте.
    lines = ["<b>📈 Последние 14 дней</b>", "", "<pre>дата    нов  ген  плат   ⭐"]
    for row in rows:
        when = datetime.fromtimestamp(row["day"], timezone(timedelta(hours=3)))
        lines.append(
            f"{when:%d.%m}  {row['new']:>4} {row['cuts']:>4} {row['paid']:>5} {row['stars']:>5}"
        )
    lines.append("</pre>")
    lines.append("нов — новые люди, ген — генерации, плат — из них платных")
    await callback.message.edit_text("\n".join(lines), reply_markup=kb.admin_refresh("daily"))
    await callback.answer()


@router.callback_query(F.data == "adm:pays")
async def cb_pays(callback: CallbackQuery) -> None:
    rows = await db.last_payments(15)
    if not rows:
        text = "💸 Платежей ещё не было."
    else:
        lines = ["💸 <b>Последние платежи</b>", ""]
        for row in rows:
            when = datetime.fromtimestamp(row["at"], timezone(timedelta(hours=3)))
            what = row["payload"]
            what = "рамка" if what == "frame" else f"{what.split(':')[-1]} частей"
            lines.append(f"{when:%d.%m %H:%M} · {_who(row)} · <b>{row['stars']}</b>⭐ · {what}")
        text = "\n".join(lines)
    await callback.message.edit_text(text, reply_markup=kb.admin_refresh("pays"))
    await callback.answer()


@router.callback_query(F.data == "adm:find")
async def cb_find(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(Lookup.query)
    await callback.message.edit_text(
        "👤 Пришли <b>id</b> или <b>@username</b> — покажу карточку человека.",
        reply_markup=kb.admin_cancel(),
    )
    await callback.answer()


@router.message(Lookup.query)
async def on_lookup(message: Message, state: FSMContext) -> None:
    await state.clear()
    row = await db.find_user(message.text or "")
    if row is None:
        await message.answer(
            "Не нашёл. Юзернейм запоминается только после захода в бота.",
            reply_markup=kb.admin(),
        )
        return

    facts = await db.user_activity(int(row["id"]))
    joined = datetime.fromtimestamp(row["joined_at"], timezone(timedelta(hours=3)))
    seen = datetime.fromtimestamp(row["last_seen"], timezone(timedelta(hours=3)))
    last_cut = (
        datetime.fromtimestamp(facts["last_cut"], timezone(timedelta(hours=3))).strftime(
            "%d.%m %H:%M"
        )
        if facts["last_cut"]
        else "не резал"
    )
    await message.answer(
        "\n".join((
            f"👤 {_who(row)} · <code>{row['id']}</code>",
            "",
            f"Пришёл: {joined:%d.%m.%Y}",
            f"Был: {seen:%d.%m %H:%M}",
            f"Открыл бота: {'да' if row['started'] else 'нет'} · "
            f"заблокировал: {'да' if row['blocked'] else 'нет'}",
            "",
            f"✂️ Генераций: <b>{facts['cuts']}</b> (платных <b>{facts['paid_cuts']}</b>)",
            f"Последняя: {last_cut}",
            f"⭐ Потратил: <b>{facts['stars']}</b>",
            f"🎁 Бесплатных осталось: <b>{row['credits']}</b>",
            "",
            f"🔗 Привёл: <b>{facts['refs_total']}</b>, "
            f"активных <b>{facts['refs_active']}</b>",
            f"Пришёл по ссылке: {row['ref_by'] or '—'}",
        )),
        reply_markup=kb.user_card(int(row["id"])),
    )


@router.callback_query(F.data == "adm:grant")
async def cb_grant(callback: CallbackQuery, state: FSMContext) -> None:
    total = await db.granted_total()
    await state.set_state(Grant.query)
    await callback.message.edit_text(
        "🎁 <b>Выдать генерации</b>\n\n"
        "Пришли одной строкой:\n"
        "<code>@username 3</code> — начислить три\n"
        "<code>123456789 -1</code> — списать одну\n"
        "<code>@username =0</code> — выставить баланс ровно\n\n"
        f"Всего выдано руками: <b>{total}</b>",
        reply_markup=kb.admin_cancel(),
    )
    await callback.answer()


@router.message(Grant.query)
async def on_grant(message: Message, state: FSMContext) -> None:
    parts = (message.text or "").split()
    if len(parts) != 2:
        await message.answer("Нужно две части: кому и сколько. Пример: <code>@vasya 3</code>")
        return

    who, raw = parts
    exact = raw.startswith("=")
    raw = raw.lstrip("=")
    try:
        amount = int(raw)
    except ValueError:
        await message.answer("Второе значение должно быть числом.")
        return

    row = await db.find_user(who)
    if row is None:
        await message.answer(
            "Не нашёл. Юзернейм запоминается только после захода в бота — "
            "попробуй числовой id.",
        )
        return

    await state.clear()
    balance = await _apply_grant(message.bot, message.from_user.id, int(row["id"]),
                                 amount, exact)
    verb = "выставлено" if exact else ("начислено" if amount > 0 else "списано")
    await message.answer(
        f"✅ {_who(row)} — {verb} <b>{abs(amount)}</b>.\n"
        f"Баланс: <b>{balance}</b>",
        reply_markup=kb.admin(),
    )


@router.callback_query(F.data.startswith("adm:give:"))
async def cb_give(callback: CallbackQuery) -> None:
    _, _, user_id, amount = callback.data.split(":")
    balance = await _apply_grant(callback.bot, callback.from_user.id,
                                 int(user_id), int(amount))
    await callback.answer(f"Баланс: {balance}", show_alert=False)
    #: Дописываем итог к карточке, а не перерисовываем её целиком: так
    #: видно всю историю нажатий за одну сессию поддержки.
    await callback.message.edit_text(
        f"{callback.message.html_text}\n\n🎁 {int(amount):+d} → баланс <b>{balance}</b>",
        reply_markup=kb.user_card(int(user_id)),
    )


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
