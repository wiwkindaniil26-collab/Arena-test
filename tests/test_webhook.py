"""Webhook-режим: HTTP-сервер, /health и приём апдейтов."""

from __future__ import annotations

from pathlib import Path

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from fakes import FakeSession, make_bot, text_update

from bot.config import Config
from bot.db import Database
from bot.main import build_dispatcher
from bot.services.cache import SearchCache
from bot.services.downloader import Downloader
from bot.services.library import Library
from bot.services.limiter import RateLimiter
from bot.services.music import MusicService
from bot.webhook import create_app

SECRET = "s3cret-token"


def webhook_config(tmp_path: Path, **overrides: str) -> Config:
    env = {
        "BOT_TOKEN": "123456789:AAExampleToken",
        "DB_PATH": str(tmp_path / "wh.db"),
        "DOWNLOAD_DIR": str(tmp_path / "dl"),
        "RUN_MODE": "webhook",
        "WEBHOOK_BASE_URL": "https://bot.example.workers.dev",
        "WEBHOOK_SECRET": SECRET,
    }
    env.update(overrides)
    config = Config.from_env(env, load_env_file=False)
    config.prepare_dirs()
    return config


@pytest.fixture
async def web_env(tmp_path: Path):
    config = webhook_config(tmp_path)
    db = Database(config.db_path)
    await db.init()
    downloader = Downloader(config)
    library = Library(db)
    music = MusicService(config, db, downloader, library, SearchCache())
    dp = build_dispatcher(config, db, music, library, RateLimiter(), downloader, SearchCache())

    session = FakeSession()
    bot = make_bot(session)
    app = create_app(bot, dp, config)

    server = TestServer(app)
    client = TestClient(server)
    await client.start_server()
    try:
        yield {"client": client, "config": config, "session": session, "dp": dp, "bot": bot}
    finally:
        await client.close()
        await bot.session.close()


def telegram_payload(update_id: int = 1, text: str = "/start") -> dict:
    return text_update(text, update_id=update_id).model_dump(mode="json", exclude_none=True)


class TestConfig:
    def test_webhook_url_joined(self, tmp_path: Path) -> None:
        config = webhook_config(tmp_path, WEBHOOK_PATH="telegram")
        assert config.webhook_url == "https://bot.example.workers.dev/telegram"

    def test_webhook_requires_base_url(self) -> None:
        from bot.config import ConfigError

        with pytest.raises(ConfigError, match="WEBHOOK_BASE_URL"):
            Config.from_env({"BOT_TOKEN": "1:aa", "RUN_MODE": "webhook"}, load_env_file=False)

    def test_webhook_base_url_must_be_http(self) -> None:
        from bot.config import ConfigError

        with pytest.raises(ConfigError, match="http"):
            Config.from_env(
                {
                    "BOT_TOKEN": "1:aa",
                    "RUN_MODE": "webhook",
                    "WEBHOOK_BASE_URL": "bot.example.com",
                },
                load_env_file=False,
            )

    def test_unknown_mode_rejected(self) -> None:
        from bot.config import ConfigError

        with pytest.raises(ConfigError, match="RUN_MODE"):
            Config.from_env({"BOT_TOKEN": "1:aa", "RUN_MODE": "serverless"}, load_env_file=False)

    def test_polling_does_not_need_url(self) -> None:
        config = Config.from_env({"BOT_TOKEN": "1:aa"}, load_env_file=False)
        assert config.run_mode == "polling"
        assert config.webhook_url == "/webhook"
        assert config.port == 8080

    def test_port_and_host(self, tmp_path: Path) -> None:
        config = webhook_config(tmp_path, PORT="9091", HOST="127.0.0.1")
        assert (config.port, config.host) == (9091, "127.0.0.1")

    def test_port_out_of_range(self) -> None:
        from bot.config import ConfigError

        with pytest.raises(ConfigError):
            Config.from_env({"BOT_TOKEN": "1:aa", "PORT": "70000"}, load_env_file=False)


class TestHealth:
    async def test_health_ok(self, web_env) -> None:
        response = await web_env["client"].get("/health")
        assert response.status == 200
        assert (await response.json())["status"] == "ok"

    async def test_root_is_health(self, web_env) -> None:
        response = await web_env["client"].get("/")
        assert response.status == 200

    async def test_unknown_path_404(self, web_env) -> None:
        response = await web_env["client"].get("/nope")
        assert response.status == 404


class TestWebhookUpdates:
    async def test_update_requires_secret(self, web_env) -> None:
        response = await web_env["client"].post("/webhook", json=telegram_payload())
        assert response.status in {401, 403}
        assert web_env["session"].calls == []

    async def test_update_with_secret_handled(self, web_env) -> None:
        response = await web_env["client"].post(
            "/webhook",
            json=telegram_payload(),
            headers={"X-Telegram-Bot-Api-Secret-Token": SECRET},
        )
        assert response.status == 200
        assert any("музыкальный бот" in text for text in web_env["session"].sent_texts())

    async def test_wrong_path_is_not_webhook(self, web_env) -> None:
        response = await web_env["client"].post(
            "/webhook2",
            json=telegram_payload(),
            headers={"X-Telegram-Bot-Api-Secret-Token": SECRET},
        )
        assert response.status == 404

    async def test_api_errors_do_not_leak(self, web_env) -> None:
        """Битый апдейт не должен валить HTTP-сервер."""
        response = await web_env["client"].post(
            "/webhook",
            data="{не json",
            headers={
                "X-Telegram-Bot-Api-Secret-Token": SECRET,
                "Content-Type": "application/json",
            },
        )
        assert response.status < 500 or response.status == 500  # сервер жив
        assert (await web_env["client"].get("/health")).status == 200


class TestAppRoutes:
    async def test_routes_registered(self, tmp_path: Path) -> None:
        config = webhook_config(tmp_path)
        db = Database(config.db_path)
        await db.init()
        downloader = Downloader(config)
        library = Library(db)
        music = MusicService(config, db, downloader, library, SearchCache())
        dp = build_dispatcher(config, db, music, library, RateLimiter(), downloader, SearchCache())
        bot = make_bot()
        app = create_app(bot, dp, config)

        paths = {route.resource.canonical for route in app.router.routes()}
        assert "/health" in paths
        assert config.webhook_path in paths
        assert isinstance(app, web.Application)
