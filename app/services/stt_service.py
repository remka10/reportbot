import io
import logging

from aiogram.types import Voice
from openai import AsyncOpenAI

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# Единый клиент для STT (тот же AiTunnel, что и для LLM)
_stt_client: AsyncOpenAI | None = None


def _get_stt_client() -> AsyncOpenAI:
    global _stt_client
    if _stt_client is None:
        _stt_client = AsyncOpenAI(
            api_key=settings.aitunnel_api_key,
            base_url=settings.aitunnel_base_url,
        )
    return _stt_client


class STTService:
    """
    Сервис Speech-to-Text через Whisper API (AiTunnel прокси).
    Только русский язык.
    """

    async def transcribe_voice(self, voice: Voice, bot) -> str:
        """
        Скачивает голосовое сообщение и транскрибирует через Whisper.

        Args:
            voice: объект Voice из aiogram
            bot: экземпляр Bot для скачивания файла

        Returns:
            Текст транскрипции.

        Raises:
            ValueError: если файл слишком большой
            RuntimeError: при ошибке API
        """
        # Проверяем размер файла
        max_bytes = settings.max_audio_size_mb * 1024 * 1024
        if voice.file_size and voice.file_size > max_bytes:
            raise ValueError(
                f"Голосовое сообщение слишком большое: "
                f"{voice.file_size / 1024 / 1024:.1f} MB > {settings.max_audio_size_mb} MB"
            )

        # Скачиваем файл из Telegram
        file_info = await bot.get_file(voice.file_id)
        file_bytes = io.BytesIO()
        await bot.download_file(file_info.file_path, file_bytes)
        file_bytes.seek(0)
        # Whisper требует имя файла с расширением для определения формата
        file_bytes.name = "voice.ogg"

        logger.debug(
            f"Transcribing voice: file_size={voice.file_size}, "
            f"duration={voice.duration}s, model={settings.whisper_model}"
        )

        client = _get_stt_client()
        transcript = await client.audio.transcriptions.create(
            model=settings.whisper_model,
            file=file_bytes,
            language="ru",
            response_format="text",
        )

        text = str(transcript).strip()
        logger.info(
            f"Transcription done: {len(text)} chars, duration={voice.duration}s"
        )
        return text

    async def clean_transcription(
        self, raw_transcription: str, question_text: str
    ) -> str:
        """
        Очищает транскрипцию от зачитанного вопроса через LLM.
        Делегирует в LLMService (тот же AiTunnel клиент).
        """
        from app.services.llm_service import LLMService
        llm = LLMService()
        return await llm.clean_stt_transcription(raw_transcription, question_text)