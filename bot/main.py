"""Точка входа: собираем зависимости и запускаем long polling."""

from __future__ import annotations

import asyncio
import logging
import sys
from contextlib import suppress

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand, ErrorEvent

from bot.config import Config, ConfigError
from bot.db import Database
from bot.handlers import common
from bot.handlers import library as library_handlers
from bot.handlers import music as music_handlers
from bot.handlers import random_track as random_handlers
from bot.middlewares import AccessMiddleware
from bot.services.cache import SearchCache
from bot.services.downloader import Downloader
from bot.services.library import Library
from bot.services.limiter import RateLimiter
from bot.services.music import MusicService

logger = logging.getLogger(__name__)

BOT_COMMANDS = [
    BotCommand(command="start", description="🏠 Меню"),
    BotCommand(command="search", description="🔍 Найти трек"),
    BotCommand(command="random", description="🎲 Случайный трек"),
    BotCommand(command="random_fav", description="⭐ Случайный из избранного"),
    BotCommand(command="library", description="📚 Библиотека"),
    BotCommand(command="favorites", description="⭐ Избранное"),
    BotCommand(command="stats", description="📊 Статистика"),
    BotCommand(command="help", description="❓ Помощь"),
]


def setup_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
    )
    logging.getLogger("aiogram.event").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)


def build_dispatcher(
    config: Config,
    db: Database,
    music: MusicService,
    library: Library,
    limiter: RateLimiter,
    downloader: Downloader,
    cache: SearchCache,
) -> Dispatcher:
    dp = Dispatcher(
        config=config,
        db=db,
        music=music,
        library=library,
        limiter=limiter,
        downloader=downloader,
        cache=cache,
    )

    access = AccessMiddleware(config.allowed_users)
    dp.message.outer_middleware(access)
    dp.callback_query.outer_middleware(access)

    dp.include_routers(
        common.router,
        random_handlers.router,
        library_handlers.router,
        music_handlers.router,
    )

    @dp.errors()
    async def on_error(event: ErrorEvent) -> bool:
        logger.error("Необработанная ошибка", exc_info=event.exception)
        update = event.update
        try:
            if update.message is not None:
                await update.message.answer("😔 Внутренняя ошибка. Попробуй ещё раз.")
            elif update.callback_query is not None:
                await update.callback_query.answer("😔 Внутренняя ошибка", show_alert=True)
        except Exception:  # noqa: BLE001
            pass
        return True

    return dp


async def main() -> None:
    try:
        config = Config.from_env()
    except ConfigError as exc:
        print(f"❌ {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    setup_logging(config.log_level)
    config.prepare_dirs()

    if not config.cookies_file:
        logger.info("COOKIES_FILE не задан — источники, требующие входа, будут недоступны")

    db = Database(config.db_path)
    await db.init()

    downloader = Downloader(config)
    library = Library(db)
    cache = SearchCache()
    limiter = RateLimiter(config.rate_limit_count, config.rate_limit_window)
    music = MusicService(config, db, downloader, library, cache)

    bot = Bot(
        token=config.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = build_dispatcher(config, db, music, library, limiter, downloader, cache)

    try:
        me = await bot.get_me()
        logger.info("Бот @%s запущен", me.username)
        await bot.set_my_commands(BOT_COMMANDS)
        await dp.start_polling(
            bot,
            allowed_updates=dp.resolve_used_update_types(),
            handle_signals=True,
        )
    finally:
        await db.close()
        await bot.session.close()
        logger.info("Бот остановлен")


if __name__ == "__main__":
    with suppress(KeyboardInterrupt, SystemExit):
        asyncio.run(main())
