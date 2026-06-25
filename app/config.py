from functools import lru_cache
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Telegram
    telegram_bot_token: str
    webhook_url: str
    admin_telegram_id: int

    # Database
    database_url: str

    # AiTunnel (единый прокси для LLM и STT)
    aitunnel_api_key: str
    aitunnel_base_url: str = "https://api.aitunnel.ru/v1"

    # Модели
    gemini_model: str = "gemini-2.5-flash"
    whisper_model: str = "whisper-1"

    # App
    debug: bool = False
    log_level: str = "INFO"
    max_audio_size_mb: int = 20
    reports_dir: str = "/app/reports"

    @field_validator("webhook_url")
    @classmethod
    def strip_trailing_slash(cls, v: str) -> str:
        return v.rstrip("/")

    @field_validator("aitunnel_base_url")
    @classmethod
    def strip_base_url_slash(cls, v: str) -> str:
        return v.rstrip("/")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()