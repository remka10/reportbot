import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.child_menu import report_review_keyboard, generate_report_keyboard
from app.bot.keyboards.main_menu import after_finalize_menu, export_menu
from app.bot.states.teacher_states import GenerationStates, QuestionStates
from app.database.models import User, DialogRole
from app.repositories.answer_repo import AnswerRepository
from app.repositories.report_repo import ReportRepository
from app.repositories.shift_repo import ShiftRepository
from app.repositories.student_repo import StudentRepository
from app.repositories.department_repo import DepartmentRepository

from app.services.llm_service import LLMService
from app.services.stt_service import STTService

logger = logging.getLogger(__name__)
router = Router(name="teacher_generation")

TG_MAX_TEXT = 4000


def _split_text(text: str, max_len: int = TG_MAX_TEXT) -> list[str]:
    """Разбивает длинный текст на части для отправки в Telegram."""
    if len(text) <= max_len:
        return [text]
    parts = []
    while text:
        if len(text) <= max_len:
            parts.append(text)
            break
        split_at = text.rfind("\n", 0, max_len)
        if split_at == -1:
            split_at = max_len
        parts.append(text[:split_at])
        text = text[split_at:].lstrip("\n")
    return parts


# ---------------------------------------------------------------------------
# Запуск генерации
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "teacher:generate")
async def cb_generate_report(
    cb: CallbackQuery, state: FSMContext, user: User, session: AsyncSession
) -> None:
    data = await state.get_data()
    student_id = data.get("student_id")
    shift_id = data.get("shift_id")
    student_name = data.get("student_name", "—")

    if not student_id or not shift_id:
        await cb.answer("Ошибка: не выбран ребёнок или смена.", show_alert=True)
        return

    await state.set_state(GenerationStates.generating)
    status_msg = await cb.message.edit_text(
        f"⏳ <b>Генерирую отчёт для {student_name}...</b>\n\n"
        f"Это займёт 10–30 секунд."
    )

    try:
        answer_repo = AnswerRepository(session)
        shift_repo = ShiftRepository(session)

        qa_pairs = await answer_repo.get_qa_pairs_for_report(user.id, student_id)
        if not qa_pairs:
            await status_msg.edit_text(
                "⚠️ Нет ответов на вопросы. Сначала заполните хотя бы несколько ответов.",
                reply_markup=generate_report_keyboard(),
            )
            await state.set_state(QuestionStates.answering)
            return

        department_id = data.get("department_id")
        shift_context = ""
        if department_id:
            dep_repo = DepartmentRepository(session)
            td = await dep_repo.get_teacher_department(user.id, department_id)
            shift_context = td.shift_context if td else ""
        if not shift_context:
            ts = await shift_repo.get_teacher_shift(user.id, shift_id)
            shift_context = ts.shift_context if ts else ""


        llm = LLMService()
        report_text = await llm.generate_report(
            qa_pairs=qa_pairs,
            shift_context=shift_context,
            student_name=student_name,
        )

        report_repo = ReportRepository(session)
        existing = await report_repo.get_by_student(user.id, student_id, shift_id)
        if existing and not existing.is_finalized:
            await report_repo.update_text(existing.id, report_text)
            report_id = existing.id
        else:
            new_report = await report_repo.create(
                teacher_id=user.id,
                student_id=student_id,
                shift_id=shift_id,
                generated_text=report_text,
            )
            report_id = new_report.id

        await report_repo.add_revision_message(
            report_id=report_id,
            role=DialogRole.assistant,
            content=report_text,
        )

        await state.update_data(report_id=report_id)
        await state.set_state(GenerationStates.reviewing)

        parts = _split_text(report_text)
        await status_msg.delete()
        for i, part in enumerate(parts):
            if i < len(parts) - 1:
                await cb.message.answer(part)
            else:
                await cb.message.answer(
                    part + "\n\n─────────────────\n"
                          "Отчёт готов. Сохранить или исправить?",
                    reply_markup=report_review_keyboard(),
                )

    except Exception as e:
        logger.error(f"Report generation error: {e}", exc_info=True)
        await status_msg.edit_text(
            "⚠️ Ошибка при генерации отчёта. Попробуйте ещё раз.",
            reply_markup=generate_report_keyboard(),
        )
        await state.set_state(QuestionStates.answering)


# ---------------------------------------------------------------------------
# Финализация отчёта
# ---------------------------------------------------------------------------

@router.callback_query(GenerationStates.reviewing, F.data == "report:finalize")
async def cb_finalize_report(
    cb: CallbackQuery, state: FSMContext, user: User, session: AsyncSession
) -> None:
    data = await state.get_data()
    report_id = data.get("report_id")
    student_id = data.get("student_id")
    shift_id = data.get("shift_id")
    student_name = data.get("student_name", "—")

    if not report_id:
        await cb.answer("Ошибка: отчёт не найден.", show_alert=True)
        return

    department_id = data.get("department_id")
    report_repo = ReportRepository(session)
    student_repo = StudentRepository(session)

    await report_repo.finalize(report_id)

    finalized_ids = await report_repo.get_finalized_student_ids(user.id, shift_id)
    if department_id:
        dep_students = await student_repo.get_by_department(department_id)
        dep_ids = {s.id for s in dep_students}
        done = len({sid for sid in finalized_ids if sid in dep_ids})
        total = len(dep_students)
    else:
        all_students = await student_repo.get_by_shift(shift_id)
        done = len(finalized_ids)
        total = len(all_students)


    await state.set_state(GenerationStates.finalized)
    await cb.message.edit_text(
        f"✅ <b>Отчёт для {student_name} сохранён!</b>\n\n"
        f"Готово отчётов: <b>{done}/{total}</b>",
        reply_markup=after_finalize_menu(done, total),
    )


# ---------------------------------------------------------------------------
# Запрос на правку
# ---------------------------------------------------------------------------

@router.callback_query(GenerationStates.reviewing, F.data == "report:revise")
async def cb_request_revision(cb: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(GenerationStates.waiting_revision)
    await cb.message.answer(
        "✏️ <b>Напишите что нужно исправить</b>\n\n"
        "Например: «Сделай тон более тёплым» или «Добавь про командную работу»\n\n"
        "Можно написать текстом или отправить <b>голосовое сообщение</b> 🎤"
    )


# ---------------------------------------------------------------------------
# Получение текстовой правки
# ---------------------------------------------------------------------------

@router.message(GenerationStates.waiting_revision, F.text)
async def revision_text(
    message: Message, state: FSMContext, user: User, session: AsyncSession
) -> None:
    request = (message.text or "").strip()
    if len(request) < 3:
        await message.answer("⚠️ Запрос слишком короткий. Напишите подробнее что исправить:")
        return
    await _apply_revision(message, state, user, session, request)


# ---------------------------------------------------------------------------
# Получение голосовой правки
# ---------------------------------------------------------------------------

@router.message(GenerationStates.waiting_revision, F.voice)
async def revision_voice(
    message: Message, state: FSMContext, user: User, session: AsyncSession
) -> None:
    status_msg = await message.answer("🎤 Распознаю голосовое...")
    try:
        stt = STTService()
        request = await stt.transcribe_voice(message.voice, message.bot)
        await status_msg.delete()
        if not request or len(request.strip()) < 3:
            await message.answer("⚠️ Не удалось распознать. Напишите правку текстом.")
            return
        await message.answer(f"Распознано: <i>{request}</i>")
        await _apply_revision(message, state, user, session, request.strip())
    except Exception as e:
        logger.error(f"Revision voice error: {e}", exc_info=True)
        await status_msg.edit_text("⚠️ Ошибка распознавания. Напишите правку текстом.")


# ---------------------------------------------------------------------------
# Применение правки
# ---------------------------------------------------------------------------

async def _apply_revision(
    message: Message,
    state: FSMContext,
    user: User,
    session: AsyncSession,
    revision_request: str,
) -> None:
    data = await state.get_data()
    report_id = data.get("report_id")
    student_name = data.get("student_name", "—")

    if not report_id:
        await message.answer("⚠️ Ошибка: отчёт не найден.")
        return

    status_msg = await message.answer(f"⏳ Применяю правки для {student_name}...")
    report_repo = ReportRepository(session)

    try:
        await report_repo.add_revision_message(
            report_id=report_id,
            role=DialogRole.user,
            content=revision_request,
        )
        history = list(await report_repo.get_revision_history(report_id))
        llm = LLMService()
        revised_text = await llm.revise_report(
            revision_request=revision_request,
            history=history[:-1],
        )
        await report_repo.update_text(report_id, revised_text)
        await report_repo.add_revision_message(
            report_id=report_id,
            role=DialogRole.assistant,
            content=revised_text,
        )
        await state.set_state(GenerationStates.reviewing)
        await status_msg.delete()
        parts = _split_text(revised_text)
        for i, part in enumerate(parts):
            if i < len(parts) - 1:
                await message.answer(part)
            else:
                await message.answer(
                    part + "\n\n─────────────────\n"
                          "Исправленный отчёт. Сохранить или исправить ещё?",
                    reply_markup=report_review_keyboard(),
                )
    except Exception as e:
        logger.error(f"Revision error: {e}", exc_info=True)
        await status_msg.edit_text(
            "⚠️ Ошибка при применении правок. Попробуйте ещё раз.",
            reply_markup=report_review_keyboard(),
        )
        await state.set_state(GenerationStates.reviewing)


# ---------------------------------------------------------------------------
# Следующий ребёнок
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "teacher:next_child")
async def cb_next_child(
    cb: CallbackQuery, state: FSMContext, user: User, session: AsyncSession
) -> None:
    # ИСПРАВЛЕНО: _show_children_list → _show_children (функция в shift.py)
    from app.bot.handlers.teacher.shift import _show_children

    data = await state.get_data()
    shift_id = data.get("shift_id")
    if not shift_id:
        await cb.answer("Сначала выберите смену.", show_alert=True)
        return

    await state.update_data(student_id=None, student_name=None, report_id=None)
    # ИСПРАВЛЕНО: передаём cb (CallbackQuery), а не cb.message — _show_children ожидает CallbackQuery
    await _show_children(cb, user, session, state, shift_id)


# ---------------------------------------------------------------------------
# Меню экспорта (только роутинг — сам экспорт в export.py)
# ВАЖНО: callback_data "teacher:export" — отдельный от "export:menu" в export.py
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "teacher:export")
async def cb_teacher_export_redirect(
    cb: CallbackQuery, state: FSMContext
) -> None:
    """
    Редирект из контекста генерации в меню экспорта.
    Используется кнопкой after_finalize_menu → "📥 Скачать отчёты".
    Настоящий экспорт обрабатывает export.py (export:single, export:zip).
    """
    data = await state.get_data()
    student_name = data.get("student_name", "—")
    await cb.message.edit_text(
        f"📥 <b>Экспорт отчётов</b>\n\nТекущий ребёнок: <b>{student_name}</b>",
        reply_markup=export_menu(),
    )