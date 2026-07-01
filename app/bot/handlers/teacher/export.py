import logging
from pathlib import Path

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, FSInputFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.main_menu import export_menu
from app.database.models import User
from app.repositories.department_repo import DepartmentRepository
from app.repositories.report_repo import ReportRepository
from app.repositories.shift_repo import ShiftRepository
from app.repositories.student_repo import StudentRepository
from app.repositories.user_repo import UserRepository
from app.services.pptx_service import PptxService
from app.services.zip_service import ZipService

logger = logging.getLogger(__name__)
router = Router(name="teacher_export")


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
async def cb_export_menu(cb: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    student_name = data.get("student_name", "—")
    await cb.message.edit_text(
        f"📥 <b>Экспорт отчётов</b>\n\nТекущий ребёнок: <b>{student_name}</b>",
        reply_markup=export_menu(),
    )


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

    if not student_id or not shift_id:
        await cb.answer("Сначала выберите ребёнка.", show_alert=True)
        return

    await cb.answer("⏳ Генерирую файл...")

    report_repo = ReportRepository(session)
    student_repo = StudentRepository(session)
    shift_repo = ShiftRepository(session)
    user_repo = UserRepository(session)

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

    # Проставляем НОМЕР департамента ребёнка — сервис возьмёт из него цвет/имя.
    student.department_number = await _resolve_dep_number(
        session, student, department_id
    )

    shift_context = await _resolve_shift_context(
        session, user.id, shift_id, department_id
    )

    try:
        pptx_svc = PptxService()
        if as_pdf:
            file_path = pptx_svc.generate_pdf(
                report=report, student=student, shift=shift, teacher=teacher,
                shift_context=shift_context,
            )
        else:
            file_path = pptx_svc.generate(
                report=report, student=student, shift=shift, teacher=teacher,
                shift_context=shift_context,
            )
            # Обновляем путь в БД (только для основного PPTX)
            await report_repo.finalize(report.id, docx_path=str(file_path))

        doc_file = FSInputFile(str(file_path), filename=file_path.name)
        await cb.message.answer_document(
            doc_file,
            caption=f"📄 Отчёт: <b>{student.full_name}</b>\n{shift.name}",
        )

        logger.info(
            f"Sent {'PDF' if as_pdf else 'PPTX'} for student={student.full_name} "
            f"to teacher={user.id}"
        )

    except Exception as e:
        logger.error(f"Export error: {e}", exc_info=True)
        await cb.message.answer("⚠️ Ошибка при генерации файла. Попробуйте ещё раз.")


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
) -> None:
    data = await state.get_data()
    shift_id = data.get("shift_id")
    department_id = data.get("department_id")

    if not shift_id:
        await cb.answer("Сначала выберите смену.", show_alert=True)
        return

    status_msg = await cb.message.edit_text("⏳ Собираю архив с отчётами...")

    report_repo = ReportRepository(session)
    student_repo = StudentRepository(session)
    shift_repo = ShiftRepository(session)
    user_repo = UserRepository(session)

    reports = list(await report_repo.get_all_finalized(user.id, shift_id))
    if not reports:
        await status_msg.edit_text(
            "⚠️ Нет финализированных отчётов для скачивания.",
            reply_markup=export_menu(),
        )
        return

    shift = await shift_repo.get_by_id(shift_id)
    teacher = await user_repo.get_by_id(user.id)

    shift_context = await _resolve_shift_context(
        session, user.id, shift_id, department_id
    )

    # Загружаем учащихся пакетно и проставляем номер департамента.
    student_map: dict[int, object] = {}
    for report in reports:
        s = await student_repo.get_by_id(report.student_id)
        if s:
            s.department_number = await _resolve_dep_number(
                session, s, department_id
            )
            student_map[report.student_id] = s

    reports_with_students = [
        (r, student_map[r.student_id])
        for r in reports
        if r.student_id in student_map
    ]

    try:
        pptx_svc = PptxService()
        zip_svc = ZipService()
        zip_buffer, archive_name = zip_svc.create_zip(
            reports_with_students=reports_with_students,
            shift=shift,
            teacher=teacher,
            report_service=pptx_svc,
            shift_context=shift_context,
            as_pdf=as_pdf,
        )

        zip_file = BufferedInputFile(
            zip_buffer.read(),
            filename=archive_name,
        )
        await status_msg.delete()
        await cb.message.answer_document(
            zip_file,
            caption=(
                f"📦 <b>Архив отчётов</b> ({'PDF' if as_pdf else 'PPTX'})\n"
                f"{shift.name}\n"
                f"Отчётов: {len(reports_with_students)}"
            ),
        )
        logger.info(
            f"Sent ZIP {archive_name}: {len(reports_with_students)} reports "
            f"to teacher={user.id}"
        )

    except Exception as e:
        logger.error(f"ZIP export error: {e}", exc_info=True)
        await status_msg.edit_text(
            "⚠️ Ошибка при создании архива.",
            reply_markup=export_menu(),
        )


@router.callback_query(F.data == "export:zip")
async def cb_export_zip(
    cb: CallbackQuery, state: FSMContext, user: User, session: AsyncSession
) -> None:
    await _export_zip(cb, state, user, session, as_pdf=False)


@router.callback_query(F.data == "export:zip_pdf")
async def cb_export_zip_pdf(
    cb: CallbackQuery, state: FSMContext, user: User, session: AsyncSession
) -> None:
    await _export_zip(cb, state, user, session, as_pdf=True)
