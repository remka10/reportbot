import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database.models import UserRole
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
            logger.warning("[AUTH] No session — skipping auth")
            return await handler(event, data)

        update: Update = data.get("event_update") or event

        # Извлекаем tg_user из всех типов апдейтов
        tg_user = None
        if hasattr(update, "message") and update.message:
            tg_user = update.message.from_user
        elif hasattr(update, "callback_query") and update.callback_query:
            tg_user = update.callback_query.from_user
        elif hasattr(update, "inline_query") and update.inline_query:
            tg_user = update.inline_query.from_user
        elif hasattr(update, "chat_member") and update.chat_member:
            tg_user = update.chat_member.from_user
        elif hasattr(update, "my_chat_member") and update.my_chat_member:
            tg_user = update.my_chat_member.from_user

        if tg_user is None:
            logger.warning("[AUTH] No tg_user — skipping auth")
            return await handler(event, data)

        tg_id = tg_user.id
        repo = UserRepository(session)
        user = await repo.get_by_id(tg_id)

        if user is None and tg_id == settings.admin_telegram_id:
            try:
                user = await repo.create(
                    user_id=tg_id,
                    full_name=tg_user.full_name or "Admin",
                    role=UserRole.admin,
                    username=tg_user.username,
                )
                await session.flush()
                logger.info(f"[AUTH] Auto-created admin id={tg_id}")
            except Exception as e:
                logger.warning(f"[AUTH] Admin create failed: {e}")
                await session.rollback()
                user = await repo.get_by_id(tg_id)

        # Обновляем username при каждом входе, чтобы не хранить устаревший
        if user is not None and tg_user.username != user.username:
            try:
                await repo.update_username(tg_id, tg_user.username)
                user.username = tg_user.username
            except Exception as e:
                logger.warning(f"[AUTH] update_username failed: {e}")

        if user is None or not user.is_active:
            logger.warning(f"[AUTH] Access denied for {tg_id}")
            try:
                if hasattr(update, "message") and update.message:
                    await update.message.answer(
                        "⛔ У вас нет доступа к этому боту.\nОбратитесь к администратору."
                    )
                elif hasattr(update, "callback_query") and update.callback_query:
                    await update.callback_query.answer("⛔ Нет доступа.", show_alert=True)
            except Exception as e:
                logger.warning(f"[AUTH] Could not send denied msg: {e}")
            return

        data["user"] = user
        return await handler(event, data)