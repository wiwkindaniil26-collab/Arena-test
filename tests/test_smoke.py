"""Проверка, что все зависимости собираются вместе и роутеры на месте."""

from __future__ import annotations

from pathlib import Path

from bot.config import Config, ConfigError
from bot.db import Database
from bot.main import build_dispatcher
from bot.services.cache import SearchCache
from bot.services.downloader import Downloader
from bot.services.library import Library
from bot.services.limiter import RateLimiter
from bot.services.music import MusicService


def make_config(tmp_path: Path) -> Config:
    return Config.from_env(
        {
            "BOT_TOKEN": "123456789:AAExampleToken",
            "DB_PATH": str(tmp_path / "smoke.db"),
            "DOWNLOAD_DIR": str(tmp_path / "dl"),
        },
        load_env_file=False,
    )


async def test_dispatcher_wiring(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    db = Database(config.db_path)
    await db.init()
    downloader = Downloader(config)
    library = Library(db)
    cache = SearchCache()
    limiter = RateLimiter()
    music = MusicService(config, db, downloader, library, cache)

    dp = build_dispatcher(config, db, music, library, limiter, downloader, cache)

    names = [router.name for router in dp.sub_routers]
    assert names == ["common", "random", "library", "music"]

    # у каждого роутера есть хотя бы один хендлер
    for router in dp.sub_routers:
        assert router.message.handlers or router.callback_query.handlers

    # вебхук-независимый polling: типы апдейтов определяются автоматически
    updates = dp.resolve_used_update_types()
    assert "message" in updates
    assert "callback_query" in updates


async def test_config_error_is_readable() -> None:
    try:
        Config.from_env({}, load_env_file=False)
    except ConfigError as exc:
        assert "BOT_TOKEN" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("ожидали ConfigError")
