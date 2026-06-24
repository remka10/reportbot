from aiogram.fsm.state import State, StatesGroup


class ShiftSelectStates(StatesGroup):
    choosing_shift = State()
    confirm_context = State()
    entering_context = State()


class ChildSelectStates(StatesGroup):
    choosing_child = State()


class QuestionStates(StatesGroup):
    answering = State()
    waiting_voice = State()


class GenerationStates(StatesGroup):
    generating = State()
    reviewing = State()
    waiting_revision = State()
    finalized = State()