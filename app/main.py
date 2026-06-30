import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from fastapi import FastAPI

from app.bot.middlewares.auth import AuthMiddleware
from app.bot.middlewares.db_session import DbSessionMiddleware
from app.bot.router import register_all_routers
from app.config import get_settings
from app.database.base import AsyncSessionLocal, engine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)
settings = get_settings()

ALLOWED_UPDATES = [
    "message",
    "callback_query",
    "inline_query",
    "chat_member",
    "my_chat_member",
]
_polling_task: asyncio.Task | None = None



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


async def _run_polling() -> None:
    """Фоновый long-polling. Исходящие соединения к api.telegram.org
    работают стабильно, в отличие от входящего webhook на этом хостинге."""
    while True:
        try:
            logger.info("Starting long-polling...")
            await dp.start_polling(
                bot,
                allowed_updates=ALLOWED_UPDATES,
                handle_signals=False,
            )
        except asyncio.CancelledError:
            logger.info("Polling cancelled")
            raise
        except Exception:
            logger.exception("Polling crashed — restart in 5s")
            await asyncio.sleep(5)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _polling_task
    logger.info("Starting ReportBot (long-polling mode)...")

    # Снимаем возможный старый webhook и сбрасываем накопленные апдейты
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        logger.info("Webhook deleted, switching to polling")
    except Exception as e:
        logger.warning("delete_webhook failed: %s", e)

    _polling_task = asyncio.create_task(_run_polling())

    yield

    logger.info("Shutting down...")
    if _polling_task is not None:
        _polling_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await _polling_task

    try:
        await dp.storage.close()
    except Exception as e:
        logger.warning("storage.close failed: %s", e)

    try:
        await bot.session.close()
    except Exception as e:
        logger.warning("bot.session.close failed: %s", e)

    await engine.dispose()


app = FastAPI(lifespan=lifespan, title="ReportBot")


@app.get("/health")
async def health_check():

    try:
        me = await bot.get_me()
        return {"status": "ok", "bot": me.username}
    except Exception as e:
        logger.warning("Health check failed: %s", e)
        return {"status": "degraded", "error": str(e)}
