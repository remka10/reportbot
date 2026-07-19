# app/services/stt_service.py
import asyncio
import io
import logging
import httpx
from aiogram.types import Voice
from aiogram import Bot
from aiogram.exceptions import TelegramNetworkError, TelegramRetryAfter
from openai import AsyncOpenAI
from app.config import get_settings

logger = logging.getLogger(__name__)

# Сколько раз пытаемся распознать голос, прежде чем сдаться. Ошибки Whisper
# через AiTunnel часто временные (таймаут, сетевой сбой, 429/5xx, разовый пустой
# ответ) — повторная попытка обычно проходит.
STT_MAX_ATTEMPTS = 3
STT_RETRY_BASE_DELAY = 1.5  # секунды; пауза растёт: 1.5с, 3с, ...

# Скачивание голосового из Telegram (get_file/download_file) тоже бывает
# отваливается по таймауту к api.telegram.org — это временный сетевой сбой,
# повтор почти всегда проходит. Держим отдельные попытки и явный таймаут запроса.
TG_DOWNLOAD_MAX_ATTEMPTS = 3
TG_DOWNLOAD_RETRY_BASE_DELAY = 1.5  # секунды
TG_REQUEST_TIMEOUT = 30.0  # таймаут одного запроса к Telegram Bot API


class VoiceDownloadError(Exception):
    """Не удалось скачать голосовое из Telegram (сеть/таймаут), а не распознать."""



class STTService:
    def __init__(self) -> None:
        settings = get_settings()
        self.client = AsyncOpenAI(
            api_key=settings.aitunnel_api_key,
            base_url=settings.aitunnel_base_url,
            http_client=httpx.AsyncClient(
                base_url=settings.aitunnel_base_url,
                timeout=httpx.Timeout(60.0),
            ),
        )
        self.model = settings.whisper_model
        self.max_size_bytes = settings.max_audio_size_mb * 1024 * 1024

    async def transcribe_voice(self, voice: Voice, bot: Bot) -> str:
        settings = get_settings()
        if voice.file_size and voice.file_size > self.max_size_bytes:
            raise ValueError(
                f"Голосовое сообщение слишком большое "
                f"(>{settings.max_audio_size_mb} МБ)."
            )

        # Скачиваем файл один раз (со своими ретраями на сетевые сбои Telegram) —
        # дальше повторяем только сам запрос к Whisper.
        raw = await self._download_voice(voice, bot)


        last_error: Exception | None = None
        for attempt in range(1, STT_MAX_ATTEMPTS + 1):
            try:
                text = await self._transcribe_once(raw)
                if text:
                    return text
                # Пустой результат — это тоже повод попробовать ещё раз.
                logger.warning(
                    f"STT attempt {attempt}/{STT_MAX_ATTEMPTS}: empty transcription"
                )
                last_error = ValueError("Пустая расшифровка")
            except Exception as e:
                last_error = e
                logger.warning(
                    f"STT attempt {attempt}/{STT_MAX_ATTEMPTS} failed: {e}"
                )

            if attempt < STT_MAX_ATTEMPTS:
                await asyncio.sleep(STT_RETRY_BASE_DELAY * attempt)

        logger.error(f"STT failed after {STT_MAX_ATTEMPTS} attempts: {last_error}")
        raise last_error if last_error else RuntimeError("STT не удалось")

    async def _download_voice(self, voice: Voice, bot: Bot) -> bytes:
        """Скачивает голосовое из Telegram с ретраями на сетевые сбои.

        get_file/download_file ходят к api.telegram.org и периодически падают по
        таймауту (TelegramNetworkError) — это временный сбой, повтор проходит.
        Не-сетевые ошибки (например, файл недоступен) не ретраим — пробрасываем
        сразу. Исчерпав попытки, кидаем VoiceDownloadError, чтобы вызывающий код
        мог отличить «не смог скачать» от «не смог распознать»."""
        last_error: Exception | None = None
        for attempt in range(1, TG_DOWNLOAD_MAX_ATTEMPTS + 1):
            try:
                file = await bot.get_file(
                    voice.file_id, request_timeout=TG_REQUEST_TIMEOUT
                )
                audio_bytes = io.BytesIO()
                await bot.download_file(
                    file.file_path,
                    destination=audio_bytes,
                    timeout=int(TG_REQUEST_TIMEOUT),
                )

                audio_bytes.seek(0)
                return audio_bytes.read()
            except TelegramRetryAfter as e:
                # Telegram явно просит подождать — уважаем retry_after.
                last_error = e
                logger.warning(
                    f"Voice download attempt {attempt}/{TG_DOWNLOAD_MAX_ATTEMPTS}: "
                    f"flood control, retry after {e.retry_after}s"
                )
                if attempt < TG_DOWNLOAD_MAX_ATTEMPTS:
                    await asyncio.sleep(e.retry_after)
            except TelegramNetworkError as e:
                last_error = e
                logger.warning(
                    f"Voice download attempt {attempt}/{TG_DOWNLOAD_MAX_ATTEMPTS} "
                    f"failed (network): {e}"
                )
                if attempt < TG_DOWNLOAD_MAX_ATTEMPTS:
                    await asyncio.sleep(TG_DOWNLOAD_RETRY_BASE_DELAY * attempt)

        logger.error(
            f"Voice download failed after {TG_DOWNLOAD_MAX_ATTEMPTS} attempts: "
            f"{last_error}"
        )
        raise VoiceDownloadError(
            "Не удалось скачать голосовое из Telegram"
        ) from last_error

    async def _transcribe_once(self, raw: bytes) -> str:
        """Один запрос к Whisper. Каждый раз даём свежий буфер: после ошибки
        поток мог быть частично прочитан и повторно не отправится корректно."""

        buf = io.BytesIO(raw)
        buf.name = "voice.ogg"
        response = await self.client.audio.transcriptions.create(
            model=self.model,
            file=buf,
            language="ru",
            response_format="text",
        )
        text = response if isinstance(response, str) else str(response)
        return text.strip()


    async def clean_transcription(self, raw_text: str, question_text: str) -> str:
        from app.services.llm_service import LLMService
        llm = LLMService()
        return await llm.clean_stt_transcription(raw_text, question_text)
