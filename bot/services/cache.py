"""Кэш результатов поиска: callback_data в Telegram ограничена 64 байтами,
поэтому вместо ссылок передаём короткий токен."""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass

from bot.services.downloader import TrackMeta

TTL_SECONDS = 60 * 60


@dataclass(slots=True)
class CachedResults:
    user_id: int
    items: list[TrackMeta]
    created_at: float


class SearchCache:
    def __init__(self, ttl: int = TTL_SECONDS, max_entries: int = 5000) -> None:
        self._ttl = ttl
        self._max_entries = max_entries
        self._items: dict[str, CachedResults] = {}

    def put(self, user_id: int, items: list[TrackMeta]) -> str:
        self._evict_expired()
        token = secrets.token_urlsafe(6)
        self._items[token] = CachedResults(
            user_id=user_id, items=list(items), created_at=time.monotonic()
        )
        if len(self._items) > self._max_entries:
            oldest = min(self._items, key=lambda key: self._items[key].created_at)
            self._items.pop(oldest, None)
        return token

    def get(self, user_id: int, token: str) -> CachedResults | None:
        entry = self._items.get(token)
        if entry is None:
            return None
        if entry.user_id != user_id:
            return None
        if time.monotonic() - entry.created_at > self._ttl:
            self._items.pop(token, None)
            return None
        return entry

    def _evict_expired(self) -> None:
        now = time.monotonic()
        expired = [key for key, value in self._items.items() if now - value.created_at > self._ttl]
        for key in expired:
            self._items.pop(key, None)

    def __len__(self) -> int:
        return len(self._items)
