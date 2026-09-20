"""Админка: статистика, топы, рассылка.

Роутер подключается ПЕРЕД основным: шаг сбора рассылки ждёт любое
сообщение в личке, и встань он после общего хендлера — текст поста
перехватывался бы как «пришли фото или выбери пункт меню».
"""

from __future__ import annotations

import asyncio
import html
import io
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from aiogram import Bot, F, Router
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramRetryAfter,
)
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, CallbackQuery, Message
from PIL import Image

import config
import db
import frames
import keyboards as kb
import subscribe
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


class FrameUpload(StatesGroup):
    file = State()


class GateAdd(StatesGroup):
    channel = State()


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
        f"{n}: <b>{parts.get(f'p{n}', 0)}</b>" for n in (3, 6, 9, 12, 15)
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


@router.callback_query(F.data == "adm:frames")
async def cb_frames(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    files = frames.custom_frames()
    #: В списке на удаление — только загруженные. Рамки из репозитория
    #: вернутся на следующем деплое, и кнопка «удалить» у них была бы
    #: обманом; к тому же их больше десятка, и они вытесняли бы из
    #: панели именно то, что удалить можно.
    uploaded = [p for p in files if p.parent == config.FRAMES_DIR]
    lines = [
        "🖼 <b>Рамки</b>",
        "",
        f"Всего в карусели: <b>{len(files)}</b>",
        f"Из них загружено сюда: <b>{len(uploaded)}</b> (только их и можно удалить)",
    ]
    if uploaded:
        lines += ["", *(f"• {path.stem}" for path in uploaded[:12])]
    await callback.message.edit_text(
        "\n".join(lines), reply_markup=kb.frames_panel([p.stem for p in uploaded])
    )
    await callback.answer()


@router.callback_query(F.data == "adm:frame:add")
async def cb_frame_add(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(FrameUpload.file)
    await callback.message.edit_text(
        "🖼 Пришли картинку рамки.\n\n"
        "<b>Отправляй файлом</b>, а не фото: фото Telegram пережимает в JPEG "
        "и убивает прозрачность.\n\n"
        "Квадрат, рамка по краю, середина пустая. Фон вырежу сам, "
        "размер фото под просвет подберу тоже сам.",
        reply_markup=kb.admin_cancel(),
    )
    await callback.answer()


@router.message(FrameUpload.file, F.document | F.photo)
async def on_frame_file(message: Message, state: FSMContext) -> None:
    if message.photo:
        await message.answer(
            "⚠️ Это пришло как фото — прозрачность уже потеряна. Возьму как есть "
            "и вырежу фон, но лучше переслать тем же файлом."
        )
        file_id = message.photo[-1].file_id
        name = f"frame_{db.now()}"
    else:
        doc = message.document
        if not (doc.mime_type or "").startswith("image/"):
            await message.answer("Это не картинка. Нужен PNG.")
            return
        file_id = doc.file_id
        name = Path(doc.file_name or f"frame_{db.now()}").stem

    #: Имя чистим: оно станет подписью в карусели и именем файла на
    #: диске, а туда прилетает всё что угодно — от пробелов до кавычек.
    safe = re.sub(r"[^\w\-]+", "_", name, flags=re.UNICODE).strip("_") or f"frame_{db.now()}"
    config.FRAMES_DIR.mkdir(parents=True, exist_ok=True)
    target = config.FRAMES_DIR / f"{safe}.png"

    buffer = await message.bot.download(file_id)
    try:
        with Image.open(io.BytesIO(buffer.read())) as img:
            #: Сохраняем именно PNG: пришедший JPEG иначе останется без
            #: альфы, и вырезанный фон будет некуда записать.
            img.convert("RGBA").save(target, format="PNG", optimize=True)
    except Exception:
        logger.exception("рамка не открылась")
        await message.answer("Не смог прочитать картинку. Попробуй другой файл.")
        return

    await state.clear()
    files = frames.custom_frames()
    index = next(
        (len(frames.FRAMES) + i for i, path in enumerate(files) if path == target),
        len(frames.FRAMES),
    )
    shot = await asyncio.to_thread(frames.preview, 0, index, "проверка")
    await message.answer_photo(
        BufferedInputFile(shot, filename="frame.jpg"),
        caption=(
            f"✅ Рамка <b>{safe}</b> добавлена.\n"
            f"Всего в карусели: <b>{frames.frame_count()}</b>.\n\n"
            "Если на чёрном фоне её не видно — рамка тёмная, это нормально: "
            "посмотри на светлом."
        ),
        reply_markup=kb.admin(),
    )


@router.callback_query(F.data.startswith("adm:frame:del:"))
async def cb_frame_del(callback: CallbackQuery, state: FSMContext) -> None:
    index = int(callback.data.rsplit(":", 1)[1])
    #: Номер приходит из списка загруженных, а не из всей карусели:
    #: в ней рамки из репозитория стоят первыми и сдвинули бы индекс.
    uploaded = [p for p in frames.custom_frames() if p.parent == config.FRAMES_DIR]
    if index >= len(uploaded):
        await callback.answer("Уже удалена", show_alert=True)
        return
    target = uploaded[index]
    target.unlink(missing_ok=True)
    await callback.answer(f"Удалена: {target.stem}")
    await cb_frames(callback, state)


# --------------------------------------------------------------------------
# Обязательная подписка
# --------------------------------------------------------------------------


async def _gate_screen(bot: Bot) -> tuple[str, object]:
    """Текст и клавиатура раздела: они об одном, и собираются вместе."""
    rows = await db.channels()
    on = await db.gate_on()
    #: Спрашиваем у Telegram, админ ли бот в каждом канале. Это главная
    #: причина, по которой «подписка не работает»: канал добавили, а прав
    #: боту не выдали, и get_chat_member отвечает отказом.
    broken = {row["id"] for row in rows if not await subscribe.status(bot, row["id"])}
    lines = [
        "📢 <b>Обязательная подписка</b>",
        "",
        f"Проверка: <b>{'включена' if on else 'выключена'}</b>",
        f"Каналов: <b>{len(rows)}</b>",
    ]
    if not rows:
        lines += ["", "Пока ни одного канала — проверять нечего, бот пускает всех."]
    for row in rows:
        mark = " ⚠️ бот не админ" if row["id"] in broken else ""
        lines.append(f"• {row['title']} — <code>{row['id']}</code>{mark}")
    if broken:
        lines += [
            "",
            "⚠️ В отмеченных каналах бот не администратор и не видит подписчиков. "
            "Такие каналы проверка <b>пропускает</b>: закрыть бота для всех "
            "из-за одной кривой настройки хуже, чем не проверить один канал.",
        ]
    return "\n".join(lines), kb.gate_panel(rows, on, broken)


@router.callback_query(F.data == "adm:gate")
async def cb_gate(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    await state.clear()
    text, markup = await _gate_screen(bot)
    await callback.message.edit_text(text, reply_markup=markup)
    await callback.answer()


@router.callback_query(F.data == "adm:gate:toggle")
async def cb_gate_toggle(callback: CallbackQuery, bot: Bot) -> None:
    on = not await db.gate_on()
    await db.set_gate(on)
    #: Кеш «этот подписан» живёт пять минут. После переключения он врал бы
    #: ровно столько же, и проверка выглядела бы сломанной.
    subscribe.forget()
    text, markup = await _gate_screen(bot)
    await callback.message.edit_text(text, reply_markup=markup)
    await callback.answer("Проверка включена" if on else "Проверка выключена")


@router.callback_query(F.data == "adm:gate:add")
async def cb_gate_add(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(GateAdd.channel)
    await callback.message.edit_text(
        "📢 Пришли <b>@юзернейм</b> канала или его ID.\n\n"
        "Сначала добавь бота в канал администратором: без этого он не видит "
        "подписчиков, и проверять будет нечем.",
        reply_markup=kb.admin_back(),
    )
    await callback.answer()


@router.message(GateAdd.channel, F.text)
async def on_gate_channel(message: Message, state: FSMContext, bot: Bot) -> None:
    query = message.text.strip()
    try:
        chat = await bot.get_chat(query)
    except TelegramAPIError as err:
        await message.answer(
            f"Не нашёл такой канал: {html.escape(str(err))}\n\n"
            "Если канал закрытый — сначала добавь туда бота, иначе Telegram "
            "его не покажет.",
            reply_markup=kb.admin_back(),
        )
        return
    #: Ссылку сохраняем сразу: на стене она нужна каждому непрошедшему, а
    #: спрашивать её у Telegram на каждый показ — запрос на пустом месте.
    link = chat.invite_link or (f"https://t.me/{chat.username}" if chat.username else None)
    await db.add_channel(str(chat.id), chat.title or query, link)
    subscribe.forget()
    await state.clear()
    warn = "" if await subscribe.status(bot, str(chat.id)) else (
        "\n\n⚠️ Бот не администратор этого канала — подписчиков он не видит, "
        "и проверка будет его пропускать. Выдай права и загляни сюда снова."
    )
    note = "" if link else (
        "\n\nУ канала нет ссылки — на стене кнопка будет без перехода. "
        "Сделай пригласительную ссылку или публичный юзернейм."
    )
    title = html.escape(chat.title or query)
    await message.answer(f"✅ Канал <b>{title}</b> добавлен.{warn}{note}")
    text, markup = await _gate_screen(bot)
    await message.answer(text, reply_markup=markup)


@router.callback_query(F.data.startswith("adm:gate:del:"))
async def cb_gate_del(callback: CallbackQuery, bot: Bot) -> None:
    removed = await db.remove_channel(callback.data[len("adm:gate:del:"):])
    subscribe.forget()
    text, markup = await _gate_screen(bot)
    await callback.message.edit_text(text, reply_markup=markup)
    await callback.answer("Канал убран" if removed else "Такого канала уже нет")


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
