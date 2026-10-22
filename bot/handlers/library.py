"""Библиотека, избранное, удаление и статистика."""

from __future__ import annotations

import logging
from contextlib import suppress

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from bot.handlers.shared import chat_id_of, send_saved_with_feedback
from bot.keyboards import back_to_menu, player
from bot.keyboards import library as library_kb
from bot.services.library import Library
from bot.services.limiter import RateLimiter
from bot.services.music import MusicService
from bot.texts import library_text, stats_text

logger = logging.getLogger(__name__)
router = Router(name="library")

PER_PAGE = 5


async def show_library(
    message: Message,
    *,
    library: Library,
    page: int = 1,
    favorites_only: bool = False,
    edit: bool = False,
    callback: CallbackQuery | None = None,
) -> None:
    user_id = message.from_user.id
    tracks, page, total_pages = await library.page(
        user_id, page, PER_PAGE, favorites_only=favorites_only
    )
    total = await library.db.count_tracks(user_id, favorites_only=favorites_only)
    text = library_text(tracks, page, total_pages, total, favorites_only=favorites_only)
    markup = (
        library_kb(tracks, page, total_pages, favorites_only=favorites_only)
        if tracks
        else back_to_menu()
    )

    if edit and callback is not None and isinstance(callback.message, Message):
        try:
            await callback.message.edit_text(
                text, reply_markup=markup, disable_web_page_preview=True
            )
            return
        except Exception:  # noqa: BLE001 - «message is not modified» и т.п.
            pass
    await message.answer(text, reply_markup=markup, disable_web_page_preview=True)


@router.message(Command("library"))
async def cmd_library(message: Message, library: Library) -> None:
    parts = (message.text or "").split(maxsplit=1)
    page = 1
    if len(parts) > 1 and parts[1].strip().isdigit():
        page = int(parts[1].strip())
    await show_library(message, library=library, page=page)


@router.message(F.text == "📚 Библиотека")
async def btn_library(message: Message, library: Library) -> None:
    await show_library(message, library=library)


@router.message(Command("favorites"))
@router.message(F.text == "⭐ Избранное")
async def cmd_favorites(message: Message, library: Library) -> None:
    await show_library(message, library=library, favorites_only=True)


@router.message(Command("stats"))
async def cmd_stats(message: Message, library: Library) -> None:
    stats = await library.db.stats(message.from_user.id)
    await message.answer(stats_text(**stats))


@router.callback_query(F.data.startswith("lib:"))
async def cb_library(callback: CallbackQuery, library: Library) -> None:
    try:
        _, page_raw, fav_raw = (callback.data or "").split(":")
        page = int(page_raw)
        favorites_only = fav_raw == "1"
    except ValueError:
        await callback.answer("Некорректная страница 🙈", show_alert=True)
        return
    await callback.answer()
    if isinstance(callback.message, Message):
        await show_library(
            callback.message,
            library=library,
            page=page,
            favorites_only=favorites_only,
            edit=True,
            callback=callback,
        )


@router.callback_query(F.data.startswith("p:"))
async def cb_play(
    callback: CallbackQuery,
    library: Library,
    music: MusicService,
    limiter: RateLimiter,
) -> None:
    """Кнопка-номер в библиотеке."""
    try:
        track_id = int((callback.data or "").split(":", 1)[1])
    except (IndexError, ValueError):
        await callback.answer("Некорректная кнопка 🙈", show_alert=True)
        return

    track = await library.db.get_track(track_id, callback.from_user.id)
    if track is None:
        await callback.answer("Трек не найден — возможно, удалён.", show_alert=True)
        return

    await callback.answer("Отправляю…")
    chat_id = chat_id_of(callback)
    await send_saved_with_feedback(
        callback.bot,
        chat_id,
        callback.from_user.id,
        track,
        music=music,
        limiter=limiter,
    )


@router.callback_query(F.data.startswith("fav:"))
async def cb_favorite(callback: CallbackQuery, library: Library) -> None:
    try:
        track_id = int((callback.data or "").split(":", 1)[1])
    except (IndexError, ValueError):
        await callback.answer("Некорректная кнопка 🙈", show_alert=True)
        return

    is_favorite = await library.db.set_favorite(track_id, callback.from_user.id)
    if is_favorite is None:
        await callback.answer("Трек не найден.", show_alert=True)
        return

    await callback.answer("⭐ В избранном" if is_favorite else "Убрал из избранного")
    track = await library.db.get_track(track_id, callback.from_user.id)
    if track is not None and isinstance(callback.message, Message):
        with suppress(Exception):  # сообщение могло устареть
            await callback.message.edit_reply_markup(reply_markup=player(track))


@router.callback_query(F.data.startswith("del:"))
async def cb_delete(callback: CallbackQuery, library: Library) -> None:
    try:
        track_id = int((callback.data or "").split(":", 1)[1])
    except (IndexError, ValueError):
        await callback.answer("Некорректная кнопка 🙈", show_alert=True)
        return

    deleted = await library.db.delete_track(track_id, callback.from_user.id)
    if not deleted:
        await callback.answer("Трек уже удалён.", show_alert=True)
        return
    await callback.answer("🗑 Удалено из библиотеки")
    if isinstance(callback.message, Message):
        with suppress(Exception):  # сообщение могло устареть
            await callback.message.edit_reply_markup(reply_markup=back_to_menu())
