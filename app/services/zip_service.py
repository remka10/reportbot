# app/services/zip_service.py
import io
import logging
import zipfile
from pathlib import Path
from app.database.models import Report, Student, Shift, User
from app.services.docx_service import DocxService

logger = logging.getLogger(__name__)


class ZipService:

    def create_zip(
        self,
        reports_with_students: list[tuple[Report, Student]],
        shift: Shift,
        teacher: User,
        docx_service: DocxService,
    ) -> tuple[io.BytesIO, str]:
        """Создаёт ZIP-архив всех отчётов. Возвращает (BytesIO, archive_name)."""
        buf = io.BytesIO()

        with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            for report, student in reports_with_students:
                try:
                    docx_path: Path = docx_service.generate(
                        report=report,
                        student=student,
                        shift=shift,
                        teacher=teacher,
                    )
                    zf.write(docx_path, arcname=docx_path.name)
                except Exception as e:
                    logger.error(
                        f"Failed to generate DOCX for student={student.full_name}: {e}",
                        exc_info=True,
                    )

        safe_shift = shift.name.replace(" ", "_").replace("/", "-")
        archive_name = f"reports_{safe_shift}.zip"

        buf.seek(0)
        return buf, archive_name