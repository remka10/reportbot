import logging
from typing import Sequence

from sqlalchemy import delete, func, select, update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import (
    Answer,
    Department,
    Report,
    RevisionHistory,
    Shift,
    TeacherDepartment,
    TeacherShift,
    User,
    UserRole,
)

logger = logging.getLogger(__name__)


class UserRepository:

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, user_id: int) -> User | None:
        return await self.session.get(User, user_id)

    async def get_by_username(self, username: str) -> User | None:
        """Поиск пользователя по username (без символа @)."""
        username_clean = username.lstrip("@").lower()
        result = await self.session.execute(
            select(User).where(
                User.username.ilike(username_clean),
                User.is_active == True,
            )
        )
        return result.scalar_one_or_none()

    async def get_by_role(self, role: UserRole) -> Sequence[User]:
        result = await self.session.execute(
            select(User)
            .where(User.role == role)
            .order_by(func.lower(User.full_name), func.lower(User.username), User.id)
        )
        return result.scalars().all()

    async def get_teachers_sorted(self) -> list[tuple[User, str]]:
        """Педагоги, отсортированные по департаменту, затем по имени."""
        result = await self.session.execute(
            select(User, Shift.name, Department.department_number)
            .outerjoin(TeacherDepartment, TeacherDepartment.teacher_id == User.id)
            .outerjoin(Department, Department.id == TeacherDepartment.department_id)
            .outerjoin(Shift, Shift.id == Department.shift_id)
            .where(User.role == UserRole.teacher)
            .order_by(
                Shift.name,
                Department.department_number,
                func.lower(User.full_name),
                func.lower(User.username),
                User.id,
            )
        )
        rows = result.all()
        teachers: dict[int, tuple[User, str]] = {}
        for teacher, shift_name, department_number in rows:
            dep_label = "Без департамента"
            if shift_name and department_number:
                dep_label = f"{shift_name} / департамент {department_number}"
            teachers.setdefault(teacher.id, (teacher, dep_label))
        return list(teachers.values())

    async def get_all_active(self) -> Sequence[User]:
        result = await self.session.execute(
            select(User).where(User.is_active == True).order_by(User.username, User.id)
        )
        return result.scalars().all()

    async def create(
        self,
        user_id: int,
        full_name: str,
        role: UserRole,
        username: str | None = None,
    ) -> User:
        user = User(
            id=user_id,
            full_name=full_name,
            role=role,
            username=username,
            is_active=True,
        )
        self.session.add(user)
        await self.session.flush()
        return user

    async def update_username(self, user_id: int, username: str | None) -> None:
        """Обновляет username пользователя в БД."""
        await self.session.execute(
            sa_update(User)
            .where(User.id == user_id)
            .values(username=username)
        )
        await self.session.flush()

    async def set_role(self, user_id: int, role: UserRole) -> None:
        await self.session.execute(
            sa_update(User).where(User.id == user_id).values(role=role)
        )
        await self.session.flush()

    async def set_active(self, user_id: int, is_active: bool) -> None:
        await self.session.execute(
            sa_update(User).where(User.id == user_id).values(is_active=is_active)
        )
        await self.session.flush()

    async def delete_user(self, user_id: int) -> None:
        """Физически удаляет пользователя и зависимые записи по FK."""
        report_ids = select(Report.id).where(Report.teacher_id == user_id)
        await self.session.execute(delete(RevisionHistory).where(RevisionHistory.report_id.in_(report_ids)))
        await self.session.execute(delete(Report).where(Report.teacher_id == user_id))
        await self.session.execute(delete(Answer).where(Answer.teacher_id == user_id))
        await self.session.execute(delete(TeacherDepartment).where(TeacherDepartment.teacher_id == user_id))
        await self.session.execute(delete(TeacherShift).where(TeacherShift.teacher_id == user_id))
        await self.session.execute(
            sa_update(User).where(User.created_by == user_id).values(created_by=None)
        )
        await self.session.execute(
            sa_update(Shift).where(Shift.created_by == user_id).values(created_by=None)
        )
        await self.session.execute(delete(User).where(User.id == user_id))
        await self.session.flush()