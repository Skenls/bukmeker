from __future__ import annotations

from aiogram import Router
from aiogram.types import CallbackQuery, Message

router = Router(name="fallback")


@router.message()
async def unknown_message(message: Message) -> None:
    await message.answer("Не понял. Открой /menu или напиши /help.")


@router.callback_query()
async def unknown_callback(callback: CallbackQuery) -> None:
    await callback.answer("Кнопка устарела. Открой /menu.", show_alert=True)
