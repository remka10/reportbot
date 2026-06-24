import logging
from typing import Sequence

from openai import AsyncOpenAI

from app.config import get_settings
from app.database.models import RevisionHistory, DialogRole

logger = logging.getLogger(__name__)
settings = get_settings()

# Ленивая инициализация — создаём клиент один раз
_llm_client: AsyncOpenAI | None = None


def _get_llm_client() -> AsyncOpenAI:
    global _llm_client
    if _llm_client is None:
        _llm_client = AsyncOpenAI(
            api_key=settings.aitunnel_api_key,
            base_url=settings.aitunnel_base_url,
        )
    return _llm_client


# ──────────────────────────────────────────────
# Промты
# ──────────────────────────────────────────────

SYSTEM_PROMPT_GENERATION = """Ты — опытный педагогический психолог и методист детского лагеря. \
Твоя задача — написать глубокий, персонализированный педагогический отчёт на ребёнка \
на основе ответов педагога на вопросы.

ТРЕБОВАНИЯ К ОТЧЁТУ:
- Тон: профессиональный, тёплый, конкретный. Без общих фраз.
- Каждое утверждение должно быть подкреплено конкретным примером из ответов педагога.
- Структура: строго по блокам вопросов (Блок 1, Блок 2...).
- Объём: 400-600 слов на ребёнка.
- Язык: русский, литературный, без канцелярита.
- ЗАПРЕЩЕНО: выдумывать факты, которых нет в ответах педагога.
- Если педагог не ответил на какой-то вопрос — пропусти этот пункт, не придумывай.
"""

SYSTEM_PROMPT_REVISION = """Ты редактируешь педагогический отчёт на ребёнка. \
У тебя есть история правок в виде диалога.
При каждой правке возвращай ПОЛНЫЙ текст отчёта (не только изменённую часть).
Сохраняй профессиональный педагогический тон.
Не добавляй информацию, которой нет в исходных ответах педагога."""

SYSTEM_PROMPT_STT_CLEAN = """Тебе дана транскрипция голосового сообщения педагога. \
Педагог мог сначала прочитать вслух текст вопроса, а затем дать ответ.
Извлеки ТОЛЬКО ответ педагога, убери зачитанный вопрос если он есть.
Верни только чистый текст ответа, без пояснений и без кавычек."""


# ──────────────────────────────────────────────
# Вспомогательные функции
# ──────────────────────────────────────────────

def _format_qa_pairs(qa_pairs: list[dict]) -> str:
    """Форматирует пары вопрос-ответ для промта."""
    lines = []
    current_block = None
    for item in qa_pairs:
        if item["block"] != current_block:
            current_block = item["block"]
            lines.append(f"\n=== {current_block} ===")
        lines.append(f"В{item['question_number']}: {item['question']}")
        lines.append(f"О: {item['answer']}\n")
    return "\n".join(lines)


# ──────────────────────────────────────────────
# LLMService
# ──────────────────────────────────────────────

class LLMService:
    """
    Сервис работы с Gemini через AiTunnel (OpenAI-совместимый прокси).
    Все методы асинхронные.
    """

    async def generate_report(
        self,
        qa_pairs: list[dict],
        shift_context: str,
        student_name: str,
    ) -> str:
        """Генерирует педагогический отчёт по ответам педагога."""
        user_content = (
            f"КОНТЕКСТ СМЕНЫ:\n{shift_context or 'Контекст не указан'}\n\n"
            f"ИМЯ РЕБЁНКА: {student_name}\n\n"
            f"ВОПРОСЫ И ОТВЕТЫ ПЕДАГОГА:\n{_format_qa_pairs(qa_pairs)}"
        )

        logger.info(
            f"Generating report: student={student_name!r}, qa_pairs={len(qa_pairs)}, "
            f"model={settings.gemini_model}"
        )

        client = _get_llm_client()
        response = await client.chat.completions.create(
            model=settings.gemini_model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT_GENERATION},
                {"role": "user", "content": user_content},
            ],
            temperature=0.7,
        )

        text = response.choices[0].message.content or ""
        logger.info(f"Report generated: {len(text)} chars")
        return text

    async def revise_report(
        self,
        revision_request: str,
        history: Sequence[RevisionHistory],
    ) -> str:
        """
        Применяет правку к отчёту с учётом истории диалога.

        Args:
            revision_request: запрос педагога на правку
            history: список RevisionHistory (ВСЯ история, включая последний user-запрос)
        """
        # Формируем историю в формате OpenAI messages
        messages: list[dict] = [
            {"role": "system", "content": SYSTEM_PROMPT_REVISION}
        ]

        for msg in history:
            role = "assistant" if msg.role == DialogRole.assistant else "user"
            messages.append({"role": role, "content": msg.content})

        # Добавляем текущий запрос на правку (если не добавлен через history)
        # Проверяем что последнее сообщение в истории — не тот же запрос
        if not history or history[-1].role != DialogRole.user:
            messages.append({"role": "user", "content": revision_request})

        logger.info(
            f"Revising report: history_len={len(history)}, "
            f"request={revision_request[:80]!r}..."
        )

        client = _get_llm_client()
        response = await client.chat.completions.create(
            model=settings.gemini_model,
            messages=messages,
            temperature=0.6,
        )

        text = response.choices[0].message.content or ""
        logger.info(f"Revision done: {len(text)} chars")
        return text

    async def clean_stt_transcription(
        self, raw_transcription: str, question_text: str
    ) -> str:
        """
        Очищает транскрипцию от зачитанного вопроса через LLM.
        Возвращает только ответ педагога.
        """
        user_content = (
            f'ВОПРОС, который мог быть зачитан: "{question_text}"\n\n'
            f"Транскрипция:\n{raw_transcription}"
        )

        client = _get_llm_client()
        response = await client.chat.completions.create(
            model=settings.gemini_model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT_STT_CLEAN},
                {"role": "user", "content": user_content},
            ],
            temperature=0.1,
            max_tokens=512,
        )

        result = (response.choices[0].message.content or "").strip()
        logger.debug(
            f"STT cleaned: {len(raw_transcription)} chars -> {len(result)} chars"
        )
        return result