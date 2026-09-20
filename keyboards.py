"""Клавиатуры.

Главное меню — reply, а не inline. Inline-меню живёт внутри одного
сообщения и уезжает вверх, стоит боту прислать пятнадцать файлов; reply
висит над полем ввода всегда, и после выдачи нарезки человек видит, чем
заняться дальше, без повторного /start.
"""

from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

import config
import slicer
import texts

CUT = "✂️ Создать сторис"
FRAMES = "🖼 Рамки для авы"
MANUAL = "📘 Инструкция"
ABOUT = "💡 Для чего это"
REFERRALS = "👥 Рефералы"

MENU_BUTTONS = {CUT, FRAMES, MANUAL, ABOUT, REFERRALS}


def menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=CUT), KeyboardButton(text=FRAMES)],
            [KeyboardButton(text=MANUAL), KeyboardButton(text=ABOUT)],
            [KeyboardButton(text=REFERRALS)],
        ],
        resize_keyboard=True,
        input_field_placeholder="Пришли фото или выбери пункт меню",
    )


def welcome() -> InlineKeyboardMarkup | None:
    rows: list[list[InlineKeyboardButton]] = []
    if config.EXAMPLE_URL:
        rows.append([InlineKeyboardButton(text="👀 Пример стенки", url=config.EXAMPLE_URL)])
    if config.SECOND_BOT_URL:
        rows.append([InlineKeyboardButton(text="🎨 Наш второй бот", url=config.SECOND_BOT_URL)])
    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None


def parts() -> InlineKeyboardMarkup:
    """Варианты сетки по двое в ряд — по одному на строку список уезжает
    за экран вместе с превью, ради которого всё и затевалось."""
    options = sorted(slicer.LAYOUTS)
    #: Цена на кнопке помогает выбирать, только когда варианты стоят
    #: по-разному. При единой цене это пять одинаковых «10⭐», которые
    #: съедают место под названием сетки — её называет подпись выше.
    flat = config.flat_cut_price()
    rows: list[list[InlineKeyboardButton]] = []
    for i in range(0, len(options), 2):
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{n} {texts.plural(n, 'часть', 'части', 'частей')}"
                         + ("" if flat else f" · {config.PRICES.get(n, '?')}⭐"),
                    callback_data=f"cut:{n}",
                )
                for n in options[i : i + 2]
            ]
        )
    rows.append([InlineKeyboardButton(text="✖️ Отмена", callback_data="cut:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def confirm(parts_count: int, free: bool) -> InlineKeyboardMarkup:
    #: «Оплатить 10 звёзд», а не «Оплатить 10⭐»: эмодзи в хвосте подписи
    #: остаётся обычным — иконкой кнопки становится только первый.
    price = config.PRICES[parts_count]
    stars = texts.plural(price, "звезду", "звезды", "звёзд")
    label = "🎁 Нарезать бесплатно" if free else f"💫 Оплатить {price} {stars}"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=label, callback_data=f"go:{parts_count}")],
            [InlineKeyboardButton(text="🔁 Другая сетка", callback_data="cut:again")],
            [InlineKeyboardButton(text="✖️ Отмена", callback_data="cut:cancel")],
        ]
    )


def carousel(kind: str, index: int, total: int,
             tint: bool | None = None) -> InlineKeyboardMarkup:
    """Листалка цвета и рамки.

    Номер в callback_data не кладём: экран всё равно перерисовывается
    целиком, а без номера кнопки не протухают, если человек вернулся к
    старому сообщению через неделю.

    tint=None — переключателя нет (экран выбора фона). На экране рамки
    он показывает текущее состояние прямо в подписи: отдельная строка
    «сейчас включено» занимала бы место, а кнопка и так его называет.
    """
    rows = [
        [
            #: С подписью, а не голой стрелкой: иконка кнопки берётся из
            #: эмодзи перед текстом, а у кнопки из одного эмодзи текста
            #: нет — стрелка так и осталась бы обычной.
            InlineKeyboardButton(text="⬅️ Назад", callback_data=f"{kind}:prev"),
            InlineKeyboardButton(text=f"{index}/{total}", callback_data="noop"),
            InlineKeyboardButton(text="➡️ Дальше", callback_data=f"{kind}:next"),
        ],
    ]
    if tint is not None:
        rows.append([
            InlineKeyboardButton(
                text="🎨 Под фон: вкл" if tint else "🎨 Под фон: выкл",
                callback_data=f"{kind}:tint",
            )
        ])
    rows.append([InlineKeyboardButton(text="✅ Выбрать", callback_data=f"{kind}:pick")])
    rows.append([InlineKeyboardButton(text="✖️ Отмена", callback_data="cut:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def frames_start() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🎨 Выбрать цвет и рамку", callback_data="frames:go")]
        ]
    )


def referrals(link: str) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text="📨 Отправить приглашение",
                switch_inline_query=f"\n\nСобери стенку сторис для профиля: {link}",
            )
        ]
    ]
    if config.SUPPORT_URL:
        rows.append([InlineKeyboardButton(text="💬 Поддержка", url=config.SUPPORT_URL)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# --------------------------------------------------------------------------
# Админка
# --------------------------------------------------------------------------


def subscribe(rows) -> InlineKeyboardMarkup:
    """Стена обязательной подписки: каналы и кнопка проверки.

    Ссылку берём ту, что сохранили при добавлении канала. Спрашивать её
    у Telegram на каждом показе — лишний запрос на каждого незалогиненного
    человека, а меняется она раз в никогда.
    """
    keys = []
    for row in rows:
        link = row["link"]
        title = row["title"]
        keys.append([
            InlineKeyboardButton(text=f"📢 {title}", url=link)
            if link else
            InlineKeyboardButton(text=f"📢 {title}", callback_data="sub:none")
        ])
    keys.append([InlineKeyboardButton(text="✅ Я подписался", callback_data="sub:check")])
    return InlineKeyboardMarkup(inline_keyboard=keys)


def gate_panel(rows, on: bool, broken: set[str]) -> InlineKeyboardMarkup:
    """Админский список каналов: удалить, добавить, включить/выключить."""
    keys = []
    for row in rows:
        #: Пометка словами: второй эмодзи в подписи иконкой уже не станет
        #: и торчал бы рядом с премиальной обычным значком.
        mark = " (нет прав)" if row["id"] in broken else ""
        keys.append([InlineKeyboardButton(
            text=f"❌ {row['title']}{mark}", callback_data=f"adm:gate:del:{row['id']}"
        )])
    keys.append([InlineKeyboardButton(text="➕ Добавить канал",
                                      callback_data="adm:gate:add")])
    keys.append([InlineKeyboardButton(
        text="🔴 Выключить проверку" if on else "🟢 Включить проверку",
        callback_data="adm:gate:toggle",
    )])
    keys.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="adm:main")])
    return InlineKeyboardMarkup(inline_keyboard=keys)


def admin() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📊 Статистика", callback_data="adm:stats"),
                InlineKeyboardButton(text="📈 По дням", callback_data="adm:daily"),
            ],
            [
                InlineKeyboardButton(text="🏆 Топы", callback_data="adm:tops"),
                InlineKeyboardButton(text="💸 Платежи", callback_data="adm:pays"),
            ],
            [
                InlineKeyboardButton(text="👤 Найти человека", callback_data="adm:find"),
                InlineKeyboardButton(text="🎁 Выдать", callback_data="adm:grant"),
            ],
            [InlineKeyboardButton(text="🖼 Рамки", callback_data="adm:frames")],
            [InlineKeyboardButton(text="📢 Обязательная подписка",
                                  callback_data="adm:gate")],
            [InlineKeyboardButton(text="📣 Рассылка", callback_data="adm:cast")],
            [InlineKeyboardButton(text="🧾 История рассылок", callback_data="adm:history")],
        ]
    )


def admin_back() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="adm:main")]]
    )


def admin_refresh(target: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Обновить", callback_data=f"adm:{target}")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="adm:main")],
        ]
    )


def user_card(user_id: int) -> InlineKeyboardMarkup:
    """Быстрая выдача прямо из карточки человека.

    Кнопки с готовыми числами: в поддержке выдают почти всегда одну-три
    генерации, и набирать команду руками ради этого — лишний шаг.
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="+1", callback_data=f"adm:give:{user_id}:1"),
                InlineKeyboardButton(text="+3", callback_data=f"adm:give:{user_id}:3"),
                InlineKeyboardButton(text="+10", callback_data=f"adm:give:{user_id}:10"),
                InlineKeyboardButton(text="−1", callback_data=f"adm:give:{user_id}:-1"),
            ],
            [InlineKeyboardButton(text="⬅️ В панель", callback_data="adm:main")],
        ]
    )


def frames_panel(names: list[str]) -> InlineKeyboardMarkup:
    """Список загруженных рамок с кнопкой удаления у каждой."""
    rows = [[InlineKeyboardButton(text="➕ Добавить рамку", callback_data="adm:frame:add")]]
    for index, name in enumerate(names[:12]):
        rows.append([
            InlineKeyboardButton(text=f"🗑 {name[:28]}", callback_data=f"adm:frame:del:{index}")
        ])
    rows.append([InlineKeyboardButton(text="⬅️ В панель", callback_data="adm:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_cancel() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="✖️ Отмена", callback_data="adm:cancel")]]
    )


def cast_confirm(everyone: int, active: int) -> InlineKeyboardMarkup:
    """Числа прямо на кнопках.

    «Отправить всем» без числа рядом — самый простой способ разбудить
    базу, о размере которой забыл.
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"🚀 Всем ({everyone})", callback_data="adm:send:all")],
            [
                InlineKeyboardButton(
                    text=f"🎯 Активным за месяц ({active})", callback_data="adm:send:active"
                )
            ],
            [InlineKeyboardButton(text="✖️ Отмена", callback_data="adm:cancel")],
        ]
    )
