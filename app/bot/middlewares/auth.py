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
        logger.warning(f"[AUTH] event type: {type(event).__name__}, data keys: {list(data.keys())}")

        session: AsyncSession | None = data.get("session")
        if session is None:
            logger.warning("[AUTH] No session — skipping auth")
            return await handler(event, data)

        update: Update = data.get("event_update") or event
        logger.warning(f"[AUTH] update type: {type(update).__name__}, has message: {hasattr(update, 'message') and update.message is not None}")

        tg_user = None
        if hasattr(update, "message") and update.message:
            tg_user = update.message.from_user
        elif hasattr(update, "callback_query") and update.callback_query:
            tg_user = update.callback_query.from_user

        logger.warning(f"[AUTH] tg_user: {tg_user}")

        if tg_user is None:
            logger.warning("[AUTH] No tg_user — skipping auth")
            return await handler(event, data)

        tg_id = tg_user.id
        repo = UserRepository(session)
        user = await repo.get_by_id(tg_id)
        logger.warning(f"[AUTH] user from DB: {user}, tg_id={tg_id}, admin_id={settings.admin_telegram_id}")

        if user is None and tg_id == settings.admin_telegram_id:
            try:
                user = await repo.create(
                    user_id=tg_id,
                    full_name=tg_user.full_name or "Admin",
                    role=UserRole.admin,
                    username=tg_user.username,
                )
                await session.flush()
                logger.warning(f"[AUTH] Auto-created admin id={tg_id}")
            except Exception as e:
                logger.warning(f"[AUTH] Admin create failed: {e}")
                await session.rollback()
                user = await repo.get_by_id(tg_id)

        logger.warning(f"[AUTH] Final user: {user}, is_active: {getattr(user, 'is_active', None)}")

        if user is None or not user.is_active:
            logger.warning(f"[AUTH] Access denied for {tg_id}")
            try:
                if hasattr(update, "message") and update.message:
                    await update.message.answer("⛔ У вас нет доступа к этому боту.\nОбратитесь к администратору.")
                elif hasattr(update, "callback_query") and update.callback_query:
                    await update.callback_query.answer("⛔ Нет доступа.", show_alert=True)
            except Exception as e:
                logger.warning(f"[AUTH] Could not send denied msg: {e}")
            return

        data["user"] = user
        logger.warning(f"[AUTH] Passing to handler, user={user.id}, role={user.role}")
        return await handler(event, data)
