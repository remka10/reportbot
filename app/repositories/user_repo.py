import logging
from typing import Sequence

from sqlalchemy import select, update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import User, UserRole

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
            select(User).where(User.role == role).order_by(User.full_name)
        )
        return result.scalars().all()

    async def get_all_active(self) -> Sequence[User]:
        result = await self.session.execute(
            select(User).where(User.is_active == True).order_by(User.full_name)
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