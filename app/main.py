from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand

from .access import all_admin_ids
from .config import load_settings
from .db import Database
from .handlers import admin as admin_handlers
from .handlers import bets as bets_handlers
from .handlers import fallback
from .handlers import menu as menu_handlers
from .handlers import transfer as transfer_handlers
from .middlewares import UserMiddleware

logger = logging.getLogger(__name__)


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("aiogram.event").setLevel(logging.WARNING)

    settings = load_settings()
    db = Database(
        settings.db_path,
        start_balance=settings.start_balance,
        min_bet=settings.min_bet,
        max_pending=settings.max_pending,
    )
    await db.connect()

    bot = Bot(
        settings.bot_token,
        default=DefaultBotProperties(
            parse_mode=ParseMode.HTML,
            link_preview_is_disabled=True,
        ),
    )
    # FSM хранится в памяти: после рестарта незавершённые вводы теряются.
    dp = Dispatcher(storage=MemoryStorage())
    dp["db"] = db
    dp["settings"] = settings

    middleware = UserMiddleware(db)
    dp.message.outer_middleware(middleware)
    dp.callback_query.outer_middleware(middleware)

    dp.include_router(menu_handlers.router)
    dp.include_router(bets_handlers.router)
    dp.include_router(transfer_handlers.router)
    dp.include_router(admin_handlers.router)
    dp.include_router(fallback.router)

    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await bot.set_my_commands(
            [
                BotCommand(command="start", description="Запуск и главное меню"),
                BotCommand(command="menu", description="Главное меню"),
                BotCommand(command="help", description="Правила"),
                BotCommand(command="cancel", description="Отменить ввод"),
            ]
        )
        me = await bot.get_me()
        admins = await all_admin_ids(db, settings)
        logger.info("Запущен @%s; администраторов: %d", me.username, len(admins))
        if not admins:
            logger.warning(
                "Администраторы не назначены: задайте ADMIN_IDS "
                "или используйте /claim с кодом из ADMIN_CLAIM_CODE"
            )
        await dp.start_polling(bot)
    finally:
        await bot.session.close()
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
