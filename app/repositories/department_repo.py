import logging
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import (
    Department, TeacherDepartment, Shift, DEPARTMENTS, get_department_name,
)

logger = logging.getLogger(__name__)


class DepartmentRepository:

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, department_id: int) -> Department | None:
        return await self.session.get(Department, department_id)

    async def create_for_shift(self, shift_id: int) -> list[Department]:
        """
        Создаёт все 9 департаментов для смены (идемпотентно).
        Возвращает список департаментов смены.
        """
        existing = list(await self.get_by_shift(shift_id))
        existing_numbers = {d.department_number for d in existing}
        created: list[Department] = list(existing)
        for number in DEPARTMENTS.keys():
            if number in existing_numbers:
                continue
            dep = Department(shift_id=shift_id, department_number=number)
            self.session.add(dep)
            created.append(dep)
        await self.session.flush()
        logger.info(f"Ensured 9 departments for shift_id={shift_id}")
        created.sort(key=lambda d: d.department_number)
        return created

    async def get_by_shift(self, shift_id: int) -> Sequence[Department]:
        result = await self.session.execute(
            select(Department)
            .where(Department.shift_id == shift_id)
            .order_by(Department.department_number)
        )
        return result.scalars().all()

    async def get_all_active(self) -> Sequence[Department]:
        """Все департаменты всех активных смен (для админа/модератора)."""
        result = await self.session.execute(
            select(Department)
            .join(Shift, Shift.id == Department.shift_id)
            .where(Shift.is_active == True)
            .order_by(Shift.start_date.desc(), Department.department_number)
        )
        return result.scalars().all()

    async def get_for_teacher(self, teacher_id: int) -> Sequence[Department]:

        """Все департаменты активных смен, к которым привязан педагог."""
        result = await self.session.execute(
            select(Department)
            .join(TeacherDepartment, TeacherDepartment.department_id == Department.id)
            .join(Shift, Shift.id == Department.shift_id)
            .where(
                TeacherDepartment.teacher_id == teacher_id,
                Shift.is_active == True,
            )
            .order_by(Shift.start_date.desc(), Department.department_number)
        )
        return result.scalars().all()

    async def assign_teacher(
        self, department_id: int, teacher_id: int
    ) -> TeacherDepartment:
        existing = await self.session.get(
            TeacherDepartment,
            {"teacher_id": teacher_id, "department_id": department_id},
        )
        if existing:
            return existing
        td = TeacherDepartment(teacher_id=teacher_id, department_id=department_id)
        self.session.add(td)
        await self.session.flush()
        logger.info(f"Assigned teacher_id={teacher_id} to department_id={department_id}")
        return td

    async def get_teacher_department(
        self, teacher_id: int, department_id: int
    ) -> TeacherDepartment | None:
        return await self.session.get(
            TeacherDepartment,
            {"teacher_id": teacher_id, "department_id": department_id},
        )

    async def update_context(
        self, teacher_id: int, department_id: int, context: str
    ) -> bool:
        td = await self.session.get(
            TeacherDepartment,
            {"teacher_id": teacher_id, "department_id": department_id},
        )
        if td is None:
            return False
        td.shift_context = context
        await self.session.flush()
        return True
