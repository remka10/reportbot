import logging
from typing import Sequence

from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession


from app.database.models import (
    Department, TeacherDepartment, Shift, User, UserRole,
    DEPARTMENTS, get_department_name,
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

    async def get_any_context(self, department_id: int) -> str:
        """Любой непустой контекст смены по департаменту (без учёта teacher_id).

        Нужно для экспорта: если отчёт заполнял один аккаунт (напр. админ), а
        скачивает другой — «ЛЕГЕНДА СМЕНЫ» всё равно должна отрисоваться.
        """
        result = await self.session.execute(
            select(TeacherDepartment.shift_context)
            .where(
                TeacherDepartment.department_id == department_id,
                TeacherDepartment.shift_context.isnot(None),
                TeacherDepartment.shift_context != "",
            )
            .limit(1)
        )
        return (result.scalars().first() or "")


    async def update_context(
        self, teacher_id: int, department_id: int, context: str
    ) -> bool:
        """Сохраняет контекст смены ОБЩИМ для всего департамента.

        ВАЖНО (2026-07-02): контекст — это свойство ДЕПАРТАМЕНТА/СМЕНЫ, а не
        приватная заметка одного педагога. Поэтому пишем один и тот же текст
        во ВСЕ строки teacher_departments этого департамента (и в строку
        текущего пользователя, создав её при необходимости). Так контекст,
        введённый одним аккаунтом (напр. админом), виден всем остальным.
        """
        # Гарантируем, что строка текущего пользователя существует.
        current = await self.session.get(
            TeacherDepartment,
            {"teacher_id": teacher_id, "department_id": department_id},
        )
        if current is None:
            current = TeacherDepartment(
                teacher_id=teacher_id, department_id=department_id
            )
            self.session.add(current)
            await self.session.flush()

        # Обновляем контекст у ВСЕХ педагогов этого департамента.
        await self.session.execute(
            update(TeacherDepartment)
            .where(TeacherDepartment.department_id == department_id)
            .values(shift_context=context)
        )
        await self.session.flush()
        return True

    async def clear_context(self, department_id: int) -> bool:
        """Полностью удаляет общий контекст департамента у всех привязок."""
        await self.session.execute(
            update(TeacherDepartment)
            .where(TeacherDepartment.department_id == department_id)
            .values(shift_context=None)
        )
        await self.session.flush()
        return True

    async def get_teachers_for_shift(
        self, shift_id: int
    ) -> list[tuple[User, Department]]:
        """Возвращает список (педагог, департамент) для всех привязок в смене.

        Используется в админке для карточки смены: показать, кто к каким
        департаментам привязан. Админов исключаем (они привязываются к
        департаментам технически, чтобы заполнять отчёты).
        """
        result = await self.session.execute(
            select(User, Department)
            .join(TeacherDepartment, TeacherDepartment.teacher_id == User.id)
            .join(Department, Department.id == TeacherDepartment.department_id)
            .where(
                Department.shift_id == shift_id,
                User.role == UserRole.teacher,
            )
            .order_by(Department.department_number, User.full_name)
        )
        return [(u, d) for u, d in result.all()]

    async def unassign_teacher(
        self, department_id: int, teacher_id: int
    ) -> bool:
        """Отвязать педагога от департамента."""
        td = await self.session.get(
            TeacherDepartment,
            {"teacher_id": teacher_id, "department_id": department_id},
        )
        if td is None:
            return False
        await self.session.delete(td)
        await self.session.flush()
        logger.info(
            f"Unassigned teacher_id={teacher_id} from department_id={department_id}"
        )
        return True

    async def count_departments_with_context(self, shift_id: int) -> int:
        """Сколько департаментов смены имеют заполненный контекст."""
        result = await self.session.execute(
            select(func.count(func.distinct(TeacherDepartment.department_id)))
            .join(Department, Department.id == TeacherDepartment.department_id)
            .where(
                Department.shift_id == shift_id,
                TeacherDepartment.shift_context.isnot(None),
                TeacherDepartment.shift_context != "",
            )
        )
        return result.scalar_one()



