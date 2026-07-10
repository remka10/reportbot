import asyncio
import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.child_menu import (
    report_review_keyboard,
    generate_report_keyboard,
    confirm_generate_keyboard,
    finalized_report_keyboard,
    back_to_report_keyboard,
)
from app.repositories.question_repo import QuestionRepository

from app.bot.keyboards.main_menu import after_finalize_menu, export_mode_menu

from app.bot.states.teacher_states import GenerationStates, QuestionStates
from app.database.models import User, DialogRole, get_department_name
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

# Разделитель между блоком ответов на вопросы (1..13) и итоговым отчётом.
REPORT_MARKER = "=== ИТОГОВЫЙ ОТЧЁТ ==="



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
# Устойчивые обёртки над Telegram-вызовами
# ---------------------------------------------------------------------------
# Контекст: сеть до api.telegram.org иногда моргает (TelegramNetworkError).
# Если UI-вызов (edit_text/answer) падает голым исключением, DbSessionMiddleware
# откатывает ВСЮ транзакцию хендлера — включая уже выполненные записи в БД
# (например report_repo.finalize). Эти обёртки делают несколько попыток и НЕ
# роняют хендлер: при неудаче логируют и возвращают None, чтобы бизнес-логика
# (commit в middleware) не терялась из-за проблем с доставкой сообщения.

_RETRY_DELAYS = (0.5, 1.0, 2.0)


async def safe_edit_text(
    message: Message,
    text: str,
    reply_markup=None,
    retries: int = 3,
) -> Message | None:
    """edit_text с ретраями на сетевые сбои и фолбэком на answer.

    TelegramBadRequest (в т.ч. «message is not modified») не ретраится —
    это не сетевая проблема, повтор не поможет.
    """
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            return await message.edit_text(text, reply_markup=reply_markup)
        except TelegramNetworkError as e:
            last_err = e
            if attempt < retries - 1:
                await asyncio.sleep(_RETRY_DELAYS[min(attempt, len(_RETRY_DELAYS) - 1)])
        except TelegramBadRequest as e:
            logger.warning(f"safe_edit_text: BadRequest, пропускаю ретраи: {e}")
            return None
    logger.error(f"safe_edit_text: не удалось отредактировать после {retries} попыток: {last_err}")
    # Фолбэк: пробуем отправить новым сообщением, чтобы пользователь всё же увидел результат.
    return await safe_answer(message, text, reply_markup=reply_markup)


async def safe_answer(
    message: Message,
    text: str,
    reply_markup=None,
    retries: int = 3,
) -> Message | None:
    """answer с ретраями на сетевые сбои. Никогда не роняет хендлер."""
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            return await message.answer(text, reply_markup=reply_markup)
        except TelegramNetworkError as e:
            last_err = e
            if attempt < retries - 1:
                await asyncio.sleep(_RETRY_DELAYS[min(attempt, len(_RETRY_DELAYS) - 1)])
        except TelegramBadRequest as e:
            logger.warning(f"safe_answer: BadRequest, пропускаю ретраи: {e}")
            return None
    logger.error(f"safe_answer: не удалось отправить после {retries} попыток: {last_err}")
    return None


# Пауза между частями длинного сообщения. Telegram лимитирует ~1 сообщение/сек
# на чат: если слать части подряд без паузы, часть упирается во flood-limit и
# «долетает» с задержкой (педагог видит «зависло, потом пришло»).
_PART_DELAY = 0.4


async def _send_parts(
    message: Message,
    parts: list[str],
    final_suffix: str = "",
    final_markup=None,
) -> None:
    """Отправляет длинный текст частями с паузой, чтобы не ловить flood-limit.

    К последней части добавляет final_suffix и клавиатуру final_markup.
    Все отправки идут через safe_answer — сетевой сбой не роняет хендлер.
    """
    total = len(parts)
    for i, part in enumerate(parts):
        is_last = i == total - 1
        await safe_answer(
            message,
            part + final_suffix if is_last else part,
            reply_markup=final_markup if is_last else None,
        )
        if not is_last:
            await asyncio.sleep(_PART_DELAY)


# ---------------------------------------------------------------------------
# Busy-lock: защита от повторных запусков тяжёлых операций (LLM)
# ---------------------------------------------------------------------------
# Пока для педагога идёт генерация/правка отчёта (запрос к LLM 10–90 сек), он
# может нетерпеливо жать кнопку ещё раз. Без защиты это запускало ВТОРОЙ запрос к
# LLM параллельно → двойные ответы, гонки за одно сообщение, «зависания». Флаг в
# FSM (llm_busy) не даёт запустить вторую операцию, пока не завершилась первая.

async def _is_busy(state: FSMContext) -> bool:
    return bool((await state.get_data()).get("llm_busy", False))


async def _set_busy(state: FSMContext, value: bool) -> None:
    await state.update_data(llm_busy=value)


# ---------------------------------------------------------------------------
# Возврат к меню отчёта из экранов просмотра/правки
# ---------------------------------------------------------------------------

# ВАЖНО: без фильтра по состоянию — кнопка «← Назад к меню отчёта» должна
# срабатывать из любого экрана (просмотр/ИИ-правка/ручная правка/ввод правки),
# даже если FSM-состояние потерялось. callback_data однозначно определяет
# действие, поэтому состояние тут избыточно и только мешало бы.
@router.callback_query(F.data == "report:back")
async def cb_back_to_report(
    cb: CallbackQuery, state: FSMContext, user: User, session: AsyncSession
) -> None:
    """Возвращает педагога к меню текущего отчёта.

    Логика навигации «строго назад по меню»:
      • есть финализированный отчёт → меню финализированного отчёта
        (finalized_report_keyboard — «Посмотреть/Скачать/Редактировать…»);
      • есть черновик отчёта → меню черновика (report_review_keyboard —
        «Сохранить/Исправить/…»);
      • отчёта нет / потеряна сессия → откат к списку детей департамента.
    """
    data = await state.get_data()
    student_id = data.get("student_id")
    shift_id = data.get("shift_id")
    department_id = data.get("department_id")
    student_name = data.get("student_name", "—")

    await cb.answer()

    # Фолбэк: сессия по отчёту потеряна — возвращаемся к списку детей.
    if not student_id or not shift_id:
        if department_id:
            from app.bot.handlers.teacher.shift import _show_children
            await _show_children(cb, user, session, state, department_id)
            return
        await safe_answer(cb.message, "⚠️ Отчёт не найден. Откройте ребёнка из списка ещё раз.")
        return

    report_repo = ReportRepository(session)
    report = await report_repo.get_by_student(user.id, student_id, shift_id)

    # Отчёта нет — возвращаемся к списку детей (там есть навигация дальше).
    if report is None or not (report.generated_text or "").strip():
        if department_id:
            from app.bot.handlers.teacher.shift import _show_children
            await _show_children(cb, user, session, state, department_id)
            return
        await safe_answer(cb.message, "⚠️ Отчёт не найден. Откройте ребёнка из списка ещё раз.")
        return

    if getattr(report, "is_finalized", False):
        await state.update_data(report_id=report.id, current_report_text=report.generated_text)
        await state.set_state(GenerationStates.finalized)
        await safe_answer(
            cb.message,
            f"📄 <b>Отчёт для {student_name}</b>\n\nВыберите действие:",
            reply_markup=finalized_report_keyboard(),
        )
    else:
        await state.update_data(report_id=report.id, current_report_text=report.generated_text)
        await state.set_state(GenerationStates.reviewing)
        await safe_answer(
            cb.message,
            f"📄 <b>Черновик отчёта для {student_name}</b>\n\nВыберите действие:",
            reply_markup=report_review_keyboard(),
        )


# ---------------------------------------------------------------------------
# Проверка перед генерацией: все ли вопросы заполнены
# ---------------------------------------------------------------------------



@router.callback_query(F.data == "teacher:generate_check")
async def cb_generate_check(
    cb: CallbackQuery, state: FSMContext, user: User, session: AsyncSession
) -> None:
    """Кнопка «Сгенерировать отчёт» с экрана вопросов.

    Если заполнены НЕ все вопросы — спрашиваем подтверждение. Если все —
    сразу запускаем генерацию.
    """
    data = await state.get_data()
    student_id = data.get("student_id")
    if not student_id:
        await cb.answer("Сначала выберите ребёнка.", show_alert=True)
        return

    q_repo = QuestionRepository(session)
    answer_repo = AnswerRepository(session)
    total = len(list(await q_repo.get_all_active()))
    answered = await answer_repo.count_answered(user.id, student_id)

    if answered < total:
        await cb.answer()
        await safe_answer(
            cb.message,
            f"⚠️ <b>Заполнены не все вопросы: {answered}/{total}.</b>\n\n"
            "Вы уверены, что хотите сгенерировать отчёт сейчас?",
            reply_markup=confirm_generate_keyboard(answered, total),
        )
        return


    # Все вопросы заполнены — запускаем генерацию сразу.
    await cb_generate_report(cb, state, user, session)


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

    # Мгновенно снимаем «часики» с кнопки — ещё до тяжёлой работы (LLM 10–90 сек).
    # Без этого Telegram держит кнопку «нажатой», и педагогу кажется, что всё зависло.
    await cb.answer()

    # Busy-lock: если генерация/правка уже идёт — не запускаем вторую (двойной тап
    # по «Сгенерировать» иначе слал два параллельных запроса к LLM с гонками).
    if await _is_busy(state):
        await cb.answer("⏳ Уже генерирую, подождите…", show_alert=True)
        return
    await _set_busy(state, True)

    await state.set_state(GenerationStates.generating)
    status_msg = await safe_edit_text(
        cb.message,
        f"⏳ <b>Генерирую отчёт для {student_name}...</b>\n\n"
        f"Это займёт 10–30 секунд.",
    )

    try:

        answer_repo = AnswerRepository(session)
        shift_repo = ShiftRepository(session)

        qa_pairs = await answer_repo.get_qa_pairs_for_report(user.id, student_id)
        if not qa_pairs:
            await safe_edit_text(
                status_msg,
                "⚠️ Нет ответов на вопросы. Сначала заполните хотя бы несколько ответов.",
                reply_markup=generate_report_keyboard(),
            )
            await state.set_state(QuestionStates.answering)
            return


        department_id = data.get("department_id")
        shift_context = ""
        if department_id:
            dep_repo = DepartmentRepository(session)
            department = await dep_repo.get_by_id(department_id)
            td = await dep_repo.get_teacher_department(user.id, department_id)
            shift_context = (td.shift_context if td else "") or ""
            # Фолбэк: контекст мог заполнить другой аккаунт по этому департаменту.
            if not shift_context:
                shift_context = await dep_repo.get_any_context(department_id)
        if not shift_context:
            ts = await shift_repo.get_teacher_shift(user.id, shift_id)
            shift_context = (ts.shift_context if ts else "") or ""

        if department_id and department:
            shift_context = (
                f"Департамент: {get_department_name(department.department_number)}\n\n"
                f"{shift_context}"
            ).strip()



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

        # ВАЖНО: обновляем и current_report_text — иначе после повторной генерации
        # («Вернуться к анкете» → «Сгенерировать заново») в FSM остаётся старый
        # текст, и ИИ-правка показывала бы устаревший отчёт.
        await state.update_data(report_id=report_id, current_report_text=report_text)
        await state.set_state(GenerationStates.reviewing)

        # Удаляем статус «Генерирую…» и шлём готовый отчёт частями с паузами
        # (иначе части упираются во flood-limit Telegram и приходят с задержкой).
        if status_msg is not None:
            try:
                await status_msg.delete()
            except Exception:
                logger.debug("status_msg.delete failed", exc_info=True)
        await _send_parts(
            cb.message,
            _split_text(report_text),
            final_suffix="\n\n─────────────────\n"
                         "Отчёт готов. Сохранить или исправить?",
            final_markup=report_review_keyboard(),
        )

    except Exception as e:
        logger.error(f"Report generation error: {e}", exc_info=True)
        if status_msg is not None:
            await safe_edit_text(
                status_msg,
                "⚠️ Ошибка при генерации отчёта. Попробуйте ещё раз.",
                reply_markup=generate_report_keyboard(),
            )
        else:
            await safe_answer(
                cb.message,
                "⚠️ Ошибка при генерации отчёта. Попробуйте ещё раз.",
                reply_markup=generate_report_keyboard(),
            )
        await state.set_state(QuestionStates.answering)
    finally:
        # Снимаем busy-lock в любом случае — иначе после ошибки кнопка «Сгенерировать»
        # осталась бы навсегда заблокированной («⏳ Уже генерирую…»).
        await _set_busy(state, False)




# ---------------------------------------------------------------------------
# Просмотр уже сохранённого отчёта
# ---------------------------------------------------------------------------

def _split_report(text: str) -> tuple[str, str]:
    """Разбивает отчёт на (блок ответов 1..13, итоговый отчёт) по разделителю.

    Если разделитель не найден — считаем, что блока ответов нет, а весь текст
    является итоговым отчётом.
    """
    if not text:
        return "", ""
    idx = text.find(REPORT_MARKER)
    if idx == -1:
        return "", text.strip()
    answers = text[:idx].strip()
    final = text[idx + len(REPORT_MARKER):].strip()
    return answers, final


def _extract_final_report(text: str) -> str:
    """Возвращает итоговый отчёт (часть после «=== ИТОГОВЫЙ ОТЧЁТ ===»),
    либо весь текст, если разделитель не найден."""
    return _split_report(text)[1] or (text or "").strip()



@router.callback_query(F.data == "report:view")
async def cb_view_report(
    cb: CallbackQuery, state: FSMContext, user: User, session: AsyncSession
) -> None:
    data = await state.get_data()
    student_id = data.get("student_id")
    shift_id = data.get("shift_id")
    student_name = data.get("student_name", "—")

    if not student_id or not shift_id:
        await cb.answer("Сначала выберите ребёнка.", show_alert=True)
        return

    await cb.answer()
    report_repo = ReportRepository(session)
    report = await report_repo.get_by_student(user.id, student_id, shift_id)
    if not report or not (report.generated_text or "").strip():
        await cb.message.answer(
            "⚠️ Сохранённый отчёт не найден.",
            reply_markup=back_to_report_keyboard(),
        )
        return

    # Показываем ПОЛНЫЙ текст отчёта (блок ответов 1..13 + итоговый отчёт),
    # а не только итоговую часть — педагог должен видеть отчёт целиком.
    # Части шлём с паузами через _send_parts, иначе Telegram flood-limit
    # доставляет их рывками (педагогу кажется, что «зависло, потом пришло»).
    # К последней части прикрепляем кнопку «← Назад к меню отчёта».
    await safe_answer(cb.message, f"📄 <b>Отчёт: {student_name}</b>")
    await _send_parts(
        cb.message,
        _split_text(report.generated_text),
        final_markup=back_to_report_keyboard(),
    )



# ---------------------------------------------------------------------------
# Финализация отчёта
# ---------------------------------------------------------------------------

# ВАЖНО: без фильтра по состоянию. Раньше стоял GenerationStates.reviewing —
# если FSM-состояние терялось/не совпадало, кнопка «Сохранить» не ловилась ни
# одним хендлером и апдейт уходил в «not handled» (кнопка «залипала»).
# callback_data однозначно определяет действие, поэтому состояние тут избыточно.
@router.callback_query(F.data == "report:finalize")
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

    try:
        department_id = data.get("department_id")
        report_repo = ReportRepository(session)
        student_repo = StudentRepository(session)

        # Ключевой шаг: фиксация отчёта в БД. Коммит выполнит DbSessionMiddleware
        # после успешного возврата хендлера. Все последующие Telegram-вызовы идут
        # через safe_* — сетевой сбой доставки НЕ должен откатывать этот finalize.
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
        await safe_edit_text(
            cb.message,
            f"✅ <b>Отчёт для {student_name} сохранён!</b>\n\n"
            f"Готово отчётов: <b>{done}/{total}</b>",
            reply_markup=after_finalize_menu(done, total),
        )
        await cb.answer("Сохранено ✅")
    except Exception as e:
        logger.error(f"Finalize report error: {e}", exc_info=True)
        # finalize уже выполнен в рамках сессии и будет закоммичен; сообщаем мягко.
        await cb.answer("⚠️ Отчёт сохранён, но экран мог не обновиться.", show_alert=True)



# ---------------------------------------------------------------------------
# Запрос на правку
# ---------------------------------------------------------------------------

# Без фильтра по состоянию — см. пояснение у report:finalize.
@router.callback_query(F.data == "report:revise")
async def cb_request_revision(cb: CallbackQuery, state: FSMContext) -> None:

    data = await state.get_data()
    current_text = ""
    report_id = data.get("report_id")
    if report_id:
        # Полный текст отчёта показывается перед LLM-правкой, чтобы педагог видел,
        # что именно он просит изменить.
        # session здесь нет, поэтому используем только сохранённый в FSM текст при наличии.
        current_text = data.get("current_report_text", "")
    await state.set_state(GenerationStates.waiting_revision)
    text = (
        "✏️ <b>Напишите что нужно исправить</b>\n\n"
        "Например: «Сделай тон более тёплым» или «Добавь про командную работу»\n\n"
        "Можно написать текстом или отправить <b>голосовое сообщение</b> 🎤"
    )
    if current_text:
        text = f"📄 <b>Текущий полный текст отчёта:</b>\n\n<blockquote>{current_text}</blockquote>\n\n" + text
    # Кнопка «← Назад к меню отчёта» — чтобы можно было отказаться от правки.
    await cb.message.answer(text, reply_markup=back_to_report_keyboard())


@router.callback_query(F.data == "report:ai_edit")
async def cb_ai_edit_report(
    cb: CallbackQuery, state: FSMContext, user: User, session: AsyncSession
) -> None:
    """Редактирование отчёта с помощью ИИ, в т.ч. финализированного.

    Загружает актуальный отчёт в FSM и переводит педагога в обычный флоу
    ИИ-правки (тот же, что и «✏️ Исправить текст» после генерации).
    """
    data = await state.get_data()
    report_id = data.get("report_id")
    student_id = data.get("student_id")
    shift_id = data.get("shift_id")

    report_repo = ReportRepository(session)
    report = await report_repo.get_by_id(report_id) if report_id else None
    if report is None and student_id and shift_id:
        report = await report_repo.get_by_student(user.id, student_id, shift_id)
    if report is None or not (report.generated_text or "").strip():
        await cb.answer("⚠️ Отчёт не найден", show_alert=True)
        return

    await state.update_data(report_id=report.id, current_report_text=report.generated_text)
    await state.set_state(GenerationStates.waiting_revision)
    await cb.answer()

    await safe_answer(cb.message, "📄 <b>Текущий полный текст отчёта:</b>")
    await _send_parts(cb.message, _split_text(report.generated_text))
    # Кнопка «← Назад к меню отчёта» — чтобы можно было отказаться от ИИ-правки.
    await safe_answer(
        cb.message,
        "✏️ <b>Напишите что нужно исправить</b>\n\n"
        "Например: «Сделай тон более тёплым» или «Добавь про командную работу»\n\n"
        "Можно написать текстом или отправить <b>голосовое сообщение</b> 🎤",
        reply_markup=back_to_report_keyboard(),
    )



@router.callback_query(F.data == "report:manual_edit")
async def cb_manual_edit_report(

    cb: CallbackQuery, state: FSMContext, user: User, session: AsyncSession
) -> None:
    """Ручное редактирование полного текста отчёта, включая финализированный."""
    data = await state.get_data()
    report_id = data.get("report_id")
    student_id = data.get("student_id")
    shift_id = data.get("shift_id")
    student_name = data.get("student_name", "—")

    report_repo = ReportRepository(session)
    report = await report_repo.get_by_id(report_id) if report_id else None
    if report is None and student_id and shift_id:
        report = await report_repo.get_by_student(user.id, student_id, shift_id)
    if report is None or not (report.generated_text or "").strip():
        await cb.answer("⚠️ Отчёт не найден", show_alert=True)
        return

    await state.update_data(report_id=report.id, current_report_text=report.generated_text)
    await state.set_state(GenerationStates.manual_editing)
    await cb.answer()
    await safe_answer(cb.message, f"📄 <b>Полный текст отчёта для {student_name}:</b>")
    await _send_parts(cb.message, _split_text(report.generated_text))
    # Кнопка «← Назад к меню отчёта» — чтобы можно было отказаться от ручной правки.
    await safe_answer(
        cb.message,
        "⌨️ <b>Отправьте новым сообщением полный исправленный текст отчёта.</b>\n\n"
        "Он заменит текущую версию целиком. Можно редактировать даже финализированный отчёт.",
        reply_markup=back_to_report_keyboard(),
    )



@router.message(GenerationStates.manual_editing, F.text)
async def manual_edit_text(
    message: Message, state: FSMContext, user: User, session: AsyncSession
) -> None:
    new_text = (message.text or "").strip()
    if len(new_text) < 10:
        await message.answer("⚠️ Текст слишком короткий. Отправьте полный текст отчёта.")
        return
    data = await state.get_data()
    report_id = data.get("report_id")
    student_name = data.get("student_name", "—")
    if not report_id:
        await message.answer("⚠️ Ошибка: отчёт не найден.")
        return

    report_repo = ReportRepository(session)
    ok = await report_repo.update_text(report_id, new_text)
    if not ok:
        await message.answer("⚠️ Не удалось сохранить отчёт.")
        return
    await report_repo.add_revision_message(
        report_id=report_id,
        role=DialogRole.user,
        content="Ручное редактирование полного текста отчёта",
    )
    await report_repo.add_revision_message(
        report_id=report_id,
        role=DialogRole.assistant,
        content=new_text,
    )
    await state.update_data(current_report_text=new_text)
    await state.set_state(GenerationStates.reviewing)
    # safe_answer: текст уже сохранён в БД, сетевой сбой доставки не должен откатывать его.
    await safe_answer(
        message,
        f"✅ Полный текст отчёта для <b>{student_name}</b> сохранён.\n\n"
        "Можно сохранить/финализировать, исправить ещё или вернуться к списку детей.",
        reply_markup=report_review_keyboard(),
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
# Сбор контекста департамента/смены
# ---------------------------------------------------------------------------

async def _build_shift_context(
    session: AsyncSession,
    user: User,
    shift_id: int | None,
    department_id: int | None,
) -> str:
    """Собирает контекст департамента/смены (тот же, что при генерации отчёта).

    Используется при ИИ-правке отчёта, чтобы передать в LLM справочный фон
    (мир лагеря + сюжет департамента). Логика идентична cb_generate_report:
    берём контекст teacher_departments, с фолбэком на общий контекст
    департамента и legacy-контекст смены; префиксуем названием департамента.
    """
    shift_context = ""
    department = None
    if department_id:
        dep_repo = DepartmentRepository(session)
        department = await dep_repo.get_by_id(department_id)
        td = await dep_repo.get_teacher_department(user.id, department_id)
        shift_context = (td.shift_context if td else "") or ""
        # Фолбэк: контекст мог заполнить другой аккаунт по этому департаменту.
        if not shift_context:
            shift_context = await dep_repo.get_any_context(department_id)
    if not shift_context and shift_id:
        shift_repo = ShiftRepository(session)
        ts = await shift_repo.get_teacher_shift(user.id, shift_id)
        shift_context = (ts.shift_context if ts else "") or ""

    if department_id and department:
        shift_context = (
            f"Департамент: {get_department_name(department.department_number)}\n\n"
            f"{shift_context}"
        ).strip()
    return shift_context


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
    shift_id = data.get("shift_id")
    department_id = data.get("department_id")
    student_name = data.get("student_name", "—")

    if not report_id:
        await message.answer("⚠️ Ошибка: отчёт не найден.")
        return

    # Busy-lock: правка уже идёт → не запускаем вторую (иначе двойная отправка
    # текста подряд запускала бы два параллельных запроса к LLM с гонками).
    if await _is_busy(state):
        await message.answer("⏳ Уже применяю предыдущую правку, подождите…")
        return
    await _set_busy(state, True)

    status_msg = await message.answer(f"⏳ Применяю правки для {student_name}...")
    report_repo = ReportRepository(session)

    try:

        # Текущий (актуальный) текст отчёта. В модель отправляем именно его +
        # новую правку (НЕ всю растущую историю правок — иначе вход разрастается
        # в «полотно», а ответ упирается в лимит и обрывается на полуслове).
        current_report = await report_repo.get_by_id(report_id)
        current_text = current_report.generated_text if current_report else ""
        prev_answers, _ = _split_report(current_text)

        # Контекст департамента/смены — тот же, что и при генерации отчёта. Он
        # передаётся в LLM как справочный фон, чтобы правки сохраняли мир лагеря
        # и роль департамента (в промте помечен как контекст, а не факты).
        shift_context = await _build_shift_context(
            session, user, shift_id, department_id
        )

        # Историю всё равно ведём для аудита/просмотра, но в LLM её не шлём.
        await report_repo.add_revision_message(
            report_id=report_id,
            role=DialogRole.user,
            content=revision_request,
        )
        llm = LLMService()
        revised_text = await llm.revise_report(
            current_report=current_text,
            revision_request=revision_request,
            shift_context=shift_context,
        )



        # Гарантия сохранности ответов: если у отчёта был блок ответов 1..13,
        # но модель его не вернула (потеряла/обрезала), пересобираем полный текст
        # из сохранённого блока ответов + свежего итогового отчёта.
        new_answers, new_final = _split_report(revised_text)
        if prev_answers and not new_answers:
            final_part = new_final or revised_text.strip()
            revised_text = f"{prev_answers}\n\n{REPORT_MARKER}\n\n{final_part}"

        await report_repo.update_text(report_id, revised_text)
        await report_repo.add_revision_message(
            report_id=report_id,
            role=DialogRole.assistant,
            content=revised_text,
        )
        await state.update_data(current_report_text=revised_text)
        await state.set_state(GenerationStates.reviewing)
        try:
            await status_msg.delete()
        except Exception:
            logger.debug("status_msg.delete failed", exc_info=True)

        # safe_answer + паузы: правка уже сохранена в БД выше — доставка не должна
        # её откатывать, а паузы между частями не дают ловить flood-limit Telegram.
        await _send_parts(
            message,
            _split_text(revised_text),
            final_suffix="\n\n─────────────────\n"
                         "Исправленный отчёт. Сохранить или исправить ещё?",
            final_markup=report_review_keyboard(),
        )
    except Exception as e:
        logger.error(f"Revision error: {e}", exc_info=True)
        await safe_edit_text(
            status_msg,
            "⚠️ Ошибка при применении правок. Попробуйте ещё раз.",
            reply_markup=report_review_keyboard(),
        )
        await state.set_state(GenerationStates.reviewing)
    finally:
        # Снимаем busy-lock в любом случае — иначе после ошибки правка осталась бы
        # навсегда заблокированной («⏳ Уже применяю…»).
        await _set_busy(state, False)




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
    # ИСПРАВЛЕНО: _show_children ожидает department_id, а не shift_id.
    # Раньше сюда передавался shift_id → get_by_department(shift_id) не находил
    # детей → ошибочно показывалось «В этом департаменте пока нет учащихся».
    department_id = data.get("department_id")
    if not department_id:
        await cb.answer("Сначала выберите департамент.", show_alert=True)
        return

    await state.update_data(student_id=None, student_name=None, report_id=None)
    # ИСПРАВЛЕНО: передаём cb (CallbackQuery), а не cb.message — _show_children ожидает CallbackQuery
    await _show_children(cb, user, session, state, department_id)



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
    Настоящий экспорт обрабатывает export.py (пошаговый флоу: смена/ребёнок → формат).
    """
    await cb.message.edit_text(
        "📥 <b>Скачать отчёты</b>\n\nЧто вы хотите скачать?",
        reply_markup=export_mode_menu(),
    )
    await cb.answer()
