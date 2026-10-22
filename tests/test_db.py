from __future__ import annotations

from pathlib import Path

import pytest

from bot.db import Database

USER = 111
OTHER = 222


@pytest.fixture
async def db(tmp_path: Path) -> Database:
    database = Database(tmp_path / "test.db")
    await database.init()
    return database


async def add(database: Database, url: str = "https://youtube.com/watch?v=1", **kwargs) -> None:
    params = {
        "user_id": USER,
        "url": url,
        "title": "Song",
        "performer": "Artist",
        "duration": 200,
    }
    params.update(kwargs)
    await database.save_track(**params)


class TestSaveTrack:
    async def test_creates_row(self, db: Database) -> None:
        track = await db.save_track(
            user_id=USER, url="https://a/1", title="T", performer="P", duration=10
        )
        assert track.id > 0
        assert track.title == "T"
        assert track.is_favorite is False
        assert track.created_at

    async def test_duplicate_updates_instead_of_inserting(self, db: Database) -> None:
        await add(db, title="Old")
        await add(db, title="New", performer="P2")
        tracks = await db.list_tracks(USER)
        assert len(tracks) == 1
        assert tracks[0].title == "New"
        assert tracks[0].performer == "P2"

    async def test_duplicate_keeps_file_id(self, db: Database) -> None:
        track = await db.save_track(user_id=USER, url="https://a/1", title="T")
        await db.update_telegram_file(track.id, file_id="FILE", file_size=100)
        await db.save_track(user_id=USER, url="https://a/1", title="T2")
        refreshed = await db.get_track(track.id, USER)
        assert refreshed is not None
        assert refreshed.file_id == "FILE"
        assert refreshed.title == "T2"

    async def test_same_url_different_users(self, db: Database) -> None:
        await add(db, url="https://a/1")
        await add(db, url="https://a/1", user_id=OTHER)
        assert await db.count_tracks(USER) == 1
        assert await db.count_tracks(OTHER) == 1


class TestReadWrite:
    async def test_track_isolation(self, db: Database) -> None:
        await add(db, url="https://a/1")
        assert await db.get_track(1, OTHER) is None
        assert await db.delete_track(1, OTHER) is False

    async def test_find_by_url(self, db: Database) -> None:
        await add(db, url="https://a/1")
        assert (await db.find_by_url(USER, "https://a/1")).title == "Song"
        assert await db.find_by_url(USER, "https://a/2") is None

    async def test_favorites_toggle(self, db: Database) -> None:
        await add(db, url="https://a/1")
        track_id = 1
        assert await db.set_favorite(track_id, USER) is True
        assert await db.count_tracks(USER, favorites_only=True) == 1
        assert await db.set_favorite(track_id, USER) is False
        assert await db.count_tracks(USER, favorites_only=True) == 0
        assert await db.set_favorite(track_id, OTHER) is None

    async def test_favorites_set_explicitly(self, db: Database) -> None:
        await add(db, url="https://a/1")
        assert await db.set_favorite(1, USER, value=True) is True
        assert await db.set_favorite(1, USER, value=True) is True

    async def test_update_file(self, db: Database) -> None:
        track = await db.save_track(user_id=USER, url="https://a/1", title="T")
        await db.update_telegram_file(track.id, file_id="F", file_unique_id="U", file_size=1234)
        refreshed = await db.get_track(track.id, USER)
        assert refreshed is not None
        assert (refreshed.file_id, refreshed.file_unique_id, refreshed.file_size) == (
            "F",
            "U",
            1234,
        )

    async def test_delete(self, db: Database) -> None:
        await add(db, url="https://a/1")
        assert await db.delete_track(1, USER) is True
        assert await db.count_tracks(USER) == 0


class TestRandom:
    async def test_random_returns_member(self, db: Database) -> None:
        for index in range(5):
            await add(db, url=f"https://a/{index}")
        track = await db.random_track(USER)
        assert track is not None
        assert track.url.startswith("https://a/")

    async def test_random_empty(self, db: Database) -> None:
        assert await db.random_track(USER) is None

    async def test_random_excludes_ids(self, db: Database) -> None:
        for index in range(5):
            await add(db, url=f"https://a/{index}")
        ids = [track.id for track in await db.list_tracks(USER, limit=4)]
        track = await db.random_track(USER, exclude_ids=ids)
        assert track is not None
        assert track.id not in ids

    async def test_random_excludes_everything(self, db: Database) -> None:
        await add(db, url="https://a/1")
        assert await db.random_track(USER, exclude_ids=[1]) is None

    async def test_random_favorites_only(self, db: Database) -> None:
        await add(db, url="https://a/1")
        await add(db, url="https://a/2")
        await db.set_favorite(2, USER, value=True)
        for _ in range(5):
            track = await db.random_track(USER, favorites_only=True)
            assert track is not None
            assert track.id == 2

    async def test_random_tracks_limit(self, db: Database) -> None:
        for index in range(4):
            await add(db, url=f"https://a/{index}")
        tracks = await db.random_tracks(USER, limit=2)
        assert len(tracks) == 2
        assert len({track.id for track in tracks}) == 2


class TestPagingAndStats:
    async def test_ordering_is_newest_first(self, db: Database) -> None:
        for index in range(3):
            await add(db, url=f"https://a/{index}")
        tracks = await db.list_tracks(USER)
        assert [track.url for track in tracks] == [
            "https://a/2",
            "https://a/1",
            "https://a/0",
        ]

    async def test_offset_limit(self, db: Database) -> None:
        for index in range(5):
            await add(db, url=f"https://a/{index}")
        page = await db.list_tracks(USER, offset=2, limit=2)
        assert [track.url for track in page] == ["https://a/2", "https://a/1"]

    async def test_stats(self, db: Database) -> None:
        await add(db, url="https://a/1", duration=100)
        await add(db, url="https://a/2", duration=50)
        await db.set_favorite(2, USER, value=True)
        stats = await db.stats(USER)
        assert stats == {"total": 2, "favorites": 1, "duration": 150}

    async def test_stats_empty(self, db: Database) -> None:
        assert await db.stats(USER) == {"total": 0, "favorites": 0, "duration": 0}
