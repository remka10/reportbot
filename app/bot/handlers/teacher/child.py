import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.child_menu import (
    question_keyboard, questions_list_keyboard, generate_report_keyboard,
    finalized_report_keyboard, confirm_reopen_keyboard,
)
from app.bot.states.teacher_states import ChildSelectStates, QuestionStates
from app.bot.utils.text import truncate_for_telegram
from app.database.models import User
from app.repositories.answer_repo import AnswerRepository
from app.repositories.report_repo import ReportRepository
from app.repositories.student_repo import StudentRepository

logger = logging.getLogger(__name__)
router = Router(name="teacher_child")


# ---------------------------------------------------------------------------
# Выбор ребёнка
# ---------------------------------------------------------------------------

# Без фильтра по состоянию: callback_data «teacher:child:<id>» однозначно
# определяет действие. Раньше стоял ChildSelectStates.choosing_child — если
# состояние терялось/не совпадало, кнопка выбора ребёнка «залипала».
@router.callback_query(F.data.startswith("teacher:child:"))
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
        await state.update_data(
            student_id=student_id,
            student_name=student.full_name,
            report_id=report.id,
        )
        await cb.message.edit_text(
            f"✅ Отчёт для <b>{student.full_name}</b> уже финализирован.\n"
            "Хотите посмотреть, скачать или сгенерировать заново?",
            reply_markup=finalized_report_keyboard(),
        )
        return

    await state.update_data(student_id=student_id, student_name=student.full_name)
    await _go_to_question(cb.message, state, user, session, question_num=1, edit=True)


@router.callback_query(F.data == "report:reopen")
async def cb_reopen_confirm_prompt(
    cb: CallbackQuery, state: FSMContext, user: User, session: AsyncSession
) -> None:
    """Показывает предупреждение перед возвратом к анкете финализированного отчёта.

    Если педагог вернётся к вопросам и сгенерирует отчёт заново — текущий
    сохранённый текст будет заменён (старый отчёт удалён). Поэтому сначала
    просим подтверждение, и только по «Подтвердить» (report:reopen_confirm)
    реально снимаем финализацию и открываем анкету.
    """
    await cb.answer()
    await cb.message.edit_text(
        "⚠️ <b>Внимание!</b>\n\n"
        "Если вернуться к заполнению анкеты и сгенерировать отчёт заново, "
        "текущий сохранённый отчёт будет <b>заменён</b> — старый текст будет удалён.\n\n"
        "Продолжить?",
        reply_markup=confirm_reopen_keyboard(),
    )


@router.callback_query(F.data == "report:reopen_confirm")
async def cb_reopen_report(
    cb: CallbackQuery, state: FSMContext, user: User, session: AsyncSession
) -> None:
    """Снимает финализацию отчёта и открывает анкету для дозаполнения вопросов.

    Нужно, когда отчёт уже финализирован, но педагогу надо вернуться и
    заполнить/поправить ответы на вопросы. Сам текст отчёта сохраняется —
    его можно перегенерировать позже.
    """
    data = await state.get_data()
    report_id = data.get("report_id")
    student_id = data.get("student_id")
    shift_id = data.get("shift_id")

    report_repo = ReportRepository(session)
    report = await report_repo.get_by_id(report_id) if report_id else None
    if report is None and student_id and shift_id:
        report = await report_repo.get_by_student(user.id, student_id, shift_id)
    if report is None:
        await cb.answer("⚠️ Отчёт не найден", show_alert=True)
        return

    await report_repo.unfinalize(report.id)
    await state.update_data(report_id=report.id)
    await cb.answer("Отчёт открыт для дозаполнения")
    await _go_to_question(cb.message, state, user, session, question_num=1, edit=True)


# ---------------------------------------------------------------------------
# Навигация по вопросам (← / →)
# ---------------------------------------------------------------------------


# Навигационные кнопки — без фильтра по состоянию: действие однозначно задаётся
# callback_data. Раньше стоял QuestionStates.answering — при потере/несовпадении
# состояния (напр. после генерации отчёта) старые кнопки навигации «залипали».
# Защита от отсутствия выбранного ребёнка — внутри _go_to_question / хендлеров.
@router.callback_query(F.data.startswith("q:prev:"))
async def cb_prev_question(
    cb: CallbackQuery, state: FSMContext, user: User, session: AsyncSession
) -> None:
    num = int(cb.data.split(":")[-1])
    await cb.answer()
    await _go_to_question(cb.message, state, user, session, question_num=num, edit=True)


@router.callback_query(F.data.startswith("q:next:"))
async def cb_next_question(
    cb: CallbackQuery, state: FSMContext, user: User, session: AsyncSession
) -> None:
    num = int(cb.data.split(":")[-1])
    await cb.answer()
    await _go_to_question(cb.message, state, user, session, question_num=num, edit=True)


@router.callback_query(F.data.startswith("q:goto:"))
async def cb_goto_question(
    cb: CallbackQuery, state: FSMContext, user: User, session: AsyncSession
) -> None:
    num = int(cb.data.split(":")[-1])
    await cb.answer()
    await _go_to_question(cb.message, state, user, session, question_num=num, edit=True)


@router.callback_query(F.data == "q:skip")
async def cb_skip_question(
    cb: CallbackQuery, state: FSMContext, user: User, session: AsyncSession
) -> None:
    data = await state.get_data()
    if not data.get("student_id"):
        await cb.answer("❌ Сессия истекла. Начните заново /start", show_alert=True)
        return
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


@router.callback_query(F.data == "q:list")
async def cb_questions_list(
    cb: CallbackQuery, state: FSMContext, user: User, session: AsyncSession
) -> None:
    from app.repositories.question_repo import QuestionRepository
    data = await state.get_data()
    student_id = data.get("student_id")
    if not student_id:
        await cb.answer("❌ Сессия истекла. Начните заново /start", show_alert=True)
        return
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
    # Защита от потерянного состояния: без выбранного ребёнка навигация по
    # вопросам невозможна. Мягко просим начать заново, а не падаем KeyError.
    student_id = data.get("student_id")
    student_name = data.get("student_name")
    if not student_id:
        text = "❌ Сессия истекла. Начните заново командой /start"
        if edit:
            try:
                await message_obj.edit_text(text)
            except Exception:
                await message_obj.answer(text)
        else:
            await message_obj.answer(text)
        return

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
        # Обрезаем ответ: длинный текст (напр. расшифровка голосового) вместе с
        # разметкой мог превысить лимит Telegram 4096 → MESSAGE_TOO_LONG, и
        # ребёнок со значком ⏳ «не нажимался». Полный ответ всё равно виден при
        # ответе на вопрос заново.
        answer_preview = truncate_for_telegram(existing_answer.answer_text, limit=2500)
        text += f"\n\n<b>Текущий ответ:</b>\n<blockquote>{answer_preview}</blockquote>"


    keyboard = question_keyboard(
        current_num=question_num,
        total=total,
        has_prev=question_num > 1,
    )
    # Дополнительная защита: если сообщение всё же не удалось отправить/
    # отредактировать (в т.ч. из-за длины), не роняем хендлер, а шлём новым.
    if edit:
        try:
            await message_obj.edit_text(text, reply_markup=keyboard)
        except Exception:
            logger.warning("edit_text failed in _go_to_question, fallback to answer", exc_info=True)
            await message_obj.answer(text, reply_markup=keyboard)
    else:
        await message_obj.answer(text, reply_markup=keyboard)
