from aiogram.fsm.state import State, StatesGroup


class ProposeStates(StatesGroup):
    title = State()
    odds = State()
    confirm = State()


class BetStates(StatesGroup):
    amount = State()
    confirm = State()


class TransferStates(StatesGroup):
    recipient = State()
    amount = State()
    confirm = State()
