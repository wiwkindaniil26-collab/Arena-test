"""SQLite-хранилище библиотеки пользователей.

Одна строка = один трек, добавленный конкретным пользователем.
Повторная ссылка того же пользователя не дублируется, а обновляется
(например, когда мы получили свежий ``file_id`` из Telegram).
"""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS tracks (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id        INTEGER NOT NULL,
    url            TEXT    NOT NULL,
    title          TEXT    NOT NULL,
    performer      TEXT    NOT NULL DEFAULT '',
    duration       INTEGER,
    source         TEXT    NOT NULL DEFAULT 'link',
    file_id        TEXT,
    file_unique_id TEXT,
    file_size      INTEGER,
    is_favorite    INTEGER NOT NULL DEFAULT 0,
    created_at     TEXT    NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_tracks_user_url
    ON tracks (user_id, url);
CREATE INDEX IF NOT EXISTS idx_tracks_user_created
    ON tracks (user_id, created_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_tracks_user_fav
    ON tracks (user_id, is_favorite);
"""


@dataclass(slots=True, frozen=True)
class Track:
    id: int
    user_id: int
    url: str
    title: str
    performer: str
    duration: int | None
    source: str
    file_id: str | None
    file_unique_id: str | None
    file_size: int | None
    is_favorite: bool
    created_at: str

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> Track:
        return cls(
            id=row["id"],
            user_id=row["user_id"],
            url=row["url"],
            title=row["title"],
            performer=row["performer"] or "",
            duration=row["duration"],
            source=row["source"] or "link",
            file_id=row["file_id"],
            file_unique_id=row["file_unique_id"],
            file_size=row["file_size"],
            is_favorite=bool(row["is_favorite"]),
            created_at=row["created_at"],
        )


class Database:
    """Тонкая асинхронная обёртка над sqlite3.

    Соединение открывается на каждую операцию и уходит в отдельный поток,
    поэтому event loop бота не блокируется. WAL + busy_timeout позволяют
    безопасно работать при нескольких одновременных загрузках.
    """

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._initialized = False
        self._init_lock = asyncio.Lock()

    @property
    def path(self) -> Path:
        return self._path

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self._path, timeout=15)
        try:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=10000")
            conn.execute("PRAGMA foreign_keys=ON")
            yield conn
            conn.commit()
        finally:
            conn.close()

    async def init(self) -> None:
        async with self._init_lock:
            if self._initialized:
                return
            self._path.parent.mkdir(parents=True, exist_ok=True)

            def _create() -> None:
                with self._connect() as conn:
                    conn.executescript(SCHEMA)

            await asyncio.to_thread(_create)
            self._initialized = True

    async def close(self) -> None:
        """Соединения короткоживущие, закрывать нечего — метод для симметрии."""
        self._initialized = False

    async def _run(self, func, *args: Any) -> Any:
        await self.init()
        return await asyncio.to_thread(func, *args)

    # ---------------------------------------------------------------- запись

    async def save_track(
        self,
        *,
        user_id: int,
        url: str,
        title: str,
        performer: str = "",
        duration: int | None = None,
        source: str = "link",
        file_id: str | None = None,
        file_unique_id: str | None = None,
        file_size: int | None = None,
    ) -> Track:
        created_at = datetime.now(UTC).isoformat(timespec="seconds")

        def _save() -> sqlite3.Row:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO tracks (
                        user_id, url, title, performer, duration, source,
                        file_id, file_unique_id, file_size, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT (user_id, url) DO UPDATE SET
                        title          = excluded.title,
                        performer      = excluded.performer,
                        duration       = COALESCE(excluded.duration, tracks.duration),
                        source         = excluded.source,
                        file_id        = COALESCE(excluded.file_id, tracks.file_id),
                        file_unique_id = COALESCE(excluded.file_unique_id, tracks.file_unique_id),
                        file_size      = COALESCE(excluded.file_size, tracks.file_size)
                    """,
                    (
                        user_id,
                        url,
                        title,
                        performer,
                        duration,
                        source,
                        file_id,
                        file_unique_id,
                        file_size,
                        created_at,
                    ),
                )
                row = conn.execute(
                    "SELECT * FROM tracks WHERE user_id = ? AND url = ?",
                    (user_id, url),
                ).fetchone()
            assert row is not None
            return row

        return Track.from_row(await self._run(_save))

    async def update_telegram_file(
        self,
        track_id: int,
        *,
        file_id: str,
        file_unique_id: str | None = None,
        file_size: int | None = None,
    ) -> None:
        def _update() -> None:
            with self._connect() as conn:
                conn.execute(
                    """
                    UPDATE tracks
                       SET file_id = ?, file_unique_id = COALESCE(?, file_unique_id),
                           file_size = COALESCE(?, file_size)
                     WHERE id = ?
                    """,
                    (file_id, file_unique_id, file_size, track_id),
                )

        await self._run(_update)

    async def set_favorite(
        self, track_id: int, user_id: int, value: bool | None = None
    ) -> bool | None:
        """Ставит/снимает лайк. ``value=None`` переключает. None — трека нет."""

        def _toggle() -> bool | None:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT is_favorite FROM tracks WHERE id = ? AND user_id = ?",
                    (track_id, user_id),
                ).fetchone()
                if row is None:
                    return None
                new_value = (not bool(row["is_favorite"])) if value is None else bool(value)
                conn.execute(
                    "UPDATE tracks SET is_favorite = ? WHERE id = ? AND user_id = ?",
                    (int(new_value), track_id, user_id),
                )
            return new_value

        return await self._run(_toggle)

    async def delete_track(self, track_id: int, user_id: int) -> bool:
        def _delete() -> bool:
            with self._connect() as conn:
                cursor = conn.execute(
                    "DELETE FROM tracks WHERE id = ? AND user_id = ?", (track_id, user_id)
                )
                return cursor.rowcount > 0

        return await self._run(_delete)

    # --------------------------------------------------------------- чтение

    async def get_track(self, track_id: int, user_id: int) -> Track | None:
        def _get() -> sqlite3.Row | None:
            with self._connect() as conn:
                return conn.execute(
                    "SELECT * FROM tracks WHERE id = ? AND user_id = ?",
                    (track_id, user_id),
                ).fetchone()

        row = await self._run(_get)
        return Track.from_row(row) if row else None

    async def find_by_url(self, user_id: int, url: str) -> Track | None:
        def _find() -> sqlite3.Row | None:
            with self._connect() as conn:
                return conn.execute(
                    "SELECT * FROM tracks WHERE user_id = ? AND url = ?",
                    (user_id, url),
                ).fetchone()

        row = await self._run(_find)
        return Track.from_row(row) if row else None

    async def list_tracks(
        self,
        user_id: int,
        *,
        offset: int = 0,
        limit: int = 5,
        favorites_only: bool = False,
    ) -> list[Track]:
        def _list() -> list[sqlite3.Row]:
            with self._connect() as conn:
                return conn.execute(
                    """
                    SELECT * FROM tracks
                     WHERE user_id = ? AND (? = 0 OR is_favorite = 1)
                     ORDER BY created_at DESC, id DESC
                     LIMIT ? OFFSET ?
                    """,
                    (user_id, int(favorites_only), limit, offset),
                ).fetchall()

        rows: Sequence[sqlite3.Row] = await self._run(_list)
        return [Track.from_row(row) for row in rows]

    async def count_tracks(self, user_id: int, *, favorites_only: bool = False) -> int:
        def _count() -> int:
            with self._connect() as conn:
                row = conn.execute(
                    """
                    SELECT COUNT(*) AS n FROM tracks
                     WHERE user_id = ? AND (? = 0 OR is_favorite = 1)
                    """,
                    (user_id, int(favorites_only)),
                ).fetchone()
            return int(row["n"]) if row else 0

        return await self._run(_count)

    async def random_track(
        self,
        user_id: int,
        *,
        favorites_only: bool = False,
        exclude_ids: Sequence[int] = (),
    ) -> Track | None:
        """Случайный трек. ``exclude_ids`` помогает не повторяться подряд."""

        def _random() -> sqlite3.Row | None:
            ids = [int(track_id) for track_id in exclude_ids]
            placeholders = ",".join("?" for _ in ids)
            exclude_clause = f"AND id NOT IN ({placeholders})" if ids else ""
            sql = f"""
                SELECT * FROM tracks
                 WHERE user_id = ? AND (? = 0 OR is_favorite = 1) {exclude_clause}
                 ORDER BY RANDOM() LIMIT 1
            """
            params: list[Any] = [user_id, int(favorites_only), *ids]
            with self._connect() as conn:
                return conn.execute(sql, params).fetchone()

        row = await self._run(_random)
        return Track.from_row(row) if row else None

    async def random_tracks(
        self,
        user_id: int,
        *,
        limit: int = 5,
        favorites_only: bool = False,
    ) -> list[Track]:
        """Несколько случайных треков — для «перемешать» и авто-подборки."""

        def _random() -> list[sqlite3.Row]:
            with self._connect() as conn:
                return conn.execute(
                    """
                    SELECT * FROM tracks
                     WHERE user_id = ? AND (? = 0 OR is_favorite = 1)
                     ORDER BY RANDOM() LIMIT ?
                    """,
                    (user_id, int(favorites_only), max(1, limit)),
                ).fetchall()

        rows = await self._run(_random)
        return [Track.from_row(row) for row in rows]

    async def stats(self, user_id: int) -> dict[str, int]:
        def _stats() -> dict[str, int]:
            with self._connect() as conn:
                row = conn.execute(
                    """
                    SELECT COUNT(*) AS total,
                           COALESCE(SUM(is_favorite), 0) AS favorites,
                           COALESCE(SUM(duration), 0) AS duration
                      FROM tracks WHERE user_id = ?
                    """,
                    (user_id,),
                ).fetchone()
            return {
                "total": int(row["total"]),
                "favorites": int(row["favorites"]),
                "duration": int(row["duration"]),
            }

        return await self._run(_stats)
