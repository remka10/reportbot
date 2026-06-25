import logging
from datetime import date
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Shift, TeacherShift

logger = logging.getLogger(__name__)


class ShiftRepository:

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, shift_id: int) -> Shift | None:
        return await self.session.get(Shift, shift_id)

    async def get_all_active(self) -> Sequence[Shift]:
        result = await self.session.execute(
            select(Shift)
            .where(Shift.is_active == True)
            .order_by(Shift.start_date.desc())
        )
        return result.scalars().all()

    async def get_for_teacher(self, teacher_id: int) -> Sequence[Shift]:
        """Все активные смены, к которым привязан педагог."""
        result = await self.session.execute(
            select(Shift)
            .join(TeacherShift, TeacherShift.shift_id == Shift.id)
            .where(
                TeacherShift.teacher_id == teacher_id,
                Shift.is_active == True,
            )
            .order_by(Shift.start_date.desc())
        )
        return result.scalars().all()

    async def create(
        self,
        name: str,
        department_id: int,
        start_date: date,
        end_date: date,
        created_by: int,
    ) -> Shift:
        shift = Shift(
            name=name,
            department_id=department_id,
            start_date=start_date,
            end_date=end_date,
            created_by=created_by,
        )
        self.session.add(shift)
        await self.session.flush()
        logger.info(f"Created shift id={shift.id} name={name!r}")
        return shift

    async def assign_teacher(
        self, shift_id: int, teacher_id: int
    ) -> TeacherShift:
        """Привязать педагога к смене."""
        # Проверяем существование
        existing = await self.session.get(
            TeacherShift, {"teacher_id": teacher_id, "shift_id": shift_id}
        )
        if existing:
            return existing

        ts = TeacherShift(teacher_id=teacher_id, shift_id=shift_id)
        self.session.add(ts)
        await self.session.flush()
        logger.info(f"Assigned teacher_id={teacher_id} to shift_id={shift_id}")
        return ts

    async def get_teacher_shift(
        self, teacher_id: int, shift_id: int
    ) -> TeacherShift | None:
        return await self.session.get(
            TeacherShift, {"teacher_id": teacher_id, "shift_id": shift_id}
        )

    async def update_context(
        self, teacher_id: int, shift_id: int, context: str
    ) -> bool:
        ts = await self.session.get(
            TeacherShift, {"teacher_id": teacher_id, "shift_id": shift_id}
        )
        if ts is None:
            return False
        ts.shift_context = context
        await self.session.flush()
        return True

    async def archive(self, shift_id: int) -> bool:
        shift = await self.session.get(Shift, shift_id)
        if shift is None:
            return False
        shift.is_active = False
        await self.session.flush()
        logger.info(f"Archived shift id={shift_id}")
        return True