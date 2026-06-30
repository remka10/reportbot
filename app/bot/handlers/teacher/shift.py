import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.shift_menu import departments_keyboard, context_exists_keyboard
from app.bot.keyboards.child_menu import children_keyboard
from app.bot.states.teacher_states import ShiftSelectStates, ChildSelectStates
from app.database.models import User
from app.repositories.shift_repo import ShiftRepository
from app.repositories.department_repo import DepartmentRepository
from app.repositories.answer_repo import AnswerRepository
from app.repositories.report_repo import ReportRepository
from app.repositories.student_repo import StudentRepository
from app.services.stt_service import STTService

logger = logging.getLogger(__name__)
router = Router(name="teacher_shift")
_stt_service: "STTService | None" = None


def get_stt() -> "STTService":
    global _stt_service
    if _stt_service is None:
        _stt_service = STTService()
    return _stt_service


@router.callback_query(F.data == "teacher:shifts")
async def show_departments(
    callback: CallbackQuery, user: User, session: AsyncSession, state: FSMContext
) -> None:
    """Показывает список департаментов педагога (по всем его сменам)."""
    await state.clear()
    dep_repo = DepartmentRepository(session)
    shift_repo = ShiftRepository(session)
    departments = list(await dep_repo.get_for_teacher(user.id))

    if not departments:
        await callback.message.edit_text(
            "📭 У вас нет привязанных департаментов.\n"
            "Обратитесь к администратору."
        )
        await callback.answer()
        return

    # Карта shift_id -> название смены (для подписи кнопок)
    shift_name_map: dict[int, str] = {}
    for d in departments:
        if d.shift_id not in shift_name_map:
            shift = await shift_repo.get_by_id(d.shift_id)
            shift_name_map[d.shift_id] = shift.name if shift else f"Смена {d.shift_id}"

    await callback.message.edit_text(
        "📂 <b>Ваши департаменты</b>\n\nВыберите департамент для работы:",
        reply_markup=departments_keyboard(departments, shift_name_map),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("teacher:department:"))
async def select_department(
    callback: CallbackQuery, user: User, session: AsyncSession, state: FSMContext
) -> None:
    """Обрабатывает выбор департамента."""
    department_id = int(callback.data.split(":")[-1])
    dep_repo = DepartmentRepository(session)
    shift_repo = ShiftRepository(session)

    department = await dep_repo.get_by_id(department_id)
    if department is None:
        await callback.answer("❌ Департамент не найден", show_alert=True)
        return

    teacher_dep = await dep_repo.get_teacher_department(user.id, department_id)
    if teacher_dep is None:
        await callback.answer("❌ Вы не привязаны к этому департаменту", show_alert=True)
        return

    shift = await shift_repo.get_by_id(department.shift_id)
    shift_name = shift.name if shift else f"Смена {department.shift_id}"

    # Сохраняем выбранный департамент и его смену в FSM
    await state.update_data(department_id=department_id, shift_id=department.shift_id)

    if teacher_dep.shift_context:
        context_preview = (
            teacher_dep.shift_context[:300] + "..."
            if len(teacher_dep.shift_context) > 300
            else teacher_dep.shift_context
        )
        await callback.message.edit_text(
            f"📂 <b>{shift_name}</b>\n"
            f"🏢 {department.name}\n\n"
            f"<b>Контекст:</b>\n<i>{context_preview}</i>\n\n"
            "Использовать сохранённый контекст или ввести новый?",
            reply_markup=context_exists_keyboard(),
        )
        await state.set_state(ShiftSelectStates.confirm_context)
    else:
        await callback.message.edit_text(
            f"📂 <b>{shift_name}</b>\n"
            f"🏢 {department.name}\n\n"
            "✏️ <b>Введите контекст</b> — расскажите о сюжете, "
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
    data = await state.get_data()
    await _show_children(callback, user, session, state, data["department_id"])
    await callback.answer()


@router.callback_query(
    ShiftSelectStates.confirm_context, F.data == "teacher:context:change"
)
async def change_context(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.message.edit_text(
        "✏️ <b>Введите новый контекст:</b>\n\n"
        "Расскажите о сюжете, чем занимались дети, ключевые события.\n"
        "Можно написать текстом или отправить голосовое сообщение."
    )
    await state.set_state(ShiftSelectStates.entering_context)
    await callback.answer()


@router.message(ShiftSelectStates.entering_context, F.text)
async def save_context_text(
    message: Message, user: User, session: AsyncSession, state: FSMContext
) -> None:
    data = await state.get_data()
    department_id = data["department_id"]
    dep_repo = DepartmentRepository(session)
    await dep_repo.update_context(user.id, department_id, message.text.strip())
    await _show_children_message(message, user, session, state, department_id)


@router.message(ShiftSelectStates.entering_context, F.voice)
async def save_context_voice(
    message: Message, user: User, session: AsyncSession, state: FSMContext
) -> None:
    data = await state.get_data()
    department_id = data["department_id"]

    processing_msg = await message.answer("⏳ Распознаю голосовое сообщение...")
    try:
        transcription = await get_stt().transcribe_voice(message.voice, message.bot)
    except ValueError as e:
        await processing_msg.delete()
        await message.answer(f"❌ {e}")
        return
    except Exception as e:
        logger.error(f"STT error in save_context_voice: {e}", exc_info=True)
        await processing_msg.delete()
        await message.answer("❌ Не удалось распознать голосовое сообщение. Попробуйте ещё раз.")
        return

    dep_repo = DepartmentRepository(session)
    await dep_repo.update_context(user.id, department_id, transcription)
    await processing_msg.delete()
    await _show_children_message(message, user, session, state, department_id)


async def _build_children_view(
    user: User,
    session: AsyncSession,
    state: FSMContext,
    department_id: int,
):
    """Готовит данные для списка детей департамента."""
    student_repo = StudentRepository(session)
    answer_repo = AnswerRepository(session)
    report_repo = ReportRepository(session)
    dep_repo = DepartmentRepository(session)

    department = await dep_repo.get_by_id(department_id)
    shift_id = department.shift_id if department else None
    students = list(await student_repo.get_by_department(department_id))

    if not students:
        return None, None, None, None

    student_ids = [s.id for s in students]
    progress_map = await answer_repo.get_progress_map(user.id, student_ids)
    # Финализированные ограничиваем студентами этого департамента
    all_finalized = await report_repo.get_finalized_student_ids(user.id, shift_id)
    finalized_ids = {sid for sid in all_finalized if sid in set(student_ids)}

    await state.update_data(department_id=department_id, shift_id=shift_id)
    await state.set_state(ChildSelectStates.choosing_child)
    return students, progress_map, finalized_ids, len(students)


async def _show_children(
    callback: CallbackQuery,
    user: User,
    session: AsyncSession,
    state: FSMContext,
    department_id: int,
) -> None:
    students, progress_map, finalized_ids, total = await _build_children_view(
        user, session, state, department_id
    )
    if students is None:
        await callback.message.edit_text(
            "📭 В этом департаменте пока нет учащихся.\n"
            "Добавьте их через /admin."
        )
        return
    await callback.message.edit_text(
        f"👦 <b>Список детей</b>\n"
        f"Готово: {len(finalized_ids)}/{total} отчётов\n\n"
        "Выберите ребёнка:",
        reply_markup=children_keyboard(students, progress_map, finalized_ids),
    )


async def _show_children_message(
    message: Message,
    user: User,
    session: AsyncSession,
    state: FSMContext,
    department_id: int,
) -> None:
    students, progress_map, finalized_ids, total = await _build_children_view(
        user, session, state, department_id
    )
    if students is None:
        await message.answer(
            "✅ Контекст сохранён!\n\n"
            "📭 В этом департаменте пока нет учащихся. Добавьте их через /admin."
        )
        await state.clear()
        return
    await message.answer(
        f"✅ Контекст сохранён!\n\n"
        f"👦 <b>Список детей</b>\n"
        f"Готово: {len(finalized_ids)}/{total} отчётов\n\n"
        "Выберите ребёнка:",
        reply_markup=children_keyboard(students, progress_map, finalized_ids),
    )


@router.callback_query(F.data == "teacher:child_list")
async def back_to_child_list(
    callback: CallbackQuery, user: User, session: AsyncSession, state: FSMContext
) -> None:
    """Возврат к списку детей."""
    data = await state.get_data()
    department_id = data.get("department_id")

    if not department_id:
        await callback.answer("❌ Сессия истекла. Начните заново /start", show_alert=True)
        return

    await _show_children(callback, user, session, state, department_id)
    await callback.answer()
