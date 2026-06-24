import logging
from pathlib import Path

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, FSInputFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards.main_menu import export_menu
from app.database.models import User
from app.repositories.report_repo import ReportRepository
from app.repositories.shift_repo import ShiftRepository
from app.repositories.student_repo import StudentRepository
from app.repositories.user_repo import UserRepository
from app.services.docx_service import DocxService
from app.services.zip_service import ZipService

logger = logging.getLogger(__name__)
router = Router(name="teacher_export")


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
# Скачать DOCX одного ребёнка
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "export:single")
async def cb_export_single(
    cb: CallbackQuery, state: FSMContext, user: User, session: AsyncSession
) -> None:
    data = await state.get_data()
    student_id = data.get("student_id")
    shift_id = data.get("shift_id")

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

    try:
        docx_svc = DocxService()
        docx_path = docx_svc.generate(
            report=report,
            student=student,
            shift=shift,
            teacher=teacher,
        )

        # Обновляем путь в БД
        await report_repo.finalize(report.id, docx_path=str(docx_path))

        # Отправляем файл
        doc_file = FSInputFile(str(docx_path), filename=docx_path.name)
        await cb.message.answer_document(
            doc_file,
            caption=f"📄 Отчёт: <b>{student.full_name}</b>\n{shift.name}",
        )

        logger.info(f"Sent DOCX for student={student.full_name} to teacher={user.id}")

    except FileNotFoundError as e:
        logger.error(f"Template not found: {e}")
        await cb.message.answer(
            "⚠️ Шаблон отчёта не найден.\n"
            "Убедитесь что файл <code>report_template.docx</code> "
            "помещён в папку <code>app/templates/</code>."
        )
    except Exception as e:
        logger.error(f"DOCX export error: {e}", exc_info=True)
        await cb.message.answer("⚠️ Ошибка при генерации файла. Попробуйте ещё раз.")


# ---------------------------------------------------------------------------
# Скачать ZIP всех финализированных отчётов
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "export:zip")
async def cb_export_zip(
    cb: CallbackQuery, state: FSMContext, user: User, session: AsyncSession
) -> None:
    data = await state.get_data()
    shift_id = data.get("shift_id")

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

    # Загружаем учащихся пакетно
    student_map: dict[int, object] = {}
    for report in reports:
        s = await student_repo.get_by_id(report.student_id)
        if s:
            student_map[report.student_id] = s

    reports_with_students = [
        (r, student_map[r.student_id])
        for r in reports
        if r.student_id in student_map
    ]

    try:
        docx_svc = DocxService()
        zip_svc = ZipService()
        zip_buffer, archive_name = zip_svc.create_zip(
            reports_with_students=reports_with_students,
            shift=shift,
            teacher=teacher,
            docx_service=docx_svc,
        )

        zip_file = BufferedInputFile(
            zip_buffer.read(),
            filename=archive_name,
        )
        await status_msg.delete()
        await cb.message.answer_document(
            zip_file,
            caption=(
                f"📦 <b>Архив отчётов</b>\n"
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