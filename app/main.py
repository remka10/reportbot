import logging
from contextlib import asynccontextmanager

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Update
from fastapi import FastAPI, Request, Response

from app.bot.middlewares.auth import AuthMiddleware
from app.bot.middlewares.db_session import DbSessionMiddleware  # ИСПРАВЛЕНО: db_session (с подчёркиванием)
from app.bot.router import register_all_routers
from app.config import get_settings
from app.database.base import engine, AsyncSessionLocal

logger = logging.getLogger(__name__)
settings = get_settings()

bot = Bot(
    token=settings.telegram_bot_token,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)
dp = Dispatcher(storage=MemoryStorage())


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting ReportBot...")

    register_all_routers(dp)
    dp.update.middleware(DbSessionMiddleware(session_factory=AsyncSessionLocal))
    dp.update.middleware(AuthMiddleware())

    webhook_url = f"{settings.webhook_url}/webhook/{settings.telegram_bot_token}"
    await bot.set_webhook(webhook_url)
    logger.info(f"Webhook set: {webhook_url}")

    yield

    logger.info("Shutting down ReportBot...")
    await bot.delete_webhook()
    await engine.dispose()


app = FastAPI(lifespan=lifespan, title="ReportBot")


@app.post("/webhook/{token}")
async def webhook_handler(token: str, request: Request) -> Response:
    if token != settings.telegram_bot_token:
        return Response(status_code=403)
    body = await request.json()
    update = Update.model_validate(body)
    await dp.feed_update(bot=bot, update=update)
    return Response(status_code=200)


@app.get("/health")
async def health_check():
    return {"status": "ok", "bot": (await bot.get_me()).username}