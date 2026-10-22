"""Логика библиотеки: сохранение треков, страницы и рандомайзер без повторов."""

from __future__ import annotations

import random
from collections import defaultdict, deque

from bot.db import Database, Track
from bot.services.downloader import DownloadedTrack
from bot.utils import normalize_url

DEFAULT_HISTORY = 10


class Library:
    def __init__(self, db: Database, history_size: int = DEFAULT_HISTORY) -> None:
        self.db = db
        self._history_size = max(0, history_size)
        # последние проигранные треки по пользователям — чтобы рандом не повторялся
        self._history: dict[int, deque[int]] = defaultdict(lambda: deque(maxlen=self._history_size))

    def note_played(self, user_id: int, track_id: int) -> None:
        history = self._history[user_id]
        if history and history[-1] == track_id:
            return  # не дублируем один и тот же трек в истории
        history.append(track_id)

    def recent_ids(self, user_id: int) -> list[int]:
        return list(self._history[user_id])

    async def save_download(self, user_id: int, downloaded: DownloadedTrack) -> Track:
        meta = downloaded.meta
        return await self.db.save_track(
            user_id=user_id,
            url=normalize_url(meta.url),
            title=meta.title,
            performer=meta.performer,
            duration=meta.duration,
            source=meta.source,
        )

    async def page(
        self,
        user_id: int,
        page: int,
        per_page: int,
        *,
        favorites_only: bool = False,
    ) -> tuple[list[Track], int, int]:
        """Возвращает (треки страницы, номер страницы, всего страниц). 1-based."""
        total = await self.db.count_tracks(user_id, favorites_only=favorites_only)
        total_pages = max(1, (total + per_page - 1) // per_page)
        page = min(max(1, page), total_pages)
        tracks = await self.db.list_tracks(
            user_id,
            offset=(page - 1) * per_page,
            limit=per_page,
            favorites_only=favorites_only,
        )
        return tracks, page, total_pages

    async def pick_random(self, user_id: int, *, favorites_only: bool = False) -> Track | None:
        """Случайный трек с попыткой не повторить последние проигранные."""
        exclude = self.recent_ids(user_id)
        track = await self.db.random_track(
            user_id, favorites_only=favorites_only, exclude_ids=exclude
        )
        if track is None:
            # история съела всю библиотеку — сбрасываем и берём любого
            self._history[user_id].clear()
            track = await self.db.random_track(user_id, favorites_only=favorites_only)
        if track is not None:
            self.note_played(user_id, track.id)
        return track

    async def random_batch(
        self, user_id: int, limit: int = 5, *, favorites_only: bool = False
    ) -> list[Track]:
        tracks = await self.db.random_tracks(user_id, limit=limit, favorites_only=favorites_only)
        random.shuffle(tracks)
        return tracks
