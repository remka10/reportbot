from typing import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Question


class QuestionRepository:

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_all_active(self) -> Sequence[Question]:
        result = await self.session.execute(
            select(Question)
            .where(Question.is_active == True)
            .order_by(Question.question_number)
        )
        return result.scalars().all()

    async def get_by_id(self, question_id: int) -> Question | None:
        return await self.session.get(Question, question_id)