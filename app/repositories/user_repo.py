import logging
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import User, UserRole

logger = logging.getLogger(__name__)


class UserRepository:

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, user_id: int) -> User | None:
        return await self.session.get(User, user_id)

    async def get_by_role(self, role: UserRole) -> Sequence[User]:
        result = await self.session.execute(
            select(User)
            .where(User.role == role, User.is_active == True)
            .order_by(User.full_name)
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
        created_by: int | None = None,
    ) -> User:
        user = User(
            id=user_id,
            full_name=full_name,
            role=role,
            username=username,
            is_active=True,
            created_by=created_by,
        )
        self.session.add(user)
        await self.session.flush()
        logger.info(f"Created user id={user_id} role={role.value} name={full_name!r}")
        return user

    async def update_role(self, user_id: int, new_role: UserRole) -> bool:
        user = await self.session.get(User, user_id)
        if user is None:
            return False
        user.role = new_role
        await self.session.flush()
        logger.info(f"Changed role user id={user_id} -> {new_role.value}")
        return True

    async def deactivate(self, user_id: int) -> bool:
        user = await self.session.get(User, user_id)
        if user is None:
            return False
        user.is_active = False
        await self.session.flush()
        logger.info(f"Deactivated user id={user_id}")
        return True

    async def exists(self, user_id: int) -> bool:
        user = await self.session.get(User, user_id)
        return user is not None