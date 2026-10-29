from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from aiogram import html

MIN_TITLE = 5
MAX_TITLE = 200
ODDS_MIN_X100 = 101
ODDS_MAX_X100 = 10_000

_ODDS_RE = re.compile(r"^(?:100(?:\.0{1,2})?|[1-9]\d?(?:\.\d{1,2})?)$")
_AMOUNT_RE = re.compile(r"^\d{1,9}$")

EVENT_STATUS_LABELS = {
    "pending": "⏳ на модерации",
    "open": "🟢 открыто",
    "won": "✅ событие произошло",
    "lost": "❌ событие не произошло",
    "cancelled": "↩️ отменено",
    "rejected": "🚫 отклонено",
}

BET_STATUS_LABELS = {
    "active": "🟡 активна",
    "won": "✅ выиграла",
    "lost": "❌ проиграла",
    "refunded": "↩️ возврат",
}


def esc(value: object) -> str:
    return html.quote(str(value))


def short(value: str, limit: int = 36) -> str:
    return value if len(value) <= limit else value[: limit - 1] + "…"


def fmt_gold(amount: int) -> str:
    return f"{amount:,}".replace(",", " ")


def fmt_signed(amount: int) -> str:
    sign = "+" if amount >= 0 else "−"
    return f"{sign}{fmt_gold(abs(amount))}"


def fmt_odds(odds_x100: int) -> str:
    return f"{odds_x100 / 100:.2f}".rstrip("0").rstrip(".")


def user_label(full_name: str | None, username: str | None) -> str:
    name = esc(full_name or "Игрок")
    return f"{name} (@{esc(username)})" if username else name


def clean_title(raw: str) -> str:
    # Убираем управляющие и невидимые символы, затем схлопываем пробелы.
    cleaned = "".join(ch for ch in raw if ch.isprintable() or ch.isspace())
    title = " ".join(cleaned.split())
    if not (MIN_TITLE <= len(title) <= MAX_TITLE):
        raise ValueError(f"Название должно быть от {MIN_TITLE} до {MAX_TITLE} символов.")
    return title


def parse_odds(raw: str) -> int:
    text = raw.strip().replace(",", ".")
    if not _ODDS_RE.fullmatch(text):
        raise ValueError("Коэффициент — число от 1.01 до 100, не более 2 знаков после запятой.")
    try:
        odds_x100 = int(Decimal(text) * 100)
    except InvalidOperation:
        raise ValueError("Не удалось разобрать коэффициент.") from None
    if not (ODDS_MIN_X100 <= odds_x100 <= ODDS_MAX_X100):
        raise ValueError("Коэффициент должен быть от 1.01 до 100.")
    return odds_x100


def parse_amount(raw: str, min_bet: int, balance: int) -> int:
    text = raw.strip()
    if not _AMOUNT_RE.fullmatch(text):
        raise ValueError("Сумма — целое число голды без пробелов и знаков.")
    amount = int(text)
    if amount < min_bet:
        raise ValueError(f"Минимальная ставка — {fmt_gold(min_bet)} голды.")
    if amount > balance:
        raise ValueError(f"Недостаточно голды. Баланс: {fmt_gold(balance)}.")
    return amount
