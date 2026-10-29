from __future__ import annotations

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from .utils import fmt_odds, short


class MenuCB(CallbackData, prefix="menu"):
    action: str


class EventCB(CallbackData, prefix="ev"):
    action: str
    event_id: int = 0
    offset: int = 0


class BetCB(CallbackData, prefix="bet"):
    action: str
    event_id: int = 0


class ProposeCB(CallbackData, prefix="prop"):
    action: str


class AdminCB(CallbackData, prefix="adm"):
    action: str
    event_id: int = 0
    offset: int = 0
    outcome: str = ""


def _btn(text: str, callback_data: CallbackData) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=callback_data.pack())


def main_menu(is_admin: bool) -> InlineKeyboardMarkup:
    rows = [
        [
            _btn("🎲 События", MenuCB(action="events")),
            _btn("👤 Профиль", MenuCB(action="profile")),
        ],
        [
            _btn("➕ Предложить событие", MenuCB(action="propose")),
            _btn("📝 Мои ставки", MenuCB(action="mybets")),
        ],
        [
            _btn("🗂 Мои заявки", MenuCB(action="myevents")),
            _btn("🏆 Статистика", MenuCB(action="stats")),
        ],
        [_btn("ℹ️ Помощь", MenuCB(action="help"))],
    ]
    if is_admin:
        rows.append([_btn("🛠 Админ-панель", MenuCB(action="admin"))])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def back_to_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[_btn("🏠 Главное меню", MenuCB(action="main"))]]
    )


def events_list(
    events: list[dict],
    offset: int,
    total: int,
    page_size: int,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for event in events:
        rows.append(
            [
                _btn(
                    f"#{event['id']} · {short(str(event['title']), 38)} · "
                    f"x{fmt_odds(int(event['odds_x100']))}",
                    EventCB(action="view", event_id=int(event["id"]), offset=offset),
                )
            ]
        )

    nav: list[InlineKeyboardButton] = []
    if offset > 0:
        nav.append(
            _btn(
                "⬅️ Назад",
                EventCB(action="list", offset=max(0, offset - page_size)),
            )
        )
    if offset + page_size < total:
        nav.append(
            _btn(
                "Вперёд ➡️",
                EventCB(action="list", offset=offset + page_size),
            )
        )
    if nav:
        rows.append(nav)

    rows.append([_btn("➕ Предложить событие", MenuCB(action="propose"))])
    rows.append([_btn("🏠 Главное меню", MenuCB(action="main"))])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def event_card(event_id: int, can_bet: bool, offset: int) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if can_bet:
        rows.append(
            [
                _btn(
                    "🎟 Сделать ставку",
                    EventCB(action="bet", event_id=event_id, offset=offset),
                )
            ]
        )
    rows.append(
        [
            _btn(
                "⬅️ К событиям",
                EventCB(action="list", offset=offset),
            )
        ]
    )
    rows.append([_btn("🏠 Главное меню", MenuCB(action="main"))])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def bet_amount(event_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_btn("✖️ Отмена", BetCB(action="cancel", event_id=event_id))]
        ]
    )


def bet_confirm(event_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                _btn("✅ Подтвердить", BetCB(action="confirm", event_id=event_id)),
                _btn("✖️ Отмена", BetCB(action="cancel", event_id=event_id)),
            ]
        ]
    )


def propose_cancel() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[_btn("✖️ Отмена", ProposeCB(action="cancel"))]]
    )


def propose_confirm() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                _btn("✅ Отправить", ProposeCB(action="submit")),
                _btn("✖️ Отмена", ProposeCB(action="cancel")),
            ]
        ]
    )


def admin_menu(pending: int, open_events: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_btn(f"📥 Заявки ({pending})", AdminCB(action="pending", offset=0))],
            [_btn(f"🎲 Открытые ({open_events})", AdminCB(action="open", offset=0))],
            [_btn("🏠 Главное меню", MenuCB(action="main"))],
        ]
    )


def admin_pending_list(
    events: list[dict],
    offset: int,
    total: int,
    page_size: int,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for event in events:
        rows.append(
            [
                _btn(
                    f"#{event['id']} · {short(str(event['title']), 34)}",
                    AdminCB(
                        action="pending_view",
                        event_id=int(event["id"]),
                        offset=offset,
                    ),
                )
            ]
        )
    nav: list[InlineKeyboardButton] = []
    if offset > 0:
        nav.append(
            _btn(
                "⬅️ Назад",
                AdminCB(action="pending", offset=max(0, offset - page_size)),
            )
        )
    if offset + page_size < total:
        nav.append(
            _btn(
                "Вперёд ➡️",
                AdminCB(action="pending", offset=offset + page_size),
            )
        )
    if nav:
        rows.append(nav)
    rows.append([_btn("🛠 Админ-панель", MenuCB(action="admin"))])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_pending_card(event_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                _btn(
                    "✅ Принять",
                    AdminCB(action="approve", event_id=event_id),
                ),
                _btn(
                    "❌ Отклонить",
                    AdminCB(action="reject", event_id=event_id),
                ),
            ],
            [_btn("⬅️ К заявкам", AdminCB(action="pending", offset=0))],
            [_btn("🛠 Админ-панель", MenuCB(action="admin"))],
        ]
    )


def admin_open_list(
    events: list[dict],
    offset: int,
    total: int,
    page_size: int,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for event in events:
        rows.append(
            [
                _btn(
                    f"#{event['id']} · {short(str(event['title']), 34)} · "
                    f"x{fmt_odds(int(event['odds_x100']))}",
                    AdminCB(
                        action="open_view",
                        event_id=int(event["id"]),
                        offset=offset,
                    ),
                )
            ]
        )
    nav: list[InlineKeyboardButton] = []
    if offset > 0:
        nav.append(
            _btn(
                "⬅️ Назад",
                AdminCB(action="open", offset=max(0, offset - page_size)),
            )
        )
    if offset + page_size < total:
        nav.append(
            _btn(
                "Вперёд ➡️",
                AdminCB(action="open", offset=offset + page_size),
            )
        )
    if nav:
        rows.append(nav)
    rows.append([_btn("🛠 Админ-панель", MenuCB(action="admin"))])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_event_card(event_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                _btn(
                    "✅ Событие произошло",
                    AdminCB(
                        action="resolve_ask", event_id=event_id, outcome="won"
                    ),
                )
            ],
            [
                _btn(
                    "❌ Событие не произошло",
                    AdminCB(
                        action="resolve_ask", event_id=event_id, outcome="lost"
                    ),
                )
            ],
            [
                _btn(
                    "↩️ Отменить и вернуть ставки",
                    AdminCB(
                        action="resolve_ask",
                        event_id=event_id,
                        outcome="cancelled",
                    ),
                )
            ],
            [
                _btn("⬅️ К событиям", AdminCB(action="open", offset=0)),
                _btn("🛠 Панель", MenuCB(action="admin")),
            ],
        ]
    )


def admin_confirm(event_id: int, outcome: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                _btn(
                    "✅ Подтвердить",
                    AdminCB(
                        action="resolve", event_id=event_id, outcome=outcome
                    ),
                )
            ],
            [
                _btn(
                    "⬅️ Назад",
                    AdminCB(action="open_view", event_id=event_id),
                )
            ],
        ]
    )


def admin_result() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_btn("🎲 Открытые события", AdminCB(action="open", offset=0))],
            [_btn("🛠 Админ-панель", MenuCB(action="admin"))],
        ]
    )


def proposal_notification(event_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                _btn(
                    "✅ Принять",
                    AdminCB(action="approve", event_id=event_id),
                ),
                _btn(
                    "❌ Отклонить",
                    AdminCB(action="reject", event_id=event_id),
                ),
            ]
        ]
    )
