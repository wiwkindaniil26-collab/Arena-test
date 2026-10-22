"""Повторяющиеся куски хендлеров: скачивание с обработкой ошибок и лимитов."""

from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from bot.db import Track
from bot.services.downloader import DownloadError
from bot.services.limiter import RateLimiter
from bot.services.music import MusicService

logger = logging.getLogger(__name__)


def chat_id_of(callback: CallbackQuery) -> int:
    """Чат, куда прислать результат: сообщение с кнопкой или личка пользователя."""
    if isinstance(callback.message, Message):
        return callback.message.chat.id
    return callback.from_user.id


async def download_with_feedback(
    bot: Bot,
    chat_id: int,
    user_id: int,
    url: str,
    *,
    music: MusicService,
    limiter: RateLimiter,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> Track | None:
    """Скачивает трек и сообщает пользователю о любых проблемах.

    Возвращает трек или ``None``, если не вышло / сработал антифлуд.
    """
    if not limiter.check(user_id):
        wait = limiter.retry_after(user_id)
        await bot.send_message(
            chat_id,
            f"⏳ Слишком много загрузок подряд. Подожди ~{wait} с и попробуй снова.",
        )
        return None

    try:
        track, _ = await music.download_and_send(
            bot, chat_id, user_id, url, reply_markup=reply_markup
        )
        return track
    except DownloadError as exc:
        text = f"😔 {exc.user_message}"
        if exc.hint:
            text += f"\n\n<i>{exc.hint}</i>"
        await bot.send_message(chat_id, text)
    except Exception:  # noqa: BLE001 - бот не должен падать из-за одного трека
        logger.exception("Ошибка при скачивании %s (user_id=%s)", url, user_id)
        await bot.send_message(
            chat_id,
            "😔 Что-то пошло не так при скачивании. Попробуй ещё раз или пришли другую ссылку.",
        )
    return None


async def send_saved_with_feedback(
    bot: Bot,
    chat_id: int,
    user_id: int,
    track: Track,
    *,
    music: MusicService,
    limiter: RateLimiter,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> Track | None:
    """Присылает трек из библиотеки, обрабатывая возможные ошибки."""
    if not track.file_id and not limiter.check(user_id):
        wait = limiter.retry_after(user_id)
        await bot.send_message(chat_id, f"⏳ Слишком много загрузок подряд. Подожди ~{wait} с.")
        return None
    try:
        return await music.send_saved(bot, chat_id, track, reply_markup=reply_markup)
    except DownloadError as exc:
        text = f"😔 {exc.user_message}"
        if exc.hint:
            text += f"\n\n<i>{exc.hint}</i>"
        await bot.send_message(chat_id, text)
    except Exception:  # noqa: BLE001
        logger.exception("Ошибка при отправке трека %s (user_id=%s)", track.id, user_id)
        await bot.send_message(chat_id, "😔 Не удалось прислать этот трек. Попробуй другой.")
    return None
