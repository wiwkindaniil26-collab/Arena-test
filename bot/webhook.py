"""Webhook-режим для хостингов без долгоживущего polling-процесса.

Нужен там, где контейнер получает входящие HTTP-запросы: Cloudflare Containers,
PaaS, k8s. Telegram шлёт апдейты POST-запросом на публичный URL, а бот отвечает 200.
"""

from __future__ import annotations

import asyncio
import logging
import signal
from contextlib import suppress

from aiogram import Bot, Dispatcher
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

from bot.config import Config

logger = logging.getLogger(__name__)

READY_TEXT = "ok"


async def healthcheck(_: web.Request) -> web.Response:
    """Проверка живости: по ней Cloudflare понимает, что контейнер поднялся."""
    return web.json_response({"status": READY_TEXT})


def create_app(bot: Bot, dp: Dispatcher, config: Config) -> web.Application:
    """Собирает aiohttp-приложение с обработчиком апдейтов и /health."""
    app = web.Application()

    handler = SimpleRequestHandler(
        dispatcher=dp,
        bot=bot,
        # отвечаем 200 сразу: скачивание трека дольше таймаута Telegram (60 с),
        # иначе апдейт придёт повторно и трек скачается дважды
        handle_in_background=True,
        secret_token=config.webhook_secret or None,
    )
    handler.register(app, path=config.webhook_path)
    app.router.add_get("/health", healthcheck)
    app.router.add_get("/", healthcheck)

    setup_application(app, dp, bot=bot)
    return app


class _StopSignal:
    """Ставит событие по SIGTERM/SIGINT — контейнеры гасят процессы именно так."""

    def __init__(self) -> None:
        self.event = asyncio.Event()

    def install(self) -> None:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            with suppress(NotImplementedError, AttributeError, ValueError):
                loop.add_signal_handler(sig, self.event.set)

    def uninstall(self) -> None:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            with suppress(NotImplementedError, AttributeError, ValueError):
                loop.remove_signal_handler(sig)


async def serve(bot: Bot, dp: Dispatcher, config: Config) -> None:
    """Поднимает HTTP-сервер, регистрирует webhook и ждёт сигнала остановки."""
    app = create_app(bot, dp, config)

    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, host=config.host, port=config.port)
    await site.start()
    logger.info("HTTP-сервер слушает %s:%s%s", config.host, config.port, config.webhook_path)

    await bot.set_webhook(
        url=config.webhook_url,
        secret_token=config.webhook_secret or None,
        allowed_updates=dp.resolve_used_update_types(),
        drop_pending_updates=True,
    )
    logger.info("Webhook зарегистрирован: %s", config.webhook_url)

    stop = _StopSignal()
    stop.install()
    try:
        await stop.event.wait()
    finally:
        stop.uninstall()
        await runner.cleanup()
        logger.info("HTTP-сервер остановлен")
