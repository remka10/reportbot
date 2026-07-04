# app/services/zip_service.py
import io
import logging
import zipfile
from pathlib import Path

from app.database.models import Report, Student, Shift, User

logger = logging.getLogger(__name__)


class ZipService:

    @staticmethod
    def _safe_part(value: str) -> str:
        return (
            value.replace("/", "-")
            .replace("\\", "-")
            .replace(":", "-")
            .replace(" ", "_")
        )

    def create_zip(
        self,
        report_items: list[dict],
        shift: Shift,
        teacher: User,
        report_service,
        as_pdf: bool = False,
        archive_label: str | None = None,
    ) -> tuple[io.BytesIO, str, int, int]:
        """
        Создаёт ZIP-архив всех отчётов.
        Возвращает (BytesIO, archive_name, added_count, failed_count).

        report_items — список словарей вида:
        {"report": Report, "student": Student, "shift_context": str, "subfolder": str}
        """
        buf = io.BytesIO()
        gen = report_service.generate_pdf if as_pdf else report_service.generate

        added_count = 0
        failed_count = 0

        with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            for item in report_items:
                report: Report = item["report"]
                student: Student = item["student"]
                shift_context = item.get("shift_context")
                subfolder = item.get("subfolder")
                try:
                    file_path: Path = gen(
                        report=report,
                        student=student,
                        shift=shift,
                        teacher=teacher,
                        shift_context=shift_context,
                    )
                    arcname = file_path.name
                    if subfolder:
                        arcname = str(Path(subfolder) / file_path.name)
                    zf.write(file_path, arcname=arcname)
                    added_count += 1
                except Exception as e:
                    failed_count += 1
                    logger.error(
                        f"Failed to generate report for student={student.full_name}: {e}",
                        exc_info=True,
                    )

        safe_shift = self._safe_part(archive_label or shift.name)
        suffix = "_pdf" if as_pdf else ""
        archive_name = f"reports_{safe_shift}{suffix}.zip"

        buf.seek(0)
        return buf, archive_name, added_count, failed_count




