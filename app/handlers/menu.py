from __future__ import annotations

import secrets

from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from ..access import is_admin
from ..config import Settings
from ..db import Database
from ..keyboards import MenuCB, main_menu
from ..ui import main_screen, show
from ..utils import (
    esc,
    fmt_gold,
    fmt_signed,
    short,
    user_label,
)

router = Router(name="menu")


def _welcome_text(user: dict, is_admin_user: bool) -> str:
    label = user_label(user["full_name"], user["username"])
    balance = fmt_gold(int(user["balance"]))
    admin_note = "\n🛠 Доступна админ-панель." if is_admin_user else ""
    return (
        "🪙 <b>GoldBet</b>\n\n"
        f"Привет, {label}!\n"
        f"Баланс: <b>{balance}</b> голды.\n\n"
        "Ставь вымышленную голду на события, предлагай свои "
        "и следи за статистикой.\n\n"
        "Выбери раздел:" + admin_note
    )


def _help_text(settings: Settings) -> str:
    return (
        "ℹ️ <b>Правила и помощь</b>\n\n"
        "🪙 Голда — вымышленная валюта. Реальных денег в боте нет.\n"
        "🎲 В разделе «События» выбери открытое событие и сделай ставку.\n"
        "➕ Любой игрок может предложить событие с коэффициентом. "
        "Заявку проверяет администратор.\n\n"
        "<b>Расчёт</b>\n"
        "• Коэффициент: от 1.01 до 100.\n"
        f"• Минимальная ставка: {fmt_gold(settings.min_bet)} голды.\n"
        "• Выигрыш = ставка × коэффициент, округление вниз.\n"
        "• Если событие не произошло — ставка сгорает.\n"
        "• При отмене события ставка возвращается.\n"
        "• Одна ставка на одно событие.\n\n"
        "<b>Ограничения</b>\n"
        "• На своё событие ставить нельзя.\n"
        "• Администраторы не делают ставок.\n"
        f"• Заявок на модерации одновременно: до {settings.max_pending}.\n\n"
        "<b>Команды</b>\n"
        "/start — запуск\n"
        "/menu — главное меню\n"
        "/cancel — отменить ввод\n"
        "/help — эта справка"
    )


@router.message(CommandStart())
async def start(
    message: Message,
    db: Database,
    settings: Settings,
) -> None:
    user = await db.get_user(message.from_user.id)
    if user is None:
        await message.answer("Не удалось загрузить профиль. Попробуй /start ещё раз.")
        return
    admin = await is_admin(db, settings, message.from_user.id)
    await message.answer(
        _welcome_text(user, admin),
        reply_markup=main_menu(admin),
    )


@router.message(Command("menu"))
async def menu(message: Message, db: Database, settings: Settings) -> None:
    text, keyboard = await main_screen(db, settings, message.from_user.id)
    await message.answer(text, reply_markup=keyboard)


@router.message(Command("help"))
async def help_command(
    message: Message, db: Database, settings: Settings
) -> None:
    await message.answer(
        _help_text(settings),
        reply_markup=main_menu(await is_admin(db, settings, message.from_user.id)),
    )


@router.message(Command("cancel"))
async def cancel_command(
    message: Message,
    state: FSMContext,
    db: Database,
    settings: Settings,
) -> None:
    await state.clear()
    text, keyboard = await main_screen(db, settings, message.from_user.id)
    await message.answer("Отменено.\n\n" + text, reply_markup=keyboard)


@router.message(Command("claim"))
async def claim_admin(
    message: Message,
    command: CommandObject,
    db: Database,
    settings: Settings,
) -> None:
    user_id = message.from_user.id
    if await is_admin(db, settings, user_id):
        await message.answer("Вы уже администратор.")
        return
    if settings.admin_ids:
        await message.answer("Администратор уже настроен через ADMIN_IDS.")
        return
    if not settings.admin_claim_code:
        await message.answer(
            "Bootstrap-код не настроен. Задайте ADMIN_IDS или "
            "ADMIN_CLAIM_CODE в .env и перезапустите бота."
        )
        return
    code = (command.args or "").strip()
    if not code or not secrets.compare_digest(code, settings.admin_claim_code):
        await message.answer("Неверный код.")
        return
    if not await db.claim_admin(user_id):
        await message.answer("Администратор уже назначен.")
        return
    await message.answer(
        "✅ Готово. Теперь вы администратор.\n"
        "Заявки на события будут приходить вам в личные сообщения.",
        reply_markup=main_menu(True),
    )


@router.callback_query(MenuCB.filter(F.action == "main"))
async def cb_main(
    callback: CallbackQuery,
    db: Database,
    settings: Settings,
) -> None:
    await callback.answer()
    text, keyboard = await main_screen(db, settings, callback.from_user.id)
    await show(callback, text, keyboard)


@router.callback_query(MenuCB.filter(F.action == "profile"))
async def cb_profile(
    callback: CallbackQuery, db: Database, settings: Settings
) -> None:
    await callback.answer()
    user = await db.get_user(callback.from_user.id)
    if user is None:
        await show(callback, "Профиль не найден. Открой /start.", main_menu(False))
        return
    stats = await db.stats_for_user(callback.from_user.id)
    label = user_label(user["full_name"], user["username"])
    text = (
        "👤 <b>Профиль</b>\n\n"
        f"{label}\n"
        f"ID: <code>{int(user['user_id'])}</code>\n\n"
        f"🪙 Баланс: <b>{fmt_gold(int(user['balance']))}</b> голды\n"
        f"🎟 Ставок: {stats['total']} · в игре: {stats['active']} "
        f"({fmt_gold(stats['in_play'])} голды)\n"
        f"✅ Выиграно: {stats['won']} · ❌ Проиграно: {stats['lost']} · "
        f"↩️ Возвратов: {stats['refunded']}\n"
        f"📈 Оборот: {fmt_gold(stats['staked'])} голды\n"
        f"💵 Профит по закрытым: <b>{fmt_signed(stats['net'])}</b> голды"
    )
    await show(callback, text, main_menu(await is_admin(db, settings, callback.from_user.id)))


@router.callback_query(MenuCB.filter(F.action == "stats"))
async def cb_stats(callback: CallbackQuery, db: Database, settings: Settings) -> None:
    await callback.answer()
    stats = await db.global_stats()
    leaders = await db.leaderboard(5)
    lines: list[str] = []
    for index, row in enumerate(leaders, start=1):
        name = esc(short(str(row["full_name"]), 24))
        if row["username"]:
            name += f" (@{esc(row['username'])})"
        marker = " ← ты" if int(row["user_id"]) == callback.from_user.id else ""
        lines.append(
            f"{index}. {name} — <b>{fmt_gold(int(row['balance']))}</b>{marker}"
        )
    top = "\n".join(lines) if lines else "—"
    text = (
        "📊 <b>Статистика</b>\n\n"
        f"👥 Игроков: {stats['users']}\n"
        f"🎲 Открытых событий: {stats['open_events']}\n"
        f"⏳ На модерации: {stats['pending_events']}\n"
        f"🎟 Ставок: {stats['bets']} на {fmt_gold(stats['volume'])} голды\n\n"
        f"🏆 <b>Топ по балансу</b>\n{top}"
    )
    await show(callback, text, main_menu(await is_admin(db, settings, callback.from_user.id)))


@router.callback_query(MenuCB.filter(F.action == "help"))
async def cb_help(
    callback: CallbackQuery,
    settings: Settings,
    db: Database,
) -> None:
    await callback.answer()
    await show(
        callback,
        _help_text(settings),
        main_menu(await is_admin(db, settings, callback.from_user.id)),
    )
