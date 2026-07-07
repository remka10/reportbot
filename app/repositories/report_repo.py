import logging
from datetime import datetime, timezone
from typing import Sequence

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Report, RevisionHistory, DialogRole

logger = logging.getLogger(__name__)


class ReportRepository:

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, report_id: int) -> Report | None:
        return await self.session.get(Report, report_id)

    async def get_by_student(
        self, teacher_id: int, student_id: int, shift_id: int
    ) -> Report | None:
        # ВАЖНО (2026-07-02): отчёты ОБЩИЕ по (student, shift) — teacher_id
        # игнорируется, чтобы отчёт, сгенерированный одним аккаунтом (напр.
        # админом), был виден и скачивался с любого другого аккаунта.
        # Дубли на одну тройку могли накопиться исторически — берём самый
        # свежий отчёт (по id DESC), поэтому не используем scalar_one_or_none().
        result = await self.session.execute(
            select(Report)
            .where(
                Report.student_id == student_id,
                Report.shift_id == shift_id,
            )
            .order_by(Report.id.desc())
            .limit(1)
        )
        return result.scalars().first()


    async def create(
        self,
        teacher_id: int,
        student_id: int,
        shift_id: int,
        generated_text: str,
    ) -> Report:
        report = Report(
            teacher_id=teacher_id,
            student_id=student_id,
            shift_id=shift_id,
            generated_text=generated_text,
            revision_count=0,
            is_finalized=False,
        )
        self.session.add(report)
        await self.session.flush()
        logger.info(f"Created report id={report.id} student={student_id}")
        return report

    async def update_text(self, report_id: int, new_text: str) -> bool:
        report = await self.session.get(Report, report_id)
        if report is None:
            return False
        report.generated_text = new_text
        report.revision_count += 1
        await self.session.flush()
        return True

    async def finalize(
        self, report_id: int, docx_path: str | None = None
    ) -> bool:
        report = await self.session.get(Report, report_id)
        if report is None:
            return False
        report.is_finalized = True
        report.finalized_at = datetime.now(timezone.utc)
        if docx_path:
            report.docx_file_path = docx_path
        await self.session.flush()
        logger.info(f"Finalized report id={report_id}")
        return True

    async def unfinalize(self, report_id: int) -> bool:
        """Снимает статус финализации, чтобы вернуться к дозаполнению анкеты."""
        report = await self.session.get(Report, report_id)
        if report is None:
            return False
        report.is_finalized = False
        report.finalized_at = None
        await self.session.flush()
        logger.info(f"Unfinalized report id={report_id}")
        return True


    async def add_revision_message(
        self, report_id: int, role: DialogRole, content: str
    ) -> RevisionHistory:
        msg = RevisionHistory(
            report_id=report_id,
            role=role,
            content=content,
        )
        self.session.add(msg)
        await self.session.flush()
        return msg

    async def get_revision_history(
        self, report_id: int
    ) -> Sequence[RevisionHistory]:
        result = await self.session.execute(
            select(RevisionHistory)
            .where(RevisionHistory.report_id == report_id)
            .order_by(RevisionHistory.created_at)
        )
        return result.scalars().all()

    async def clear_revision_history(self, report_id: int) -> None:
        from sqlalchemy import delete
        await self.session.execute(
            delete(RevisionHistory).where(RevisionHistory.report_id == report_id)
        )
        await self.session.flush()

    async def get_finalized_student_ids(
        self, teacher_id: int, shift_id: int
    ) -> set[int]:
        """Множество student_id с финализированными отчётами по смене.

        ОБЩЕЕ по смене (без учёта teacher_id) — прогресс и статус «готово»
        одинаковы для всех аккаунтов.
        """
        result = await self.session.execute(
            select(Report.student_id)
            .where(
                Report.shift_id == shift_id,
                Report.is_finalized == True,
            )
        )
        return set(result.scalars().all())

    async def get_all_finalized(
        self, teacher_id: int, shift_id: int
    ) -> Sequence[Report]:
        """Все финализированные отчёты по смене (ОБЩИЕ, без учёта teacher_id).

        Так ZIP-выгрузка на любом аккаунте включает отчёты, сделанные другими
        аккаунтами. Дубли по (student, shift) схлопываем — берём самый свежий.
        """
        result = await self.session.execute(
            select(Report)
            .where(
                Report.shift_id == shift_id,
                Report.is_finalized == True,
            )
            .order_by(Report.student_id, Report.id.desc())
        )
        reports = result.scalars().all()
        # Оставляем по одному (самому свежему) отчёту на ребёнка.
        seen: set[int] = set()
        unique: list[Report] = []
        for r in reports:
            if r.student_id in seen:
                continue
            seen.add(r.student_id)
            unique.append(r)
        unique.sort(key=lambda r: (r.finalized_at or datetime.min.replace(tzinfo=timezone.utc)))
        return unique

