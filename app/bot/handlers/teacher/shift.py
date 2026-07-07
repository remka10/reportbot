import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.shift_menu import (
    departments_keyboard,
    context_exists_keyboard,
    context_preview_keyboard,
)
from app.bot.keyboards.child_menu import children_keyboard
from app.bot.states.teacher_states import ShiftSelectStates, ChildSelectStates
from app.database.models import User, get_department_name
from app.repositories.shift_repo import ShiftRepository
from app.repositories.department_repo import DepartmentRepository
from app.repositories.answer_repo import AnswerRepository
from app.repositories.report_repo import ReportRepository
from app.repositories.student_repo import StudentRepository
from app.services.stt_service import STTService
from app.services.llm_service import LLMService

logger = logging.getLogger(__name__)
router = Router(name="teacher_shift")
_stt_service: "STTService | None" = None
_llm_service: "LLMService | None" = None


def get_stt() -> "STTService":
    global _stt_service
    if _stt_service is None:
        _stt_service = STTService()
    return _stt_service


def get_llm() -> "LLMService":
    global _llm_service
    if _llm_service is None:
        _llm_service = LLMService()
    return _llm_service


async def _beautify_and_preview(
    message: Message,
    user: User,
    session: AsyncSession,
    state: FSMContext,
    raw_context: str,
) -> None:
    """
    Прогоняет надиктованный/введённый контекст смены через ИИ (AiTunnel),
    показывает педагогу оформленный вариант и просит подтвердить сохранение.
    Сам контекст в БД пока НЕ пишется — только после подтверждения (accept).
    При ошибке ИИ — сохраняем исходный текст, чтобы педагог не потерял работу.
    """
    data = await state.get_data()
    department_id = data["department_id"]
    department_name = data.get("department_name") or "Департамент не указан"

    processing_msg = await message.answer("✨ Оформляю контекст с помощью ИИ...")
    try:
        beautified = await get_llm().beautify_shift_context(raw_context, department_name)
    except Exception as e:
        logger.error(f"LLM beautify error: {e}", exc_info=True)
        await processing_msg.delete()
        # Фолбэк: сохраняем сырой текст сразу, чтобы работа не пропала.
        dep_repo = DepartmentRepository(session)
        await dep_repo.update_context(user.id, department_id, raw_context)
        await message.answer(
            "⚠️ Не удалось оформить контекст через ИИ — сохранил ваш исходный текст."
        )
        await _show_children_message(message, user, session, state, department_id)
        return

    await state.update_data(raw_context=raw_context, pending_context=beautified)
    await state.set_state(ShiftSelectStates.preview_context)
    await processing_msg.delete()
    await message.answer(
        "✨ <b>Вот оформленный контекст смены:</b>\n\n"
        f"<i>{beautified}</i>\n\n"
        "Сохранить этот вариант, переформулировать заново "
        "или ввести контекст заново?",
        reply_markup=context_preview_keyboard(),
    )




@router.callback_query(F.data == "teacher:shifts")
async def show_departments(
    callback: CallbackQuery, user: User, session: AsyncSession, state: FSMContext
) -> None:
    """Показывает список департаментов педагога (по всем его сменам).

    Если педагог привязан всего к одному департаменту — этап выбора
    пропускается, и сразу открывается его единственный департамент.
    Если все департаменты принадлежат одной смене — выбор смены не нужен,
    показываем только список департаментов без префикса смены в подписи.
    """
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

    # Единственный департамент — сразу открываем его, без выбора смены/департамента.
    if len(departments) == 1:
        await open_department(callback, user, session, state, departments[0].id)
        return

    # Определяем, в скольких сменах работает педагог.
    shift_ids = {d.shift_id for d in departments}
    single_shift = len(shift_ids) == 1

    shift_name_map: dict[int, str] | None
    if single_shift:
        # Все департаменты в одной смене → не показываем название смены в кнопках.
        shift_name_map = None
    else:
        # Педагог работает в нескольких сменах → подписываем департаменты сменой.
        shift_name_map = {}
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
    await open_department(callback, user, session, state, department_id)


async def open_department(
    callback: CallbackQuery,
    user: User,
    session: AsyncSession,
    state: FSMContext,
    department_id: int,
) -> None:
    """
    Открывает работу с департаментом: показывает контекст или просит ввести его.
    Используется как педагогами, так и администраторами (через admin/fill.py).
    Предполагается, что пользователь уже привязан к департаменту
    (TeacherDepartment существует) — для админа привязка создаётся заранее.
    """
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

    # Контекст ОБЩИЙ по департаменту: если у текущего аккаунта своей строки/
    # контекста нет, берём любой непустой контекст, заполненный другим
    # аккаунтом (напр. админом).
    shared_context = (teacher_dep.shift_context or "") if teacher_dep else ""
    if not shared_context:
        shared_context = await dep_repo.get_any_context(department_id)

    # Сохраняем выбранный департамент, смену, название и текущий контекст в FSM.
    await state.update_data(
        department_id=department_id,
        shift_id=department.shift_id,
        department_name=get_department_name(department.department_number),
        current_context=shared_context,
    )

    if shared_context:
        # Если контекст уже заполнен, не заставляем педагога каждый раз
        # подтверждать его отдельным экраном. Сразу открываем список детей;
        # изменить контекст можно кнопкой «✏️ Изменить контекст смены» внизу.
        await _show_children(callback, user, session, state, department_id)
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
    data = await state.get_data()
    current = (data.get("current_context") or "").strip()
    current_block = f"\n\n<b>Текущий контекст:</b>\n<i>{current}</i>\n" if current else ""
    await callback.message.edit_text(
        "✏️ <b>Введите новый контекст:</b>"
        f"{current_block}\n\n"
        "Расскажите о сюжете, чем занимались дети, ключевые события.\n"
        "Можно написать текстом или отправить голосовое сообщение."
    )
    await state.set_state(ShiftSelectStates.entering_context)
    await callback.answer()


@router.message(ShiftSelectStates.entering_context, F.text)
async def save_context_text(
    message: Message, user: User, session: AsyncSession, state: FSMContext
) -> None:
    """Педагог ввёл контекст текстом → отдаём ИИ на оформление и показываем превью."""
    raw = (message.text or "").strip()
    if not raw:
        await message.answer("❌ Пустой контекст. Напишите текст или отправьте голосовое.")
        return
    await _beautify_and_preview(message, user, session, state, raw)


@router.message(ShiftSelectStates.entering_context, F.voice)
async def save_context_voice(
    message: Message, user: User, session: AsyncSession, state: FSMContext
) -> None:
    """Педагог надиктовал контекст голосом → STT → ИИ оформляет → превью."""
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

    await processing_msg.delete()
    await _beautify_and_preview(message, user, session, state, transcription.strip())


@router.callback_query(
    ShiftSelectStates.preview_context, F.data == "teacher:context:accept"
)
async def accept_beautified_context(
    callback: CallbackQuery, user: User, session: AsyncSession, state: FSMContext
) -> None:
    """Педагог подтвердил оформленный ИИ контекст → сохраняем в БД."""
    try:
        data = await state.get_data()
        department_id = data["department_id"]
        pending = data.get("pending_context")
        if not pending:
            await callback.answer("❌ Нет оформленного контекста. Введите заново.", show_alert=True)
            return
        dep_repo = DepartmentRepository(session)
        await dep_repo.update_context(user.id, department_id, pending)
        await callback.answer("✅ Контекст сохранён")
        await _show_children(callback, user, session, state, department_id)
    except Exception as e:
        logger.exception(f"Error in accept_beautified_context: {e}")
        await callback.answer("⚠️ Произошла ошибка. Попробуйте снова.", show_alert=True)


@router.callback_query(
    ShiftSelectStates.preview_context, F.data == "teacher:context:regenerate"
)
async def regenerate_beautified_context(
    callback: CallbackQuery, user: User, session: AsyncSession, state: FSMContext
) -> None:
    """Педагог хочет другой вариант оформления того же исходного текста."""
    try:
        data = await state.get_data()
        raw = data.get("raw_context")
        if not raw:
            await callback.answer("❌ Нет исходного текста. Введите заново.", show_alert=True)
            return
        await callback.answer("🔄 Переформулирую...")
        await callback.message.edit_text("✨ Переформулирую контекст с помощью ИИ...")
        try:
            beautified = await get_llm().beautify_shift_context(raw, data.get("department_name"))
        except Exception as e:
            logger.error(f"LLM regenerate error: {e}", exc_info=True)
            await callback.message.answer(
                "⚠️ Не удалось переформулировать. Попробуйте ещё раз или введите заново."
            )
            return
        await state.update_data(pending_context=beautified)
        await callback.message.answer(
            "✨ <b>Новый вариант контекста:</b>\n\n"
            f"<i>{beautified}</i>\n\n"
            "Сохранить, переформулировать ещё раз или ввести заново?",
            reply_markup=context_preview_keyboard(),
        )
    except Exception as e:
        logger.exception(f"Error in regenerate_beautified_context: {e}")
        await callback.answer("⚠️ Произошла ошибка. Попробуйте снова.", show_alert=True)


@router.callback_query(
    ShiftSelectStates.preview_context, F.data == "teacher:context:redo"
)
async def redo_context_input(callback: CallbackQuery, state: FSMContext) -> None:
    """Педагог хочет заново надиктовать/ввести контекст."""
    await callback.message.edit_text(
        "✏️ <b>Введите контекст заново:</b>\n\n"
        "Расскажите о сюжете, чем занимались дети, ключевые события.\n"
        "Можно написать текстом или отправить голосовое сообщение."
    )
    await state.set_state(ShiftSelectStates.entering_context)
    await callback.answer()


@router.callback_query(
    ShiftSelectStates.preview_context, F.data == "teacher:context:revise"
)
async def ask_revision_comment(callback: CallbackQuery, state: FSMContext) -> None:
    """Педагог хочет исправить оформленный контекст, оставив комментарий."""
    await callback.message.edit_text(
        "💬 <b>Что нужно исправить?</b>\n\n"
        "Опишите, что именно поправить в контексте (например: "
        "«убери про поход», «добавь, что дети победили в конкурсе», "
        "«сделай короче»).\n\n"
        "Можно написать текстом или отправить <b>голосовое сообщение</b>."
    )
    await state.set_state(ShiftSelectStates.revising_context)
    await callback.answer()


async def _revise_and_preview(
    message: Message,
    state: FSMContext,
    comment: str,
) -> None:
    """
    Отправляет ИИ прежний оформленный контекст + комментарий педагога,
    показывает исправленный вариант с теми же кнопками превью.
    """
    data = await state.get_data()
    previous = data.get("pending_context")
    if not previous:
        await message.answer("❌ Нет текущего контекста для правки. Введите заново.")
        await state.set_state(ShiftSelectStates.entering_context)
        return

    processing_msg = await message.answer("✨ Вношу правки с помощью ИИ...")
    try:
        revised = await get_llm().revise_shift_context(previous, comment)
    except Exception as e:
        logger.error(f"LLM revise error: {e}", exc_info=True)
        await processing_msg.delete()
        await message.answer(
            "⚠️ Не удалось внести правки через ИИ. Попробуйте ещё раз."
        )
        # Возвращаем педагога к превью прежнего варианта
        await state.set_state(ShiftSelectStates.preview_context)
        await message.answer(
            "✨ <b>Текущий контекст смены:</b>\n\n"
            f"<i>{previous}</i>",
            reply_markup=context_preview_keyboard(),
        )
        return

    await state.update_data(pending_context=revised)
    await state.set_state(ShiftSelectStates.preview_context)
    await processing_msg.delete()
    await message.answer(
        "✨ <b>Исправленный контекст смены:</b>\n\n"
        f"<i>{revised}</i>\n\n"
        "Сохранить, исправить ещё раз, переформулировать или ввести заново?",
        reply_markup=context_preview_keyboard(),
    )


@router.message(ShiftSelectStates.revising_context, F.text)
async def revise_context_text(message: Message, state: FSMContext) -> None:
    """Педагог прислал текстовый комментарий для правки контекста."""
    comment = (message.text or "").strip()
    if not comment:
        await message.answer("❌ Пустой комментарий. Опишите, что нужно исправить.")
        return
    await _revise_and_preview(message, state, comment)


@router.message(ShiftSelectStates.revising_context, F.voice)
async def revise_context_voice(message: Message, state: FSMContext) -> None:
    """Педагог надиктовал комментарий для правки контекста голосом → STT → ИИ."""
    processing_msg = await message.answer("⏳ Распознаю голосовое сообщение...")
    try:
        transcription = await get_stt().transcribe_voice(message.voice, message.bot)
    except ValueError as e:
        await processing_msg.delete()
        await message.answer(f"❌ {e}")
        return
    except Exception as e:
        logger.error(f"STT error in revise_context_voice: {e}", exc_info=True)
        await processing_msg.delete()
        await message.answer("❌ Не удалось распознать голосовое сообщение. Попробуйте ещё раз.")
        return

    await processing_msg.delete()
    comment = transcription.strip()
    if not comment:
        await message.answer("❌ Не удалось распознать комментарий. Попробуйте ещё раз.")
        return
    await _revise_and_preview(message, state, comment)


@router.callback_query(
    ShiftSelectStates.preview_context, F.data == "teacher:context:manual"
)
async def start_manual_context(callback: CallbackQuery, state: FSMContext) -> None:
    """Педагог хочет ввести/исправить контекст полностью вручную, без ИИ."""
    data = await state.get_data()
    current = data.get("pending_context", "")
    text = (
        "⌨️ <b>Ручной ввод контекста</b>\n\n"
        "Отправьте <b>текстом</b> итоговый контекст смены — он будет "
        "сохранён как есть, без обработки ИИ."
    )
    if current:
        text += (
            "\n\nТекущий вариант (можно скопировать и поправить):\n\n"
            f"<code>{current}</code>"
        )
    await callback.message.edit_text(text)
    await state.set_state(ShiftSelectStates.manual_context)
    await callback.answer()


@router.message(ShiftSelectStates.manual_context, F.text)
async def save_manual_context(
    message: Message, user: User, session: AsyncSession, state: FSMContext
) -> None:
    """Сохраняет введённый вручную контекст напрямую в БД, без ИИ."""
    raw = (message.text or "").strip()
    if not raw:
        await message.answer("❌ Пустой контекст. Отправьте текст.")
        return
    try:
        data = await state.get_data()
        department_id = data["department_id"]
        dep_repo = DepartmentRepository(session)
        await dep_repo.update_context(user.id, department_id, raw)
        await _show_children_message(message, user, session, state, department_id)
    except Exception as e:
        logger.exception(f"Error in save_manual_context: {e}")
        await message.answer("⚠️ Не удалось сохранить контекст. Попробуйте ещё раз.")





async def _build_children_view(
    user: User,
    session: AsyncSession,
    state: FSMContext,
    department_id: int,
):
    """Готовит данные для списка детей департамента.

    Возвращает (students, progress_map, finalized_ids, total, multiple_departments),
    где multiple_departments — True, если у пользователя больше одного
    доступного департамента (нужно для кнопки «Назад к департаментам»).
    """
    student_repo = StudentRepository(session)
    answer_repo = AnswerRepository(session)
    report_repo = ReportRepository(session)
    dep_repo = DepartmentRepository(session)

    department = await dep_repo.get_by_id(department_id)
    shift_id = department.shift_id if department else None
    students = list(await student_repo.get_by_department(department_id))

    # Сколько всего департаментов доступно пользователю — определяет, нужна ли
    # кнопка возврата к списку департаментов (при единственном возвращаться некуда).
    all_departments = list(await dep_repo.get_for_teacher(user.id))
    multiple_departments = len(all_departments) > 1

    if not students:
        return None, None, None, None, multiple_departments

    student_ids = [s.id for s in students]
    progress_map = await answer_repo.get_progress_map(user.id, student_ids)
    # Финализированные ограничиваем студентами этого департамента
    all_finalized = await report_repo.get_finalized_student_ids(user.id, shift_id)
    finalized_ids = {sid for sid in all_finalized if sid in set(student_ids)}

    await state.update_data(
        department_id=department_id,
        shift_id=shift_id,
        multiple_departments=multiple_departments,
    )
    await state.set_state(ChildSelectStates.choosing_child)
    return students, progress_map, finalized_ids, len(students), multiple_departments


async def _show_children(
    callback: CallbackQuery,
    user: User,
    session: AsyncSession,
    state: FSMContext,
    department_id: int,
    page: int = 0,
) -> None:
    students, progress_map, finalized_ids, total, multiple_departments = (
        await _build_children_view(user, session, state, department_id)
    )
    if students is None:
        await callback.message.edit_text(
            "📭 В этом департаменте пока нет учащихся.\n"
            "Добавьте их через /admin."
        )
        return
    await state.update_data(child_page=page)
    await callback.message.edit_text(
        f"👦 <b>Список детей</b>\n"
        f"Готово: {len(finalized_ids)}/{total} отчётов\n"
        "Прогресс у ребёнка: отвечено вопросов из 13.\n\n"
        "Выберите ребёнка:",
        reply_markup=children_keyboard(
            students, progress_map, finalized_ids, page=page,
            show_back_to_departments=multiple_departments,
        ),
    )


async def _show_children_message(
    message: Message,
    user: User,
    session: AsyncSession,
    state: FSMContext,
    department_id: int,
    page: int = 0,
) -> None:
    students, progress_map, finalized_ids, total, multiple_departments = (
        await _build_children_view(user, session, state, department_id)
    )
    if students is None:
        await message.answer(
            "✅ Контекст сохранён!\n\n"
            "📭 В этом департаменте пока нет учащихся. Добавьте их через /admin."
        )
        await state.clear()
        return
    await state.update_data(child_page=page)
    await message.answer(
        f"✅ Контекст сохранён!\n\n"
        f"👦 <b>Список детей</b>\n"
        f"Готово: {len(finalized_ids)}/{total} отчётов\n"
        "Прогресс у ребёнка: отвечено вопросов из 13.\n\n"
        "Выберите ребёнка:",
        reply_markup=children_keyboard(
            students, progress_map, finalized_ids, page=page,
            show_back_to_departments=multiple_departments,
        ),
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

    await _show_children(callback, user, session, state, department_id,
                         page=data.get("child_page", 0))
    await callback.answer()


@router.callback_query(F.data.startswith("teacher:child_page:"))
async def paginate_children(
    callback: CallbackQuery, user: User, session: AsyncSession, state: FSMContext
) -> None:
    """Постраничная навигация по списку детей."""
    raw = callback.data.split(":")[-1]
    if raw == "noop":
        # Нажатие на индикатор «N/M» — ничего не делаем.
        await callback.answer()
        return

    data = await state.get_data()
    department_id = data.get("department_id")
    if not department_id:
        await callback.answer("❌ Сессия истекла. Начните заново /start", show_alert=True)
        return

    try:
        page = int(raw)
    except ValueError:
        page = 0

    await _show_children(callback, user, session, state, department_id, page=page)
    await callback.answer()


@router.callback_query(F.data == "teacher:context:edit")
async def edit_context_from_list(
    callback: CallbackQuery, user: User, session: AsyncSession, state: FSMContext
) -> None:
    """Изменение контекста смены из экрана списка детей (отдельная кнопка).

    Работает независимо от текущего состояния FSM: переводит педагога в ввод
    нового контекста для текущего департамента.
    """
    data = await state.get_data()
    department_id = data.get("department_id")
    if not department_id:
        await callback.answer("❌ Сессия истекла. Начните заново /start", show_alert=True)
        return

    dep_repo = DepartmentRepository(session)
    teacher_dep = await dep_repo.get_teacher_department(user.id, department_id)
    current_context = (teacher_dep.shift_context if teacher_dep else "") or ""
    if not current_context:
        current_context = await dep_repo.get_any_context(department_id)
    await state.update_data(current_context=current_context)
    current_block = (
        f"\n\n<b>Текущий контекст:</b>\n<i>{current_context}</i>\n"
        if current_context else ""
    )

    await callback.message.edit_text(
        "✏️ <b>Введите новый контекст смены:</b>"
        f"{current_block}\n\n"
        "Расскажите о сюжете, чем занимались дети, ключевые события.\n"
        "Можно написать текстом или отправить голосовое сообщение."
    )
    await state.set_state(ShiftSelectStates.entering_context)
    await callback.answer()


@router.callback_query(F.data == "teacher:context:delete")
async def delete_context(
    callback: CallbackQuery, user: User, session: AsyncSession, state: FSMContext
) -> None:
    """Полностью удаляет общий контекст текущего департамента."""
    data = await state.get_data()
    department_id = data.get("department_id")
    if not department_id:
        await callback.answer("❌ Сессия истекла. Начните заново /start", show_alert=True)
        return
    dep_repo = DepartmentRepository(session)
    await dep_repo.clear_context(department_id)
    await state.update_data(current_context="", pending_context="", raw_context="")
    await callback.answer("✅ Контекст удалён")
    await _show_children(callback, user, session, state, department_id)
