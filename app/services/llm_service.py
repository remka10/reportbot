# app/services/llm_service.py
import logging
import httpx
from openai import AsyncOpenAI
from app.config import get_settings

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


def _make_client() -> AsyncOpenAI:
    settings = get_settings()
    return AsyncOpenAI(
        api_key=settings.aitunnel_api_key,
        base_url=settings.aitunnel_base_url,
        http_client=httpx.AsyncClient(
            base_url=settings.aitunnel_base_url,
            timeout=httpx.Timeout(120.0),
        ),
    )


def _format_qa_pairs(qa_pairs: list[dict]) -> str:
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
    def __init__(self) -> None:
        self.client = _make_client()
        self.model = get_settings().gemini_model

    async def generate_report(
        self,
        qa_pairs: list[dict],
        shift_context: str,
        student_name: str,
    ) -> str:
        qa_formatted = _format_qa_pairs(qa_pairs)
        system_prompt = SYSTEM_PROMPT_GENERATION.format(
            shift_context=shift_context or "Контекст смены не указан.",
            qa_pairs=qa_formatted,
        )
        logger.info(f"Generating report for {student_name!r}, {len(qa_pairs)} QA pairs")
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Напиши педагогический отчёт на ребёнка: {student_name}"},
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
        messages = [{"role": "system", "content": SYSTEM_PROMPT_REVISION}]
        messages.extend(revision_history)
        messages.append({"role": "user", "content": revision_request})
        logger.info(f"Revising report: history_len={len(revision_history)}")
        response = await self.client.chat.completions.create(
            model=self.model,
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
        system_prompt = SYSTEM_PROMPT_STT_CLEAN.format(question_text=question_text)
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": raw_transcription},
            ],
            temperature=0.1,
            max_tokens=500,
        )
        text = response.choices[0].message.content or raw_transcription
        return text.strip()
