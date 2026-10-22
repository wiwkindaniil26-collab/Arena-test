"""Рандомайзер: случайный трек из библиотеки и из избранного."""

from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from bot.handlers.shared import chat_id_of, send_saved_with_feedback
from bot.services.limiter import RateLimiter
from bot.services.music import MusicService

logger = logging.getLogger(__name__)
router = Router(name="random")

EMPTY_TEXT = {
    False: (
        "🎲 Библиотека пуста — нечего включать.\n\n"
        "Пришли ссылку на трек или найди его по названию, и рандом сразу заработает."
    ),
    True: (
        "⭐ В избранном пока пусто.\n\n"
        "Нажми ⭐ под присланным треком — и он попадёт в случайную подборку."
    ),
}


async def send_random_track(
    bot: Bot,
    chat_id: int,
    user_id: int,
    *,
    music: MusicService,
    limiter: RateLimiter,
    favorites_only: bool = False,
) -> None:
    total = await music.db.count_tracks(user_id, favorites_only=favorites_only)
    if total == 0:
        await bot.send_message(chat_id, EMPTY_TEXT[favorites_only])
        return

    if not limiter.check(user_id):
        wait = limiter.retry_after(user_id)
        await bot.send_message(
            chat_id, f"⏳ Ты уже много всего включил. Подожди ~{wait} с и жми 🎲 снова."
        )
        return

    track = await music.library.pick_random(user_id, favorites_only=favorites_only)
    if track is None:
        await bot.send_message(chat_id, EMPTY_TEXT[favorites_only])
        return

    await send_saved_with_feedback(bot, chat_id, user_id, track, music=music, limiter=limiter)


@router.message(Command("random"))
@router.message(F.text == "🎲 Случайный")
async def cmd_random(message: Message, music: MusicService, limiter: RateLimiter) -> None:
    await send_random_track(
        message.bot,
        message.chat.id,
        message.from_user.id,
        music=music,
        limiter=limiter,
    )


@router.message(Command("random_fav"))
async def cmd_random_fav(message: Message, music: MusicService, limiter: RateLimiter) -> None:
    await send_random_track(
        message.bot,
        message.chat.id,
        message.from_user.id,
        music=music,
        limiter=limiter,
        favorites_only=True,
    )


@router.callback_query(F.data.startswith("rnd:"))
async def cb_random(callback: CallbackQuery, music: MusicService, limiter: RateLimiter) -> None:
    favorites_only = (callback.data or "").endswith(":1")
    await callback.answer("Кручу барабан 🎲")
    chat_id = chat_id_of(callback)
    await send_random_track(
        callback.bot,
        chat_id,
        callback.from_user.id,
        music=music,
        limiter=limiter,
        favorites_only=favorites_only,
    )
