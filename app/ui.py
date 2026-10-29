from __future__ import annotations

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardMarkup

from .access import is_admin
from .config import Settings
from .db import Database
from .keyboards import main_menu
from .utils import fmt_gold


async def show(
    callback: CallbackQuery,
    text: str,
    keyboard: InlineKeyboardMarkup,
) -> None:
    message = callback.message
    if message is None:
        return
    try:
        await message.edit_text(text, reply_markup=keyboard)
    except TelegramBadRequest as exc:
        if "message is not modified" in exc.message:
            return
        await message.answer(text, reply_markup=keyboard)


async def main_screen(
    db: Database,
    settings: Settings,
    user_id: int,
) -> tuple[str, InlineKeyboardMarkup]:
    user = await db.get_user(user_id)
    balance = int(user["balance"]) if user else 0
    text = (
        "🏠 <b>Главное меню</b>\n"
        f"Баланс: <b>{fmt_gold(balance)}</b> голды\n\n"
        "Выбери действие:"
    )
    return text, main_menu(await is_admin(db, settings, user_id))
