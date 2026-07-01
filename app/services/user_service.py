import logging
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import User, UserRole
from app.repositories.user_repo import UserRepository

logger = logging.getLogger(__name__)


@dataclass
class ServiceResult:
    success: bool
    message: str


class UserService:
    """Бизнес-логика управления пользователями."""

    def __init__(self, session: AsyncSession) -> None:
        self.repo = UserRepository(session)

    async def add_user(
        self,
        actor: User,
        new_user_id: int,
        full_name: str,
        role: UserRole,
    ) -> ServiceResult:
        """
        Добавить нового пользователя.
        Модератор может добавить только teacher.
        Администратор — любую роль.
        """
        # Проверка прав
        if actor.role == UserRole.moderator and role != UserRole.teacher:
            return ServiceResult(
                success=False,
                message="⚠️ Модератор может добавлять только педагогов.",
            )

        # Проверяем — не существует ли уже
        existing = await self.repo.get_by_id(new_user_id)
        if existing:
            if existing.is_active:
                return ServiceResult(
                    success=False,
                    message=f"⚠️ Пользователь <code>{new_user_id}</code> уже существует "
                            f"с ролью <b>{existing.role.value}</b>.",
                )
            else:
                # Реактивируем
                existing.is_active = True
                existing.role = role
                existing.full_name = full_name
                return ServiceResult(
                    success=True,
                    message=f"✅ Пользователь <b>{full_name}</b> реактивирован "
                            f"с ролью <b>{role.value}</b>.",
                )

        await self.repo.create(
            user_id=new_user_id,
            full_name=full_name,
            role=role,
        )

        return ServiceResult(
            success=True,
            message=f"✅ Пользователь <b>{full_name}</b> добавлен "
                    f"с ролью <b>{role.value}</b>.\n"
                    f"ID: <code>{new_user_id}</code>",
        )

    async def change_role(
        self,
        actor: User,
        target_user_id: int,
        new_role: UserRole,
    ) -> ServiceResult:
        """Изменить роль пользователя. Только для admin."""
        if actor.role != UserRole.admin:
            return ServiceResult(
                success=False,
                message="⚠️ Изменить роль может только администратор.",
            )
        if actor.id == target_user_id:
            return ServiceResult(
                success=False,
                message="⚠️ Нельзя изменить собственную роль.",
            )

        target = await self.repo.get_by_id(target_user_id)
        if not target:
            return ServiceResult(
                success=False,
                message="⚠️ Пользователь не найден.",
            )
        await self.repo.set_role(target_user_id, new_role)
        return ServiceResult(
            success=True,
            message=f"✅ Роль изменена на <b>{new_role.value}</b>.",
        )


    async def deactivate(
        self, actor: User, target_user_id: int
    ) -> ServiceResult:
        """Деактивировать пользователя."""
        if actor.id == target_user_id:
            return ServiceResult(
                success=False,
                message="⚠️ Нельзя деактивировать самого себя.",
            )

        target = await self.repo.get_by_id(target_user_id)
        if not target:
            return ServiceResult(
                success=False,
                message="⚠️ Пользователь не найден.",
            )
        await self.repo.set_active(target_user_id, False)
        return ServiceResult(
            success=True,
            message="✅ Пользователь деактивирован.",
        )

