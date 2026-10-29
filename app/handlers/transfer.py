from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from ..config import Settings
from ..db import ActionError, Database
from ..keyboards import MenuCB, TransferCB, transfer_cancel, transfer_confirm
from ..notify import safe_send
from ..states import TransferStates
from ..ui import main_screen, show
from ..utils import (
    esc,
    fmt_gold,
    parse_transfer_amount,
    user_label,
    validate_recipient_query,
)

router = Router(name="transfer")


@router.callback_query(MenuCB.filter(F.action == "transfer"))
async def cb_transfer_start(
    callback: CallbackQuery,
    state: FSMContext,
    db: Database,
    settings: Settings,
) -> None:
    user = await db.get_user(callback.from_user.id)
    if user is None or user["balance"] <= 0:
        await callback.answer("У вас нет голды для перевода.", show_alert=True)
        return

    await state.clear()
    await state.set_state(TransferStates.recipient)
    await callback.answer()
    text = (
        "💸 <b>Перевод голды · шаг 1/2</b>\n\n"
        f"Твой баланс: <b>{fmt_gold(user['balance'])}</b> голды\n\n"
        "Введи <b>@username</b> или числовой <b>Telegram ID</b> получателя:\n"
        "<i>Получатель должен быть зарегистрирован в боте (хотя бы раз нажать /start).</i>"
    )
    await show(callback, text, transfer_cancel())


@router.callback_query(TransferCB.filter(F.action == "cancel"))
async def cb_transfer_cancel(
    callback: CallbackQuery,
    state: FSMContext,
    db: Database,
    settings: Settings,
) -> None:
    await state.clear()
    await callback.answer("Отменено")
    text, kb = await main_screen(db, settings, callback.from_user.id)
    await show(callback, "Перевод отменён.\n\n" + text, kb)


@router.message(TransferStates.recipient, F.text)
async def transfer_recipient_input(
    message: Message,
    state: FSMContext,
    db: Database,
    settings: Settings,
) -> None:
    try:
        query = validate_recipient_query(message.text)
    except ValueError as exc:
        await message.answer(f"⚠️ {esc(str(exc))}", reply_markup=transfer_cancel())
        return

    recipient = await db.find_user_by_query(query)
    if recipient is None:
        await message.answer(
            "⚠️ Пользователь не найден.\n"
            "Убедись, что @username или ID указаны верно и пользователь уже запускал этого бота (/start).",
            reply_markup=transfer_cancel(),
        )
        return

    if recipient["user_id"] == message.from_user.id:
        await message.answer(
            "⚠️ Нельзя переводить голду самому себе.\n"
            "Укажи @username или ID другого игрока.",
            reply_markup=transfer_cancel(),
        )
        return

    sender = await db.get_user(message.from_user.id)
    if sender is None or sender["balance"] <= 0:
        await state.clear()
        text, kb = await main_screen(db, settings, message.from_user.id)
        await message.answer("У вас нет голды для перевода.\n\n" + text, reply_markup=kb)
        return

    await state.update_data(
        recipient_id=recipient["user_id"],
        recipient_name=recipient["full_name"],
        recipient_username=recipient["username"],
    )
    await state.set_state(TransferStates.amount)

    target_label = user_label(recipient["full_name"], recipient["username"])
    text = (
        "💸 <b>Перевод голды · шаг 2/2</b>\n\n"
        f"Получатель: {target_label} (ID: <code>{recipient['user_id']}</code>)\n"
        f"Твой баланс: <b>{fmt_gold(sender['balance'])}</b> голды\n\n"
        "Сколько голды перевести? Введи целое число:"
    )
    await message.answer(text, reply_markup=transfer_cancel())


@router.message(TransferStates.amount, F.text)
async def transfer_amount_input(
    message: Message,
    state: FSMContext,
    db: Database,
    settings: Settings,
) -> None:
    data = await state.get_data()
    recipient_id = data.get("recipient_id")
    if not recipient_id:
        await state.clear()
        text, kb = await main_screen(db, settings, message.from_user.id)
        await message.answer("Сессия устарела. Начни заново.\n\n" + text, reply_markup=kb)
        return

    sender = await db.get_user(message.from_user.id)
    if sender is None:
        await state.clear()
        text, kb = await main_screen(db, settings, message.from_user.id)
        await message.answer("Профиль не найден.\n\n" + text, reply_markup=kb)
        return

    try:
        amount = parse_transfer_amount(message.text, sender["balance"])
    except ValueError as exc:
        await message.answer(f"⚠️ {esc(str(exc))}", reply_markup=transfer_cancel())
        return

    await state.update_data(amount=amount)
    await state.set_state(TransferStates.confirm)

    recipient_name = data.get("recipient_name", "")
    recipient_username = data.get("recipient_username")
    target_label = user_label(recipient_name, recipient_username)

    text = (
        "📝 <b>Подтверждение перевода</b>\n\n"
        f"Получатель: {target_label}\n"
        f"ID: <code>{recipient_id}</code>\n"
        f"Сумма: <b>{fmt_gold(amount)}</b> голды\n\n"
        f"Остаток на балансе после перевода: <b>{fmt_gold(sender['balance'] - amount)}</b> голды.\n\n"
        "Отправить перевод?"
    )
    await message.answer(text, reply_markup=transfer_confirm(recipient_id))


@router.callback_query(TransferCB.filter(F.action == "submit"), TransferStates.confirm)
async def cb_transfer_submit(
    callback: CallbackQuery,
    callback_data: TransferCB,
    state: FSMContext,
    db: Database,
    settings: Settings,
    bot: Bot,
) -> None:
    data = await state.get_data()
    recipient_id = data.get("recipient_id")
    amount = data.get("amount")
    if (
        not isinstance(recipient_id, int)
        or not isinstance(amount, int)
        or recipient_id != callback_data.recipient_id
    ):
        await state.clear()
        await callback.answer("Сессия устарела. Начни заново.", show_alert=True)
        return

    try:
        result = await db.transfer_gold(
            from_user_id=callback.from_user.id,
            to_user_id=recipient_id,
            amount=amount,
        )
    except ActionError as exc:
        await state.clear()
        await callback.answer(str(exc), show_alert=True)
        text, kb = await main_screen(db, settings, callback.from_user.id)
        await show(callback, f"❌ Перевод не выполнен.\n\n{esc(str(exc))}\n\n{text}", kb)
        return

    await state.clear()
    await callback.answer("Перевод выполнен!")

    sender_label = user_label(
        callback.from_user.full_name or "Игрок",
        callback.from_user.username,
    )
    recipient_text = (
        "🎁 <b>Вам поступил перевод голды!</b>\n\n"
        f"От: {sender_label}\n"
        f"Сумма: <b>+{fmt_gold(amount)}</b> голды\n"
        f"Ваш баланс: <b>{fmt_gold(result['to_balance'])}</b> голды"
    )
    await safe_send(bot, recipient_id, recipient_text)

    recipient_name = data.get("recipient_name", "")
    recipient_username = data.get("recipient_username")
    target_label = user_label(recipient_name, recipient_username)

    text = (
        "✅ <b>Перевод успешно отправлен!</b>\n\n"
        f"Получатель: {target_label}\n"
        f"Сумма: <b>{fmt_gold(amount)}</b> голды\n"
        f"Твой баланс: <b>{fmt_gold(result['from_balance'])}</b> голды"
    )
    _, kb = await main_screen(db, settings, callback.from_user.id)
    await show(callback, text, kb)


@router.message(TransferStates.recipient)
async def transfer_recipient_not_text(message: Message) -> None:
    await message.answer(
        "Отправь @username или ID текстом, либо /cancel.",
        reply_markup=transfer_cancel(),
    )


@router.message(TransferStates.amount)
async def transfer_amount_not_text(message: Message) -> None:
    await message.answer(
        "Отправь сумму числом, либо /cancel.",
        reply_markup=transfer_cancel(),
    )


@router.message(TransferStates.confirm)
async def transfer_confirm_not_text(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    recipient_id = data.get("recipient_id", 0)
    await message.answer(
        "Нажми «Подтвердить перевод» или «Отмена», либо /cancel.",
        reply_markup=transfer_confirm(recipient_id),
    )
