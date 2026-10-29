from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from ..access import is_admin
from ..config import Settings
from ..db import ActionError, Database
from ..keyboards import (
    BetCB,
    EventCB,
    MenuCB,
    ProposeCB,
    back_to_menu,
    bet_amount,
    bet_confirm,
    event_card,
    events_list,
    proposal_notification,
    propose_cancel,
    propose_confirm,
)
from ..notify import notify_admins
from ..states import BetStates, ProposeStates
from ..ui import main_screen, show
from ..utils import (
    BET_STATUS_LABELS,
    EVENT_STATUS_LABELS,
    clean_title,
    esc,
    fmt_gold,
    fmt_odds,
    parse_amount,
    parse_odds,
    user_label,
)

router = Router(name="bets")
PAGE_SIZE = 6


async def _render_events(
    callback: CallbackQuery, db: Database, offset: int
) -> None:
    total = await db.count_events("open")
    pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    if total:
        offset = min(max(0, offset), (pages - 1) * PAGE_SIZE)
    else:
        offset = 0
    events = await db.list_events("open", offset, PAGE_SIZE)
    if events:
        text = (
            "🎲 <b>Открытые события</b>\n\n"
            f"Страница {offset // PAGE_SIZE + 1} из {pages}\n"
            "Выбери событие:"
        )
    else:
        text = (
            "🎲 <b>Открытые события</b>\n\n"
            "Пока пусто. Предложи своё событие — админ его проверит."
        )
    await show(callback, text, events_list(events, offset, total, PAGE_SIZE))


@router.callback_query(MenuCB.filter(F.action == "events"))
async def cb_events(callback: CallbackQuery, db: Database) -> None:
    await callback.answer()
    await _render_events(callback, db, 0)


@router.callback_query(EventCB.filter(F.action == "list"))
async def cb_events_page(
    callback: CallbackQuery, callback_data: EventCB, db: Database
) -> None:
    await callback.answer()
    await _render_events(callback, db, callback_data.offset)


@router.callback_query(EventCB.filter(F.action == "view"))
async def cb_event_view(
    callback: CallbackQuery,
    callback_data: EventCB,
    db: Database,
    settings: Settings,
) -> None:
    event = await db.get_event(callback_data.event_id)
    if event is None or event["status"] != "open":
        await callback.answer("Событие уже закрыто.", show_alert=True)
        await _render_events(callback, db, callback_data.offset)
        return

    user_id = callback.from_user.id
    my_bet = await db.get_user_bet(event["id"], user_id)
    admin = await is_admin(db, settings, user_id)
    own = event["proposer_id"] == user_id
    can_bet = not own and not admin and my_bet is None

    text = (
        f"🎲 <b>{esc(event['title'])}</b>\n\n"
        f"№{event['id']} · автор: "
        f"{user_label(event['proposer_name'], event['proposer_username'])}\n"
        f"Коэф.: <b>x{fmt_odds(event['odds_x100'])}</b>\n"
        f"Ставок: {event['bet_count']} · банк: "
        f"{fmt_gold(event['pool'])} голды"
    )
    if my_bet is not None:
        text += (
            f"\n\n🎟 Твоя ставка: {fmt_gold(my_bet['amount'])} × "
            f"x{fmt_odds(my_bet['odds_x100'])}"
        )
    elif own:
        text += "\n\nЭто твоё событие — ставить на него нельзя."
    elif admin:
        text += "\n\nТы администратор — ставки недоступны."

    await callback.answer()
    await show(
        callback,
        text,
        event_card(event["id"], can_bet, callback_data.offset),
    )


@router.callback_query(MenuCB.filter(F.action == "mybets"))
async def cb_my_bets(callback: CallbackQuery, db: Database) -> None:
    bets = await db.list_user_bets(callback.from_user.id)
    lines = ["🎟 <b>Мои ставки</b>", ""]
    if not bets:
        lines.append("Ставок пока нет. Загляни в раздел «События».")
    else:
        for bet in bets:
            status = bet["status"]
            line = (
                f"№{bet['id']} · <b>{esc(bet['event_title'])}</b>\n"
                f"{fmt_gold(bet['amount'])} × x{fmt_odds(bet['odds_x100'])} · "
                f"{BET_STATUS_LABELS.get(status, status)}"
            )
            if status == "won":
                line += f" · выплата {fmt_gold(bet['payout'])}"
            elif status == "refunded":
                line += f" · возврат {fmt_gold(bet['payout'])}"
            elif status == "active":
                possible = bet["amount"] * bet["odds_x100"] // 100
                line += f" · потенциально {fmt_gold(possible)}"
            lines.append(line)
            lines.append("")
        if len(bets) == 10:
            lines.append("Показаны последние 10 ставок.")
    await callback.answer()
    await show(callback, "\n".join(lines).strip(), back_to_menu())


@router.callback_query(MenuCB.filter(F.action == "myevents"))
async def cb_my_events(callback: CallbackQuery, db: Database) -> None:
    events = await db.list_user_events(callback.from_user.id)
    lines = ["🗂 <b>Мои заявки</b>", ""]
    if not events:
        lines.append("Заявок пока нет. Предложи событие через главное меню.")
    else:
        for event in events:
            line = (
                f"№{event['id']} · <b>{esc(event['title'])}</b>\n"
                f"x{fmt_odds(event['odds_x100'])} · "
                f"{EVENT_STATUS_LABELS.get(event['status'], event['status'])}"
            )
            if event["status"] == "open":
                line += f" · ставок: {event['bet_count']}"
            lines.append(line)
            lines.append("")
        if len(events) == 10:
            lines.append("Показаны последние 10 заявок.")
    await callback.answer()
    await show(callback, "\n".join(lines).strip(), back_to_menu())


@router.callback_query(EventCB.filter(F.action == "bet"))
async def cb_event_bet(
    callback: CallbackQuery,
    callback_data: EventCB,
    state: FSMContext,
    db: Database,
    settings: Settings,
) -> None:
    event = await db.get_event(callback_data.event_id)
    user_id = callback.from_user.id
    if event is None or event["status"] != "open":
        await callback.answer("Ставки закрыты.", show_alert=True)
        return
    if event["proposer_id"] == user_id:
        await callback.answer("Нельзя ставить на своё событие.", show_alert=True)
        return
    if await is_admin(db, settings, user_id):
        await callback.answer("Администраторы не делают ставок.", show_alert=True)
        return
    my_bet = await db.get_user_bet(event["id"], user_id)
    if my_bet is not None:
        await callback.answer("Ты уже поставил на это событие.", show_alert=True)
        return
    user = await db.get_user(user_id)
    if user is None or user["balance"] < settings.min_bet:
        await callback.answer("Недостаточно голды для ставки.", show_alert=True)
        return

    await state.clear()
    await state.set_state(BetStates.amount)
    await state.update_data(
        event_id=event["id"],
        title=event["title"],
        odds_x100=event["odds_x100"],
    )
    await callback.answer()
    text = (
        f"🎟 <b>Ставка на событие №{event['id']}</b>\n"
        f"{esc(event['title'])}\n"
        f"Коэф.: <b>x{fmt_odds(event['odds_x100'])}</b>\n\n"
        "Сколько голды поставить?\n"
        f"Минимум: {fmt_gold(settings.min_bet)}\n"
        f"Баланс: <b>{fmt_gold(user['balance'])}</b>"
    )
    await show(callback, text, bet_amount(event["id"]))


@router.message(BetStates.amount, F.text)
async def bet_amount_input(
    message: Message,
    state: FSMContext,
    db: Database,
    settings: Settings,
) -> None:
    data = await state.get_data()
    event_id = data.get("event_id")
    user = await db.get_user(message.from_user.id)
    if event_id is None or user is None:
        await state.clear()
        text, kb = await main_screen(db, settings, message.from_user.id)
        await message.answer("Сессия устарела. Начни заново.\n\n" + text, reply_markup=kb)
        return
    try:
        amount = parse_amount(message.text, settings.min_bet, user["balance"])
    except ValueError as exc:
        await message.answer(f"⚠️ {esc(str(exc))}")
        return

    event = await db.get_event(event_id)
    if event is None or event["status"] != "open":
        await state.clear()
        text, kb = await main_screen(db, settings, message.from_user.id)
        await message.answer("Событие уже закрыто. Ставка не принята.\n\n" + text, reply_markup=kb)
        return
    if event["proposer_id"] == message.from_user.id:
        await state.clear()
        await message.answer("Нельзя ставить на своё событие. Заявка отменена.")
        return
    if await is_admin(db, settings, message.from_user.id):
        await state.clear()
        await message.answer("Администраторы не делают ставок.")
        return
    if await db.get_user_bet(event_id, message.from_user.id) is not None:
        await state.clear()
        await message.answer("Ты уже поставил на это событие.")
        return

    possible = amount * event["odds_x100"] // 100
    await state.update_data(amount=amount)
    await state.set_state(BetStates.confirm)
    text = (
        "🎟 <b>Подтверждение ставки</b>\n\n"
        f"Событие: <b>{esc(event['title'])}</b>\n"
        f"Ставка: <b>{fmt_gold(amount)}</b> голды\n"
        f"Коэф.: <b>x{fmt_odds(event['odds_x100'])}</b>\n"
        f"Потенциальный выигрыш: <b>{fmt_gold(possible)}</b> голды\n\n"
        "Если событие не произойдёт, ставка сгорит."
    )
    await message.answer(text, reply_markup=bet_confirm(event["id"]))


@router.callback_query(BetCB.filter(F.action == "confirm"), BetStates.confirm)
async def cb_bet_confirm(
    callback: CallbackQuery,
    callback_data: BetCB,
    state: FSMContext,
    db: Database,
    settings: Settings,
) -> None:
    data = await state.get_data()
    if data.get("event_id") != callback_data.event_id:
        await callback.answer("Сессия устарела. Начни заново.", show_alert=True)
        return
    amount = data.get("amount")
    if not isinstance(amount, int):
        await state.clear()
        await callback.answer("Сессия устарела. Начни заново.", show_alert=True)
        return

    try:
        result = await db.place_bet(callback.from_user.id, callback_data.event_id, amount)
    except ActionError as exc:
        await state.clear()
        await callback.answer(str(exc), show_alert=True)
        text, kb = await main_screen(db, settings, callback.from_user.id)
        await show(callback, f"❌ Ставка не принята.\n\n{esc(str(exc))}\n\n{text}", kb)
        return

    await state.clear()
    await callback.answer("Ставка принята")
    text = (
        "✅ <b>Ставка принята</b>\n\n"
        f"Событие: <b>{esc(data.get('title', ''))}</b>\n"
        f"Ставка: {fmt_gold(amount)} × x{fmt_odds(result['odds_x100'])}\n"
        f"Возможный выигрыш: <b>{fmt_gold(result['payout'])}</b> голды\n"
        f"Баланс: <b>{fmt_gold(result['balance'])}</b> голды\n\n"
        "Удачи!"
    )
    _, kb = await main_screen(db, settings, callback.from_user.id)
    await show(callback, text, kb)


@router.callback_query(BetCB.filter(F.action == "cancel"))
async def cb_bet_cancel(
    callback: CallbackQuery,
    state: FSMContext,
    db: Database,
    settings: Settings,
) -> None:
    await state.clear()
    await callback.answer("Отменено")
    text, kb = await main_screen(db, settings, callback.from_user.id)
    await show(callback, "Ставка отменена.\n\n" + text, kb)


@router.message(BetStates.amount)
async def bet_amount_not_text(message: Message) -> None:
    await message.answer("Отправь сумму текстом или /cancel.")


@router.message(BetStates.confirm)
async def bet_confirm_not_text(message: Message) -> None:
    await message.answer("Нажми «Подтвердить» или «Отмена», либо /cancel.")


@router.callback_query(MenuCB.filter(F.action == "propose"))
async def cb_propose_start(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    await state.clear()
    await state.set_state(ProposeStates.title)
    await callback.answer()
    text = (
        "➕ <b>Новое событие · шаг 1/2</b>\n\n"
        "Напиши событие и его условие одним сообщением.\n"
        "Например: «Сборная X выиграет матч у Y 1 ноября».\n"
        "Длина: 5–200 символов."
    )
    await show(callback, text, propose_cancel())


@router.message(ProposeStates.title, F.text)
async def propose_title_input(message: Message, state: FSMContext) -> None:
    try:
        title = clean_title(message.text)
    except ValueError as exc:
        await message.answer(f"⚠️ {esc(str(exc))}")
        return
    await state.update_data(title=title)
    await state.set_state(ProposeStates.odds)
    await message.answer(
        "➕ <b>Шаг 2/2: коэффициент</b>\n\n"
        "Введи коэффициент от 1.01 до 100.\n"
        "Например: 1.5, 2, 3.25.",
        reply_markup=propose_cancel(),
    )


@router.message(ProposeStates.odds, F.text)
async def propose_odds_input(message: Message, state: FSMContext) -> None:
    try:
        odds_x100 = parse_odds(message.text)
    except ValueError as exc:
        await message.answer(f"⚠️ {esc(str(exc))}")
        return
    data = await state.get_data()
    title = data.get("title")
    if not isinstance(title, str):
        await state.clear()
        await message.answer("Сессия устарела. Начни заново через /menu.")
        return
    await state.update_data(odds_x100=odds_x100)
    await state.set_state(ProposeStates.confirm)
    text = (
        "📝 <b>Проверь заявку</b>\n\n"
        f"Событие: <b>{esc(title)}</b>\n"
        f"Коэф.: <b>x{fmt_odds(odds_x100)}</b>\n\n"
        "После отправки заявка уйдёт администратору."
    )
    await message.answer(text, reply_markup=propose_confirm())


@router.callback_query(ProposeCB.filter(F.action == "submit"), ProposeStates.confirm)
async def cb_propose_submit(
    callback: CallbackQuery,
    state: FSMContext,
    db: Database,
    settings: Settings,
    bot: Bot,
) -> None:
    data = await state.get_data()
    title = data.get("title")
    odds_x100 = data.get("odds_x100")
    if not isinstance(title, str) or not isinstance(odds_x100, int):
        await state.clear()
        await callback.answer("Сессия устарела. Начни заново.", show_alert=True)
        return
    try:
        event_id = await db.create_event(callback.from_user.id, title, odds_x100)
    except ActionError as exc:
        await state.clear()
        await callback.answer(str(exc), show_alert=True)
        text, kb = await main_screen(db, settings, callback.from_user.id)
        await show(callback, f"❌ Заявка не создана.\n\n{esc(str(exc))}\n\n{text}", kb)
        return

    await state.clear()
    await callback.answer("Заявка отправлена")
    label = user_label(callback.from_user.full_name, callback.from_user.username)
    notification = (
        f"📥 <b>Новая заявка №{event_id}</b>\n\n"
        f"<b>{esc(title)}</b>\n"
        f"Коэф.: <b>x{fmt_odds(odds_x100)}</b>\n"
        f"Автор: {label}\n"
        f"ID автора: <code>{callback.from_user.id}</code>\n\n"
        "Принять или отклонить?"
    )
    sent = await notify_admins(
        bot, db, settings, notification, proposal_notification(event_id)
    )
    text = (
        f"✅ <b>Заявка №{event_id} отправлена</b>\n\n"
        f"{esc(title)}\n"
        f"Коэф.: x{fmt_odds(odds_x100)}\n\n"
        "Статус смотри в «Мои заявки»."
    )
    if sent == 0:
        text += (
            "\n\n⚠️ Администратор ещё не назначен: заявка сохранена, "
            "но уведомление отправить некому."
        )
    _, kb = await main_screen(db, settings, callback.from_user.id)
    await show(callback, text, kb)


@router.callback_query(ProposeCB.filter(F.action == "cancel"))
async def cb_propose_cancel(
    callback: CallbackQuery,
    state: FSMContext,
    db: Database,
    settings: Settings,
) -> None:
    await state.clear()
    await callback.answer("Отменено")
    text, kb = await main_screen(db, settings, callback.from_user.id)
    await show(callback, "Создание заявки отменено.\n\n" + text, kb)


@router.message(ProposeStates.title)
async def propose_title_not_text(message: Message) -> None:
    await message.answer("Отправь название события текстом или /cancel.")


@router.message(ProposeStates.odds)
async def propose_odds_not_text(message: Message) -> None:
    await message.answer("Отправь коэффициент текстом или /cancel.")


@router.message(ProposeStates.confirm)
async def propose_confirm_not_text(message: Message) -> None:
    await message.answer("Нажми «Отправить» или «Отмена», либо /cancel.")


