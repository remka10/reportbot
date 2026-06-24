import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, Voice
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.shift_menu import (
    shifts_keyboard, context_exists_keyboard,
)
from app.bot.keyboards.child_menu import children_keyboard, generate_report_keyboard
from app.bot.states.teacher_states import ShiftSelectStates, ChildSelectStates
from app.database.models import User, UserRole
from app.repositories.shift_repo import ShiftRepository
from app.repositories.student_repo import StudentRepository
from app.repositories.answer_repo import AnswerRepository
from app.repositories.report_repo import ReportRepository
from app.services.stt_service import STTService

logger = logging.getLogger(__name__)
router = Router(name="teacher_shift")


def teacher_only(user: User) -> bool:
    return user.role == UserRole.teacher


# ---------------------------------------------------------------------------
# Список смен педагога
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "teacher:shifts")
async def cb_teacher_shifts(
    cb: CallbackQuery, state: FSMContext, user: User, session: AsyncSession
) -> None:
    if not teacher_only(user):
        await cb.answer("Этот раздел только для педагогов.", show_alert=True)
        return

    repo = ShiftRepository(session)
    shifts = list(await repo.get_for_teacher(user.id))

    if not shifts:
        await cb.message.edit_text(
            "У вас пока нет привязанных смен."
            "Обратитесь к администратору."
        )
        return

    await state.set_state(ShiftSelectStates.choosing_shift)
    await cb.message.edit_text(
        "📂 <b>Ваши смены</b>Выберите смену для работы:",
        reply_markup=shifts_keyboard(shifts),
    )


# ---------------------------------------------------------------------------
# Выбор смены → проверка контекста
# ---------------------------------------------------------------------------

@router.callback_query(ShiftSelectStates.choosing_shift, F.data.startswith("teacher:shift:"))
async def cb_shift_selected(
    cb: CallbackQuery, state: FSMContext, user: User, session: AsyncSession
) -> None:
    shift_id = int(cb.data.split(":")[-1])

    shift_repo = ShiftRepository(session)
    shift = await shift_repo.get_by_id(shift_id)
    if not shift:
        await cb.answer("Смена не найдена.", show_alert=True)
        return

    # Сохраняем контекст сессии
    await state.update_data(shift_id=shift_id, shift_name=shift.name)

    # Проверяем наличие контекста смены
    ts = await shift_repo.get_teacher_shift(user.id, shift_id)
    if ts and ts.shift_context:
        await state.update_data(shift_context=ts.shift_context)
        await state.set_state(ShiftSelectStates.confirm_context)
        await cb.message.edit_text(
            f"📂 <b>{shift.name}</b>"
            f"<b>Текущий контекст смены:</b>"
            f"<blockquote>{ts.shift_context[:500]}{'...' if len(ts.shift_context) > 500 else ''}</blockquote>"
            f"Использовать этот контекст или изменить?",
            reply_markup=context_exists_keyboard(),
        )
    else:
        await state.set_state(ShiftSelectStates.entering_context)
        await cb.message.edit_text(
            f"📂 <b>{shift.name}</b>"
            "Введите <b>контекст смены</b> — расскажите о сюжете, "
            "чем занимались дети, ключевые события."
            "Можно написать текстом или отправить <b>голосовое сообщение</b> 🎤",
        )


# ---------------------------------------------------------------------------
# Использовать существующий контекст
# ---------------------------------------------------------------------------

@router.callback_query(ShiftSelectStates.confirm_context, F.data == "teacher:context:use")
async def cb_use_existing_context(
    cb: CallbackQuery, state: FSMContext, user: User, session: AsyncSession
) -> None:
    data = await state.get_data()
    await _show_children_list(cb.message, state, user, session, data["shift_id"], edit=True)


# ---------------------------------------------------------------------------
# Изменить контекст
# ---------------------------------------------------------------------------

@router.callback_query(ShiftSelectStates.confirm_context, F.data == "teacher:context:change")
async def cb_change_context(cb: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(ShiftSelectStates.entering_context)
    await cb.message.edit_text(
        "Введите новый <b>контекст смены</b>:"
        "Можно написать текстом или отправить <b>голосовое сообщение</b> 🎤",
    )


# ---------------------------------------------------------------------------
# Получение контекста — текст
# ---------------------------------------------------------------------------

@router.message(ShiftSelectStates.entering_context, F.text)
async def enter_context_text(
    message: Message, state: FSMContext, user: User, session: AsyncSession
) -> None:
    context = message.text.strip()
    if len(context) < 10:
        await message.answer("⚠️ Контекст слишком короткий. Расскажите подробнее:")
        return
    await _save_context_and_proceed(message, state, user, session, context)


# ---------------------------------------------------------------------------
# Получение контекста — голос
# ---------------------------------------------------------------------------

@router.message(ShiftSelectStates.entering_context, F.voice)
async def enter_context_voice(
    message: Message, state: FSMContext, user: User, session: AsyncSession
) -> None:
    status_msg = await message.answer("🎤 Распознаю голосовое сообщение...")
    try:
        stt = STTService()
        context = await stt.transcribe_voice(message.voice, message.bot)
        await status_msg.delete()
        if not context or len(context.strip()) < 5:
            await message.answer("⚠️ Не удалось распознать. Попробуйте ещё раз или напишите текстом.")
            return
        await message.answer(f"Распознано:<blockquote>{context}</blockquote>")
        await _save_context_and_proceed(message, state, user, session, context.strip())
    except Exception as e:
        logger.error(f"STT error for context: {e}")
        await status_msg.edit_text("⚠️ Ошибка распознавания. Напишите контекст текстом.")


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------

async def _save_context_and_proceed(
    message: Message,
    state: FSMContext,
    user: User,
    session: AsyncSession,
    context: str,
) -> None:
    data = await state.get_data()
    shift_id = data["shift_id"]

    repo = ShiftRepository(session)
    await repo.update_shift_context(user.id, shift_id, context)
    await state.update_data(shift_context=context)

    await _show_children_list(message, state, user, session, shift_id, edit=False)


async def _show_children_list(
    message_or_obj,
    state: FSMContext,
    user: User,
    session: AsyncSession,
    shift_id: int,
    edit: bool = False,
) -> None:
    """Показать список детей с прогресс-индикатором."""
    student_repo = StudentRepository(session)
    answer_repo = AnswerRepository(session)
    report_repo = ReportRepository(session)

    students = list(await student_repo.get_by_shift(shift_id))
    if not students:
        text = "В этой смене пока нет учащихся. Обратитесь к администратору."
        if edit:
            await message_or_obj.edit_text(text)
        else:
            await message_or_obj.answer(text)
        return

    student_ids = [s.id for s in students]
    progress_map = await answer_repo.get_progress_map(user.id, student_ids)
    finalized_ids = await report_repo.get_finalized_student_ids(user.id, shift_id)

    data = await state.get_data()
    shift_name = data.get("shift_name", "")
    done = len(finalized_ids)
    total = len(students)

    text = (
        f"👦 <b>Учащиеся: {shift_name}</b>"
        f"Готово отчётов: {done}/{total}"
        f"Выберите ребёнка:"
    )
    kb = children_keyboard(students, progress_map, finalized_ids)
    await state.set_state(ChildSelectStates.choosing_child)

    if edit:
        await message_or_obj.edit_text(text, reply_markup=kb)
    else:
        await message_or_obj.answer(text, reply_markup=kb)


@router.callback_query(F.data == "teacher:child_list")
async def cb_back_to_children(
    cb: CallbackQuery, state: FSMContext, user: User, session: AsyncSession
) -> None:
    data = await state.get_data()
    shift_id = data.get("shift_id")
    if not shift_id:
        await cb.answer("Сначала выберите смену.", show_alert=True)
        return
    await _show_children_list(cb.message, state, user, session, shift_id, edit=True)