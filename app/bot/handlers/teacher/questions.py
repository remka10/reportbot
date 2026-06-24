import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.handlers.teacher.child import _go_to_question
from app.bot.keyboards.child_menu import generate_report_keyboard
from app.bot.states.teacher_states import QuestionStates
from app.database.models import User
from app.repositories.answer_repo import AnswerRepository
from app.services.stt_service import STTService

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
# Нажатие [🎤 Уже ответил голосом]
# ---------------------------------------------------------------------------

@router.callback_query(QuestionStates.answering, F.data == "q:voice")
async def cb_waiting_voice(cb: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(QuestionStates.waiting_voice)
    await cb.message.edit_text(
        "🎤 Отправьте голосовое сообщение с ответом на вопрос."
        "<i>Говорите свободно — можете сначала повторить вопрос вслух, "
        "это не страшно, бот извлечёт только ответ.</i>"
    )


# ---------------------------------------------------------------------------
# Голосовой ответ
# ---------------------------------------------------------------------------

@router.message(QuestionStates.waiting_voice, F.voice)
async def answer_voice(
    message: Message, state: FSMContext, user: User, session: AsyncSession
) -> None:
    status_msg = await message.answer("🎤 Распознаю голосовое...")

    data = await state.get_data()
    question_text = data.get("current_question_text", "")

    try:
        stt = STTService()
        # Шаг 1: транскрипция через Whisper
        raw_transcription = await stt.transcribe_voice(message.voice, message.bot)

        if not raw_transcription or len(raw_transcription.strip()) < 3:
            await status_msg.edit_text(
                "⚠️ Не удалось распознать речь. Попробуйте ещё раз или напишите текстом."
            )
            await state.set_state(QuestionStates.answering)
            return

        # Шаг 2: очистка от зачитанного вопроса через LLM
        clean_answer = await stt.clean_transcription(raw_transcription, question_text)

        await status_msg.delete()
        await message.answer(
            f"<i>Распознано:</i><blockquote>{clean_answer}</blockquote>"
        )

        await _save_answer_and_advance(
            message, state, user, session,
            answer_text=clean_answer,
            raw_audio_transcription=raw_transcription,
        )

    except Exception as e:
        logger.error(f"Voice answer error: {e}", exc_info=True)
        await status_msg.edit_text(
            "⚠️ Ошибка при обработке голосового. Напишите ответ текстом."
        )
        await state.set_state(QuestionStates.answering)


# ---------------------------------------------------------------------------
# Голосовое пришло в неправильном состоянии — подсказка
# ---------------------------------------------------------------------------

@router.message(QuestionStates.answering, F.voice)
async def voice_in_wrong_state(message: Message) -> None:
    await message.answer(
        "Чтобы ответить голосом, нажмите кнопку <b>🎤 Уже ответил голосом</b> под вопросом."
    )


# ---------------------------------------------------------------------------
# Сохранение ответа и переход к следующему вопросу
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
            f"✅ Ответ сохранён!"
            f"Отвечено вопросов: <b>{answered_count}/{total}</b>"
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