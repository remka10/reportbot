from aiogram.fsm.state import State, StatesGroup


class ShiftSelectStates(StatesGroup):
    choosing_shift = State()
    confirm_context = State()
    entering_context = State()
    preview_context = State()  # ИИ оформил контекст — ждём подтверждения педагога
    revising_context = State()  # ждём голосовой/текстовый комментарий для правки контекста
    manual_context = State()  # ручной ввод контекста без ИИ (сохраняется как есть)



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