import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.child_menu import (
    question_keyboard, questions_list_keyboard, generate_report_keyboard,
)
from app.bot.states.teacher_states import ChildSelectStates, QuestionStates
from app.database.models import User
from app.repositories.answer_repo import AnswerRepository
from app.repositories.report_repo import ReportRepository
from app.repositories.student_repo import StudentRepository

logger = logging.getLogger(__name__)
router = Router(name="teacher_child")


# ---------------------------------------------------------------------------
# Выбор ребёнка
# ---------------------------------------------------------------------------

@router.callback_query(ChildSelectStates.choosing_child, F.data.startswith("teacher:child:"))
async def cb_child_selected(
    cb: CallbackQuery, state: FSMContext, user: User, session: AsyncSession
) -> None:
    student_id = int(cb.data.split(":")[-1])

    student_repo = StudentRepository(session)
    student = await student_repo.get_by_id(student_id)
    if not student:
        await cb.answer("Учащийся не найден.", show_alert=True)
        return

    # Проверяем — не финализирован ли уже отчёт
    report_repo = ReportRepository(session)
    data = await state.get_data()
    report = await report_repo.get_by_student(user.id, student_id, data.get("shift_id"))
    if report and report.is_finalized:
        await cb.message.edit_text(
            f"✅ Отчёт для <b>{student.full_name}</b> уже финализирован.

"
            "Хотите пересмотреть или скачать?",
            reply_markup=generate_report_keyboard(),
        )
        await state.update_data(student_id=student_id, student_name=student.full_name)
        return

    await state.update_data(student_id=student_id, student_name=student.full_name)

    # Загружаем вопросы и ответы
    await _go_to_question(cb.message, state, user, session, question_num=1, edit=True)


# ---------------------------------------------------------------------------
# Перейти к конкретному вопросу
# ---------------------------------------------------------------------------

async def _go_to_question(
    message_obj,
    state: FSMContext,
    user: User,
    session: AsyncSession,
    question_num: int,
    edit: bool = True,
) -> None:
    from app.repositories.question_repo import QuestionRepository

    data = await state.get_data()
    student_id = data["student_id"]
    student_name = data["student_name"]

    q_repo = QuestionRepository(session)
    a_repo = AnswerRepository(session)

    questions = list(await q_repo.get_all_active())
    if not questions:
        text = "⚠️ Список вопросов не загружен. Обратитесь к администратору."
        await message_obj.answer(text) if not edit else await message_obj.edit_text(text)
        return

    total = len(questions)
    # Нормализуем номер
    question_num = max(1, min(question_num, total))
    question = next((q for q in questions if q.question_number == question_num), questions[0]