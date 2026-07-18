import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from sqlalchemy.ext.asyncio import AsyncSession


from app.bot.keyboards.main_menu import (
    export_menu,
    export_mode_menu,
    export_shifts_keyboard,
    export_departments_keyboard,
    export_format_keyboard,
    export_children_keyboard,
)
from app.database.models import User, UserRole

from app.repositories.department_repo import DepartmentRepository
from app.repositories.report_repo import ReportRepository
from app.repositories.shift_repo import ShiftRepository
from app.repositories.student_repo import StudentRepository
from app.repositories.user_repo import UserRepository
from app.services.docx_service import DocxService
from app.services.zip_service import ZipService


logger = logging.getLogger(__name__)
router = Router(name="teacher_export")


# Busy-lock для экспорта: генерация файла/архива (PPTX→PDF через soffice, сборка
# ZIP) занимает секунды–минуты. Без защиты нетерпеливые повторные нажатия «PPTX/PDF»
# запускали бы параллельно несколько тяжёлых сборок → лишняя нагрузка и «зависания».
async def _export_is_busy(state: FSMContext) -> bool:
    return bool((await state.get_data()).get("export_busy", False))


async def _export_set_busy(state: FSMContext, value: bool) -> None:
    await state.update_data(export_busy=value)



def _export_back_callback(user: User) -> str | None:
    """Куда возвращать пользователя с первого экрана экспорта."""
    return "admin:main" if user.role == UserRole.admin else None


def _export_menu_for_user(user: User):
    return export_menu(
        back_callback=_export_back_callback(user),
        allow_all_shift=user.role == UserRole.admin,
    )


def _export_mode_menu_for_user(user: User):
    return export_mode_menu(
        back_callback=_export_back_callback(user),
        allow_all_shift=user.role == UserRole.admin,
    )


async def _replace_with_bottom_menu(cb: CallbackQuery, text: str, reply_markup=None):
    """Показывает актуальное меню последним сообщением в чате.

    В Telegram нельзя «закрепить» inline-клавиатуру снизу, поэтому для меню,
    с которым пользователь должен продолжать работать, удаляем старое сообщение
    с кнопками и отправляем новое. Тогда служебные сообщения/файлы остаются выше,
    а рабочее диалоговое окно оказывается внизу переписки.
    """
    try:
        await cb.message.delete()
    except Exception:
        logger.debug("Could not delete previous export menu message", exc_info=True)
    return await cb.message.answer(text, reply_markup=reply_markup)


async def _send_export_bottom_menu(
    cb: CallbackQuery, user: User, state: FSMContext | None = None
) -> None:
    """После файлов/служебных сообщений возвращает меню экспорта вниз чата.

    Для педагога, если в сессии есть выбранный департамент, добавляем прямую
    кнопку «👦 К списку детей» — чтобы после скачивания не оставаться в тупике
    из двух кнопок «PPTX/PDF», а сразу вернуться к детям для правки/выбора
    следующего ребёнка (частая жалоба: «негде редактировать, некуда вернуться»).
    """
    markup = _export_mode_menu_for_user(user)
    if state is not None and user.role != UserRole.admin:
        data = await state.get_data()
        if data.get("department_id"):
            rows = list(markup.inline_keyboard)
            rows.append([
                InlineKeyboardButton(
                    text="👦 К списку детей",
                    callback_data="teacher:child_list",
                )
            ])
            markup = InlineKeyboardMarkup(inline_keyboard=rows)
    await cb.message.answer(
        "📥 <b>Скачать ещё отчёты?</b>",
        reply_markup=markup,
    )



async def _resolve_shift_context(
    session: AsyncSession, teacher_id: int, shift_id: int, department_id: int | None
) -> str:
    """Возвращает контекст смены (по департаменту, иначе по смене)."""
    shift_context = ""
    if department_id:
        dep_repo = DepartmentRepository(session)
        td = await dep_repo.get_teacher_department(teacher_id, department_id)
        shift_context = (td.shift_context if td else "") or ""
        # Фолбэк: контекст мог заполнить ДРУГОЙ аккаунт (напр. админ) —
        # берём любой непустой контекст по этому департаменту.
        if not shift_context:
            shift_context = await dep_repo.get_any_context(department_id)
    if not shift_context:
        shift_repo = ShiftRepository(session)
        ts = await shift_repo.get_teacher_shift(teacher_id, shift_id)
        shift_context = (ts.shift_context if ts else "") or ""
    return shift_context



async def _resolve_dep_number(
    session: AsyncSession, student, state_department_id: int | None
) -> int | None:
    """
    Возвращает НОМЕР департамента (1..9) для ребёнка. Приоритет — department_id
    самого ребёнка (FK на departments.id), фолбэк — выбранный в state.
    """
    dep_id = getattr(student, "department_id", None) or state_department_id
    if dep_id:
        dep = await DepartmentRepository(session).get_by_id(dep_id)
        if dep:
            return dep.department_number
    return None


# ---------------------------------------------------------------------------
# Меню экспорта
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "export:menu")
async def cb_export_menu(cb: CallbackQuery, state: FSMContext, user: User) -> None:
    """Первый шаг скачивания: выбрать один из трёх сценариев."""
    await _replace_with_bottom_menu(
        cb,
        "📥 <b>Скачать отчёты</b>\n\n"
        "Что вы хотите скачать?",
        reply_markup=_export_mode_menu_for_user(user),
    )
    await cb.answer()


async def _available_departments(session: AsyncSession, user: User):
    """Все доступные департаменты пользователя."""
    dep_repo = DepartmentRepository(session)
    if user.role == UserRole.admin:
        departments = list(await dep_repo.get_all_active())
    else:
        departments = list(await dep_repo.get_for_teacher(user.id))
    return departments


async def _available_shifts(session: AsyncSession, user: User):
    """Все доступные смены пользователя."""
    shift_repo = ShiftRepository(session)
    if user.role == UserRole.admin:
        return list(await shift_repo.get_all_active())

    # Актуальная модель привязки преподавателя — через departments /
    # teacher_departments. Legacy teacher_shifts может быть пустой, из-за чего
    # преподаватель видел «Нет доступных смен для выгрузки» при выборе отчёта
    # одного ребёнка.
    departments = await _available_departments(session, user)
    shift_ids = {d.shift_id for d in departments}
    shifts = []
    for shift_id in shift_ids:
        shift = await shift_repo.get_by_id(shift_id)
        if shift and shift.is_active:
            shifts.append(shift)
    shifts.sort(key=lambda s: s.start_date, reverse=True)
    return shifts


async def _available_departments_for_shift(
    session: AsyncSession, user: User, shift_id: int
):
    """Доступные департаменты внутри выбранной смены."""
    if user.role == UserRole.admin:
        return list(await DepartmentRepository(session).get_by_shift(shift_id))
    departments = await _available_departments(session, user)
    return [d for d in departments if d.shift_id == shift_id]


async def _show_export_shifts(
    cb: CallbackQuery,
    state: FSMContext,
    user: User,
    session: AsyncSession,
    mode: str,
) -> None:
    """Общий шаг выбора смены для всех сценариев экспорта."""
    await state.update_data(
        export_mode=mode,
        shift_id=None,
        department_id=None,
        student_id=None,
        export_child_page=0,
    )

    shifts = await _available_shifts(session, user)
    if not shifts:
        await cb.message.edit_text(
            "📭 Нет доступных смен для выгрузки.",
            reply_markup=_export_mode_menu_for_user(user),
        )
        await cb.answer()
        return

    titles = {
        "child": "👤 <b>Отчёт одного ребёнка</b>",
        "department": "🏢 <b>Отчёты департамента</b>",
        "all": "🏕 <b>Все отчёты смены</b>",
    }
    await cb.message.edit_text(
        f"{titles.get(mode, '📥 <b>Скачать отчёты</b>')}\n\nВыберите смену:",
        reply_markup=export_shifts_keyboard(shifts),
    )
    await cb.answer()


@router.callback_query(F.data.in_({
    "export:mode:child",
    "export:mode:department",
    "export:mode:all",
    "export:mode:shift",
    "export:mode:shift_pdf",
    "export:all",
}))
async def cb_export_mode(
    cb: CallbackQuery, state: FSMContext, user: User, session: AsyncSession
) -> None:
    """Выбран режим экспорта → просим выбрать смену."""
    raw_mode = cb.data.split(":")[-1]
    if cb.data == "export:all" or raw_mode in {"shift", "shift_pdf", "all"}:
        if user.role != UserRole.admin:
            await cb.answer(
                "Полная выгрузка смены доступна только администратору.",
                show_alert=True,
            )
            return
        mode = "all"
    elif raw_mode == "department":
        mode = "department"
    else:
        mode = "child"
    await _show_export_shifts(cb, state, user, session, mode)


@router.callback_query(F.data.startswith("export:shift:"))
async def cb_export_shift(
    cb: CallbackQuery, state: FSMContext, user: User, session: AsyncSession
) -> None:
    """Выбрана смена → либо формат архива всей смены, либо список департаментов."""
    shift_id = int(cb.data.split(":")[-1])
    shift = await ShiftRepository(session).get_by_id(shift_id)
    if shift is None:
        await cb.answer("❌ Смена не найдена", show_alert=True)
        return

    await state.update_data(shift_id=shift_id, department_id=None, student_id=None)
    data = await state.get_data()
    mode = data.get("export_mode", "child")

    if mode == "all":
        if user.role != UserRole.admin:
            await cb.answer(
                "Полная выгрузка смены доступна только администратору.",
                show_alert=True,
            )
            return
        await cb.message.edit_text(
            f"🏕 <b>Все отчёты смены</b>\n{shift.name}\n\n"
            "Выберите формат архива:",
            reply_markup=export_format_keyboard("all", back_callback="export:all"),
        )
        await cb.answer()
        return

    departments = await _available_departments_for_shift(session, user, shift_id)
    if not departments:
        await cb.message.edit_text(
            "📭 В этой смене нет доступных департаментов для выгрузки.",
            reply_markup=_export_mode_menu_for_user(user),
        )
        await cb.answer()
        return

    title = "👤 <b>Отчёт одного ребёнка</b>" if mode == "child" else "🏢 <b>Отчёты департамента</b>"
    await cb.message.edit_text(
        f"{title}\n🏕 {shift.name}\n\nВыберите департамент:",
        reply_markup=export_departments_keyboard(
            departments,
            back_callback=f"export:mode:{mode}",
        ),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("export:dep:"))
async def cb_export_dep(
    cb: CallbackQuery, state: FSMContext, user: User, session: AsyncSession
) -> None:
    """Выбран департамент → список детей или формат архива департамента."""
    department_id = int(cb.data.split(":")[-1])
    dep_repo = DepartmentRepository(session)
    department = await dep_repo.get_by_id(department_id)
    if department is None:
        await cb.answer("❌ Департамент не найден", show_alert=True)
        return

    await state.update_data(
        department_id=department_id,
        shift_id=department.shift_id,
        student_id=None,
    )
    data = await state.get_data()
    mode = data.get("export_mode", "department")

    if mode == "department":
        shift = await ShiftRepository(session).get_by_id(department.shift_id)
        shift_name = shift.name if shift else "Смена"
        await cb.message.edit_text(
            f"🏢 <b>Отчёты департамента</b>\n"
            f"🏕 {shift_name}\n"
            f"🏢 {department.name}\n\n"
            "Выберите формат архива:",
            reply_markup=export_format_keyboard(
                "department",
                back_callback=f"export:shift:{department.shift_id}",
            ),
        )
        await cb.answer()
        return

    await _show_export_children(cb, state, user, session, department_id, page=0)


async def _show_export_children(
    cb: CallbackQuery, state: FSMContext, user: User, session: AsyncSession,
    department_id: int, page: int,
) -> None:
    """Показывает постраничный список детей департамента с финализированными отчётами."""
    student_repo = StudentRepository(session)
    report_repo = ReportRepository(session)
    dep_repo = DepartmentRepository(session)

    department = await dep_repo.get_by_id(department_id)
    shift_id = department.shift_id if department else None

    students = list(await student_repo.get_by_department(department_id))
    finalized_ids = await report_repo.get_finalized_student_ids(user.id, shift_id)
    ready = [s for s in students if s.id in finalized_ids]

    if not ready:
        await cb.message.edit_text(
            "📭 В этом департаменте нет готовых (финализированных) отчётов.",
            reply_markup=_export_mode_menu_for_user(user),
        )
        await cb.answer()
        return

    await state.update_data(export_child_page=page)
    await cb.message.edit_text(
        f"👤 <b>Отчёт одного ребёнка</b>\n"
        f"🏢 {department.name if department else ''}\n\n"
        "Выберите ребёнка (показаны только готовые отчёты):",
        reply_markup=export_children_keyboard(
            ready,
            page=page,
            back_callback=f"export:shift:{shift_id}",
        ),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("export:child_page:"))
async def cb_export_child_page(
    cb: CallbackQuery, state: FSMContext, user: User, session: AsyncSession
) -> None:
    """Постраничная навигация по списку детей для экспорта."""
    raw = cb.data.split(":")[-1]
    if raw == "noop":
        await cb.answer()
        return
    data = await state.get_data()
    department_id = data.get("department_id")
    if not department_id:
        await cb.answer("❌ Сессия истекла. Начните заново.", show_alert=True)
        return
    try:
        page = int(raw)
    except ValueError:
        page = 0
    await _show_export_children(cb, state, user, session, department_id, page=page)


@router.callback_query(F.data.startswith("export:child:"))
async def cb_export_child_selected(
    cb: CallbackQuery, state: FSMContext
) -> None:
    """Выбран ребёнок → просим выбрать формат файла."""
    student_id = int(cb.data.split(":")[-1])
    await state.update_data(student_id=student_id)
    data = await state.get_data()
    department_id = data.get("department_id")
    await cb.message.edit_text(
        "👤 <b>Отчёт одного ребёнка</b>\n\nВыберите формат файла:",
        reply_markup=export_format_keyboard(
            "child",
            back_callback=(f"export:dep:{department_id}" if department_id else "export:menu"),
        ),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("export:child_fmt:"))
async def cb_export_child_format(
    cb: CallbackQuery, state: FSMContext, user: User, session: AsyncSession
) -> None:
    """Формат выбран для одного ребёнка → генерируем файл."""
    as_pdf = cb.data.split(":")[-1] == "pdf"
    await _export_single(cb, state, user, session, as_pdf=as_pdf)


@router.callback_query(F.data.startswith("export:department_fmt:"))
async def cb_export_department_format(
    cb: CallbackQuery, state: FSMContext, user: User, session: AsyncSession
) -> None:
    """Формат выбран для департамента → собираем ZIP."""
    as_pdf = cb.data.split(":")[-1] == "pdf"
    await _export_zip(cb, state, user, session, as_pdf=as_pdf, export_scope="department")


@router.callback_query(F.data.startswith("export:all_fmt:"))
async def cb_export_all_format(
    cb: CallbackQuery, state: FSMContext, user: User, session: AsyncSession
) -> None:
    """Формат выбран для всей смены → собираем ZIP с папками департаментов."""
    if user.role != UserRole.admin:
        await cb.answer(
            "Полная выгрузка смены доступна только администратору.",
            show_alert=True,
        )
        return
    as_pdf = cb.data.split(":")[-1] == "pdf"
    await _export_zip(cb, state, user, session, as_pdf=as_pdf, export_scope="all")


@router.callback_query(F.data.startswith("export:shift_fmt:"))
async def cb_export_shift_format_legacy(
    cb: CallbackQuery, state: FSMContext, user: User, session: AsyncSession
) -> None:
    """Legacy callback: считаем его экспортом департамента."""
    as_pdf = cb.data.split(":")[-1] == "pdf"
    await _export_zip(cb, state, user, session, as_pdf=as_pdf, export_scope="department")



# ---------------------------------------------------------------------------
# Скачать отчёт одного ребёнка (PPTX или PDF)
# ---------------------------------------------------------------------------

async def _export_single(
    cb: CallbackQuery, state: FSMContext, user: User, session: AsyncSession,
    as_pdf: bool,
) -> None:
    data = await state.get_data()
    student_id = data.get("student_id")
    shift_id = data.get("shift_id")
    department_id = data.get("department_id")

    report_repo = ReportRepository(session)
    report = None

    report_id = data.get("report_id")
    if report_id:
        report = await report_repo.get_by_id(report_id)
        if report:
            student_id = student_id or report.student_id
            shift_id = shift_id or report.shift_id

    if not student_id or not shift_id:
        await cb.answer("Сначала выберите ребёнка.", show_alert=True)
        return

    await cb.answer("⏳ Генерирую файл...")

    student_repo = StudentRepository(session)
    shift_repo = ShiftRepository(session)
    user_repo = UserRepository(session)

    if report is None or report.student_id != student_id or report.shift_id != shift_id:
        report = await report_repo.get_by_student(user.id, student_id, shift_id)
    if not report or not report.is_finalized:
        await cb.message.answer(
            "⚠️ Отчёт не финализирован. Сначала сохраните отчёт."
        )
        return

    student = await student_repo.get_by_id(student_id)
    shift = await shift_repo.get_by_id(shift_id)
    teacher = await user_repo.get_by_id(user.id)

    if not student or not shift or not teacher:
        await cb.message.answer("⚠️ Ошибка: не найдены данные.")
        return

    # Busy-lock: не даём запустить вторую генерацию файла, пока идёт текущая.
    if await _export_is_busy(state):
        await cb.answer("⏳ Уже генерирую файл, подождите…", show_alert=True)
        return
    await _export_set_busy(state, True)

    # Проставляем НОМЕР департамента ребёнка — сервис возьмёт из него цвет/имя.
    student.department_number = await _resolve_dep_number(
        session, student, department_id
    )

    shift_context = await _resolve_shift_context(
        session, user.id, shift_id, department_id
    )

    try:
        docx_svc = DocxService()
        if as_pdf:

            file_path = await docx_svc.generate_pdf_async(
                report=report, student=student, shift=shift, teacher=teacher,
                shift_context=shift_context,
            )
        else:
            file_path = await docx_svc.generate_async(
                report=report, student=student, shift=shift, teacher=teacher,
                shift_context=shift_context,
            )

            # Обновляем путь в БД (только для основного DOCX)
            await report_repo.finalize(report.id, docx_path=str(file_path))

        doc_file = FSInputFile(str(file_path), filename=file_path.name)
        await cb.message.answer_document(
            doc_file,
            caption=f"📄 Отчёт: <b>{student.full_name}</b>\n{shift.name}",
        )
        await _send_export_bottom_menu(cb, user, state)


        logger.info(
            f"Sent {'PDF' if as_pdf else 'DOCX'} for student={student.full_name} "
            f"to teacher={user.id}"
        )


    except Exception as e:
        logger.error(f"Export error: {e}", exc_info=True)
        await cb.message.answer("⚠️ Ошибка при генерации файла. Попробуйте ещё раз.")
    finally:
        await _export_set_busy(state, False)


@router.callback_query(F.data == "export:single")

async def cb_export_single(
    cb: CallbackQuery, state: FSMContext, user: User, session: AsyncSession
) -> None:
    await _export_single(cb, state, user, session, as_pdf=False)


@router.callback_query(F.data == "export:single_pdf")
async def cb_export_single_pdf(
    cb: CallbackQuery, state: FSMContext, user: User, session: AsyncSession
) -> None:
    await _export_single(cb, state, user, session, as_pdf=True)


# ---------------------------------------------------------------------------
# Скачать ZIP всех финализированных отчётов (PPTX или PDF)
# ---------------------------------------------------------------------------

async def _export_zip(
    cb: CallbackQuery, state: FSMContext, user: User, session: AsyncSession,
    as_pdf: bool,
    export_scope: str,
) -> None:
    if export_scope == "all" and user.role != UserRole.admin:
        await cb.answer(
            "Полная выгрузка смены доступна только администратору.",
            show_alert=True,
        )
        return

    data = await state.get_data()
    shift_id = data.get("shift_id")
    department_id = data.get("department_id")

    if not shift_id:
        await cb.answer("Сначала выберите смену.", show_alert=True)
        return
    if export_scope == "department" and not department_id:
        await cb.answer("Сначала выберите департамент.", show_alert=True)
        return

    # Busy-lock: не собираем второй архив, пока идёт текущая сборка.
    if await _export_is_busy(state):
        await cb.answer("⏳ Уже собираю архив, подождите…", show_alert=True)
        return
    await _export_set_busy(state, True)

    status_text = (
        "⏳ Собираю архив департамента..."
        if export_scope == "department"
        else "⏳ Собираю архив всей смены..."
    )
    status_msg = await cb.message.edit_text(status_text)


    dep_repo = DepartmentRepository(session)
    report_repo = ReportRepository(session)
    student_repo = StudentRepository(session)
    shift_repo = ShiftRepository(session)
    user_repo = UserRepository(session)

    reports = list(await report_repo.get_all_finalized(user.id, shift_id))
    if not reports:
        await status_msg.edit_text(
            "⚠️ Нет финализированных отчётов для скачивания.",
            reply_markup=_export_menu_for_user(user),
        )
        await _export_set_busy(state, False)
        return

    shift = await shift_repo.get_by_id(shift_id)
    teacher = await user_repo.get_by_id(user.id)
    if not shift or not teacher:
        await status_msg.edit_text(
            "⚠️ Ошибка: не найдены данные для экспорта.",
            reply_markup=_export_menu_for_user(user),
        )
        await _export_set_busy(state, False)
        return


    department = await dep_repo.get_by_id(department_id) if department_id else None
    departments = await dep_repo.get_by_shift(shift_id)
    department_map = {d.id: d for d in departments}

    report_items: list[dict] = []
    for report in reports:
        student = await student_repo.get_by_id(report.student_id)
        if not student:
            continue

        student_department_id = getattr(student, "department_id", None) or department_id
        if export_scope == "department" and student_department_id != department_id:
            continue

        item_department = department_map.get(student_department_id) if student_department_id else None
        student.department_number = (
            item_department.department_number
            if item_department
            else await _resolve_dep_number(session, student, department_id)
        )

        report_items.append(
            {
                "report": report,
                "student": student,
                "shift_context": await _resolve_shift_context(
                    session,
                    user.id,
                    shift_id,
                    student_department_id,
                ),
                "subfolder": item_department.name if item_department else "Без департамента",
            }
        )

    if not report_items:
        empty_text = (
            "⚠️ В выбранном департаменте нет финализированных отчётов."
            if export_scope == "department"
            else "⚠️ Нет финализированных отчётов для скачивания."
        )
        await status_msg.edit_text(empty_text, reply_markup=_export_menu_for_user(user))
        await _export_set_busy(state, False)
        return

    try:
        docx_svc = DocxService()
        zip_svc = ZipService()

        zip_buffer, archive_name, added_count, failed_count = await zip_svc.create_zip_async(

            report_items=report_items,
            shift=shift,
            teacher=teacher,
            report_service=docx_svc,

            as_pdf=as_pdf,
            archive_label=(
                f"{shift.name}_{department.name}"
                if export_scope == "department" and department
                else shift.name
            ),
        )

        if added_count == 0:
            await status_msg.edit_text(
                "⚠️ Не удалось сгенерировать ни один файл для архива.",
                reply_markup=_export_menu_for_user(user),
            )
            return

        zip_file = BufferedInputFile(
            zip_buffer.read(),
            filename=archive_name,
        )
        await status_msg.delete()
        caption_title = (
            "📦 <b>Архив департамента</b>"
            if export_scope == "department"
            else "📦 <b>Архив отчётов смены</b>"
        )
        caption_scope = f"\n{department.name}" if export_scope == "department" and department else ""
        failed_caption = f"\nНе удалось добавить: {failed_count}" if failed_count else ""
        await cb.message.answer_document(
            zip_file,
            caption=(
                f"{caption_title} ({'PDF' if as_pdf else 'DOCX'})\n"

                f"{shift.name}\n"
                f"{caption_scope}\n"
                f"Отчётов: {added_count}"
                f"{failed_caption}"
            ),
        )
        await _send_export_bottom_menu(cb, user, state)

        logger.info(
            f"Sent ZIP {archive_name}: {added_count} reports "
            f"to teacher={user.id}"
        )

    except Exception as e:
        logger.error(f"ZIP export error: {e}", exc_info=True)
        await status_msg.edit_text(
            "⚠️ Ошибка при создании архива.",

            reply_markup=_export_menu_for_user(user),
        )
    finally:
        await _export_set_busy(state, False)


@router.callback_query(F.data == "export:zip")

async def cb_export_zip(
    cb: CallbackQuery, state: FSMContext, user: User, session: AsyncSession
) -> None:
    if user.role != UserRole.admin:
        await cb.answer(
            "Полная выгрузка смены доступна только администратору.",
            show_alert=True,
        )
        return
    await _export_zip(cb, state, user, session, as_pdf=False, export_scope="all")


@router.callback_query(F.data == "export:zip_pdf")
async def cb_export_zip_pdf(
    cb: CallbackQuery, state: FSMContext, user: User, session: AsyncSession
) -> None:
    if user.role != UserRole.admin:
        await cb.answer(
            "Полная выгрузка смены доступна только администратору.",
            show_alert=True,
        )
        return
    await _export_zip(cb, state, user, session, as_pdf=True, export_scope="all")
