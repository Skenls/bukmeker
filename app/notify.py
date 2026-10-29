from __future__ import annotations

import asyncio
import logging

from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup

from .access import all_admin_ids
from .config import Settings
from .db import Database

logger = logging.getLogger(__name__)


async def safe_send(
    bot: Bot,
    chat_id: int,
    text: str,
    keyboard: InlineKeyboardMarkup | None = None,
) -> bool:
    try:
        await bot.send_message(chat_id, text, reply_markup=keyboard)
    except Exception as exc:  # noqa: BLE001 — уведомление не должно ломать основной сценарий
        logger.warning("Не удалось отправить сообщение %s: %s", chat_id, exc)
        return False
    return True


async def notify_admins(
    bot: Bot,
    db: Database,
    settings: Settings,
    text: str,
    keyboard: InlineKeyboardMarkup | None = None,
) -> int:
    sent = 0
    for index, admin_id in enumerate(await all_admin_ids(db, settings)):
        if index:
            await asyncio.sleep(0.05)
        if await safe_send(bot, admin_id, text, keyboard):
            sent += 1
    return sent
