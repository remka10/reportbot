import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery, TelegramObject, Update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database.models import User, UserRole

logger = logging.getLogger(__name__)
settings = get_settings()

PUBLIC_COMMANDS = {"/start"}


class AuthMiddleware(BaseMiddleware):
    """
    Проверяет роль пользователя при каждом апдейте.

    Логика:
    1. Извлекаем Telegram user из апдейта.
    2. Ищем пользователя в БД.
    3. Если user_id == ADMIN_TELEGRAM_ID и в БД нет — создаём admin автоматически.
    4. Если пользователя нет в БД — отправляем сообщение об отсутствии доступа.
    5. Если is_active=False — отклоняем.
    6. Если всё ок — кладём объект User в data["user"].
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        # Достаём tg_user из апдейта
        tg_user = data.get("event_from_user")
        if tg_user is None:
            return await handler(event, data)

        session: AsyncSession = data["session"]

        # --- Проверяем первого admin через env ---
        db_user: User | None = await session.get(User, tg_user.id)

        if db_user is None:
            if tg_user.id == settings.admin_telegram_id:
                # Создаём первого администратора автоматически
                db_user = User(
                    id=tg_user.id,
                    username=tg_user.username,
                    full_name=tg_user.full_name or "Администратор",
                    role=UserRole.admin,
                    is_active=True,
                )
                session.add(db_user)
                await session.flush()
                logger.info(f"Auto-created admin user id={tg_user.id}")
            else:
                # Пользователь не зарегистрирован
                if isinstance(event, Message):
                    await event.answer(
                        "⛔ У вас нет доступа к этому боту.\n"
                        "Обратитесь к администратору для получения доступа."
                    )
                elif isinstance(event, CallbackQuery):
                    await event.answer("⛔ Нет доступа", show_alert=True)
                return  # Прерываем обработку

        # --- Проверяем активность ---
        if not db_user.is_active:
            if isinstance(event, Message):
                await event.answer("⛔ Ваш аккаунт деактивирован. Обратитесь к администратору.")
            elif isinstance(event, CallbackQuery):
                await event.answer("⛔ Аккаунт деактивирован", show_alert=True)
            return

        # Обновляем username если изменился
        if db_user.username != tg_user.username:
            db_user.username = tg_user.username

        data["user"] = db_user
        return await handler(event, data)