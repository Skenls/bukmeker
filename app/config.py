from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True, slots=True)
class Settings:
    bot_token: str
    admin_ids: tuple[int, ...]
    admin_claim_code: str
    db_path: str
    start_balance: int
    min_bet: int
    max_pending: int


def _positive_int(name: str, default: int) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError:
        raise RuntimeError(f"{name} должен быть целым числом") from None
    if value <= 0:
        raise RuntimeError(f"{name} должен быть больше нуля")
    return value


def _parse_admins(raw: str) -> tuple[int, ...]:
    ids: list[int] = []
    for part in raw.replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        if not part.isdigit() or int(part) <= 0:
            raise RuntimeError(f"ADMIN_IDS: некорректный Telegram ID {part!r}")
        ids.append(int(part))
    return tuple(dict.fromkeys(ids))


def load_settings() -> Settings:
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("BOT_TOKEN не задан. Заполните .env")

    start_balance = _positive_int("START_BALANCE", 50000)
    min_bet = _positive_int("MIN_BET", 10)
    max_pending = _positive_int("MAX_PENDING", 3)
    if min_bet > start_balance:
        raise RuntimeError("MIN_BET не может быть больше START_BALANCE")

    return Settings(
        bot_token=token,
        admin_ids=_parse_admins(os.getenv("ADMIN_IDS", "")),
        admin_claim_code=os.getenv("ADMIN_CLAIM_CODE", "").strip(),
        db_path=os.getenv("DB_PATH", "./data/bot.db").strip() or "./data/bot.db",
        start_balance=start_balance,
        min_bet=min_bet,
        max_pending=max_pending,
    )
