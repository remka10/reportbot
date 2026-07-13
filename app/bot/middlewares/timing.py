"""Middleware замера длительности обработки апдейта.

Зачем: aiogram уже пишет INFO «Update id=... is handled. Duration N ms», но это
единая строка без контекста, и «медленно, но выполнилось» в ней теряется среди
обычных апдейтов. Этот middleware отдельно выделяет МЕДЛЕННЫЕ апдейты в WARNING с
понятным контекстом (что за действие, кто, сколько длилось) — чтобы случай
«прошло, но очень долго» был явно виден в логах, а не только по общему Duration.

Регистрируется ПЕРВЫМ (внешним), чтобы охватить полное время обработки, включая
БД-сессию и остальные middleware.
"""

import logging
import time
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Update

logger = logging.getLogger(__name__)

# Порог «медленного» апдейта. Обычные callback/сообщения обрабатываются за
# десятки–сотни мс; всё, что дольше 3 секунд — повод обратить внимание
# (LLM-генерация/экспорт логируются отдельно самими хендлерами со статусами).
SLOW_UPDATE_THRESHOLD_MS = 3000


def _short_desc(update: Update | None) -> str:
    """Короткое описание апдейта для строки лога (тип + data/текст + user)."""
    if update is None:
        return "unknown"
    cb = getattr(update, "callback_query", None)
    msg = getattr(update, "message", None)
    if cb is not None:
        user_id = cb.from_user.id if cb.from_user else None
        return f"callback data={cb.data!r} user={user_id}"
    if msg is not None:
        user_id = msg.from_user.id if msg.from_user else None
        if msg.text:
            return f"message text={msg.text[:60]!r} user={user_id}"
        if msg.voice:
            return f"message voice user={user_id}"
        return f"message {msg.content_type} user={user_id}"
    return "service-update"


class TimingMiddleware(BaseMiddleware):
    """Логирует апдейты, обработка которых заняла дольше порога."""

    def __init__(self, threshold_ms: int = SLOW_UPDATE_THRESHOLD_MS) -> None:
        self.threshold_ms = threshold_ms

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        update = data.get("event_update") or event
        started = time.monotonic()
        try:
            return await handler(event, data)
        finally:
            elapsed_ms = int((time.monotonic() - started) * 1000)
            if elapsed_ms >= self.threshold_ms:
                update_id = getattr(update, "update_id", None) if isinstance(update, Update) else None
                logger.warning(
                    "SLOW UPDATE update_id=%s %s handled in %d ms (>= %d ms)",
                    update_id,
                    _short_desc(update if isinstance(update, Update) else None),
                    elapsed_ms,
                    self.threshold_ms,
                )
