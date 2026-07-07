import logging
from typing import Sequence

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Student

logger = logging.getLogger(__name__)


class StudentRepository:

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, student_id: int) -> Student | None:
        return await self.session.get(Student, student_id)

    async def get_by_shift(self, shift_id: int) -> Sequence[Student]:
        result = await self.session.execute(
            select(Student)
            .where(Student.shift_id == shift_id)
            .order_by(Student.position, Student.full_name)
        )
        return result.scalars().all()

    async def get_by_department(self, department_id: int) -> Sequence[Student]:
        result = await self.session.execute(
            select(Student)
            .where(Student.department_id == department_id)
            .order_by(Student.position, Student.full_name)
        )
        return result.scalars().all()

    async def normalize_positions(
        self,
        shift_id: int,
        department_id: int | None = None,
    ) -> None:
        """Перенумеровать учащихся подряд в рамках департамента или смены."""
        if department_id is not None:
            students = list(await self.get_by_department(department_id))
        else:
            students = list(await self.get_by_shift(shift_id))

        for index, student in enumerate(students, start=1):
            if student.position != index:
                student.position = index
        await self.session.flush()

    async def create(
        self,
        full_name: str,
        shift_id: int,
        department_id: int | None = None,
        position: int | None = None,
    ) -> Student:
        if position is None:
            # Позиция считается в рамках департамента (если задан), иначе смены.
            if department_id is not None:
                scope_col, scope_val = Student.department_id, department_id
            else:
                scope_col, scope_val = Student.shift_id, shift_id
            result = await self.session.execute(
                select(func.max(Student.position)).where(scope_col == scope_val)
            )
            max_pos = result.scalar() or 0
            position = max_pos + 1

        student = Student(
            full_name=full_name,
            shift_id=shift_id,
            department_id=department_id,
            position=position,
        )
        self.session.add(student)
        await self.session.flush()
        await self.normalize_positions(shift_id=shift_id, department_id=department_id)
        logger.info(
            f"Created student id={student.id} name={full_name!r} "
            f"shift={shift_id} dep={department_id}"
        )
        return student

    async def create_many(
        self,
        full_names: Sequence[str],
        shift_id: int,
        department_id: int | None = None,
    ) -> list[Student]:
        """Создать нескольких учащихся и вернуть созданные записи."""
        created: list[Student] = []
        for full_name in full_names:
            student = await self.create(
                full_name=full_name,
                shift_id=shift_id,
                department_id=department_id,
            )
            created.append(student)
        return created

    async def update_name(self, student_id: int, new_name: str) -> bool:
        student = await self.session.get(Student, student_id)
        if student is None:
            return False
        student.full_name = new_name
        await self.session.flush()
        return True

    async def delete(self, student_id: int) -> bool:
        student = await self.session.get(Student, student_id)
        if student is None:
            return False
        shift_id = student.shift_id
        department_id = student.department_id
        await self.session.delete(student)
        await self.session.flush()
        await self.normalize_positions(shift_id=shift_id, department_id=department_id)
        logger.info(f"Deleted student id={student_id}")
        return True

    async def count_by_shift(self, shift_id: int) -> int:
        result = await self.session.execute(
            select(func.count()).where(Student.shift_id == shift_id)
        )
        return result.scalar_one()

    async def count_by_department(self, department_id: int) -> int:
        result = await self.session.execute(
            select(func.count()).where(Student.department_id == department_id)
        )
        return result.scalar_one()
