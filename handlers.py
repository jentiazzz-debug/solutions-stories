"""Сценарии бота: нарезка, рамки, рефералы.

Порядок хендлеров в файле = порядок проверки. Сначала команды и кнопки
меню, потом картинки, и только в самом конце — «я не понял». Если
перевернуть, заглушка съест всё остальное.
"""

from __future__ import annotations

import asyncio
import html
import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    FSInputFile,
    InputMediaDocument,
    InputMediaPhoto,
    LabeledPrice,
    Message,
    PreCheckoutQuery,
)

import config
import db
import frames
import make_assets
import keyboards as kb
import slicer
import texts

router = Router(name="stories")
logger = logging.getLogger("stories.handlers")

#: Telegram не отдаёт боту файлы тяжелее 20 МБ — ловим до скачивания,
#: иначе получим невнятную ошибку от API вместо понятного текста.
MAX_FILE = 20 * 1024 * 1024

#: В одну media_group влезает десять вложений. Пятнадцать частей — это
#: две группы, и порядок между ними Telegram сохраняет.
GROUP_SIZE = 10


class Cut(StatesGroup):
    photo = State()
    parts = State()


class Frame(StatesGroup):
    colour = State()
    frame = State()
    photo = State()


# --------------------------------------------------------------------------
# Общее
# --------------------------------------------------------------------------


async def _download(bot: Bot, file_id: str) -> bytes:
    buf = await bot.download(file_id)
    return buf.read() if buf is not None else b""


def _photo_id(message: Message) -> str | None:
    """file_id картинки из фото или из документа-картинки.

    Документ берём именно по mime: люди регулярно шлют оригинал файлом,
    чтобы Telegram не жал, и отказывать им — терять лучшие исходники.
    """
    if message.photo:
        return message.photo[-1].file_id
    doc = message.document
    if doc and (doc.mime_type or "").startswith("image/"):
        return doc.file_id
    return None


def _too_big(message: Message) -> bool:
    doc = message.document
    return bool(doc and doc.file_size and doc.file_size > MAX_FILE)


async def _reward_inviter(bot: Bot, user_id: int) -> None:
    """Отметить активность и, если пора, начислить пригласившему.

    Вызывается из каждого осмысленного действия. Внутри стоит защёлка
    «уже активирован», поэтому лишних начислений не будет, а логика
    активации живёт в одном месте, а не размазана по хендлерам.
    """
    inviter = await db.activate(user_id)
    if inviter is None:
        return
    row = await db.get_user(inviter)
    credits = int(row["credits"]) if row else 0
    try:
        await bot.send_message(inviter, texts.ref_bonus(credits))
    except TelegramBadRequest:
        #: Пригласивший мог заблокировать бота. Звезда всё равно
        #: начислена — увидит, когда вернётся.
        logger.info("не доставили бонус рефереру %s", inviter)


async def _send_asset(message: Message, name: str, caption: str, markup=None) -> None:
    """Отправить картинку из assets, а если её нет — просто текст.

    Бот должен работать сразу после клона репозитория, без оформления:
    отсутствие баннера не повод ронять /start.
    """
    path = config.ASSETS_DIR / name
    if path.is_file():
        await message.answer_photo(FSInputFile(path), caption=caption, reply_markup=markup)
    else:
        await message.answer(caption, reply_markup=markup, disable_web_page_preview=True)


# --------------------------------------------------------------------------
# Старт и меню
# --------------------------------------------------------------------------


@router.message(CommandStart())
async def on_start(message: Message, command: CommandObject, state: FSMContext) -> None:
    await start_flow(message, message.from_user, (command.args or "").strip(), state)


async def start_flow(message: Message, user, payload: str, state: FSMContext) -> None:
    """Приветствие и разбор реферального кода.

    Вынесено из хендлера, потому что зайти сюда можно двумя дорогами:
    обычной /start и возвратом со стены обязательной подписки. Во втором
    случае реферальный код пришёл ещё до стены и ждал в состоянии — если
    бы приветствие жило в хендлере, друг бы не засчитался.
    """
    await state.clear()
    await db.touch_user(user.id, user.username, user.first_name or "")
    await db.mark_started(user.id)

    if payload.startswith("r") and payload[1:].isdigit():
        inviter_id = int(payload[1:])
        before = await db.get_user(user.id)
        if before and before["ref_by"] is None and inviter_id != user.id:
            await db.bind_ref(user.id, inviter_id)
            inviter = await db.get_user(inviter_id)
            if inviter:
                name = f"@{inviter['username']}" if inviter["username"] else inviter["first_name"]
                await message.answer(texts.ref_welcome(html.escape(name or "друга")))

    row = await db.get_user(user.id)
    credits = int(row["credits"]) if row else 0
    await message.answer(texts.start(html.escape(user.first_name or "друг"), credits),
                         reply_markup=kb.menu())
    await _send_asset(message, "welcome.jpg", texts.welcome_caption(), kb.welcome())


@router.message(F.text.in_(kb.said(kb.ABOUT)))
async def on_about(message: Message, state: FSMContext) -> None:
    await state.clear()
    await _personal_card(message, make_assets.personal_about, "about.jpg",
                         texts.about(), kb.welcome())
    await _reward_inviter(message.bot, message.from_user.id)


async def _profile_photo(bot: Bot, user_id: int) -> bytes | None:
    """Аватарка человека файлом — или None, если её нет.

    Аву может скрывать приватность, а может её просто не быть: и то и
    другое здесь не ошибка, а обычный случай, поэтому возвращаем None и
    показываем запасную карточку.
    """
    try:
        shots = await bot.get_user_profile_photos(user_id, limit=1)
        if not shots.photos:
            return None
        buf = await bot.download(shots.photos[0][-1].file_id)
        return buf.read() if buf is not None else None
    except TelegramBadRequest:
        return None


async def _personal_card(message: Message, build, asset: str, caption: str,
                         markup=None) -> None:
    """Карточка, собранная на аватарке того, кто нажал кнопку.

    И «Для чего это», и «Инструкция» рассказывают, что будет с его
    профилем. На чужом демо-кадре это реклама, на его собственном —
    ответ. Аву может скрывать приватность, рендер может упасть на битом
    файле: ни то ни другое не повод оставить человека без карточки,
    поэтому запасной вариант — готовый файл из assets.
    """
    user = message.from_user
    photo = await _profile_photo(message.bot, user.id)
    if photo:
        name = f"@{user.username}" if user.username else (user.first_name or "профиль")
        try:
            card = await asyncio.to_thread(build, photo, name)
        except Exception:
            logger.exception("не собрал личную карточку %s для %s", asset, user.id)
        else:
            await message.answer_photo(BufferedInputFile(card, filename=asset),
                                       caption=caption, reply_markup=markup)
            return
    await _send_asset(message, asset, caption, markup)


@router.message(Command("help"))
@router.message(F.text.in_(kb.said(kb.MANUAL)))
async def on_manual(message: Message, state: FSMContext) -> None:
    await state.clear()
    await _personal_card(message, make_assets.personal_manual, "manual.jpg",
                         texts.manual())
    await _reward_inviter(message.bot, message.from_user.id)


@router.message(F.text.in_(kb.said(kb.REFERRALS)))
async def on_referrals(message: Message, state: FSMContext, bot_username: str) -> None:
    await state.clear()
    user_id = message.from_user.id
    link = f"https://t.me/{bot_username}?start=r{user_id}"
    total, active = await db.ref_stats(user_id)
    row = await db.get_user(user_id)
    credits = int(row["credits"]) if row else 0
    await message.answer(
        texts.referrals(link, total, active, credits),
        reply_markup=kb.referrals(link),
        disable_web_page_preview=True,
    )
    await _reward_inviter(message.bot, user_id)


# --------------------------------------------------------------------------
# Нарезка
# --------------------------------------------------------------------------


@router.message(F.text.in_(kb.said(kb.CUT)))
async def on_cut(message: Message, state: FSMContext) -> None:
    await state.set_state(Cut.photo)
    await message.answer(texts.ask_photo())


@router.message(F.photo | F.document)
async def on_photo(message: Message, state: FSMContext) -> None:
    """Фото в любой момент — это заявка на нарезку.

    Отдельного «сначала нажми кнопку» нет намеренно: человек, пришедший
    по рекламе, первым делом кидает картинку, и упереться в «сначала
    выберите пункт меню» — самый дешёвый способ его потерять.
    """
    current = await state.get_state()
    if current == Frame.photo.state:
        await _frame_photo(message, state)
        return

    file_id = _photo_id(message)
    if file_id is None:
        await message.answer(texts.NOT_A_PHOTO)
        return
    if _too_big(message):
        await message.answer(texts.TOO_BIG)
        return

    await db.touch_user(message.from_user.id, message.from_user.username,
                        message.from_user.first_name or "")
    await state.set_state(Cut.parts)
    await state.update_data(file_id=file_id)

    row = await db.get_user(message.from_user.id)
    credits = int(row["credits"]) if row else 0
    await message.answer(texts.photo_taken(credits), reply_markup=kb.parts())
    await _reward_inviter(message.bot, message.from_user.id)


@router.callback_query(F.data == "cut:cancel")
async def cb_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.answer(texts.hint(), reply_markup=kb.menu())
    await callback.answer("Отменено")


@router.callback_query(F.data == "cut:again")
async def cb_again(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    if not data.get("file_id"):
        await callback.answer(texts.SESSION_LOST, show_alert=True)
        return
    await state.set_state(Cut.parts)
    row = await db.get_user(callback.from_user.id)
    await callback.message.answer(
        texts.photo_taken(int(row["credits"]) if row else 0), reply_markup=kb.parts()
    )
    await callback.answer()


@router.callback_query(F.data.startswith("cut:"))
async def cb_parts(callback: CallbackQuery, state: FSMContext) -> None:
    raw = callback.data.split(":", 1)[1]
    if not raw.isdigit() or int(raw) not in slicer.LAYOUTS:
        await callback.answer()
        return
    parts = int(raw)

    data = await state.get_data()
    file_id = data.get("file_id")
    if not file_id:
        await callback.answer(texts.SESSION_LOST, show_alert=True)
        return

    await callback.answer()
    await state.update_data(parts=parts)

    photo = await _download(callback.bot, file_id)
    if not photo:
        await callback.message.answer(texts.BROKEN)
        return

    try:
        small = await asyncio.to_thread(slicer.too_small, photo, parts)
        shot = await asyncio.to_thread(slicer.preview, photo, parts)
    except Exception:
        logger.exception("превью не собралось")
        await callback.message.answer(texts.BROKEN)
        return

    if small:
        await callback.message.answer(texts.small_photo())

    row = await db.get_user(callback.from_user.id)
    credits = int(row["credits"]) if row else 0
    await callback.message.answer_photo(
        BufferedInputFile(shot, filename="preview.jpg"),
        caption=texts.preview_caption(parts, config.PRICES[parts], credits),
        reply_markup=kb.confirm(parts, credits > 0),
    )


@router.callback_query(F.data.startswith("go:"))
async def cb_go(callback: CallbackQuery, state: FSMContext) -> None:
    parts = int(callback.data.split(":", 1)[1])
    data = await state.get_data()
    if not data.get("file_id"):
        await callback.answer(texts.SESSION_LOST, show_alert=True)
        return
    await callback.answer()

    #: Сначала пытаемся списать бесплатную — и только если её нет,
    #: выставляем счёт. Обратный порядок обидный: человек платит, имея
    #: на балансе неизрасходованную генерацию.
    if await db.spend_credit(callback.from_user.id):
        await _deliver_cut(callback.message, state, parts, paid=0)
        return

    price = config.PRICES[parts]
    await callback.message.answer_invoice(
        title=texts.invoice_title(parts),
        description=texts.invoice_description(parts),
        payload=f"cut:{parts}",
        currency=config.CURRENCY,
        prices=[LabeledPrice(label=f"{parts} сторис", amount=price)],
    )


async def _deliver_cut(message: Message, state: FSMContext, parts: int, paid: int) -> None:
    data = await state.get_data()
    file_id = data.get("file_id")
    if not file_id:
        await message.answer(texts.SESSION_LOST)
        return

    note = await message.answer(texts.cutting(parts))
    photo = await _download(message.bot, file_id)
    try:
        #: Pillow блокирующий, а пятнадцать кадров 1080×1920 с размытием
        #: — это секунды. В основном потоке они встанут поперёк всех
        #: остальных апдейтов.
        pieces = await asyncio.to_thread(slicer.cut, photo, parts, config.FILL_MODE)
    except Exception:
        logger.exception("нарезка упала")
        await note.delete()
        await message.answer(texts.BROKEN)
        return

    files = [
        BufferedInputFile(chunk, filename=f"{i:02d}_story.jpg")
        for i, chunk in enumerate(pieces, start=1)
    ]
    for start in range(0, len(files), GROUP_SIZE):
        group = files[start : start + GROUP_SIZE]
        #: Документами, а не фото: send_photo пережимает картинку, и
        #: стыки между кусками начинают отличаться по цвету.
        await message.answer_media_group([InputMediaDocument(media=f) for f in group])

    await note.delete()
    await message.answer(texts.cut_done(parts), reply_markup=kb.menu())
    await db.log_cut(message.chat.id, "cut", parts, paid)
    await state.clear()


# --------------------------------------------------------------------------
# Рамки для аватарки
# --------------------------------------------------------------------------


@router.message(F.text.in_(kb.said(kb.FRAMES)))
async def on_frames(message: Message, state: FSMContext) -> None:
    await state.clear()
    await _send_asset(message, "frames.jpg", texts.frames_intro(), kb.frames_start())
    await _reward_inviter(message.bot, message.from_user.id)


@router.callback_query(F.data == "frames:go")
async def cb_frames_go(callback: CallbackQuery, state: FSMContext) -> None:
    #: Рамки теперь только файлами, и папка может оказаться пустой.
    #: Без этой проверки карусель делит номер на ноль прямо на первом шаге.
    if frames.frame_count() == 0:
        await callback.answer(texts.NO_FRAMES, show_alert=True)
        return
    await callback.answer()
    await state.set_state(Frame.colour)
    await state.update_data(colour=0, frame=0, tint=True)
    await _show_colour(callback.message, 0, new=True)


#: Ошибки, которыми Telegram отвечает на гонку правок. Человек листает
#: карусель быстрее, чем бот успевает отрисовать превью: предыдущий
#: edit_media отменяется следующим. Это норма работы, а не сбой, —
#: показывать нечего, логировать тем более.
_EDIT_RACE = (
    "canceled by new edit message request",
    "message is not modified",
    "message to edit not found",
)


async def _swap_media(message: Message, media: InputMediaPhoto, markup) -> None:
    """Заменить картинку в сообщении, пережив гонку с соседним нажатием."""
    try:
        await message.edit_media(media, reply_markup=markup)
    except TelegramBadRequest as err:
        text = str(err).lower()
        if not any(known in text for known in _EDIT_RACE):
            raise
        logger.debug("правка карусели разошлась с соседней: %s", err)


async def _show_colour(message: Message, index: int, new: bool = False) -> None:
    total = len(frames.COLORS)
    shot = await asyncio.to_thread(frames.preview, index, None, texts.BRAND)
    caption = texts.pick_color(index + 1, total, frames.color_name(index))
    media = BufferedInputFile(shot, filename="colour.jpg")
    if new:
        await message.answer_photo(media, caption=caption,
                                   reply_markup=kb.carousel("col", index + 1, total))
        return
    await _swap_media(
        message,
        InputMediaPhoto(media=media, caption=caption),
        kb.carousel("col", index + 1, total),
    )


async def _show_frame(message: Message, colour: int, index: int, credits: int,
                      new: bool = False, tint: bool = True) -> None:
    total = frames.frame_count()
    shot = await asyncio.to_thread(frames.preview, colour, index, texts.BRAND, tint)
    caption = texts.pick_frame(index + 1, total, frames.frame_name(index),
                               config.FRAME_PRICE, credits, tint)
    media = BufferedInputFile(shot, filename="frame.jpg")
    markup = kb.carousel("frm", index + 1, total, tint)
    if new:
        await message.answer_photo(media, caption=caption, reply_markup=markup)
        return
    await _swap_media(message, InputMediaPhoto(media=media, caption=caption), markup)


@router.callback_query(F.data.startswith("col:"))
async def cb_colour(callback: CallbackQuery, state: FSMContext) -> None:
    action = callback.data.split(":", 1)[1]
    data = await state.get_data()
    index = int(data.get("colour", 0))
    total = len(frames.COLORS)

    if action == "pick":
        await callback.answer()
        await state.set_state(Frame.frame)
        row = await db.get_user(callback.from_user.id)
        await _show_frame(callback.message, index, int(data.get("frame", 0)),
                          int(row["credits"]) if row else 0,
                          tint=bool(data.get("tint", True)))
        return

    index = (index + (1 if action == "next" else -1)) % total
    await state.update_data(colour=index)
    await callback.answer()
    await _show_colour(callback.message, index)


@router.callback_query(F.data.startswith("frm:"))
async def cb_frame(callback: CallbackQuery, state: FSMContext) -> None:
    action = callback.data.split(":", 1)[1]
    data = await state.get_data()
    colour = int(data.get("colour", 0))
    index = int(data.get("frame", 0))
    tint = bool(data.get("tint", True))
    total = frames.frame_count()

    if action == "pick":
        await callback.answer()
        await state.set_state(Frame.photo)
        await callback.message.answer(
            texts.frame_ask_photo(frames.frame_name(index), frames.color_name(colour))
        )
        return

    if action == "tint":
        tint = not tint
        await state.update_data(tint=tint)
    else:
        index = (index + (1 if action == "next" else -1)) % total
        await state.update_data(frame=index)
    await callback.answer()
    row = await db.get_user(callback.from_user.id)
    await _show_frame(callback.message, colour, index,
                      int(row["credits"]) if row else 0, tint=tint)


async def _frame_photo(message: Message, state: FSMContext) -> None:
    file_id = _photo_id(message)
    if file_id is None:
        await message.answer(texts.NOT_A_PHOTO)
        return
    if _too_big(message):
        await message.answer(texts.TOO_BIG)
        return
    await state.update_data(file_id=file_id)

    if await db.spend_credit(message.from_user.id):
        await _deliver_frame(message, state, paid=0)
        return

    data = await state.get_data()
    await message.answer_invoice(
        title=texts.frame_invoice_title(),
        description=texts.frame_invoice_description(frames.frame_name(int(data.get("frame", 0)))),
        payload="frame",
        currency=config.CURRENCY,
        prices=[LabeledPrice(label="Рамка", amount=config.FRAME_PRICE)],
    )


async def _deliver_frame(message: Message, state: FSMContext, paid: int) -> None:
    data = await state.get_data()
    file_id = data.get("file_id")
    if not file_id:
        await message.answer(texts.SESSION_LOST)
        return
    photo = await _download(message.bot, file_id)
    try:
        result = await asyncio.to_thread(
            frames.apply, photo, int(data.get("colour", 0)), int(data.get("frame", 0)),
            bool(data.get("tint", True)),
        )
    except Exception:
        logger.exception("рамка не собралась")
        await message.answer(texts.BROKEN)
        return

    await message.answer_document(
        BufferedInputFile(result, filename="avatar.png"),
        caption=texts.frame_done(),
        reply_markup=kb.menu(),
    )
    await db.log_cut(message.chat.id, "frame", 0, paid)
    await state.clear()


# --------------------------------------------------------------------------
# Платежи
# --------------------------------------------------------------------------


@router.pre_checkout_query()
async def on_pre_checkout(query: PreCheckoutQuery) -> None:
    """Подтверждаем счёт. Отказ здесь Telegram показывает человеку."""
    payload = query.invoice_payload
    if payload == "frame" or (
        payload.startswith("cut:")
        and payload.split(":", 1)[1].isdigit()
        and int(payload.split(":", 1)[1]) in slicer.LAYOUTS
    ):
        await query.answer(ok=True)
        return
    await query.answer(ok=False, error_message="Счёт устарел, начни заново.")


@router.message(F.successful_payment)
async def on_paid(message: Message, state: FSMContext) -> None:
    payment = message.successful_payment
    await db.log_payment(
        message.from_user.id,
        payment.total_amount,
        payment.invoice_payload,
        payment.telegram_payment_charge_id,
    )
    if payment.invoice_payload == "frame":
        await _deliver_frame(message, state, paid=payment.total_amount)
        return
    parts = int(payment.invoice_payload.split(":", 1)[1])
    await _deliver_cut(message, state, parts, paid=payment.total_amount)


# --------------------------------------------------------------------------
# Всё остальное
# --------------------------------------------------------------------------


@router.callback_query(F.data == "noop")
async def cb_noop(callback: CallbackQuery) -> None:
    await callback.answer()


@router.message(F.chat.type == "private")
async def on_anything(message: Message) -> None:
    await db.touch_user(message.from_user.id, message.from_user.username,
                        message.from_user.first_name or "")
    await message.answer(texts.hint(), reply_markup=kb.menu())
