# app/bot/middlewares/auth.py
import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database.models import User, UserRole
from app.repositories.user_repo import UserRepository

logger = logging.getLogger(__name__)
settings = get_settings()


class AuthMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        session: AsyncSession | None = data.get("session")
        if session is None:
            return await handler(event, data)

        # Извлекаем telegram_id из апдейта
        update: Update = data.get("event_update") or event
        tg_user = None

        if hasattr(update, "message") and update.message:
            tg_user = update.message.from_user
        elif hasattr(update, "callback_query") and update.callback_query:
            tg_user = update.callback_query.from_user

        if tg_user is None:
            return await handler(event, data)

        tg_id = tg_user.id

        # Администратор — автоматически создаётся при первом старте
        repo = UserRepository(session)
        user = await repo.get_by_id(tg_id)

        if user is None and tg_id == settings.admin_telegram_id:
            user = await repo.create(
                user_id=tg_id,
                full_name=tg_user.full_name or "Admin",
                role=UserRole.admin,
                username=tg_user.username,
            )
            logger.info(f"Auto-created admin user id={tg_id}")

        if user is None or not user.is_active:
            # Неизвестный пользователь — блокируем, отвечаем
            if hasattr(update, "message") and update.message:
                await update.message.answer(
                    "⛔ У вас нет доступа к этому боту.\n"
                    "Обратитесь к администратору."
                )
            elif hasattr(update, "callback_query") and update.callback_query:
                await update.callback_query.answer(
                    "⛔ Нет доступа.", show_alert=True
                )
            return  # НЕ вызываем handler

        data["user"] = user  # ← КРИТИЧНО: инжектируем в data
        return await handler(event, data)