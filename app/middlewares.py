from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.enums import ChatType
from aiogram.types import CallbackQuery, Message, TelegramObject

from .db import Database


class UserMiddleware(BaseMiddleware):
    def __init__(self, db: Database) -> None:
        self.db = db

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if isinstance(event, Message) and event.chat.type != ChatType.PRIVATE:
            return None
        if (
            isinstance(event, CallbackQuery)
            and event.message is not None
            and event.message.chat.type != ChatType.PRIVATE
        ):
            return None

        user = getattr(event, "from_user", None)
        if user is None or user.is_bot:
            return await handler(event, data)

        await self.db.ensure_user(
            user.id,
            user.username,
            user.full_name or "Игрок",
        )
        return await handler(event, data)
