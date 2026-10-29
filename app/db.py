from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import aiosqlite

from .utils import MAX_TITLE, MIN_TITLE, ODDS_MAX_X100, ODDS_MIN_X100


class ActionError(Exception):
    """Ошибка с текстом, который можно показать пользователю."""


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id    INTEGER PRIMARY KEY,
    username   TEXT,
    full_name  TEXT NOT NULL,
    balance    INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS admins (
    user_id  INTEGER PRIMARY KEY,
    added_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    proposer_id  INTEGER NOT NULL REFERENCES users(user_id),
    title        TEXT NOT NULL,
    odds_x100    INTEGER NOT NULL CHECK (odds_x100 BETWEEN 101 AND 10000),
    status       TEXT NOT NULL DEFAULT 'pending'
                 CHECK (status IN ('pending', 'open', 'won', 'lost', 'cancelled', 'rejected')),
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    resolved_at  TEXT,
    resolved_by  INTEGER
);

CREATE TABLE IF NOT EXISTS bets (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id   INTEGER NOT NULL REFERENCES events(id),
    user_id    INTEGER NOT NULL REFERENCES users(user_id),
    amount     INTEGER NOT NULL CHECK (amount > 0),
    odds_x100  INTEGER NOT NULL,
    status     TEXT NOT NULL DEFAULT 'active'
               CHECK (status IN ('active', 'won', 'lost', 'refunded')),
    payout     INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (event_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_events_status ON events(status, id DESC);
CREATE INDEX IF NOT EXISTS idx_bets_user ON bets(user_id, id DESC);
CREATE INDEX IF NOT EXISTS idx_bets_event ON bets(event_id, status);

CREATE TABLE IF NOT EXISTS transfers (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    from_id    INTEGER NOT NULL REFERENCES users(user_id),
    to_id      INTEGER NOT NULL REFERENCES users(user_id),
    amount     INTEGER NOT NULL CHECK (amount > 0),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_transfers_from ON transfers(from_id, id DESC);
CREATE INDEX IF NOT EXISTS idx_transfers_to ON transfers(to_id, id DESC);
"""

EVENT_SELECT = """
SELECT
    e.id, e.proposer_id, e.title, e.odds_x100, e.status,
    e.created_at, e.resolved_at, e.resolved_by,
    u.full_name AS proposer_name,
    u.username  AS proposer_username,
    (SELECT COUNT(*) FROM bets b
     WHERE b.event_id = e.id AND b.status = 'active') AS bet_count,
    (SELECT COALESCE(SUM(b.amount), 0) FROM bets b
     WHERE b.event_id = e.id AND b.status = 'active') AS pool,
    (SELECT COALESCE(SUM(b.amount * b.odds_x100), 0) FROM bets b
     WHERE b.event_id = e.id AND b.status = 'active') AS liability_x100
FROM events e
JOIN users u ON u.user_id = e.proposer_id
"""


class Database:
    def __init__(
        self,
        path: str,
        *,
        start_balance: int,
        min_bet: int,
        max_pending: int,
    ) -> None:
        self._path = path
        self._start_balance = start_balance
        self._min_bet = min_bet
        self._max_pending = max_pending
        self._conn: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("База данных не подключена")
        return self._conn

    async def connect(self) -> None:
        if self._path != ":memory:":
            Path(self._path).expanduser().parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self._path, isolation_level=None)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA synchronous=NORMAL")
        await self._conn.execute("PRAGMA foreign_keys=ON")
        await self._conn.execute("PRAGMA busy_timeout=5000")
        await self._conn.executescript(SCHEMA)

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    @asynccontextmanager
    async def _tx(self) -> AsyncIterator[None]:
        async with self._lock:
            await self.conn.execute("BEGIN IMMEDIATE")
            try:
                yield
            except BaseException:
                await self.conn.rollback()
                raise
            else:
                await self.conn.commit()

    async def _fetchone(
        self, sql: str, params: tuple[Any, ...] = ()
    ) -> dict[str, Any] | None:
        async with self.conn.execute(sql, params) as cur:
            row = await cur.fetchone()
        return dict(row) if row is not None else None

    async def _fetchall(
        self, sql: str, params: tuple[Any, ...] = ()
    ) -> list[dict[str, Any]]:
        async with self.conn.execute(sql, params) as cur:
            rows = await cur.fetchall()
        return [dict(row) for row in rows]

    async def ensure_user(
        self, user_id: int, username: str | None, full_name: str
    ) -> None:
        async with self._tx():
            await self.conn.execute(
                """
                INSERT INTO users (user_id, username, full_name, balance)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    username = excluded.username,
                    full_name = excluded.full_name
                WHERE users.username IS NOT excluded.username
                   OR users.full_name IS NOT excluded.full_name
                """,
                (user_id, username, full_name, self._start_balance),
            )

    async def get_user(self, user_id: int) -> dict[str, Any] | None:
        async with self._lock:
            return await self._fetchone(
                "SELECT user_id, username, full_name, balance, created_at "
                "FROM users WHERE user_id = ?",
                (user_id,),
            )

    async def create_event(self, proposer_id: int, title: str, odds_x100: int) -> int:
        if not (MIN_TITLE <= len(title) <= MAX_TITLE):
            raise ActionError("Некорректная длина названия события.")
        if not (ODDS_MIN_X100 <= odds_x100 <= ODDS_MAX_X100):
            raise ActionError("Коэффициент должен быть от 1.01 до 100.")
        async with self._tx():
            row = await self._fetchone(
                "SELECT COUNT(*) AS c FROM events "
                "WHERE proposer_id = ? AND status = 'pending'",
                (proposer_id,),
            )
            if row and row["c"] >= self._max_pending:
                raise ActionError(
                    f"У вас уже {self._max_pending} заявки на модерации. "
                    "Дождитесь решения администратора."
                )
            cur = await self.conn.execute(
                "INSERT INTO events (proposer_id, title, odds_x100) VALUES (?, ?, ?)",
                (proposer_id, title, odds_x100),
            )
            return int(cur.lastrowid or 0)

    async def get_event(self, event_id: int) -> dict[str, Any] | None:
        async with self._lock:
            return await self._fetchone(
                EVENT_SELECT + " WHERE e.id = ?", (event_id,)
            )

    async def count_events(self, status: str) -> int:
        async with self._lock:
            row = await self._fetchone(
                "SELECT COUNT(*) AS c FROM events WHERE status = ?", (status,)
            )
        return int(row["c"]) if row else 0

    async def list_events(
        self, status: str, offset: int = 0, limit: int = 5
    ) -> list[dict[str, Any]]:
        async with self._lock:
            return await self._fetchall(
                EVENT_SELECT
                + " WHERE e.status = ? ORDER BY e.id DESC LIMIT ? OFFSET ?",
                (status, max(0, limit), max(0, offset)),
            )

    async def list_user_events(
        self, user_id: int, limit: int = 10
    ) -> list[dict[str, Any]]:
        async with self._lock:
            return await self._fetchall(
                """
                SELECT e.*,
                    (SELECT COUNT(*) FROM bets b
                     WHERE b.event_id = e.id AND b.status = 'active') AS bet_count
                FROM events e
                WHERE e.proposer_id = ?
                ORDER BY e.id DESC
                LIMIT ?
                """,
                (user_id, max(0, limit)),
            )

    async def review_event(self, event_id: int, approve: bool) -> dict[str, Any]:
        async with self._tx():
            event = await self._fetchone(
                EVENT_SELECT + " WHERE e.id = ?", (event_id,)
            )
            if event is None:
                raise ActionError("Заявка не найдена.")
            if event["status"] != "pending":
                raise ActionError("Заявка уже обработана.")

            new_status = "open" if approve else "rejected"
            cur = await self.conn.execute(
                "UPDATE events SET status = ? WHERE id = ? AND status = 'pending'",
                (new_status, event_id),
            )
            if cur.rowcount != 1:
                raise ActionError("Заявка уже обработана.")
            event["status"] = new_status
            return event

    async def get_user_bet(
        self, event_id: int, user_id: int
    ) -> dict[str, Any] | None:
        async with self._lock:
            return await self._fetchone(
                "SELECT * FROM bets WHERE event_id = ? AND user_id = ?",
                (event_id, user_id),
            )

    async def list_user_bets(
        self, user_id: int, limit: int = 10
    ) -> list[dict[str, Any]]:
        async with self._lock:
            return await self._fetchall(
                """
                SELECT b.*, e.title AS event_title, e.status AS event_status
                FROM bets b
                JOIN events e ON e.id = b.event_id
                WHERE b.user_id = ?
                ORDER BY b.id DESC
                LIMIT ?
                """,
                (user_id, max(0, limit)),
            )

    async def bets_summary(self, event_id: int) -> dict[str, Any]:
        async with self._lock:
            row = await self._fetchone(
                """
                SELECT COUNT(*) AS count,
                       COALESCE(SUM(amount), 0) AS staked,
                       COALESCE(SUM(amount * odds_x100), 0) AS liability_x100
                FROM bets
                WHERE event_id = ? AND status = 'active'
                """,
                (event_id,),
            )
        return row or {"count": 0, "staked": 0, "liability_x100": 0}

    async def place_bet(
        self, user_id: int, event_id: int, amount: int
    ) -> dict[str, int]:
        if not isinstance(amount, int) or amount < self._min_bet:
            raise ActionError(f"Минимальная ставка — {self._min_bet} голды.")

        # Одна транзакция + условный UPDATE не дают списать голду дважды.
        async with self._tx():
            event = await self._fetchone(
                "SELECT id, proposer_id, odds_x100, status FROM events WHERE id = ?",
                (event_id,),
            )
            if event is None:
                raise ActionError("Событие не найдено.")
            if event["status"] != "open":
                raise ActionError("Ставки на это событие уже закрыты.")
            if event["proposer_id"] == user_id:
                raise ActionError("Нельзя ставить на своё событие.")

            existing = await self._fetchone(
                "SELECT id FROM bets WHERE event_id = ? AND user_id = ?",
                (event_id, user_id),
            )
            if existing is not None:
                raise ActionError("Вы уже сделали ставку на это событие.")

            cur = await self.conn.execute(
                "UPDATE users SET balance = balance - ? "
                "WHERE user_id = ? AND balance >= ?",
                (amount, user_id, amount),
            )
            if cur.rowcount != 1:
                raise ActionError("Недостаточно голды на балансе.")

            payout = amount * event["odds_x100"] // 100
            await self.conn.execute(
                "INSERT INTO bets (event_id, user_id, amount, odds_x100) "
                "VALUES (?, ?, ?, ?)",
                (event_id, user_id, amount, event["odds_x100"]),
            )
            row = await self._fetchone(
                "SELECT balance FROM users WHERE user_id = ?", (user_id,)
            )
            return {
                "payout": payout,
                "balance": int(row["balance"]) if row else 0,
                "odds_x100": int(event["odds_x100"]),
            }

    async def resolve_event(
        self, event_id: int, outcome: str, admin_id: int
    ) -> tuple[dict[str, Any], list[dict[str, int]]]:
        if outcome not in {"won", "lost", "cancelled"}:
            raise ActionError("Некорректный исход события.")

        async with self._tx():
            event = await self._fetchone(
                EVENT_SELECT + " WHERE e.id = ?", (event_id,)
            )
            if event is None:
                raise ActionError("Событие не найдено.")
            if event["status"] != "open":
                raise ActionError("Событие уже закрыто.")

            cur = await self.conn.execute(
                "UPDATE events SET status = ?, resolved_at = datetime('now'), "
                "resolved_by = ? WHERE id = ? AND status = 'open'",
                (outcome, admin_id, event_id),
            )
            if cur.rowcount != 1:
                raise ActionError("Событие уже закрыто.")

            bets = await self._fetchall(
                "SELECT id, user_id, amount, odds_x100 FROM bets "
                "WHERE event_id = ? AND status = 'active'",
                (event_id,),
            )

            notifications: list[dict[str, int]] = []
            for bet in bets:
                amount = int(bet["amount"])
                if outcome == "won":
                    payout = amount * int(bet["odds_x100"]) // 100
                    await self.conn.execute(
                        "UPDATE users SET balance = balance + ? WHERE user_id = ?",
                        (payout, bet["user_id"]),
                    )
                    await self.conn.execute(
                        "UPDATE bets SET status = 'won', payout = ? WHERE id = ?",
                        (payout, bet["id"]),
                    )
                elif outcome == "cancelled":
                    payout = amount
                    await self.conn.execute(
                        "UPDATE users SET balance = balance + ? WHERE user_id = ?",
                        (amount, bet["user_id"]),
                    )
                    await self.conn.execute(
                        "UPDATE bets SET status = 'refunded', payout = ? WHERE id = ?",
                        (amount, bet["id"]),
                    )
                else:
                    payout = 0
                    await self.conn.execute(
                        "UPDATE bets SET status = 'lost', payout = 0 WHERE id = ?",
                        (bet["id"],),
                    )
                notifications.append(
                    {
                        "user_id": int(bet["user_id"]),
                        "amount": amount,
                        "payout": payout,
                    }
                )

            event["status"] = outcome
            return event, notifications

    async def stats_for_user(self, user_id: int) -> dict[str, int]:
        async with self._lock:
            row = await self._fetchone(
                """
                SELECT
                    COUNT(*) AS total,
                    COALESCE(SUM(CASE WHEN status = 'active' THEN 1 ELSE 0 END), 0) AS active,
                    COALESCE(SUM(CASE WHEN status = 'won' THEN 1 ELSE 0 END), 0) AS won,
                    COALESCE(SUM(CASE WHEN status = 'lost' THEN 1 ELSE 0 END), 0) AS lost,
                    COALESCE(SUM(CASE WHEN status = 'refunded' THEN 1 ELSE 0 END), 0) AS refunded,
                    COALESCE(SUM(amount), 0) AS staked,
                    COALESCE(SUM(CASE WHEN status = 'active' THEN amount ELSE 0 END), 0) AS in_play,
                    COALESCE(SUM(CASE WHEN status != 'active'
                                      THEN payout - amount ELSE 0 END), 0) AS net
                FROM bets
                WHERE user_id = ?
                """,
                (user_id,),
            )
        return row or {
            "total": 0,
            "active": 0,
            "won": 0,
            "lost": 0,
            "refunded": 0,
            "staked": 0,
            "in_play": 0,
            "net": 0,
        }

    async def global_stats(self) -> dict[str, int]:
        async with self._lock:
            row = await self._fetchone(
                """
                SELECT
                    (SELECT COUNT(*) FROM users) AS users,
                    (SELECT COUNT(*) FROM events WHERE status = 'open') AS open_events,
                    (SELECT COUNT(*) FROM events WHERE status = 'pending') AS pending_events,
                    (SELECT COUNT(*) FROM bets) AS bets,
                    (SELECT COALESCE(SUM(amount), 0) FROM bets) AS volume
                """
            )
        return row or {
            "users": 0,
            "open_events": 0,
            "pending_events": 0,
            "bets": 0,
            "volume": 0,
        }

    async def leaderboard(self, limit: int = 5) -> list[dict[str, Any]]:
        async with self._lock:
            return await self._fetchall(
                "SELECT user_id, username, full_name, balance FROM users "
                "ORDER BY balance DESC, user_id ASC LIMIT ?",
                (max(0, limit),),
            )

    async def is_claimed_admin(self, user_id: int) -> bool:
        async with self._lock:
            row = await self._fetchone(
                "SELECT 1 AS ok FROM admins WHERE user_id = ?", (user_id,)
            )
        return row is not None

    async def claimed_admin_ids(self) -> list[int]:
        async with self._lock:
            rows = await self._fetchall("SELECT user_id FROM admins")
        return [int(row["user_id"]) for row in rows]

    async def claim_admin(self, user_id: int) -> bool:
        async with self._tx():
            row = await self._fetchone("SELECT COUNT(*) AS c FROM admins")
            if row and row["c"] > 0:
                return False
            await self.conn.execute(
                "INSERT INTO admins (user_id) VALUES (?)", (user_id,)
            )
            return True

    async def find_user_by_query(self, query: str) -> dict[str, Any] | None:
        cleaned = query.strip()
        cleaned = cleaned.removeprefix("@")
        if not cleaned:
            return None

        async with self._lock:
            if cleaned.isdigit():
                return await self._fetchone(
                    "SELECT user_id, username, full_name, balance, created_at FROM users "
                    "WHERE user_id = ? OR LOWER(username) = LOWER(?)",
                    (int(cleaned), cleaned),
                )
            return await self._fetchone(
                "SELECT user_id, username, full_name, balance, created_at FROM users "
                "WHERE LOWER(username) = LOWER(?)",
                (cleaned,),
            )

    async def transfer_gold(
        self, from_user_id: int, to_user_id: int, amount: int
    ) -> dict[str, Any]:
        if from_user_id == to_user_id:
            raise ActionError("Нельзя переводить голду самому себе.")
        if amount <= 0:
            raise ActionError("Сумма перевода должна быть больше нуля.")

        async with self._tx():
            sender = await self._fetchone(
                "SELECT user_id, username, full_name, balance FROM users WHERE user_id = ?",
                (from_user_id,),
            )
            if sender is None:
                raise ActionError("Отправитель не найден.")
            if sender["balance"] < amount:
                raise ActionError("Недостаточно голды для перевода.")

            recipient = await self._fetchone(
                "SELECT user_id, username, full_name, balance FROM users WHERE user_id = ?",
                (to_user_id,),
            )
            if recipient is None:
                raise ActionError("Получатель не найден в боте.")

            new_from_balance = sender["balance"] - amount
            new_to_balance = recipient["balance"] + amount

            await self.conn.execute(
                "UPDATE users SET balance = balance - ? WHERE user_id = ?",
                (amount, from_user_id),
            )
            await self.conn.execute(
                "UPDATE users SET balance = balance + ? WHERE user_id = ?",
                (amount, to_user_id),
            )
            await self.conn.execute(
                "INSERT INTO transfers (from_id, to_id, amount) VALUES (?, ?, ?)",
                (from_user_id, to_user_id, amount),
            )

            return {
                "from_balance": new_from_balance,
                "to_balance": new_to_balance,
                "sender": dict(sender),
                "recipient": dict(recipient),
                "amount": amount,
            }
