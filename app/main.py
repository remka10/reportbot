import asyncio
import contextlib
import logging
import socket
from contextlib import asynccontextmanager

from aiogram import Bot, Dispatcher

from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode

from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.redis import RedisStorage
from fastapi import FastAPI


from app.admin.router import install_memory_log_handler, router as admin_router
from app.bot.middlewares.auth import AuthMiddleware
from app.bot.middlewares.db_session import DbSessionMiddleware
from app.bot.middlewares.timing import TimingMiddleware

from app.bot.router import register_all_routers
from app.config import get_settings
from app.database.base import AsyncSessionLocal, engine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
install_memory_log_handler()
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

# Long-polling: сколько секунд Telegram держит getUpdates открытым, если новых
# апдейтов нет (server-side long poll). 30с — стандартное значение aiogram.
POLLING_TIMEOUT = 30

# Таймаут ОДНОГО обычного запроса к Bot API (не getUpdates). Для getUpdates
# aiogram сам прибавляет polling_timeout: request_timeout = session.timeout +
# POLLING_TIMEOUT. ВАЖНО: aiogram 3.7.0 хранит session.timeout числом и делает
# int(session.timeout + polling_timeout) — поэтому сюда нельзя передавать
# aiohttp.ClientTimeout (будет TypeError на сложении с int), только число.
# 30с достаточно: если соединение до Telegram живое, ответ приходит быстро; если
# «мёртвое» — запрос оборвётся по таймауту и polling переоткроет его заново,
# вместо того чтобы висеть минуту (прежний timeout=60 давал «раз через раз»).
REQUEST_TIMEOUT = 30


def _make_bot() -> Bot:
    # Числовой таймаут (в секундах). Раздельные фазы (sock_read/sock_connect)
    # через AiohttpSession в этой версии aiogram задать нельзя — session.timeout
    # используется как одно число, см. комментарий к REQUEST_TIMEOUT.
    session = AiohttpSession(timeout=REQUEST_TIMEOUT)
    # Форсим IPv4 для исходящих запросов к api.telegram.org.
    # У контейнера нет IPv6-маршрута, но Docker-DNS периодически отдаёт AAAA-запись
    # (api.telegram.org -> 2001:67c:...) → попытка IPv6 виснет и даёт
    # TelegramNetworkError: Request timeout error. AF_INET убирает этот класс сбоев.
    session._connector_init["family"] = socket.AF_INET
    return Bot(
        token=settings.telegram_bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        session=session,
    )




def _make_storage():
    """FSM-хранилище: пытаемся использовать Redis (переживает рестарт бота).

    Если Redis недоступен/не установлен — не роняем бота, а откатываемся на
    MemoryStorage (состояние живёт только в памяти процесса). Так деплой не
    ломается, даже если redis ещё не поднят.
    """
    try:
        storage = RedisStorage.from_url(settings.redis_url)
        logger.info("FSM storage: Redis (%s)", settings.redis_url)
        return storage
    except Exception as e:
        logger.warning(
            "Redis storage unavailable (%s) — falling back to MemoryStorage", e
        )
        return MemoryStorage()


bot = _make_bot()
dp = Dispatcher(storage=_make_storage())


register_all_routers(dp)
# Порядок регистрации = порядок «снаружи внутрь». TimingMiddleware — самый внешний,
# чтобы замерять полное время обработки апдейта (включая БД-сессию и auth).
# Затем DbSessionMiddleware → AuthMiddleware (порядок этих двух КРИТИЧЕН, §6).
dp.update.middleware(TimingMiddleware())
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
                polling_timeout=POLLING_TIMEOUT,
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
app.include_router(admin_router)


@app.get("/health")
async def health_check():

    try:
        me = await bot.get_me()
        return {"status": "ok", "bot": me.username}
    except Exception as e:
        logger.warning("Health check failed: %s", e)
        return {"status": "degraded", "error": str(e)}
