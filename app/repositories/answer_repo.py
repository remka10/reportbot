# app/repositories/answer_repo.py
import logging
from typing import Sequence
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.database.models import Answer, Question

logger = logging.getLogger(__name__)


class AnswerRepository:
    """
    ВАЖНО (2026-07-02): ответы теперь ОБЩИЕ по ребёнку, а не приватные по педагогу.
    Раньше все выборки фильтровались по teacher_id, поэтому админ, заполнивший
    анкету, «не делился» ответами с другими аккаунтами (и наоборот). Теперь
    чтения/upsert идут по (student_id, question_id) БЕЗ учёта teacher_id.
    `teacher_id` сохраняется только как аудит-поле «кто последним заполнил».
    """

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
        # Ищем ЛЮБОЙ существующий ответ на этот вопрос по ребёнку (любого педагога),
        # чтобы не плодить дубли и чтобы правка была видна всем.
        result = await self.session.execute(
            select(Answer)
            .where(
                Answer.student_id == student_id,
                Answer.question_id == question_id,
            )
            .order_by(Answer.id.desc())
            .limit(1)
        )
        existing = result.scalars().first()
        if existing:
            existing.answer_text = answer_text
            existing.teacher_id = teacher_id  # кто последним заполнил
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
        # teacher_id игнорируется — ответ общий по ребёнку.
        result = await self.session.execute(
            select(Answer)
            .where(
                Answer.student_id == student_id,
                Answer.question_id == question_id,
            )
            .order_by(Answer.id.desc())
            .limit(1)
        )
        return result.scalars().first()

    async def get_qa_pairs_for_report(
        self, teacher_id: int, student_id: int
    ) -> list[dict]:
        """Возвращает список {'question': str, 'answer': str} для LLM.

        Ответы берутся ОБЩИЕ по ребёнку (без учёта teacher_id). Если исторически
        накопились дубли на один вопрос — берём самый свежий (по Answer.id).
        """
        result = await self.session.execute(
            select(Answer, Question)
            .join(Question, Answer.question_id == Question.id)
            .where(
                Answer.student_id == student_id,
                Answer.answer_text.isnot(None),
            )
            .order_by(Question.question_number, Answer.id.desc())
        )
        rows = result.all()
        seen: set[int] = set()
        pairs: list[dict] = []
        for row in rows:
            qid = row.Question.id
            if qid in seen:
                continue
            seen.add(qid)
            pairs.append(
                {
                    "question_number": row.Question.question_number,
                    "question": row.Question.question_text,
                    "answer": row.Answer.answer_text,
                    "block_title": row.Question.block_title,
                }
            )
        return pairs

    async def count_answered(self, teacher_id: int, student_id: int) -> int:
        # Считаем уникальные вопросы с ответом по ребёнку (без учёта teacher_id).
        result = await self.session.execute(
            select(func.count(func.distinct(Answer.question_id))).where(
                Answer.student_id == student_id,
                Answer.answer_text.isnot(None),
            )
        )
        return result.scalar_one() or 0

    async def get_progress_map(
        self, teacher_id: int, student_ids: list[int]
    ) -> dict[int, int]:
        """Возвращает {student_id: answered_count} для списка учащихся.

        Прогресс ОБЩИЙ по ребёнку (без учёта teacher_id): считаем уникальные
        вопросы с ответом.
        """
        if not student_ids:
            return {}
        result = await self.session.execute(
            select(Answer.student_id, func.count(func.distinct(Answer.question_id)))
            .where(
                Answer.student_id.in_(student_ids),
                Answer.answer_text.isnot(None),
            )
            .group_by(Answer.student_id)
        )
        return dict(result.all())
