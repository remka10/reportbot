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

    async def create(
        self, full_name: str, shift_id: int, position: int | None = None
    ) -> Student:
        if position is None:
            # Автоматически определяем следующую позицию
            result = await self.session.execute(
                select(func.max(Student.position)).where(Student.shift_id == shift_id)
            )
            max_pos = result.scalar() or 0
            position = max_pos + 1

        student = Student(
            full_name=full_name,
            shift_id=shift_id,
            position=position,
        )
        self.session.add(student)
        await self.session.flush()
        logger.info(f"Created student id={student.id} name={full_name!r} shift={shift_id}")
        return student

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
        await self.session.delete(student)
        await self.session.flush()
        logger.info(f"Deleted student id={student_id}")
        return True

    async def count_by_shift(self, shift_id: int) -> int:
        result = await self.session.execute(
            select(func.count()).where(Student.shift_id == shift_id)
        )
        return result.scalar_one()