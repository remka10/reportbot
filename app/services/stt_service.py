# app/services/stt_service.py
import io
import logging
from aiogram.types import Voice
from aiogram import Bot
from openai import AsyncOpenAI
from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class STTService:
    def __init__(self) -> None:
        self.client = AsyncOpenAI(
            api_key=settings.aitunnel_api_key,
            base_url=settings.aitunnel_base_url,
        )
        self.model = settings.whisper_model
        self.max_size_bytes = settings.max_audio_size_mb * 1024 * 1024

    async def transcribe_voice(self, voice: Voice, bot: Bot) -> str:
        """Скачивает голосовое сообщение и транскрибирует через Whisper."""
        if voice.file_size and voice.file_size > self.max_size_bytes:
            raise ValueError(
                f"Голосовое сообщение слишком большое "
                f"(>{settings.max_audio_size_mb} МБ)."
            )

        # Скачиваем файл через aiogram Bot API
        file = await bot.get_file(voice.file_id)
        buf = io.BytesIO()
        await bot.download_file(file.file_path, destination=buf)
        buf.seek(0)
        buf.name = "voice.ogg"  # OpenAI требует имя файла с расширением

        response = await self.client.audio.transcriptions.create(
            model=self.model,
            file=buf,
            language="ru",
            response_format="text",
        )
        return response.strip() if isinstance(response, str) else response

    async def clean_transcription(self, raw_text: str, question_text: str) -> str:
        """Делегирует очистку в LLMService."""
        from app.services.llm_service import LLMService
        llm = LLMService()
        return await llm.clean_transcription(raw_text, question_text)