import logging
from openai import AsyncOpenAI

from app.config import settings

logger = logging.getLogger(__name__)

SYSTEM_PROMPT_GENERATION = """
Ты — опытный педагогический психолог и методист детского лагеря.
Твоя задача — написать глубокий, персонализированный педагогический отчёт на ребёнка
на основе ответов педагога на вопросы.

ТРЕБОВАНИЯ К ОТЧЁТУ:
- Тон: профессиональный, тёплый, конкретный. Без общих фраз.
- Каждое утверждение должно быть подкреплено конкретным примером из ответов педагога.
- Структура: строго по блокам вопросов (Блок 1, Блок 2...).
- Объём: 400-600 слов на ребёнка.
- Язык: русский, литературный, без канцелярита.
- ЗАПРЕЩЕНО: выдумывать факты, которых нет в ответах педагога.
- Если педагог не ответил на какой-то вопрос — пропусти этот пункт, не придумывай.

КОНТЕКСТ СМЕНЫ:
{shift_context}

ВОПРОСЫ И ОТВЕТЫ ПЕДАГОГА:
{qa_pairs}
"""

SYSTEM_PROMPT_STT_CLEAN = """
Тебе дана транскрипция голосового сообщения педагога.
Педагог мог сначала прочитать вслух текст вопроса, а затем дать ответ.

ВОПРОС, который мог быть зачитан: "{question_text}"

Извлеки ТОЛЬКО ответ педагога, убери зачитанный вопрос если он есть.
Верни только чистый текст ответа, без пояснений.
"""

SYSTEM_PROMPT_REVISION = """
Ты редактируешь педагогический отчёт на ребёнка.
У тебя есть исходный отчёт и история правок.
При каждой правке возвращай ПОЛНЫЙ текст отчёта (не только изменённую часть).
Сохраняй профессиональный педагогический тон.
Не добавляй информацию, которой нет в исходных ответах педагога.
"""

# Единый клиент через AiTunnel (поддерживает Gemini и OpenAI-совместимые модели)
_llm_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    global _llm_client
    if _llm_client is None:
        _llm_client = AsyncOpenAI(
            api_key=settings.aitunnel_api_key,
            base_url=settings.aitunnel_base_url,
        )
    return _llm_client


def _format_qa_pairs(qa_pairs: list[dict]) -> str:
    """Форматирует список вопрос-ответ для промта."""
    lines = []
    current_block = None
    for item in qa_pairs:
        if item["block"] != current_block:
            current_block = item["block"]
            lines.append(f"\n=== {current_block} ===")
        lines.append(f"Вопрос {item['question_number']}: {item['question']}")
        lines.append(f"Ответ: {item['answer']}\n")
    return "\n".join(lines)


class LLMService:
    """
    Сервис генерации педагогических отчётов через AiTunnel (Gemini 2.5 Flash).
    """

    async def generate_report(
        self,
        qa_pairs: list[dict],
        shift_context: str,
        student_name: str,
    ) -> str:
        """
        Генерирует первичный текст отчёта.

        Args:
            qa_pairs: список {"block", "question_number", "question", "answer"}
            shift_context: контекст смены от педагога
            student_name: имя ребёнка

        Returns:
            Текст отчёта от LLM.
        """
        qa_formatted = _format_qa_pairs(qa_pairs)

        system_prompt = SYSTEM_PROMPT_GENERATION.format(
            shift_context=shift_context or "Контекст смены не указан.",
            qa_pairs=qa_formatted,
        )

        logger.info(
            f"Generating report for {student_name!r}, "
            f"{len(qa_pairs)} QA pairs, context_len={len(shift_context or '')}"
        )

        client = _get_client()
        response = await client.chat.completions.create(
            model=settings.gemini_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": f"Напиши педагогический отчёт на ребёнка: {student_name}",
                },
            ],
            temperature=0.7,
            max_tokens=2000,
        )

        text = response.choices[0].message.content or ""
        logger.info(f"Report generated: {len(text)} chars for {student_name!r}")
        return text.strip()

    async def revise_report(
        self,
        revision_history: list[dict],
        revision_request: str,
    ) -> str:
        """
        Правит отчёт с учётом истории диалога.

        Args:
            revision_history: список {"role": "assistant"/"user", "content": "..."}
            revision_request: новый запрос на правку

        Returns:
            Новая версия полного текста отчёта.
        """
        messages = [{"role": "system", "content": SYSTEM_PROMPT_REVISION}]
        messages.extend(revision_history)
        messages.append({"role": "user", "content": revision_request})

        logger.info(
            f"Revising report: history_len={len(revision_history)}, "
            f"request_len={len(revision_request)}"
        )

        client = _get_client()
        response = await client.chat.completions.create(
            model=settings.gemini_model,
            messages=messages,
            temperature=0.6,
            max_tokens=2000,
        )

        text = response.choices[0].message.content or ""
        logger.info(f"Revision done: {len(text)} chars")
        return text.strip()

    async def clean_stt_transcription(
        self,
        raw_transcription: str,
        question_text: str,
    ) -> str:
        """
        Очищает транскрипцию от зачитанного вопроса.

        Args:
            raw_transcription: сырая транскрипция от Whisper
            question_text: текст вопроса, который мог быть зачитан

        Returns:
            Очищенный текст ответа педагога.
        """
        system_prompt = SYSTEM_PROMPT_STT_CLEAN.format(question_text=question_text)

        client = _get_client()
        response = await client.chat.completions.create(
            model=settings.gemini_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": raw_transcription},
            ],
            temperature=0.1,
            max_tokens=500,
        )

        text = response.choices[0].message.content or raw_transcription
        return text.strip()