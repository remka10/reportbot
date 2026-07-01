import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.child_menu import (
    question_keyboard, questions_list_keyboard, generate_report_keyboard,
    finalized_report_keyboard,
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
    await cb.answer()  # убираем "часики" на кнопке

    student_repo = StudentRepository(session)
    student = await student_repo.get_by_id(student_id)
    if not student:
        await cb.answer("Учащийся не найден.", show_alert=True)
        return

    report_repo = ReportRepository(session)
    data = await state.get_data()
    report = await report_repo.get_by_student(user.id, student_id, data.get("shift_id"))
    if report and report.is_finalized:
        await state.update_data(student_id=student_id, student_name=student.full_name)
        await cb.message.edit_text(
            f"✅ Отчёт для <b>{student.full_name}</b> уже финализирован.\n"
            "Хотите посмотреть, скачать или сгенерировать заново?",
            reply_markup=finalized_report_keyboard(),
        )
        return

    await state.update_data(student_id=student_id, student_name=student.full_name)
    await _go_to_question(cb.message, state, user, session, question_num=1, edit=True)


# ---------------------------------------------------------------------------
# Навигация по вопросам (← / →)
# ---------------------------------------------------------------------------

@router.callback_query(QuestionStates.answering, F.data.startswith("q:prev:"))
async def cb_prev_question(
    cb: CallbackQuery, state: FSMContext, user: User, session: AsyncSession
) -> None:
    num = int(cb.data.split(":")[-1])
    await cb.answer()
    await _go_to_question(cb.message, state, user, session, question_num=num, edit=True)


@router.callback_query(QuestionStates.answering, F.data.startswith("q:next:"))
async def cb_next_question(
    cb: CallbackQuery, state: FSMContext, user: User, session: AsyncSession
) -> None:
    num = int(cb.data.split(":")[-1])
    await cb.answer()
    await _go_to_question(cb.message, state, user, session, question_num=num, edit=True)


@router.callback_query(QuestionStates.answering, F.data.startswith("q:goto:"))
async def cb_goto_question(
    cb: CallbackQuery, state: FSMContext, user: User, session: AsyncSession
) -> None:
    num = int(cb.data.split(":")[-1])
    await cb.answer()
    await _go_to_question(cb.message, state, user, session, question_num=num, edit=True)


@router.callback_query(QuestionStates.answering, F.data == "q:skip")
async def cb_skip_question(
    cb: CallbackQuery, state: FSMContext, user: User, session: AsyncSession
) -> None:
    data = await state.get_data()
    current_num = data.get("current_question_num", 1)
    total = data.get("questions_total", 1)
    await cb.answer()
    if current_num < total:
        await _go_to_question(cb.message, state, user, session, question_num=current_num + 1, edit=True)
    else:
        await cb.message.edit_text(
            "Все вопросы пройдены. Можно генерировать отчёт:",
            reply_markup=generate_report_keyboard(),
        )


@router.callback_query(QuestionStates.answering, F.data == "q:list")
async def cb_questions_list(
    cb: CallbackQuery, state: FSMContext, user: User, session: AsyncSession
) -> None:
    from app.repositories.question_repo import QuestionRepository
    data = await state.get_data()
    student_id = data.get("student_id")
    q_repo = QuestionRepository(session)
    a_repo = AnswerRepository(session)
    questions = list(await q_repo.get_all_active())
    answers = await a_repo.get_progress_map(user.id, [student_id]) if student_id else {}
    answered_count = answers.get(student_id, 0) if student_id else 0
    answered_ids: set[int] = set()
    for q in questions:
        ans = await a_repo.get_by_teacher_student_question(user.id, student_id, q.id)
        if ans:
            answered_ids.add(q.id)
    await cb.answer()
    await cb.message.edit_text(
        f"📋 <b>Список вопросов</b>\nОтвечено: {len(answered_ids)}/{len(questions)}",
        reply_markup=questions_list_keyboard(questions, answered_ids),
    )


@router.callback_query(F.data == "q:back")
async def cb_back_from_list(
    cb: CallbackQuery, state: FSMContext, user: User, session: AsyncSession
) -> None:
    data = await state.get_data()
    current_num = data.get("current_question_num", 1)
    await cb.answer()
    await _go_to_question(cb.message, state, user, session, question_num=current_num, edit=True)


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
        if edit:
            await message_obj.edit_text(text)
        else:
            await message_obj.answer(text)
        return

    total = len(questions)
    question_num = max(1, min(question_num, total))
    question = next(
        (q for q in questions if q.question_number == question_num), questions[0]
    )

    existing_answer = await a_repo.get_by_teacher_student_question(
        teacher_id=user.id,
        student_id=student_id,
        question_id=question.id,
    )

    answered_count = await a_repo.count_answered(user.id, student_id)

    await state.update_data(
        current_question_id=question.id,
        current_question_num=question.question_number,
        current_question_text=question.question_text,
        questions_total=total,
    )
    await state.set_state(QuestionStates.answering)

    answered_flag = "✅ " if existing_answer else ""
    text = (
        f"{answered_flag}<b>Вопрос {question_num}/{total}</b>\n"
        f"<i>Блок: {question.block_title}</i>\n\n"
        f"{question.question_text}\n\n"
        f"🎤 <i>Ответьте голосом или текстом.</i>"
    )
    if existing_answer:
        text += f"\n\n<b>Текущий ответ:</b>\n<blockquote>{existing_answer.answer_text}</blockquote>"


    keyboard = question_keyboard(
        current_num=question_num,
        total=total,
        has_prev=question_num > 1,
    )
    if edit:
        await message_obj.edit_text(text, reply_markup=keyboard)
    else:
        await message_obj.answer(text, reply_markup=keyboard)