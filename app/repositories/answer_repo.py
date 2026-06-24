import logging
from typing import Sequence

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.database.models import Answer, Question

logger = logging.getLogger(__name__)


class AnswerRepository:

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def upsert(
        self,
        teacher_id: int,
        student_id: int,
        question_id: int,
        answer_text: str,
        raw_audio_transcription: str | None = None,
    ) -> Answer:
        """
        INSERT ... ON CONFLICT (teacher_id, student_id, question_id) DO UPDATE.
        Возвращает актуальный объект Answer.
        """
        stmt = (
            pg_insert(Answer)
            .values(
                teacher_id=teacher_id,
                student_id=student_id,
                question_id=question_id,
                answer_text=answer_text,
                raw_audio_transcription=raw_audio_transcription,
            )
            .on_conflict_do_update(
                constraint="uq_answer",
                set_={
                    "answer_text": answer_text,
                    "raw_audio_transcription": raw_audio_transcription,
                    "updated_at": func.now(),
                },
            )
            .returning(Answer)
        )
        result = await self.session.execute(stmt)
        answer = result.scalar_one()
        logger.debug(
            f"Upserted answer teacher={teacher_id} student={student_id} q={question_id}"
        )
        return answer

    async def get_by_student(
        self, teacher_id: int, student_id: int
    ) -> Sequence[Answer]:
        """Все ответы педагога по конкретному ребёнку."""
        result = await self.session.execute(
            select(Answer)
            .where(
                Answer.teacher_id == teacher_id,
                Answer.student_id == student_id,
            )
            .order_by(Answer.question_id)
        )
        return result.scalars().all()

    async def get_qa_pairs_for_report(
        self, teacher_id: int, student_id: int
    ) -> list[dict]:
        """
        Возвращает список {"question": "...", "answer": "..."} для промта LLM.
        Только вопросы с ответами (пропущенные не включаются).
        """
        result = await self.session.execute(
            select(Question, Answer)
            .join(Answer, Answer.question_id == Question.id)
            .where(
                Answer.teacher_id == teacher_id,
                Answer.student_id == student_id,
                Answer.answer_text.isnot(None),
                Answer.answer_text != "",
            )
            .order_by(Question.question_number)
        )
        rows = result.all()
        return [
            {
                "block": q.block_title,
                "question_number": q.question_number,
                "question": q.question_text,
                "answer": a.answer_text,
            }
            for q, a in rows
        ]

    async def count_answered(self, teacher_id: int, student_id: int) -> int:
        """Количество заполненных ответов по ребёнку."""
        result = await self.session.execute(
            select(func.count())
            .select_from(Answer)
            .where(
                Answer.teacher_id == teacher_id,
                Answer.student_id == student_id,
                Answer.answer_text.isnot(None),
                Answer.answer_text != "",
            )
        )
        return result.scalar_one()

    async def get_answered_question_ids(
        self, teacher_id: int, student_id: int
    ) -> set[int]:
        """Множество question_id с непустыми ответами."""
        result = await self.session.execute(
            select(Answer.question_id)
            .where(
                Answer.teacher_id == teacher_id,
                Answer.student_id == student_id,
                Answer.answer_text.isnot(None),
                Answer.answer_text != "",
            )
        )
        return set(result.scalars().all())

    async def get_progress_map(
        self, teacher_id: int, student_ids: list[int]
    ) -> dict[int, int]:
        """
        Возвращает {student_id: кол-во_ответов} для списка детей.
        Используется для прогресс-индикатора в списке детей.
        """
        if not student_ids:
            return {}
        result = await self.session.execute(
            select(Answer.student_id, func.count().label("cnt"))
            .where(
                Answer.teacher_id == teacher_id,
                Answer.student_id.in_(student_ids),
                Answer.answer_text.isnot(None),
                Answer.answer_text != "",
            )
            .group_by(Answer.student_id)
        )
        return {row.student_id: row.cnt for row in result.all()}