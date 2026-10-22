"""Скачивание по ссылке и поиск по названию."""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from bot.config import Config
from bot.handlers.shared import chat_id_of, download_with_feedback
from bot.keyboards import MENU_TEXTS, back_to_menu, search_results
from bot.services.downloader import DownloadError
from bot.services.limiter import RateLimiter
from bot.services.music import MusicService
from bot.texts import DRM_MESSAGE, search_results_text
from bot.utils import drm_service, extract_url, truncate

logger = logging.getLogger(__name__)
router = Router(name="music")

MAX_QUERY_LENGTH = 200


def _menu_excluded(message: Message) -> bool:
    """True для кнопок меню и команд — их обрабатывают другие роутеры."""
    text = (message.text or "").strip()
    return text in MENU_TEXTS or text.startswith("/")


async def run_search(
    message: Message,
    query: str,
    *,
    music: MusicService,
) -> None:
    """Ищет треки и присылает список с кнопками-номерами."""
    query = truncate(query.strip(), MAX_QUERY_LENGTH, suffix="")
    if len(query) < 2:
        await message.answer("Напиши хотя бы два символа — так найдётся больше 🎵")
        return

    try:
        token, items = await music.search(message.from_user.id, query)
    except DownloadError as exc:
        text = f"😔 {exc.user_message}"
        if exc.hint:
            text += f"\n\n<i>{exc.hint}</i>"
        await message.answer(text)
        return
    except Exception:  # noqa: BLE001
        logger.exception("Поиск упал: %r", query)
        await message.answer("😔 Поиск временно не работает. Попробуй позже.")
        return

    if not items:
        await message.answer(search_results_text(query, items), reply_markup=back_to_menu())
        return

    await message.answer(
        search_results_text(query, items),
        reply_markup=search_results(token, len(items)),
        disable_web_page_preview=True,
    )


@router.message(Command("search"))
async def cmd_search(message: Message, music: MusicService) -> None:
    parts = (message.text or "").split(maxsplit=1)
    query = parts[1].strip() if len(parts) > 1 else ""
    if not query:
        await message.answer(
            "🔍 Пришли название песни или исполнителя.\n"
            "Например: <code>/search ленинград финт</code>"
        )
        return
    await run_search(message, query, music=music)


@router.message(F.text == "🔍 Поиск")
async def btn_search(message: Message) -> None:
    await message.answer(
        "🔍 Напиши название трека или исполнителя — найду до 5 вариантов.\n\n"
        "Хочешь искать только в SoundCloud? Добавь префикс <code>sc:</code>\n"
        "Например: <code>sc:lofi hip hop</code>"
    )


@router.callback_query(F.data.startswith("dl:"))
async def cb_download(callback: CallbackQuery, music: MusicService, limiter: RateLimiter) -> None:
    """Кнопка-номер под результатами поиска."""
    try:
        _, token, index_raw = (callback.data or "").split(":", 2)
        index = int(index_raw)
    except ValueError:
        await callback.answer("Некорректная кнопка 🙈", show_alert=True)
        return

    entry = music.cache.get(callback.from_user.id, token)
    if entry is None or not 0 <= index < len(entry.items):
        await callback.answer("Результаты устарели — поищи заново 🔄", show_alert=True)
        return

    meta = entry.items[index]
    await callback.answer("Качаю…")
    chat_id = chat_id_of(callback)
    await download_with_feedback(
        callback.bot,
        chat_id,
        callback.from_user.id,
        meta.url,
        music=music,
        limiter=limiter,
    )


@router.message(F.text, ~F.text.startswith("/"))
async def on_text(
    message: Message, music: MusicService, limiter: RateLimiter, config: Config
) -> None:
    """Ссылка → скачиваем. Любой другой текст → поиск."""
    text = (message.text or "").strip()
    if _menu_excluded(message):
        return  # защитная ветка: кнопки меню обрабатываются раньше
    if not text:
        return

    url = extract_url(text)
    if url:
        service = drm_service(url)
        if service:
            await message.answer(DRM_MESSAGE.format(service=service))
            return
        await download_with_feedback(
            message.bot,
            message.chat.id,
            message.from_user.id,
            url,
            music=music,
            limiter=limiter,
        )
        return

    await run_search(message, text, music=music)
