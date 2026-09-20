"""SQLite: люди, нарезки, рефералы, платежи, рассылки.

Нарезки пишутся журналом, а не счётчиком. Счётчик отвечает только на «а
сколько всего», журнал — ещё и на «когда», «на сколько частей» и «за
звёзды или бесплатно»; по нему же видно, какой вариант сетки людям
реально нужен, и где цена мимо.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

import aiosqlite

import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id          INTEGER PRIMARY KEY,
    username    TEXT,
    first_name  TEXT,
    joined_at   INTEGER NOT NULL,
    last_seen   INTEGER NOT NULL DEFAULT 0,
    started     INTEGER NOT NULL DEFAULT 0,
    blocked     INTEGER NOT NULL DEFAULT 0,
    credits     INTEGER NOT NULL DEFAULT 0,
    cuts        INTEGER NOT NULL DEFAULT 0,
    stars       INTEGER NOT NULL DEFAULT 0,
    ref_by      INTEGER,
    activated   INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS users_seen ON users (last_seen);
CREATE INDEX IF NOT EXISTS users_ref ON users (ref_by);

CREATE TABLE IF NOT EXISTS cuts (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    at      INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    kind    TEXT NOT NULL,
    parts   INTEGER NOT NULL DEFAULT 0,
    paid    INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS cuts_at ON cuts (at);
CREATE INDEX IF NOT EXISTS cuts_user ON cuts (user_id, at);

CREATE TABLE IF NOT EXISTS payments (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    at        INTEGER NOT NULL,
    user_id   INTEGER NOT NULL,
    stars     INTEGER NOT NULL,
    payload   TEXT NOT NULL,
    charge_id TEXT
);
CREATE INDEX IF NOT EXISTS payments_at ON payments (at);

CREATE TABLE IF NOT EXISTS grants (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    at       INTEGER NOT NULL,
    admin_id INTEGER NOT NULL,
    user_id  INTEGER NOT NULL,
    amount   INTEGER NOT NULL,
    balance  INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS grants_at ON grants (at);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS channels (
    id       TEXT PRIMARY KEY,
    title    TEXT NOT NULL,
    link     TEXT,
    added_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS broadcasts (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    at       INTEGER NOT NULL,
    admin_id INTEGER NOT NULL,
    total    INTEGER NOT NULL,
    sent     INTEGER NOT NULL,
    blocked  INTEGER NOT NULL,
    failed   INTEGER NOT NULL
);
"""

_db: aiosqlite.Connection | None = None


def now() -> int:
    return int(time.time())


def day_start(days_ago: int = 0) -> int:
    """Полночь по Москве, а не по UTC сервера.

    «Нарезок за сегодня» должно означать сегодня у того, кто смотрит
    статистику: на UTC-хостинге счётчик иначе обнуляется в три часа ночи
    посреди самого живого времени.
    """
    local = datetime.now(timezone.utc) + timedelta(hours=3)
    midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
    midnight -= timedelta(days=days_ago)
    return int((midnight - timedelta(hours=3)).replace(tzinfo=timezone.utc).timestamp())


async def connect() -> None:
    global _db
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    _db = await aiosqlite.connect(config.DB_PATH)
    _db.row_factory = aiosqlite.Row
    await _db.executescript(SCHEMA)
    await _db.commit()


async def close() -> None:
    if _db is not None:
        await _db.close()


def conn() -> aiosqlite.Connection:
    if _db is None:
        raise RuntimeError("База не открыта: сначала db.connect()")
    return _db


async def _all(sql: str, args: Iterable[Any] = ()) -> list[aiosqlite.Row]:
    async with conn().execute(sql, tuple(args)) as cur:
        return list(await cur.fetchall())


async def _one(sql: str, args: Iterable[Any] = ()) -> aiosqlite.Row | None:
    async with conn().execute(sql, tuple(args)) as cur:
        return await cur.fetchone()


async def _scalar(sql: str, args: Iterable[Any] = ()) -> int:
    row = await _one(sql, args)
    return int(row[0]) if row and row[0] is not None else 0


async def _run(sql: str, args: Iterable[Any] = ()) -> None:
    await conn().execute(sql, tuple(args))
    await conn().commit()


# --------------------------------------------------------------------------
# Люди
# --------------------------------------------------------------------------


async def touch_user(user_id: int, username: str | None, first_name: str) -> None:
    """Запомнить человека и обновить имя.

    Метка blocked снимается при каждой встрече: раз человек снова что-то
    жмёт, значит бота он разблокировал — и в следующую рассылку обязан
    попасть, иначе однажды забаненный останется вычеркнутым навсегда.
    """
    await _run(
        """
        INSERT INTO users (id, username, first_name, joined_at, last_seen, credits)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT (id) DO UPDATE SET
            username = excluded.username,
            first_name = excluded.first_name,
            last_seen = excluded.last_seen,
            blocked = 0
        """,
        (user_id, username, first_name, now(), now(), config.WELCOME_CREDITS),
    )


async def get_user(user_id: int) -> aiosqlite.Row | None:
    return await _one("SELECT * FROM users WHERE id = ?", (user_id,))


async def mark_started(user_id: int) -> None:
    await _run("UPDATE users SET started = 1, blocked = 0 WHERE id = ?", (user_id,))


async def mark_blocked(user_id: int) -> None:
    await _run("UPDATE users SET blocked = 1 WHERE id = ?", (user_id,))


async def audience(active_days: int | None = None) -> list[int]:
    sql = "SELECT id FROM users WHERE started = 1 AND blocked = 0"
    args: list[Any] = []
    if active_days:
        sql += " AND last_seen >= ?"
        args.append(now() - active_days * 86400)
    return [int(row["id"]) for row in await _all(sql, args)]


# --------------------------------------------------------------------------
# Рефералы
# --------------------------------------------------------------------------
#
# Приглашение засчитывается не в момент перехода по ссылке, а когда
# новичок впервые что-то сделал. Иначе вся механика сводится к рассылке
# ссылки по чатам: сто открытых /start — тридцать три бесплатных
# нарезки, и ни одного живого человека.


async def bind_ref(user_id: int, inviter_id: int) -> None:
    """Привязать новичка к пригласившему — один раз и навсегда.

    Перезаписывать нельзя: иначе последний, кто скинул ссылку, забирает
    чужого реферала, и ссылками начинают бить друг по другу.
    """
    if user_id == inviter_id:
        return
    await _run(
        "UPDATE users SET ref_by = ? WHERE id = ? AND ref_by IS NULL",
        (inviter_id, user_id),
    )


async def activate(user_id: int) -> int | None:
    """Отметить первое осмысленное действие. Вернуть id пригласившего,
    если тому пора начислять бесплатную генерацию.
    """
    row = await get_user(user_id)
    if row is None or row["activated"]:
        return None
    await _run("UPDATE users SET activated = 1 WHERE id = ?", (user_id,))

    inviter = row["ref_by"]
    if not inviter:
        return None
    active = await _scalar(
        "SELECT COUNT(*) FROM users WHERE ref_by = ? AND activated = 1", (inviter,)
    )
    #: Начисляем ровно на каждом третьем, а не «выдать active // 3»:
    #: второй вариант при пересчёте задним числом раздаёт кратные суммы
    #: повторно, стоит один раз тронуть формулу.
    if active % config.REF_PER_FREE == 0:
        await add_credits(inviter, 1)
        return int(inviter)
    return None


async def ref_stats(user_id: int) -> tuple[int, int]:
    """Сколько всего перешло и сколько из них активных."""
    total = await _scalar("SELECT COUNT(*) FROM users WHERE ref_by = ?", (user_id,))
    active = await _scalar(
        "SELECT COUNT(*) FROM users WHERE ref_by = ? AND activated = 1", (user_id,)
    )
    return total, active


# --------------------------------------------------------------------------
# Бесплатные генерации
# --------------------------------------------------------------------------


async def add_credits(user_id: int, count: int) -> int:
    await _run("UPDATE users SET credits = credits + ? WHERE id = ?", (count, user_id))
    return await _scalar("SELECT credits FROM users WHERE id = ?", (user_id,))


async def set_credits(user_id: int, value: int) -> int:
    """Выставить баланс ровно. Ниже нуля не опускаем."""
    value = max(0, value)
    await _run("UPDATE users SET credits = ? WHERE id = ?", (value, user_id))
    return value


async def log_grant(admin_id: int, user_id: int, amount: int, balance: int) -> None:
    """Журнал выдач.

    Бесплатное, выданное руками, — это деньги, которых бот не получит.
    Без журнала через месяц не ответить, кто и сколько раздал, а спорят
    об этом всегда задним числом.
    """
    await _run(
        "INSERT INTO grants (at, admin_id, user_id, amount, balance) VALUES (?, ?, ?, ?, ?)",
        (now(), admin_id, user_id, amount, balance),
    )


async def last_grants(limit: int = 15) -> list[aiosqlite.Row]:
    return await _all(
        """
        SELECT g.at, g.amount, g.balance, g.admin_id, u.username, u.first_name, u.id
        FROM grants g LEFT JOIN users u ON u.id = g.user_id
        ORDER BY g.at DESC LIMIT ?
        """,
        (limit,),
    )


async def granted_total() -> int:
    return await _scalar("SELECT COALESCE(SUM(amount), 0) FROM grants WHERE amount > 0")


async def spend_credit(user_id: int) -> bool:
    """Списать одну бесплатную генерацию.

    Условие credits > 0 стоит в самом UPDATE, а не в отдельной проверке:
    два быстрых нажатия на «нарезать» — это две корутины, и между
    «прочитали» и «записали» вторая успевает списать тот же остаток.
    """
    cur = await conn().execute(
        "UPDATE users SET credits = credits - 1 WHERE id = ? AND credits > 0", (user_id,)
    )
    await conn().commit()
    return cur.rowcount > 0


# --------------------------------------------------------------------------
# Работа и деньги
# --------------------------------------------------------------------------


async def log_cut(user_id: int, kind: str, parts: int, paid: int) -> None:
    await _run(
        "INSERT INTO cuts (at, user_id, kind, parts, paid) VALUES (?, ?, ?, ?, ?)",
        (now(), user_id, kind, parts, paid),
    )
    await _run("UPDATE users SET cuts = cuts + 1 WHERE id = ?", (user_id,))


async def log_payment(user_id: int, stars: int, payload: str, charge_id: str | None) -> None:
    await _run(
        "INSERT INTO payments (at, user_id, stars, payload, charge_id) VALUES (?, ?, ?, ?, ?)",
        (now(), user_id, stars, payload, charge_id),
    )
    await _run("UPDATE users SET stars = stars + ? WHERE id = ?", (stars, user_id))


# --------------------------------------------------------------------------
# Статистика
# --------------------------------------------------------------------------


async def overview() -> dict[str, Any]:
    week = now() - 7 * 86400
    month = now() - 30 * 86400
    today = day_start()
    yesterday = day_start(1)

    parts = await _one(
        """
        SELECT
            SUM(parts = 3) p3, SUM(parts = 6) p6, SUM(parts = 9) p9,
            SUM(parts = 12) p12, SUM(parts = 15) p15,
            SUM(kind = 'frame') frames
        FROM cuts
        """
    )
    return {
        "users": await _scalar("SELECT COUNT(*) FROM users"),
        "started": await _scalar("SELECT COUNT(*) FROM users WHERE started = 1"),
        "blocked": await _scalar("SELECT COUNT(*) FROM users WHERE blocked = 1"),
        "new_today": await _scalar("SELECT COUNT(*) FROM users WHERE joined_at >= ?", (today,)),
        "new_week": await _scalar("SELECT COUNT(*) FROM users WHERE joined_at >= ?", (week,)),
        "active_today": await _scalar("SELECT COUNT(*) FROM users WHERE last_seen >= ?", (today,)),
        "active_month": await _scalar("SELECT COUNT(*) FROM users WHERE last_seen >= ?", (month,)),
        "cuts": await _scalar("SELECT COUNT(*) FROM cuts"),
        "cuts_today": await _scalar("SELECT COUNT(*) FROM cuts WHERE at >= ?", (today,)),
        "cuts_yesterday": await _scalar(
            "SELECT COUNT(*) FROM cuts WHERE at >= ? AND at < ?", (yesterday, today)
        ),
        "cuts_week": await _scalar("SELECT COUNT(*) FROM cuts WHERE at >= ?", (week,)),
        "free": await _scalar("SELECT COUNT(*) FROM cuts WHERE paid = 0"),
        "stars": await _scalar("SELECT COALESCE(SUM(stars), 0) FROM payments"),
        "stars_today": await _scalar(
            "SELECT COALESCE(SUM(stars), 0) FROM payments WHERE at >= ?", (today,)
        ),
        "stars_week": await _scalar(
            "SELECT COALESCE(SUM(stars), 0) FROM payments WHERE at >= ?", (week,)
        ),
        "buyers": await _scalar("SELECT COUNT(DISTINCT user_id) FROM payments"),
        "granted": await granted_total(),
        "credits_left": await _scalar("SELECT COALESCE(SUM(credits), 0) FROM users"),
        "referred": await _scalar("SELECT COUNT(*) FROM users WHERE ref_by IS NOT NULL"),
        "referred_active": await _scalar(
            "SELECT COUNT(*) FROM users WHERE ref_by IS NOT NULL AND activated = 1"
        ),
        "parts": {k: int(parts[k] or 0) for k in ("p3", "p6", "p9", "p12", "p15", "frames")}
        if parts
        else {},
    }


async def daily(days: int = 14) -> list[dict[str, Any]]:
    """Сводка по дням: новые, генерации, звёзды.

    Считаем одним проходом по каждой таблице, а не запросом на каждый
    день: четырнадцать дней — это сорок два запроса, и на бесплатном
    хостинге админка начинает думать по несколько секунд.
    """
    since = day_start(days - 1)
    buckets: dict[int, dict[str, int]] = {
        day_start(i): {"new": 0, "cuts": 0, "stars": 0, "paid": 0} for i in range(days)
    }

    def bucket_of(at: int) -> int | None:
        for start in buckets:
            if start <= at < start + 86400:
                return start
        return None

    for row in await _all("SELECT joined_at FROM users WHERE joined_at >= ?", (since,)):
        key = bucket_of(int(row["joined_at"]))
        if key is not None:
            buckets[key]["new"] += 1
    for row in await _all("SELECT at, paid FROM cuts WHERE at >= ?", (since,)):
        key = bucket_of(int(row["at"]))
        if key is not None:
            buckets[key]["cuts"] += 1
            if int(row["paid"]):
                buckets[key]["paid"] += 1
    for row in await _all("SELECT at, stars FROM payments WHERE at >= ?", (since,)):
        key = bucket_of(int(row["at"]))
        if key is not None:
            buckets[key]["stars"] += int(row["stars"])

    return [
        {"day": start, **values}
        for start, values in sorted(buckets.items(), reverse=True)
    ]


async def last_payments(limit: int = 15) -> list[aiosqlite.Row]:
    return await _all(
        """
        SELECT p.at, p.stars, p.payload, u.username, u.first_name
        FROM payments p LEFT JOIN users u ON u.id = p.user_id
        ORDER BY p.at DESC LIMIT ?
        """,
        (limit,),
    )


async def find_user(query: str) -> aiosqlite.Row | None:
    """Найти человека по id или @username — для разбора жалоб."""
    query = query.strip().lstrip("@")
    if query.isdigit():
        return await _one("SELECT * FROM users WHERE id = ?", (int(query),))
    return await _one("SELECT * FROM users WHERE username = ? COLLATE NOCASE", (query,))


async def user_activity(user_id: int) -> dict[str, Any]:
    """Что человек делал: генерации, траты, кого привёл."""
    total, active = await ref_stats(user_id)
    return {
        "cuts": await _scalar("SELECT COUNT(*) FROM cuts WHERE user_id = ?", (user_id,)),
        "paid_cuts": await _scalar(
            "SELECT COUNT(*) FROM cuts WHERE user_id = ? AND paid > 0", (user_id,)
        ),
        "stars": await _scalar(
            "SELECT COALESCE(SUM(stars), 0) FROM payments WHERE user_id = ?", (user_id,)
        ),
        "last_cut": await _scalar(
            "SELECT COALESCE(MAX(at), 0) FROM cuts WHERE user_id = ?", (user_id,)
        ),
        "refs_total": total,
        "refs_active": active,
    }


async def top_users(limit: int = 5) -> list[aiosqlite.Row]:
    return await _all(
        "SELECT username, first_name, cuts, stars FROM users WHERE cuts > 0 "
        "ORDER BY stars DESC, cuts DESC LIMIT ?",
        (limit,),
    )


async def top_inviters(limit: int = 5) -> list[aiosqlite.Row]:
    return await _all(
        """
        SELECT u.username, u.first_name, COUNT(r.id) total,
               SUM(r.activated) active
        FROM users u JOIN users r ON r.ref_by = u.id
        GROUP BY u.id ORDER BY active DESC, total DESC LIMIT ?
        """,
        (limit,),
    )


# --------------------------------------------------------------------------
# Рассылки
# --------------------------------------------------------------------------


async def save_broadcast(
    admin_id: int, total: int, sent: int, blocked: int, failed: int
) -> None:
    await _run(
        "INSERT INTO broadcasts (at, admin_id, total, sent, blocked, failed) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (now(), admin_id, total, sent, blocked, failed),
    )


async def last_broadcasts(limit: int = 10) -> list[aiosqlite.Row]:
    return await _all("SELECT * FROM broadcasts ORDER BY at DESC LIMIT ?", (limit,))


# --------------------------------------------------------------------------
# Настройки и каналы обязательной подписки
# --------------------------------------------------------------------------


async def get_setting(key: str, default: str = "") -> str:
    row = await _one("SELECT value FROM settings WHERE key = ?", (key,))
    return row["value"] if row else default


async def set_setting(key: str, value: str) -> None:
    await _run(
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


async def gate_on() -> bool:
    """Включена ли обязательная подписка.

    Флаг отдельно от списка каналов: админ выключает проверку на время
    (канал переехал, идёт закупка) и не теряет настроенные каналы.
    """
    return await get_setting("gate", "0") == "1"


async def set_gate(on: bool) -> None:
    await set_setting("gate", "1" if on else "0")


async def channels() -> list[aiosqlite.Row]:
    return await _all("SELECT * FROM channels ORDER BY added_at")


async def add_channel(chat_id: str, title: str, link: str | None) -> None:
    await _run(
        "INSERT INTO channels (id, title, link, added_at) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(id) DO UPDATE SET title = excluded.title, link = excluded.link",
        (str(chat_id), title, link, now()),
    )


async def remove_channel(chat_id: str) -> bool:
    before = await _scalar("SELECT COUNT(*) FROM channels WHERE id = ?", (str(chat_id),))
    await _run("DELETE FROM channels WHERE id = ?", (str(chat_id),))
    return bool(before)
