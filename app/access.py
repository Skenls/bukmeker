from __future__ import annotations

from .config import Settings
from .db import Database


async def is_admin(db: Database, settings: Settings, user_id: int) -> bool:
    if user_id in settings.admin_ids:
        return True
    return await db.is_claimed_admin(user_id)


async def all_admin_ids(db: Database, settings: Settings) -> list[int]:
    claimed = await db.claimed_admin_ids()
    return list(dict.fromkeys([*settings.admin_ids, *claimed]))
