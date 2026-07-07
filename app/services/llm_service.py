# app/services/llm_service.py
import logging
import httpx
from openai import AsyncOpenAI
from app.config import get_settings
from app.services import model_settings


logger = logging.getLogger(__name__)

# Базовое знание ИИ о лагере. Официальное название проекта — «Летово Игра»,
# внутриигровое — «Корпорация Летово». Утверждено заказчиком.
CAMP_CONTEXT = """
Официальное название проекта — «Летово Игра». Внутри игрового мира дети становятся
сотрудниками международной «Корпорации Летово».

«Летово Игра» — это масштабная ролевая игра, где каждая смена становится новой главой
большой истории: мир сталкивается с очередной глобальной угрозой, и только команда
юных специалистов «Корпорации Летово» способна её предотвратить.

Каждый департамент Корпорации берёт на себя особую миссию — одни управляют процессами,
другие выстраивают коммуникации, третьи создают технологии, проводят исследования или
проектируют будущее. Работая плечом к плечу, дети спасают мир и одновременно осваивают
настоящие «взрослые» профессии. Из названия можно понять чем занимаются департаменты.

Здесь ребёнок может безопасно примерить на себя серьёзные задачи, почувствовать
ответственность, ошибаться и расти. «Корпорация Летово» — это пространство, где обучение
превращается в приключение, а каждый день наполнен смыслом, командной работой и
настоящими открытиями.
"""

SYSTEM_PROMPT_GENERATION = """
Ты — опытный педагогический психолог и методист детского лагеря.
Твоя задача — написать глубокий, персонализированный педагогический отчёт на ребёнка
на основе ответов педагога на вопросы.

О ЛАГЕРЕ (общий фон, всегда учитывай при написании):
{camp_context}

ФОРМАТ ОТВЕТА (СТРОГО СОБЛЮДАЙ):

Сначала — краткие, лаконичные ответы по каждому вопросу, максимально точно
передающие суть ответа педагога. Каждый пункт с номером вопроса, с новой строки:
1. <краткий, ёмкий ответ по вопросу 1>
2. <краткий, ёмкий ответ по вопросу 2>
...
13. <краткий, ёмкий ответ по вопросу 13>

Затем — строка-разделитель ровно такого вида:
=== ИТОГОВЫЙ ОТЧЁТ ===

После неё — короткий, цельный и связный педагогический отчёт на ребёнка
(СТРОГО 120–180 слов, 2-4 небольших абзаца). Отчёт должен быть ёмким: лучше
меньше слов, но по существу.

ТРЕБОВАНИЯ:
- Нумерация пунктов должна СТРОГО соответствовать номерам вопросов ниже (1..13).
- Краткие ответы: 1–3 предложения, по делу, без «воды» и общих фраз.
- ИТОГОВЫЙ ОТЧЁТ должен быть коротким и НЕ пересказывать пункты по очереди, а
  органично СВЯЗЫВАТЬ ответы педагога между собой в единую картину личности
  ребёнка, мягко вплетая контекст смены (роль в департаменте, сюжет) как фон.
- Контекст смены используй лишь как лёгкую опору для связности — НЕ делай отчёт
  зависимым от него и НЕ пересказывай сюжет смены подробно.
- Тон: профессиональный, тёплый, конкретный.
- Каждое утверждение подкреплено конкретикой из ответов педагога.
- Язык: русский, литературный, без канцелярита.
- ЗАПРЕЩЕНО выдумывать факты, которых нет в ответах педагога.
- Если педагог не ответил на вопрос — в кратком пункте поставь «—», в итоговом
  отчёте просто не упоминай этот аспект (ничего не придумывай).

КОНТЕКСТ СМЕНЫ:
{shift_context}

ВОПРОСЫ И ОТВЕТЫ ПЕДАГОГА:
{qa_pairs}
"""


SYSTEM_PROMPT_BEAUTIFY_CONTEXT = """
Ты — редактор детского ролевого лагеря «Летово Игра».
Педагог надиктовал (голосом или текстом) черновой контекст смены своего департамента:
чем занимались дети, сюжет, ключевые события. Текст может быть сырым, с оговорками,
разговорным, местами сбивчивым.

Твоя задача — превратить его в красивый, связный и вдохновляющий контекст смены,
опираясь на общий мир лагеря (ниже). Это описание затем используется как фон для
педагогических отчётов на детей.

О ЛАГЕРЕ (общий мир, всегда учитывай, но не пересказывай целиком):
{camp_context}

ТРЕБОВАНИЯ:
- Пиши литературным русским языком, тепло и живо, но без канцелярита и штампов.
- Сохрани ВСЕ конкретные факты, события и детали из надиктованного текста.
- ЗАПРЕЩЕНО выдумывать события, которых не было в исходном тексте.
- Органично впиши сюжет департамента в мир «Летово Игры» / «Корпорации Летово».
- Объём: 2–3 связных абзаца (примерно 100–200 слов).
- Верни ТОЛЬКО готовый текст контекста, без заголовков и пояснений.
"""

SYSTEM_PROMPT_REVISE_CONTEXT = """
Ты — редактор детского ролевого лагеря «Летово Игра».
Ранее ты уже оформил контекст смены департамента. Теперь педагог прислал
комментарий с тем, что нужно исправить или изменить в этом контексте.

Твоя задача — вернуть ПОЛНЫЙ исправленный текст контекста смены с учётом
комментария педагога, сохранив стилистику мира лагеря (ниже).

О ЛАГЕРЕ (общий мир, всегда учитывай, но не пересказывай целиком):
{camp_context}

ТРЕБОВАНИЯ:
- Учти ВСЕ пожелания из комментария педагога.
- Сохрани факты и детали из прежнего текста, которые педагог не просил менять.
- ЗАПРЕЩЕНО выдумывать события, которых не было и о которых не просил педагог.
- Пиши литературным русским языком, тепло и живо, без канцелярита и штампов.
- Объём: 2–3 связных абзаца (примерно 100–200 слов).
- Верни ТОЛЬКО готовый исправленный текст контекста, без заголовков и пояснений.
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

СТРУКТУРА ОТЧЁТА (СТРОГО СОХРАНЯЙ ЕЁ ЦЕЛИКОМ):
1. Сначала идёт блок кратких пронумерованных ответов по вопросам (1..13).
2. Затем строка-разделитель ровно такого вида:
=== ИТОГОВЫЙ ОТЧЁТ ===
3. После неё — связный итоговый педагогический отчёт.

ПРАВИЛА ПРАВКИ:
- При каждой правке возвращай ПОЛНЫЙ текст отчёта (не только изменённую часть):
  и блок пронумерованных ответов 1..13, и строку-разделитель, и итоговый отчёт.
- НИКОГДА не удаляй и не сокращай блок пронумерованных ответов (1..13). Если
  педагог не просил менять эти ответы — верни их ДОСЛОВНО, без изменений.
- Строку-разделитель «=== ИТОГОВЫЙ ОТЧЁТ ===» всегда сохраняй ровно в таком виде.
- По умолчанию правки педагога относятся к ИТОГОВОМУ ОТЧЁТУ — меняй именно его,
  если явно не сказано иначе.
- Сохраняй профессиональный педагогический тон.
- Не добавляй информацию, которой нет в исходных ответах педагога.
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
    for idx, item in enumerate(qa_pairs, start=1):
        # Ключ блока: поддерживаем и 'block_title' (из БД), и 'block' (legacy)
        block = item.get("block_title") or item.get("block") or ""
        if block and block != current_block:
            current_block = block
            lines.append(f"\n=== {block} ===")
        q_num = item.get("question_number", idx)
        question = item.get("question", "")
        answer = item.get("answer", "")
        lines.append(f"Вопрос {q_num}: {question}")
        lines.append(f"Ответ: {answer}\n")
    return "\n".join(lines)



class LLMService:
    def __init__(self) -> None:
        self.client = _make_client()
        # Whisper-правки всегда идут на Gemini, независимо от переключателя.
        self.stt_clean_model = get_settings().gemini_model


    async def generate_report(
        self,
        qa_pairs: list[dict],
        shift_context: str,
        student_name: str,
    ) -> str:
        qa_formatted = _format_qa_pairs(qa_pairs)
        system_prompt = SYSTEM_PROMPT_GENERATION.format(
            camp_context=CAMP_CONTEXT.strip(),
            shift_context=shift_context or "Контекст смены не указан.",
            qa_pairs=qa_formatted,
        )
        model = model_settings.get_model("generation")
        logger.info(f"Generating report for {student_name!r}, {len(qa_pairs)} QA pairs (model={model})")
        response = await self.client.chat.completions.create(
            model=model,
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


    async def beautify_shift_context(self, raw_context: str) -> str:
        """
        Превращает сырой (надиктованный) контекст смены в красивый связный текст,
        опираясь на общий мир лагеря «Летово Игра» / «Корпорация Летово».
        """
        system_prompt = SYSTEM_PROMPT_BEAUTIFY_CONTEXT.format(
            camp_context=CAMP_CONTEXT.strip(),
        )
        model = model_settings.get_model("context")
        logger.info(f"Beautifying shift context: {len(raw_context)} chars in (model={model})")
        response = await self.client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": (
                        "Вот черновой контекст смены, оформи его:\n\n"
                        f"{raw_context}"

                    ),
                },
            ],
            temperature=0.7,
            max_tokens=1000,
        )
        text = response.choices[0].message.content or raw_context
        logger.info(f"Shift context beautified: {len(text)} chars out")
        return text.strip()

    async def revise_shift_context(
        self,
        previous_context: str,
        comment: str,
    ) -> str:
        """
        Исправляет ранее оформленный контекст смены с учётом комментария педагога
        (что именно поправить), сохраняя стилистику мира «Летово Игра».
        """
        system_prompt = SYSTEM_PROMPT_REVISE_CONTEXT.format(
            camp_context=CAMP_CONTEXT.strip(),
        )
        logger.info(
            f"Revising shift context: prev={len(previous_context)} chars, "
            f"comment={len(comment)} chars"
        )
        model = model_settings.get_model("context")
        response = await self.client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": (
                        "Текущий вариант контекста смены:\n\n"

                        f"{previous_context}\n\n"
                        "Комментарий педагога — что нужно исправить:\n\n"
                        f"{comment}"
                    ),
                },
            ],
            temperature=0.7,
            max_tokens=1000,
        )
        text = response.choices[0].message.content or previous_context
        logger.info(f"Shift context revised: {len(text)} chars out")
        return text.strip()

    async def revise_report(
        self,
        revision_history: list[dict],
        revision_request: str,
    ) -> str:
        messages = [{"role": "system", "content": SYSTEM_PROMPT_REVISION}]
        messages.extend(revision_history)
        messages.append({"role": "user", "content": revision_request})
        model = model_settings.get_model("generation")
        logger.info(f"Revising report: history_len={len(revision_history)} (model={model})")
        response = await self.client.chat.completions.create(
            model=model,
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
        # Правки Whisper всегда на Gemini — не зависят от переключателя моделей.
        response = await self.client.chat.completions.create(
            model=self.stt_clean_model,
            messages=[

                {"role": "system", "content": system_prompt},
                {"role": "user", "content": raw_transcription},
            ],
            temperature=0.1,
            max_tokens=500,
        )
        text = response.choices[0].message.content or raw_transcription
        return text.strip()
