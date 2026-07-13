import asyncio
import logging
import time
import traceback
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.exceptions import (
    TelegramNetworkError,
    TelegramRetryAfter,
)

from aiogram.types import CallbackQuery, Message, TelegramObject, Update
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

logger = logging.getLogger(__name__)


# Классификация исключений: сетевые/временные сбои связи с Telegram — это НЕ баг
# в коде хендлера, а «моргнувшая» сеть до api.telegram.org. Их логируем мягче
# (WARNING) и предлагаем пользователю повторить, а не пишем как настоящую ошибку.
_NETWORK_ERRORS = (
    TelegramNetworkError,
    TelegramRetryAfter,
    asyncio.TimeoutError,
    TimeoutError,
    ConnectionError,
)


def _extract_update(event: TelegramObject, data: dict[str, Any]) -> Update | None:
    """Достаёт объект Update из события/данных (middleware висит на dp.update)."""
    update = data.get("event_update") or event
    return update if isinstance(update, Update) else None


def _describe_event(update: Update | None) -> dict[str, Any]:
    """Готовит краткое человекочитаемое описание апдейта для лога.

    Возвращает поля: update_id, type, user_id, а также data (для callback) или
    text (для сообщения) — этого достаточно, чтобы по логу однозначно понять,
    какое именно действие пользователя упало.
    """
    info: dict[str, Any] = {
        "update_id": None,
        "type": "unknown",
        "user_id": None,
        "chat_id": None,
        "payload": None,
    }
    if update is None:
        return info

    info["update_id"] = getattr(update, "update_id", None)

    cb = getattr(update, "callback_query", None)
    msg = getattr(update, "message", None)

    if cb is not None:
        info["type"] = "callback_query"
        info["user_id"] = cb.from_user.id if cb.from_user else None
        info["payload"] = f"data={cb.data!r}"
        if cb.message:
            info["chat_id"] = cb.message.chat.id
    elif msg is not None:
        info["type"] = "message"
        info["user_id"] = msg.from_user.id if msg.from_user else None
        info["chat_id"] = msg.chat.id if msg.chat else None
        if msg.text:
            info["payload"] = f"text={msg.text[:80]!r}"
        elif msg.voice:
            info["payload"] = "voice"
        else:
            info["payload"] = f"content_type={msg.content_type}"
    else:
        # inline_query / chat_member / my_chat_member и т.п.
        for attr in ("inline_query", "chat_member", "my_chat_member"):
            obj = getattr(update, attr, None)
            if obj is not None:
                info["type"] = attr
                info["user_id"] = getattr(getattr(obj, "from_user", None), "id", None)
                break
    return info


async def _notify_user(update: Update | None, is_network: bool) -> None:
    """Сообщает пользователю об ошибке, чтобы он не видел «зависшие часики».

    Без этого при исключении в хендлере (которое middleware глушит) пользователь
    не получает никакой реакции — кнопка «нажата» навсегда, сообщение без ответа.
    Сам вызов обёрнут в try/except: если сеть недоступна, уведомить не выйдет —
    это не должно приводить к повторному исключению в middleware.
    """
    if update is None:
        return

    if is_network:
        text_alert = "⚠️ Проблема со связью. Попробуйте ещё раз через пару секунд."
        text_message = (
            "⚠️ Похоже, connection к Telegram на секунду прервался.\n"
            "Повторите действие ещё раз."
        )
    else:
        text_alert = "⚠️ Произошла ошибка. Попробуйте снова или /start."
        text_message = "⚠️ Произошла ошибка при обработке. Попробуйте снова или /start."

    try:
        cb: CallbackQuery | None = getattr(update, "callback_query", None)
        msg: Message | None = getattr(update, "message", None)
        if cb is not None:
            # show_alert=True — заметное всплывающее окно и снятие «часиков» с кнопки.
            await cb.answer(text_alert, show_alert=True)
        elif msg is not None:
            await msg.answer(text_message)
    except Exception as notify_err:
        logger.warning(f"[DB_MW] Не удалось уведомить пользователя об ошибке: {notify_err}")


class DbSessionMiddleware(BaseMiddleware):
    """Сессия БД на апдейт + единая обработка исключений хендлеров.

    Помимо выдачи/commit/rollback сессии, здесь находится «сеть безопасности»:
    любое непойманное исключение хендлера логируется со structured-контекстом
    (какой апдейт, пользователь, callback_data/текст, тип ошибки) и пользователю
    отправляется понятное сообщение. Это НЕ отменяет правило §10 (в каждом
    хендлере — свой try/except с осмысленным сообщением), а служит последним
    рубежом, чтобы ни один сбой не оставался «немым».
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        update = _extract_update(event, data)
        started = time.monotonic()
        async with self.session_factory() as session:
            data["session"] = session
            try:
                result = await handler(event, data)
                await session.commit()
                return result
            except Exception as exc:
                # rollback обязателен — без него сессия остаётся «грязной»
                await session.rollback()

                elapsed_ms = int((time.monotonic() - started) * 1000)
                is_network = isinstance(exc, _NETWORK_ERRORS)
                ctx = _describe_event(update)
                kind = "NETWORK" if is_network else "HANDLER"

                # Заголовок — одной строкой, чтобы легко грепать (ERROR/WARNING +
                # тип + update_id + user + payload + сколько длилось до падения).
                header = (
                    f"=== {kind} EXCEPTION === "
                    f"update_id={ctx['update_id']} type={ctx['type']} "
                    f"user={ctx['user_id']} chat={ctx['chat_id']} "
                    f"{ctx['payload'] or ''} elapsed={elapsed_ms}ms "
                    f"err={type(exc).__name__}: {exc}"
                )
                if is_network:
                    # Сетевой сбой доставки/приёма — это временно, не «баг».
                    # WARNING + короткий traceback (полный не нужен, стек всегда aiohttp).
                    logger.warning(header)
                else:
                    logger.error(f"{header}\n{traceback.format_exc()}")

                await _notify_user(update, is_network)
                return None
