import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.shift_menu import shifts_keyboard, context_exists_keyboard
from app.bot.keyboards.child_menu import children_keyboard
from app.bot.states.teacher_states import ShiftSelectStates, ChildSelectStates
from app.database.models import User
from app.repositories.shift_repo import ShiftRepository
from app.repositories.answer_repo import AnswerRepository
from app.repositories.report_repo import ReportRepository
from app.repositories.student_repo import StudentRepository
from app.services.stt_service import STTService

logger = logging.getLogger(__name__)
router = Router(name="teacher_shift")
stt_service = STTService()


@router.callback_query(F.data == "teacher:shifts")
async def show_shifts(
    callback: CallbackQuery, user: User, session: AsyncSession, state: FSMContext
) -> None:
    """Показывает список смен педагога."""
    await state.clear()
    shift_repo = ShiftRepository(session)
    shifts = list(await shift_repo.get_for_teacher(user.id))

    if not shifts:
        await callback.message.edit_text(
            "📭 У вас нет привязанных смен.\n"
            "Обратитесь к администратору."
        )
        await callback.answer()
        return

    await callback.message.edit_text(
        "📂 <b>Ваши смены</b>\n\nВыберите смену для работы:",
        reply_markup=shifts_keyboard(shifts),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("teacher:shift:"))
async def select_shift(
    callback: CallbackQuery, user: User, session: AsyncSession, state: FSMContext
) -> None:
    """Обрабатывает выбор смены."""
    shift_id = int(callback.data.split(":")[-1])
    shift_repo = ShiftRepository(session)

    shift = await shift_repo.get_by_id(shift_id)
    if shift is None:
        await callback.answer("❌ Смена не найдена", show_alert=True)
        return

    # Проверяем — есть ли контекст смены
    teacher_shift = await shift_repo.get_teacher_shift(user.id, shift_id)
    if teacher_shift is None:
        await callback.answer("❌ Вы не привязаны к этой смене", show_alert=True)
        return

    # Сохраняем выбранную смену в FSM
    await state.update_data(shift_id=shift_id)

    if teacher_shift.shift_context:
        # Контекст уже есть — показываем и предлагаем выбор
        context_preview = (
            teacher_shift.shift_context[:300] + "..."
            if len(teacher_shift.shift_context) > 300
            else teacher_shift.shift_context
        )
        await callback.message.edit_text(
            f"📂 <b>{shift.name}</b>\n"
            f"🏢 {shift.department_name}\n\n"
            f"<b>Контекст смены:</b>\n<i>{context_preview}</i>\n\n"
            "Использовать сохранённый контекст или ввести новый?",
            reply_markup=context_exists_keyboard(),
        )
        await state.set_state(ShiftSelectStates.confirm_context)
    else:
        # Контекста нет — просим ввести
        await callback.message.edit_text(
            f"📂 <b>{shift.name}</b>\n"
            f"🏢 {shift.department_name}\n\n"
            "✏️ <b>Введите контекст смены</b> — расскажите о сюжете, "
            "чем занимались дети, ключевые события.\n\n"
            "Можно написать текстом или отправить <b>голосовое сообщение</b>."
        )
        await state.set_state(ShiftSelectStates.entering_context)

    await callback.answer()


@router.callback_query(
    ShiftSelectStates.confirm_context, F.data == "teacher:context:use"
)
async def use_existing_context(
    callback: CallbackQuery, user: User, session: AsyncSession, state: FSMContext
) -> None:
    """Педагог выбирает использовать существующий контекст."""
    data = await state.get_data()
    shift_id = data["shift_id"]
    await _show_children(callback, user, session, state, shift_id)
    await callback.answer()


@router.callback_query(
    ShiftSelectStates.confirm_context, F.data == "teacher:context:change"
)
async def change_context(
    callback: CallbackQuery, state: FSMContext
) -> None:
    """Педагог хочет изменить контекст."""
    await callback.message.edit_text(
        "✏️ <b>Введите новый контекст смены:</b>\n\n"
        "Расскажите о сюжете, чем занимались дети, ключевые события.\n"
        "Можно написать текстом или отправить голосовое сообщение."
    )
    await state.set_state(ShiftSelectStates.entering_context)
    await callback.answer()


@router.message(ShiftSelectStates.entering_context, F.text)
async def save_context_text(
    message: Message, user: User, session: AsyncSession, state: FSMContext
) -> None:
    """Педагог вводит контекст текстом."""
    data = await state.get_data()
    shift_id = data["shift_id"]
    shift_repo = ShiftRepository(session)

    await shift_repo.update_context(user.id, shift_id, message.text.strip())
    await _show_children_message(message, user, session, state, shift_id)


@router.message(ShiftSelectStates.entering_context, F.voice)
async def save_context_voice(
    message: Message, user: User, session: AsyncSession, state: FSMContext
) -> None:
    """Педагог вводит контекст голосом."""
    data = await state.get_data()
    shift_id = data["shift_id"]

    processing_msg = await message.answer("⏳ Распознаю голосовое сообщение...")

    try:
        transcription = await stt_service.transcribe_voice(
            message.voice, message.bot
        )
    except ValueError as e:
        await processing_msg.delete()
        await message.answer(f"❌ {e}")
        return
    except Exception as e:
        logger.error(f"STT error in save_context_voice: {e}", exc_info=True)
        await processing_msg.delete()
        await message.answer("❌ Не удалось распознать голосовое сообщение. Попробуйте ещё раз.")
        return

    shift_repo = ShiftRepository(session)
    await shift_repo.update_context(user.id, shift_id, transcription)
    await processing_msg.delete()
    await _show_children_message(message, user, session, state, shift_id)


async def _show_children(
    callback: CallbackQuery,
    user: User,
    session: AsyncSession,
    state: FSMContext,
    shift_id: int,
) -> None:
    """Показывает список детей (версия для callback)."""
    student_repo = StudentRepository(session)
    answer_repo = AnswerRepository(session)
    report_repo = ReportRepository(session)

    students = list(await student_repo.get_by_shift(shift_id))

    if not students:
        await callback.message.edit_text(
            "📭 В этой смене пока нет учащихся.\n"
            "Добавьте их через /admin."
        )
        return

    student_ids = [s.id for s in students]
    progress_map = await answer_repo.get_progress_map(user.id, student_ids)
    finalized_ids = await report_repo.get_finalized_student_ids(user.id, shift_id)
    finalized_count = len(finalized_ids)

    await state.update_data(shift_id=shift_id)
    await state.set_state(ChildSelectStates.choosing_child)

    await callback.message.edit_text(
        f"👦 <b>Список детей</b>\n"
        f"Готово: {finalized_count}/{len(students)} отчётов\n\n"
        "Выберите ребёнка:",
        reply_markup=children_keyboard(students, progress_map, finalized_ids),
    )


async def _show_children_message(
    message: Message,
    user: User,
    session: AsyncSession,
    state: FSMContext,
    shift_id: int,
) -> None:
    """Показывает список детей (версия для message)."""
    student_repo = StudentRepository(session)
    answer_repo = AnswerRepository(session)
    report_repo = ReportRepository(session)

    students = list(await student_repo.get_by_shift(shift_id))

    if not students:
        await message.answer(
            "✅ Контекст смены сохранён!\n\n"
            "📭 В этой смене пока нет учащихся. Добавьте их через /admin."
        )
        await state.clear()
        return

    student_ids = [s.id for s in students]
    progress_map = await answer_repo.get_progress_map(user.id, student_ids)
    finalized_ids = await report_repo.get_finalized_student_ids(user.id, shift_id)
    finalized_count = len(finalized_ids)

    await state.update_data(shift_id=shift_id)
    await state.set_state(ChildSelectStates.choosing_child)

    await message.answer(
        f"✅ Контекст сохранён!\n\n"
        f"👦 <b>Список детей</b>\n"
        f"Готово: {finalized_count}/{len(students)} отчётов\n\n"
        "Выберите ребёнка:",
        reply_markup=children_keyboard(students, progress_map, finalized_ids),
    )


@router.callback_query(F.data == "teacher:child_list")
async def back_to_child_list(
    callback: CallbackQuery, user: User, session: AsyncSession, state: FSMContext
) -> None:
    """Возврат к списку детей."""
    data = await state.get_data()
    shift_id = data.get("shift_id")

    if not shift_id:
        await callback.answer("❌ Сессия истекла. Начните заново /start", show_alert=True)
        return

    await _show_children(callback, user, session, state, shift_id)
    await callback.answer()