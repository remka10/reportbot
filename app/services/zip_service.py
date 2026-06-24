import io
import logging
import zipfile
from pathlib import Path

from app.database.models import Report, Student, Shift, User
from app.services.docx_service import DocxService, _safe_archive_name

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
        Создаёт ZIP-архив со всеми финализированными отчётами.

        Returns:
            (BytesIO буфер, имя архива)
        """
        from datetime import date
        archive_name = _safe_archive_name(shift.name)
        buffer = io.BytesIO()

        with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            for report, student in reports_with_students:
                try:
                    if report.docx_file_path and Path(report.docx_file_path).exists():
                        docx_path = Path(report.docx_file_path)
                    else:
                        docx_path = docx_service.generate(
                            report=report,
                            student=student,
                            shift=shift,
                            teacher=teacher,
                        )
                    zf.write(str(docx_path), arcname=docx_path.name)
                    logger.debug(f"Added to ZIP: {docx_path.name}")
                except Exception as e:
                    logger.error(
                        f"Failed to add {student.full_name} to ZIP: {e}",
                        exc_info=True,
                    )

        buffer.seek(0)
        logger.info(
            f"ZIP created: {archive_name}, {len(reports_with_students)} reports, "
            f"{buffer.getbuffer().nbytes} bytes"
        )
        return buffer, archive_name