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
    # Ответ на вопрос принимается прямо в состоянии answering: и текстом, и
    # голосом. Голос расшифровывается асинхронно в фоне (см. teacher/questions.py),
    # поэтому отдельное состояние ожидания голоса больше не нужно.



class GenerationStates(StatesGroup):
    generating = State()
    reviewing = State()
    waiting_revision = State()
    finalized = State()