from __future__ import annotations

import asyncio

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from ..access import is_admin
from ..config import Settings
from ..db import ActionError, Database
from ..keyboards import (
    AdminCB,
    MenuCB,
    admin_confirm,
    admin_event_card,
    admin_menu,
    admin_open_list,
    admin_pending_card,
    admin_pending_list,
    admin_result,
)
from ..notify import safe_send
from ..ui import show
from ..utils import EVENT_STATUS_LABELS, esc, fmt_gold, fmt_odds, user_label

router = Router(name="admin")
PAGE_SIZE = 5


async def _require_admin(callback: CallbackQuery, db: Database, settings: Settings) -> bool:
    if await is_admin(db, settings, callback.from_user.id):
        return True
    await callback.answer("Недостаточно прав.", show_alert=True)
    return False


def _panel_text(stats: dict) -> str:
    return (
        "🛠 <b>Админ-панель</b>\n\n"
        f"📥 Заявок на модерации: <b>{stats['pending_events']}</b>\n"
        f"🎲 Открытых событий: <b>{stats['open_events']}</b>"
    )


@router.message(Command("admin"))
async def admin_command(message: Message, db: Database, settings: Settings) -> None:
    if not await is_admin(db, settings, message.from_user.id):
        await message.answer("Недостаточно прав.")
        return
    stats = await db.global_stats()
    await message.answer(
        _panel_text(stats),
        reply_markup=admin_menu(stats["pending_events"], stats["open_events"]),
    )


@router.callback_query(MenuCB.filter(F.action == "admin"))
async def cb_admin_panel(
    callback: CallbackQuery, db: Database, settings: Settings
) -> None:
    if not await _require_admin(callback, db, settings):
        return
    stats = await db.global_stats()
    await callback.answer()
    await show(
        callback,
        _panel_text(stats),
        admin_menu(stats["pending_events"], stats["open_events"]),
    )


@router.callback_query(AdminCB.filter(F.action == "pending"))
async def cb_pending_list(
    callback: CallbackQuery,
    callback_data: AdminCB,
    db: Database,
    settings: Settings,
) -> None:
    if not await _require_admin(callback, db, settings):
        return
    total = await db.count_events("pending")
    pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    offset = min(max(0, callback_data.offset), (pages - 1) * PAGE_SIZE)
    events = await db.list_events("pending", offset, PAGE_SIZE)
    page = offset // PAGE_SIZE + 1
    if events:
        text = (
            "📥 <b>Заявки на модерацию</b>\n\n"
            f"Страница {page} из {pages}\n"
            "Выбери заявку:"
        )
    else:
        text = "📥 <b>Заявки на модерацию</b>\n\nЗаявок нет."
    await callback.answer()
    await show(callback, text, admin_pending_list(events, offset, total, PAGE_SIZE))


@router.callback_query(AdminCB.filter(F.action == "pending_view"))
async def cb_pending_view(
    callback: CallbackQuery,
    callback_data: AdminCB,
    db: Database,
    settings: Settings,
) -> None:
    if not await _require_admin(callback, db, settings):
        return
    event = await db.get_event(callback_data.event_id)
    if event is None:
        await callback.answer("Заявка не найдена.", show_alert=True)
        return
    lines = [
        f"📥 <b>Заявка №{event['id']}</b>",
        "",
        f"<b>{esc(event['title'])}</b>",
        f"Коэф.: <b>x{fmt_odds(event['odds_x100'])}</b>",
        f"Автор: {user_label(event['proposer_name'], event['proposer_username'])}",
        f"Создана: {event['created_at']} UTC",
    ]
    if event["status"] != "pending":
        lines.append(f"\nСтатус: {EVENT_STATUS_LABELS.get(event['status'], event['status'])}")
        keyboard = admin_result()
    else:
        keyboard = admin_pending_card(event["id"])
    await callback.answer()
    await show(callback, "\n".join(lines), keyboard)


@router.callback_query(AdminCB.filter(F.action.in_({"approve", "reject"})))
async def cb_review(
    callback: CallbackQuery,
    callback_data: AdminCB,
    db: Database,
    settings: Settings,
    bot: Bot,
) -> None:
    if not await _require_admin(callback, db, settings):
        return
    approve = callback_data.action == "approve"
    try:
        event = await db.review_event(callback_data.event_id, approve=approve)
    except ActionError as exc:
        await callback.answer(str(exc), show_alert=True)
        event = await db.get_event(callback_data.event_id)
        if event is not None:
            await show(
                callback,
                f"Заявка №{event['id']}: {EVENT_STATUS_LABELS.get(event['status'], event['status'])}",
                admin_result(),
            )
        return

    title = esc(event["title"])
    if approve:
        await safe_send(
            bot,
            event["proposer_id"],
            (
                f"✅ <b>Заявка №{event['id']} принята</b>\n\n"
                f"{title}\n"
                f"Коэф.: <b>x{fmt_odds(event['odds_x100'])}</b>\n\n"
                "Событие открыто для ставок."
            ),
        )
        text = (
            f"✅ <b>Заявка №{event['id']} принята</b>\n\n"
            f"{title}\n\nСобытие открыто для ставок."
        )
        note = "Принято"
    else:
        await safe_send(
            bot,
            event["proposer_id"],
            (
                f"❌ <b>Заявка №{event['id']} отклонена</b>\n\n"
                f"{title}"
            ),
        )
        text = f"❌ <b>Заявка №{event['id']} отклонена</b>\n\n{title}"
        note = "Отклонено"
    await callback.answer(note)
    await show(callback, text, admin_result())


@router.callback_query(AdminCB.filter(F.action == "open"))
async def cb_open_list(
    callback: CallbackQuery,
    callback_data: AdminCB,
    db: Database,
    settings: Settings,
) -> None:
    if not await _require_admin(callback, db, settings):
        return
    total = await db.count_events("open")
    pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    offset = min(max(0, callback_data.offset), (pages - 1) * PAGE_SIZE)
    events = await db.list_events("open", offset, PAGE_SIZE)
    page = offset // PAGE_SIZE + 1
    if events:
        text = (
            "🎲 <b>Открытые события</b>\n\n"
            f"Страница {page} из {pages}\n"
            "Выбери событие для расчёта:"
        )
    else:
        text = "🎲 <b>Открытые события</b>\n\nОткрытых событий нет."
    await callback.answer()
    await show(callback, text, admin_open_list(events, offset, total, PAGE_SIZE))


def _admin_event_text(event: dict) -> str:
    return (
        f"🎲 <b>Событие №{event['id']}</b>\n\n"
        f"<b>{esc(event['title'])}</b>\n"
        f"Коэф.: <b>x{fmt_odds(event['odds_x100'])}</b>\n"
        f"Автор: {user_label(event['proposer_name'], event['proposer_username'])}\n"
        f"Ставок: {event['bet_count']} · банк: {fmt_gold(event['pool'])} голды\n"
        f"Потенциальная выплата: {fmt_gold(event['liability_x100'] // 100)} голды"
    )


@router.callback_query(AdminCB.filter(F.action == "open_view"))
async def cb_open_view(
    callback: CallbackQuery,
    callback_data: AdminCB,
    db: Database,
    settings: Settings,
) -> None:
    if not await _require_admin(callback, db, settings):
        return
    event = await db.get_event(callback_data.event_id)
    if event is None:
        await callback.answer("Событие не найдено.", show_alert=True)
        return
    if event["status"] != "open":
        await callback.answer("Событие уже закрыто.", show_alert=True)
        await show(
            callback,
            f"🎲 Событие №{event['id']}: {EVENT_STATUS_LABELS.get(event['status'], event['status'])}",
            admin_result(),
        )
        return
    await callback.answer()
    await show(callback, _admin_event_text(event), admin_event_card(event["id"]))


@router.callback_query(AdminCB.filter(F.action == "resolve_ask"))
async def cb_resolve_ask(
    callback: CallbackQuery,
    callback_data: AdminCB,
    db: Database,
    settings: Settings,
) -> None:
    if not await _require_admin(callback, db, settings):
        return
    if callback_data.outcome not in {"won", "lost", "cancelled"}:
        await callback.answer("Неверный исход.", show_alert=True)
        return
    event = await db.get_event(callback_data.event_id)
    if event is None or event["status"] != "open":
        await callback.answer("Событие уже закрыто.", show_alert=True)
        return
    summary = await db.bets_summary(event["id"])
    outcome = callback_data.outcome
    if outcome == "won":
        action_text = (
            f"Исход: <b>событие произошло</b>\n"
            f"К выплате: <b>{fmt_gold(summary['liability_x100'] // 100)}</b> голды"
        )
    elif outcome == "lost":
        action_text = (
            f"Исход: <b>событие не произошло</b>\n"
            f"Сгорит: <b>{fmt_gold(summary['staked'])}</b> голды"
        )
    else:
        action_text = (
            f"Исход: <b>отмена</b>\n"
            f"К возврату: <b>{fmt_gold(summary['staked'])}</b> голды"
        )
    text = (
        f"⚠️ <b>Расчёт события №{event['id']}</b>\n\n"
        f"<b>{esc(event['title'])}</b>\n"
        f"{action_text}\n"
        f"Затронуто ставок: <b>{summary['count']}</b>\n\n"
        "Подтвердить расчёт?"
    )
    await callback.answer()
    await show(callback, text, admin_confirm(event["id"], outcome))


@router.callback_query(AdminCB.filter(F.action == "resolve"))
async def cb_resolve(
    callback: CallbackQuery,
    callback_data: AdminCB,
    db: Database,
    settings: Settings,
    bot: Bot,
) -> None:
    if not await _require_admin(callback, db, settings):
        return
    outcome = callback_data.outcome
    if outcome not in {"won", "lost", "cancelled"}:
        await callback.answer("Неизвестный исход.", show_alert=True)
        return
    try:
        event, bets = await db.resolve_event(
            callback_data.event_id, outcome, callback.from_user.id
        )
    except ActionError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    title = esc(event["title"])
    total_paid = sum(item["payout"] for item in bets)
    total_staked = sum(item["amount"] for item in bets)
    for index, item in enumerate(bets):
        if outcome == "won":
            text = (
                f"🎉 <b>Событие №{event['id']} сыграло!</b>\n\n{title}\n"
                f"Ставка: {fmt_gold(item['amount'])} × x{fmt_odds(event['odds_x100'])}\n"
                f"Выплата: <b>{fmt_gold(item['payout'])}</b> голды."
            )
        elif outcome == "lost":
            text = (
                f"😔 <b>Событие №{event['id']} не сыграло</b>\n\n{title}\n"
                f"Ставка {fmt_gold(item['amount'])} голды сгорела."
            )
        else:
            text = (
                f"↩️ <b>Событие №{event['id']} отменено</b>\n\n{title}\n"
                f"Возврат: <b>{fmt_gold(item['amount'])}</b> голды."
            )
        await safe_send(bot, item["user_id"], text)
        if index % 20 == 19:
            await asyncio.sleep(1)
    names = {"won": "произошло", "lost": "не произошло", "cancelled": "отменено"}
    await safe_send(
        bot,
        event["proposer_id"],
        f"ℹ️ Событие №{event['id']} «{title}» рассчитано.\n"
        f"Исход: <b>{names[outcome]}</b>.",
    )
    if outcome == "won":
        result = (
            f"✅ <b>Событие №{event['id']} рассчитано</b>\n\n{title}\n"
            f"Исход: произошло\nВыплачено: <b>{fmt_gold(total_paid)}</b> голды."
        )
    elif outcome == "lost":
        result = (
            f"❌ <b>Событие №{event['id']} рассчитано</b>\n\n{title}\n"
            f"Исход: не произошло\nСгорело: {fmt_gold(total_staked)} голды."
        )
    else:
        result = (
            f"↩️ <b>Событие №{event['id']} отменено</b>\n\n{title}\n"
            f"Возвращено: <b>{fmt_gold(total_staked)}</b> голды."
        )
    await callback.answer("Событие рассчитано.")
    await show(callback, result, admin_result())
