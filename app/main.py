import asyncio
import logging
from contextlib import asynccontextmanager
from urllib.parse import unquote

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
from app.database.base import AsyncSessionLocal, engine

logger = logging.getLogger(__name__)
settings = get_settings()


def _make_bot() -> Bot:
    session = AiohttpSession(timeout=60)
    return Bot(
        token=settings.telegram_bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        session=session,
    )


bot = _make_bot()
dp = Dispatcher(storage=MemoryStorage())

register_all_routers(dp)
dp.update.middleware(DbSessionMiddleware(session_factory=AsyncSessionLocal))
dp.update.middleware(AuthMiddleware())


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting ReportBot...")

    webhook_url = f"{settings.webhook_url}/webhook/{settings.telegram_bot_token}"
    allowed_updates = [
        "message",
        "callback_query",
        "inline_query",
        "chat_member",
        "my_chat_member",
    ]

    for attempt in range(1, 4):
        try:
            await bot.set_webhook(
                url=webhook_url,
                drop_pending_updates=True,
                allowed_updates=allowed_updates,
            )
            logger.info("Webhook set OK: %s", webhook_url)
            break
        except Exception as e:
            logger.warning("Webhook attempt %s/3 failed: %s", attempt, e)
            if attempt < 3:
                await asyncio.sleep(5 * attempt)
            else:
                logger.exception("All webhook attempts failed")

    yield

    logger.info("Shutting down...")
    try:
        await bot.session.close()
    except Exception as e:
        logger.warning("bot.session.close failed: %s", e)

    await engine.dispose()


app = FastAPI(lifespan=lifespan, title="ReportBot")


@app.post("/webhook/{token}")
async def webhook_handler(token: str, request: Request) -> Response:
    if unquote(token) != settings.telegram_bot_token:
        return Response(status_code=403)

    try:
        body = await request.json()
        update = Update.model_validate(body)
        await dp.feed_update(bot=bot, update=update)
    except Exception as e:
        logger.exception("Webhook handler error: %s", e)

    return Response(status_code=200)


@app.get("/health")
async def health_check():
    try:
        me = await bot.get_me()
        return {"status": "ok", "bot": me.username}
    except Exception as e:
        logger.warning("Health check failed: %s", e)
        return {"status": "degraded", "error": str(e)}
