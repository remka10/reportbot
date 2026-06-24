import io
import logging
from pathlib import Path

from app.services.docx_service import _safe_archive_name, DocxService
from app.database.models import Report, Student, Shift, User

logger = logging.getLogger(__name__)


class ZipService:

    def create_zip(
        self,
        reports_with_students: list[tuple[Report, Student]],
        shift: Shift,
        teacher: User,
        docx_service: DocxService,
    ) -> tuple[io.BytesIO, str]:
        """
        Создаёт ZIP-архив со всеми финализированными отчётами смены.

        Args:
            reports_with_students: список пар (Report, Student)
            shift: объект смены
            teacher: объект педагога
            docx_service: инстанс DocxService для генерации DOCX

        Returns:
            Tuple (BytesIO буфер с ZIP, имя архива)
        """
        import zipfile

        archive_name = _safe_archive_name(shift.name)
        buffer = io.BytesIO()

        with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            for report, student in reports_with_students:
                try:
                    # Генерируем DOCX (или берём уже существующий)
                    if report.docx_file_path and Path(report.docx_file_path).exists():
                        docx_path = Path(report.docx_file_path)
                    else:
                        docx_path = docx_service.generate(
                            report=report,
                            student=student,
                            shift=shift,
                            teacher=teacher,
                        )

                    # Добавляем в архив
                    arcname = docx_path.name
                    zf.write(str(docx_path), arcname=arcname)
                    logger.debug(f"Added to ZIP: {arcname}")

                except Exception as e:
                    logger.error(
                        f"Failed to add report for {student.full_name} to ZIP: {e}",
                        exc_info=True,
                    )
                    # Продолжаем — не прерываем архив из-за одного файла

        buffer.seek(0)
        logger.info(
            f"ZIP created: {archive_name}, "
            f"{len(reports_with_students)} reports, "
            f"{buffer.getbuffer().nbytes} bytes"
        )
        return buffer, archive_name