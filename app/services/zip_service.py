# app/services/zip_service.py
import io
import logging
import zipfile
from pathlib import Path
from app.database.models import Report, Student, Shift, User

logger = logging.getLogger(__name__)


class ZipService:

    def create_zip(
        self,
        reports_with_students: list[tuple[Report, Student]],
        shift: Shift,
        teacher: User,
        report_service,
        shift_context: str | None = None,
        as_pdf: bool = False,
    ) -> tuple[io.BytesIO, str]:
        """
        Создаёт ZIP-архив всех отчётов. Возвращает (BytesIO, archive_name).

        report_service — сервис с методами generate(...) → Path (PPTX) и
        generate_pdf(...) → Path (PDF). При as_pdf=True в архив кладутся PDF.
        """
        buf = io.BytesIO()
        gen = report_service.generate_pdf if as_pdf else report_service.generate

        with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            for report, student in reports_with_students:
                try:
                    file_path: Path = gen(
                        report=report,
                        student=student,
                        shift=shift,
                        teacher=teacher,
                        shift_context=shift_context,
                    )
                    zf.write(file_path, arcname=file_path.name)
                except Exception as e:
                    logger.error(
                        f"Failed to generate report for student={student.full_name}: {e}",
                        exc_info=True,
                    )

        safe_shift = shift.name.replace(" ", "_").replace("/", "-")
        suffix = "_pdf" if as_pdf else ""
        archive_name = f"reports_{safe_shift}{suffix}.zip"

        buf.seek(0)
        return buf, archive_name


