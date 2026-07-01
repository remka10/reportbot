# app/repositories/answer_repo.py
import logging
from typing import Sequence
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
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
        from datetime import datetime, timezone
        result = await self.session.execute(
            select(Answer).where(
                Answer.teacher_id == teacher_id,
                Answer.student_id == student_id,
                Answer.question_id == question_id,
            )
        )
        existing = result.scalar_one_or_none()
        if existing:
            existing.answer_text = answer_text
            existing.updated_at = datetime.now(timezone.utc)
            if raw_audio_transcription:
                existing.raw_audio_transcription = raw_audio_transcription
            await self.session.flush()
            return existing
        else:
            answer = Answer(
                teacher_id=teacher_id,
                student_id=student_id,
                question_id=question_id,
                answer_text=answer_text,
                raw_audio_transcription=raw_audio_transcription,
            )
            self.session.add(answer)
            await self.session.flush()
            return answer

    async def get_by_teacher_student_question(
        self, teacher_id: int, student_id: int, question_id: int
    ) -> Answer | None:
        result = await self.session.execute(
            select(Answer).where(
                Answer.teacher_id == teacher_id,
                Answer.student_id == student_id,
                Answer.question_id == question_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_qa_pairs_for_report(
        self, teacher_id: int, student_id: int
    ) -> list[dict]:
        """Возвращает список {'question': str, 'answer': str} для LLM."""
        result = await self.session.execute(
            select(Answer, Question)
            .join(Question, Answer.question_id == Question.id)
            .where(
                Answer.teacher_id == teacher_id,
                Answer.student_id == student_id,
                Answer.answer_text.isnot(None),
            )
            .order_by(Question.question_number)
        )
        rows = result.all()
        return [
            {
                "question_number": row.Question.question_number,
                "question": row.Question.question_text,
                "answer": row.Answer.answer_text,
                "block_title": row.Question.block_title,
            }
            for row in rows
        ]


    async def count_answered(self, teacher_id: int, student_id: int) -> int:
        result = await self.session.execute(
            select(func.count(Answer.id)).where(
                Answer.teacher_id == teacher_id,
                Answer.student_id == student_id,
                Answer.answer_text.isnot(None),
            )
        )
        return result.scalar_one() or 0

    async def get_progress_map(
        self, teacher_id: int, student_ids: list[int]
    ) -> dict[int, int]:
        """Возвращает {student_id: answered_count} для списка учащихся."""
        if not student_ids:
            return {}
        result = await self.session.execute(
            select(Answer.student_id, func.count(Answer.id))
            .where(
                Answer.teacher_id == teacher_id,
                Answer.student_id.in_(student_ids),
                Answer.answer_text.isnot(None),
            )
            .group_by(Answer.student_id)
        )
        return dict(result.all())