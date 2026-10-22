"""Сценарии «скачать / найти / прислать» — общая логика для всех хендлеров."""

from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, Message

from bot.config import Config
from bot.db import Database, Track
from bot.keyboards import player
from bot.services.cache import SearchCache
from bot.services.delivery import (
    meta_to_audio_kwargs,
    run_with_progress,
    send_audio,
    track_to_audio_kwargs,
)
from bot.services.downloader import DownloadedTrack, Downloader, Progress, TrackMeta
from bot.services.library import Library
from bot.utils import normalize_url

logger = logging.getLogger(__name__)


class MusicService:
    def __init__(
        self,
        config: Config,
        db: Database,
        downloader: Downloader,
        library: Library,
        cache: SearchCache,
    ) -> None:
        self.config = config
        self.db = db
        self.downloader = downloader
        self.library = library
        self.cache = cache

    # ------------------------------------------------------------------ поиск

    async def search(self, user_id: int, query: str) -> tuple[str, list[TrackMeta]]:
        items = await self.downloader.search(query, self.config.search_results)
        token = self.cache.put(user_id, items)
        return token, items

    # ------------------------------------------------------------- загрузка

    async def download_and_send(
        self,
        bot: Bot,
        chat_id: int,
        user_id: int,
        url: str,
        *,
        reply_markup: InlineKeyboardMarkup | None = None,
    ) -> tuple[Track, bool]:
        """Скачивает по ссылке и отправляет аудио.

        Возвращает (трек, из_кэша). Если трек уже лежит в библиотеке
        с известным ``file_id`` — ничего не скачиваем повторно.
        """
        cached = await self.db.find_by_url(user_id, normalize_url(url))
        if cached is not None and cached.file_id:
            await send_audio(
                bot,
                chat_id,
                **track_to_audio_kwargs(cached),
                file_id=cached.file_id,
                caption="📚 Из твоей библиотеки",
                reply_markup=reply_markup or player(cached),
            )
            self.library.note_played(user_id, cached.id)
            return cached, True

        progress = Progress()
        downloaded = await run_with_progress(
            bot,
            chat_id,
            "🔎 Получаю информацию о треке…",
            self.downloader.download(url, progress),
            progress,
        )
        try:
            track = await self.library.save_download(user_id, downloaded)
            message = await self._send_downloaded(bot, chat_id, downloaded, track, reply_markup)
            track = await self._remember_file(track, message)
            self.library.note_played(user_id, track.id)
            return track, False
        finally:
            downloaded.cleanup()

    async def _send_downloaded(
        self,
        bot: Bot,
        chat_id: int,
        downloaded: DownloadedTrack,
        track: Track,
        reply_markup: InlineKeyboardMarkup | None,
    ) -> Message:
        return await send_audio(
            bot,
            chat_id,
            **meta_to_audio_kwargs(downloaded.meta),
            file_path=downloaded.file_path,
            thumbnail=downloaded.thumbnail_path,
            reply_markup=reply_markup or player(track),
        )

    async def _remember_file(self, track: Track, message: Message) -> Track:
        """Сохраняет file_id, чтобы в следующий раз отдавать трек мгновенно."""
        audio = message.audio
        if audio is None:
            return track
        try:
            await self.db.update_telegram_file(
                track.id,
                file_id=audio.file_id,
                file_unique_id=audio.file_unique_id,
                file_size=audio.file_size,
            )
        except Exception:  # noqa: BLE001 - кэш не критичен
            logger.exception("Не удалось сохранить file_id для трека %s", track.id)
            return track
        refreshed = await self.db.get_track(track.id, track.user_id)
        return refreshed or track

    # --------------------------------------------------------- из библиотеки

    async def send_saved(
        self,
        bot: Bot,
        chat_id: int,
        track: Track,
        *,
        reply_markup: InlineKeyboardMarkup | None = None,
    ) -> Track:
        """Присылает сохранённый трек, дозагружая файл при необходимости."""
        if track.file_id:
            await send_audio(
                bot,
                chat_id,
                **track_to_audio_kwargs(track),
                file_id=track.file_id,
                reply_markup=reply_markup or player(track),
            )
            self.library.note_played(track.user_id, track.id)
            return track

        progress = Progress()
        downloaded = await run_with_progress(
            bot,
            chat_id,
            "🔎 Файла нет в кэше Telegram — качаю заново…",
            self.downloader.download(track.url, progress),
            progress,
        )
        try:
            message = await self._send_downloaded(bot, chat_id, downloaded, track, reply_markup)
            refreshed = await self._remember_file(track, message)
            self.library.note_played(track.user_id, track.id)
            return refreshed
        finally:
            downloaded.cleanup()
