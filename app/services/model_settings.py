# app/services/model_settings.py
"""
Лёгкое персистентное хранилище выбора LLM-модели для генерации.

Бот и веб-панель /admin работают в одном процессе (uvicorn, 1 воркер),
поэтому выбор держим в модульном кэше и дублируем в JSON-файл на persistent
volume (REPORTS_DIR/model_settings.json). Это переживает рестарт контейнера и
НЕ требует alembic-миграции.

Две независимые области переключения:
  - "generation" — итоговый отчёт (generate_report / revise_report);
  - "context"    — контекст смены (beautify_shift_context / revise_shift_context).

Правки Whisper (clean_stt_transcription) НЕ переключаются — всегда Gemini.
"""
import json
import logging
from pathlib import Path
from typing import Any

from app.config import get_settings

logger = logging.getLogger(__name__)

# Ключи выбора → человекочитаемые подписи. Реальные id моделей берутся из
# настроек (get_settings) в момент запроса, чтобы .env оставался единым
# источником правды для конкретных версий моделей.
MODEL_CHOICES: dict[str, str] = {
    "gemini": "Gemini 2.5 Flash",
    "haiku": "Claude Haiku 4.5",
}

# Области переключения и их дефолты.
DEFAULTS: dict[str, str] = {
    "generation": "gemini",
    "context": "gemini",
}

_state: dict[str, str] | None = None


def _settings_path() -> Path:
    return Path(get_settings().reports_dir) / "model_settings.json"


def _resolve_model_id(choice: str) -> str:
    settings = get_settings()
    if choice == "haiku":
        return settings.haiku_model
    return settings.gemini_model


def _load() -> dict[str, str]:
    global _state
    if _state is not None:
        return _state
    state = dict(DEFAULTS)
    path = _settings_path()
    try:
        if path.exists():
            raw = json.loads(path.read_text(encoding="utf-8"))
            for key in DEFAULTS:
                value = raw.get(key)
                if value in MODEL_CHOICES:
                    state[key] = value
    except Exception as e:  # файл повреждён / нет доступа — работаем на дефолтах
        logger.warning("model_settings load failed: %s", e)
    _state = state
    return _state


def _save() -> None:
    path = _settings_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(_load(), ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        logger.warning("model_settings save failed: %s", e)


def get_choice(kind: str) -> str:
    """Возвращает ключ выбранной модели ("gemini"|"haiku") для области kind."""
    return _load().get(kind, DEFAULTS.get(kind, "gemini"))


def get_model(kind: str) -> str:
    """Возвращает реальный id модели для области kind (generation|context)."""
    return _resolve_model_id(get_choice(kind))


def set_choice(kind: str, choice: str) -> None:
    """Устанавливает и персистит выбор модели для области kind."""
    if kind not in DEFAULTS:
        raise ValueError(f"Unknown model area: {kind}")
    if choice not in MODEL_CHOICES:
        raise ValueError(f"Unknown model choice: {choice}")
    state = _load()
    state[kind] = choice
    _save()
    logger.info("model_settings: %s -> %s (%s)", kind, choice, _resolve_model_id(choice))


def snapshot() -> dict[str, Any]:
    """Текущее состояние + список опций для админ-панели."""
    settings = get_settings()
    state = _load()
    return {
        "areas": {
            kind: {
                "choice": state.get(kind, default),
                "model_id": _resolve_model_id(state.get(kind, default)),
            }
            for kind, default in DEFAULTS.items()
        },
        "options": [
            {"key": key, "label": label, "model_id": _resolve_model_id(key)}
            for key, label in MODEL_CHOICES.items()
        ],
        # Whisper-правки не переключаются — всегда Gemini (для отображения).
        "whisper_clean_model": settings.gemini_model,
    }
