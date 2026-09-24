"""Точка запуска приложения."""
import asyncio
import contextlib
import logging
import re
import sys
from pathlib import Path

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.fsm.storage.memory import MemoryStorage, SimpleEventIsolation

from .bot import appointments, booking, business, calendar, schedule, services
from .bot.common import ContextMiddleware, HOME, forms_router, one, send
from .bot.notifications import worker
from .config import Settings
from .logic.booking import BookingService
from .storage import MemoryRepository


class RedactSecrets(logging.Formatter):
    def format(self, record):
        return re.sub(r"\b\d{6,}:[A-Za-z0-9_-]{25,}\b", "[BOT_TOKEN]", super().format(record))


@contextlib.contextmanager
def process_lock(path):
    """Prevent two local processes sharing a JSON store or polling the same bot."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as file:
        file.seek(0)
        if not file.read(1):
            file.write(b"0")
            file.flush()
        file.seek(0)
        try:
            if sys.platform == "win32":
                import msvcrt

                msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise RuntimeError("Notebook уже запущен в этой папке. Остановите первый процесс.") from None
        try:
            yield
        finally:
            file.seek(0)
            if sys.platform == "win32":
                msvcrt.locking(file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(file.fileno(), fcntl.LOCK_UN)


def build_app(settings):
    if settings.storage == "database":
        from .database.db import create_repository

        repo = create_repository()
    elif settings.storage in ("memory", "json"):
        repo = MemoryRepository(settings.data_file if settings.storage == "json" else None)
    else:
        raise ValueError("STORAGE: json, memory или database")
    return BookingService(repo, settings.timezone)


def build_dispatcher(app):
    from .bot import menu

    dp = Dispatcher(storage=MemoryStorage(), events_isolation=SimpleEventIsolation())
    middleware = ContextMiddleware(app)
    dp.message.outer_middleware(middleware)
    dp.callback_query.outer_middleware(middleware)
    # Deep links before /start without payload; navigation before generic form input.
    dp.include_router(business.router)
    dp.include_router(menu.router)
    dp.include_router(services.router)
    dp.include_router(schedule.router)
    dp.include_router(calendar.router)
    dp.include_router(booking.router)
    dp.include_router(appointments.router)
    dp.include_router(forms_router)
    fallback = Router(name="fallback")

    @fallback.callback_query()
    async def stale(callback):
        await send(callback, "Кнопка устарела. Откройте главное меню.", one(HOME))

    @fallback.message(F.text)
    async def unknown(message):
        await send(message, "Используйте /start или кнопки меню.", one(HOME))

    @fallback.errors()
    async def unexpected(event):
        logging.getLogger(__name__).error(
            "Unhandled bot error",
            exc_info=(type(event.exception), event.exception, event.exception.__traceback__),
        )
        update = event.update
        target = update.callback_query or update.message
        if target:
            with contextlib.suppress(Exception):
                await send(
                    target, "Не удалось выполнить действие. Откройте меню и попробуйте снова.", one(HOME)
                )
        return True

    dp.include_router(fallback)
    return dp


async def main():
    settings = Settings.load()
    handler = logging.StreamHandler()
    handler.setFormatter(RedactSecrets("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)
    with process_lock(Path("data/notebook.lock")):
        app = build_app(settings)
        dp = build_dispatcher(app)
        async with Bot(settings.token, session=AiohttpSession(proxy=settings.proxy, timeout=30)) as bot:
            info = await bot.get_me()
            webhook = await bot.get_webhook_info()
            if webhook.url:
                raise RuntimeError("У бота установлен webhook. Для polling сначала отключите прежний запуск.")
            logging.info("Notebook started as @%s", info.username)
            task = asyncio.create_task(worker(bot, app))
            try:
                await dp.start_polling(
                    bot, allowed_updates=dp.resolve_used_update_types(), close_bot_session=False
                )
            finally:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
                await dp.storage.close()


def run():
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    run()
