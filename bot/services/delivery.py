"""Отправка треков в Telegram и «живой» прогресс загрузки."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable
from contextlib import suppress
from pathlib import Path
from typing import TypeVar

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.types import FSInputFile, InlineKeyboardMarkup, Message

from bot.db import Track
from bot.services.downloader import Progress, TrackMeta

logger = logging.getLogger(__name__)

T = TypeVar("T")


async def run_with_progress(
    bot: Bot,
    chat_id: int,
    placeholder: str,
    action: Awaitable[T],
    progress: Progress,
    *,
    interval: float = 1.5,
) -> T:
    """Запускает тяжёлую операцию и обновляет сообщение-прогресс.

    Сообщение-заглушка удаляется в конце: на его место придёт результат.
    """
    status = await bot.send_message(chat_id, placeholder)
    task = asyncio.ensure_future(action)
    last_text = placeholder
    try:
        while not task.done():
            done, _ = await asyncio.wait({task}, timeout=interval)
            if done:
                break
            text = progress.as_text()
            if text == last_text:
                continue
            try:
                await bot.edit_message_text(
                    chat_id=chat_id, message_id=status.message_id, text=text
                )
                last_text = text
            except TelegramRetryAfter as exc:  # мягко ждём лимит
                await asyncio.sleep(min(exc.retry_after, 5))
            except TelegramBadRequest:
                pass  # «message is not modified» и прочее — не критично
        return await task
    finally:
        if not task.done():
            task.cancel()
            with suppress(BaseException):
                await task
        with suppress(Exception):
            await bot.delete_message(chat_id, status.message_id)


async def send_audio(
    bot: Bot,
    chat_id: int,
    *,
    title: str,
    performer: str = "",
    duration: int | None = None,
    file_path: Path | None = None,
    file_id: str | None = None,
    thumbnail: Path | None = None,
    caption: str | None = None,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> Message:
    """Отправляет mp3. Если известен ``file_id`` — переиспользует его (быстро и без трафика)."""
    audio = file_id if file_id else FSInputFile(file_path) if file_path else None
    if audio is None:
        raise ValueError("Нужен либо file_path, либо file_id")

    kwargs: dict = {
        "chat_id": chat_id,
        "audio": audio,
        "title": title[:64] or "Без названия",
        "performer": (performer or "")[:64],
        "duration": duration or 0,
        "reply_markup": reply_markup,
    }
    if caption:
        kwargs["caption"] = caption
    if thumbnail is not None and not file_id and await asyncio.to_thread(thumbnail.exists):
        kwargs["thumbnail"] = FSInputFile(thumbnail)

    return await bot.send_audio(**kwargs)


def track_to_audio_kwargs(track: Track) -> dict:
    """Общие поля для повторной отправки из библиотеки."""
    return {
        "title": track.title,
        "performer": track.performer,
        "duration": track.duration,
    }


def meta_to_audio_kwargs(meta: TrackMeta) -> dict:
    return {
        "title": meta.title,
        "performer": meta.performer,
        "duration": meta.duration,
    }
