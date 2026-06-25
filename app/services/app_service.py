import logging
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.answer_repo import AnswerRepository
from app.repositories.question_repo import QuestionRepository
from app.repositories.report_repo import ReportRepository
from app.repositories.shift_repo import ShiftRepository
from app.repositories.student_repo import StudentRepository
from app.database.models import DialogRole

logger = logging.getLogger(__name__)


class AppService:
    """
    Координирует работу между репозиториями и сервисами.
    Предоставляет бизнес-операции высокого уровня для хэндлеров.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.answer_repo = AnswerRepository(session)
        self.question_repo = QuestionRepository(session)
        self.report_repo = ReportRepository(session)
        self.shift_repo = ShiftRepository(session)
        self.student_repo = StudentRepository(session)

    async def get_qa_pairs(self, teacher_id: int, student_id: int) -> list[dict]:
        """Получить все ответы педагога по ребёнку для LLM."""
        return await self.answer_repo.get_qa_pairs_for_report(teacher_id, student_id)

    async def get_shift_context(self, teacher_id: int, shift_id: int) -> str:
        """Получить контекст смены педагога."""
        ts = await self.shift_repo.get_teacher_shift(teacher_id, shift_id)
        return (ts.shift_context or "") if ts else ""

    async def save_answer(
        self,
        teacher_id: int,
        student_id: int,
        question_id: int,
        answer_text: str,
        raw_audio: str | None = None,
    ) -> None:
        """Сохранить ответ на вопрос (upsert)."""
        await self.answer_repo.upsert(
            teacher_id=teacher_id,
            student_id=student_id,
            question_id=question_id,
            answer_text=answer_text,
            raw_audio_transcription=raw_audio,
        )

    async def get_or_create_report(
        self,
        teacher_id: int,
        student_id: int,
        shift_id: int,
        generated_text: str,
    ):
        """Создать или обновить отчёт."""
        existing = await self.report_repo.get_by_student(teacher_id, student_id, shift_id)
        if existing:
            await self.report_repo.update_text(existing.id, generated_text)
            return existing
        return await self.report_repo.create(teacher_id, student_id, shift_id, generated_text)

    async def add_revision_message(
        self, report_id: int, role: str, content: str
    ) -> None:
        """Добавить сообщение в историю диалога правок."""
        dialog_role = DialogRole(role)
        await self.report_repo.add_revision_message(report_id, dialog_role, content)

    async def get_revision_history_for_llm(self, report_id: int) -> list[dict]:
        """Получить историю диалога в формате для LLM."""
        history = await self.report_repo.get_revision_history(report_id)
        return [{"role": h.role.value, "content": h.content} for h in history]