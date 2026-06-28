import logging
import socket
from contextlib import asynccontextmanager

import aiohttp
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Update
from fastapi import FastAPI, Request, Response

from app.bot.middlewares.auth import AuthMiddleware
from app.bot.middlewares.db_session import DbSessionMiddleware
from app.bot.router import register_all_routers
from app.config import get_settings
from app.database.base import engine, AsyncSessionLocal

logger = logging.getLogger(__name__)
settings = get_settings()


def _make_bot() -> Bot:
    """Создаём бота с явным IPv4-only коннектором."""
    connector = aiohttp.TCPConnector(
        family=socket.AF_INET,
        ssl=True,
    )
    session = AiohttpSession(timeout=60)
    # Подменяем внутренний коннектор сессии на IPv4-only
    session._connector_class = lambda **kw: connector  # type: ignore
    return Bot(
        token=settings.telegram_bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        session=session,
    )


bot = _make_bot()
dp = Dispatcher(storage=MemoryStorage())


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting ReportBot...")

    register_all_routers(dp)
    dp.update.middleware(DbSessionMiddleware(session_factory=AsyncSessionLocal))
    dp.update.middleware(AuthMiddleware())

    webhook_url = f"{settings.webhook_url}/webhook/{settings.telegram_bot_token}"

    for attempt in range(1, 4):
        try:
            await bot.set_webhook(
                webhook_url,
                drop_pending_updates=True,
                allowed_updates=["message", "callback_query"],
            )
            logger.info(f"Webhook set OK: {webhook_url}")
            break
        except Exception as e:
            logger.warning(f"Webhook attempt {attempt}/3 failed: {e}")
            if attempt < 3:
                import asyncio
                await asyncio.sleep(5 * attempt)
            else:
                logger.error("All webhook attempts failed!")

    yield

    logger.info("Shutting down...")
    try:
        await bot.delete_webhook()
    except Exception as e:
        logger.warning(f"delete_webhook failed: {e}")
    await engine.dispose()


app = FastAPI(lifespan=lifespan, title="ReportBot")


@app.post("/webhook/{token}")
async def webhook_handler(token: str, request: Request) -> Response:
    if token != settings.telegram_bot_token:
        return Response(status_code=403)
    try:
        body = await request.json()
        update = Update.model_validate(body)
        await dp.feed_update(bot=bot, update=update)
    except Exception as e:
        logger.error(f"Webhook handler error: {e}", exc_info=True)
    return Response(status_code=200)


@app.get("/health")
async def health_check():
    try:
        me = await bot.get_me()
        return {"status": "ok", "bot": me.username}
    except Exception as e:
        return {"status": "degraded", "error": str(e)}
