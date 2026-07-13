import asyncio
import logging

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, Voice
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.handlers.teacher.child import _go_to_question
from app.bot.keyboards.child_menu import generate_report_keyboard
from app.bot.states.teacher_states import QuestionStates
from app.database.base import AsyncSessionLocal
from app.database.models import User
from app.bot.utils.text import truncate_for_telegram
from app.repositories.answer_repo import AnswerRepository
from app.services.stt_service import STTService, VoiceDownloadError



logger = logging.getLogger(__name__)
router = Router(name="teacher_questions")


# ---------------------------------------------------------------------------
# Текстовый ответ на вопрос
# ---------------------------------------------------------------------------

@router.message(QuestionStates.answering, F.text)
async def answer_text(
    message: Message, state: FSMContext, user: User, session: AsyncSession
) -> None:
    answer_text = (message.text or "").strip()
    if len(answer_text) < 1:
        await message.answer("⚠️ Ответ не может быть пустым.")
        return

    await _save_answer_and_advance(message, state, user, session, answer_text)


# ---------------------------------------------------------------------------
# Голосовой ответ (принимается прямо в состоянии ответа на вопрос)
#
# Голос НЕ блокирует педагога: расшифровка идёт в фоне, а педагога сразу
# перекидывает на следующий вопрос. Когда фоновая задача закончит распознавание,
# ответ сохранится в БД и придёт уведомление с распознанным текстом.
# ---------------------------------------------------------------------------

@router.message(QuestionStates.answering, F.voice)
async def answer_voice(
    message: Message, state: FSMContext, user: User, session: AsyncSession
) -> None:
    data = await state.get_data()
    student_id = data["student_id"]
    question_id = data["current_question_id"]
    question_num = data["current_question_num"]
    question_text = data.get("current_question_text", "")
    total = data["questions_total"]

    # Запускаем расшифровку в фоне — педагог не ждёт её окончания.
    asyncio.create_task(
        _transcribe_and_save(
            bot=message.bot,
            chat_id=message.chat.id,
            voice=message.voice,
            teacher_id=user.id,
            student_id=student_id,
            question_id=question_id,
            question_num=question_num,
            question_text=question_text,
        )
    )

    await message.answer(
        f"🎤 Голос для вопроса <b>{question_num}</b> принят — распознаю в фоне. "
        "Можно сразу отвечать на следующий."
    )

    # Сразу переходим к следующему вопросу (или к генерации, если он был последним).
    if question_num >= total:
        await message.answer(
            "Все вопросы пройдены. Можно генерировать отчёт "
            "(последний голосовой ответ ещё дораспознаётся в фоне):",
            reply_markup=generate_report_keyboard(),
        )
    else:
        await _go_to_question(
            message, state, user, session,
            question_num=question_num + 1,
            edit=False,
        )


# ---------------------------------------------------------------------------
# Фоновая расшифровка голоса и сохранение ответа
#
# Работает в отдельной задаче со своей сессией БД, поэтому не зависит от
# сессии хендлера (которую middleware уже закоммитил/закрыл).
# ---------------------------------------------------------------------------

async def _transcribe_and_save(
    bot: Bot,
    chat_id: int,
    voice: Voice,
    teacher_id: int,
    student_id: int,
    question_id: int,
    question_num: int,
    question_text: str,
) -> None:
    try:
        stt = STTService()
        # Шаг 1: транскрипция через Whisper
        raw_transcription = await stt.transcribe_voice(voice, bot)

        if not raw_transcription or len(raw_transcription.strip()) < 3:
            await bot.send_message(
                chat_id,
                f"⚠️ Вопрос {question_num}: не удалось распознать голос. "
                "Ответьте на него текстом или голосом ещё раз.",
            )
            return

        # Шаг 2: очистка от зачитанного вопроса через LLM
        clean_answer = await stt.clean_transcription(raw_transcription, question_text)

        # Шаг 3: сохранение в БД (собственная сессия)
        async with AsyncSessionLocal() as session:
            repo = AnswerRepository(session)
            await repo.upsert(
                teacher_id=teacher_id,
                student_id=student_id,
                question_id=question_id,
                answer_text=clean_answer,
                raw_audio_transcription=raw_transcription,
            )
            await session.commit()

        # Обрезаем распознанный текст для уведомления: длинное голосовое вместе
        # с разметкой могло превысить лимит Telegram 4096 → MESSAGE_TOO_LONG.
        # Полный ответ сохранён в БД и виден при открытии вопроса.
        await bot.send_message(
            chat_id,
            f"✅ Вопрос {question_num} — ответ распознан и сохранён:\n"
            f"<blockquote>{truncate_for_telegram(clean_answer, limit=3000)}</blockquote>",
        )

    except VoiceDownloadError as e:
        # Не смогли скачать голосовое из Telegram (сеть/таймаут) — это НЕ ошибка
        # распознавания. Сообщаем отдельно, чтобы педагог понял, что нужно
        # просто переотправить голос.
        logger.warning(f"Voice download error (q{question_num}): {e}")
        try:
            await bot.send_message(
                chat_id,
                f"⚠️ Вопрос {question_num}: не удалось загрузить голосовое из Telegram "
                "(временный сетевой сбой). Отправьте его ещё раз или ответьте текстом.",
            )
        except Exception:
            logger.error("Failed to notify user about download error", exc_info=True)

    except Exception as e:
        logger.error(f"Background voice transcription error (q{question_num}): {e}", exc_info=True)
        try:
            await bot.send_message(
                chat_id,
                f"⚠️ Вопрос {question_num}: ошибка при распознавании голоса. "
                "Ответьте на него текстом или голосом ещё раз.",
            )
        except Exception:
            logger.error("Failed to notify user about transcription error", exc_info=True)



# ---------------------------------------------------------------------------
# Сохранение текстового ответа и переход к следующему вопросу
# ---------------------------------------------------------------------------

async def _save_answer_and_advance(
    message: Message,
    state: FSMContext,
    user: User,
    session: AsyncSession,
    answer_text: str,
    raw_audio_transcription: str | None = None,
) -> None:
    data = await state.get_data()
    student_id = data["student_id"]
    question_id = data["current_question_id"]
    current_num = data["current_question_num"]
    total = data["questions_total"]

    repo = AnswerRepository(session)
    await repo.upsert(
        teacher_id=user.id,
        student_id=student_id,
        question_id=question_id,
        answer_text=answer_text,
        raw_audio_transcription=raw_audio_transcription,
    )

    if current_num >= total:
        # Последний вопрос — предлагаем генерацию
        answered_count = await repo.count_answered(user.id, student_id)
        await message.answer(
            f"✅ Ответ сохранён!\n"
            f"Отвечено вопросов: <b>{answered_count}/{total}</b>\n"
            f"Все вопросы пройдены. Можно генерировать отчёт:",
            reply_markup=generate_report_keyboard(),
        )
    else:
        # Переходим к следующему вопросу
        await _go_to_question(
            message, state, user, session,
            question_num=current_num + 1,
            edit=False,
        )
