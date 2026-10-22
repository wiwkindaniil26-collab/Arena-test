from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

import bot.services.cache as cache_module
import bot.services.limiter as limiter_module
from bot.db import Database
from bot.services.cache import SearchCache
from bot.services.downloader import TrackMeta
from bot.services.library import Library
from bot.services.limiter import RateLimiter


class TestRateLimiter:
    def test_allows_up_to_limit(self) -> None:
        limiter = RateLimiter(limit=2, window=60)
        assert limiter.check(1) is True
        assert limiter.check(1) is True
        assert limiter.check(1) is False
        assert limiter.check(2) is True  # у второго пользователя свой лимит

    def test_window_expires(self, monkeypatch: pytest.MonkeyPatch) -> None:
        now = [1000.0]
        monkeypatch.setattr(limiter_module.time, "monotonic", lambda: now[0])
        limiter = RateLimiter(limit=1, window=10)
        assert limiter.check(1) is True
        assert limiter.check(1) is False
        now[0] += 11
        assert limiter.check(1) is True

    def test_remaining_and_retry(self, monkeypatch: pytest.MonkeyPatch) -> None:
        now = [100.0]
        monkeypatch.setattr(limiter_module.time, "monotonic", lambda: now[0])
        limiter = RateLimiter(limit=1, window=30)
        assert limiter.remaining(1) == 1
        limiter.check(1)
        assert limiter.remaining(1) == 0
        now[0] += 10
        assert 0 < limiter.retry_after(1) <= 21


class TestSearchCache:
    def make_meta(self, index: int) -> TrackMeta:
        return TrackMeta(url=f"https://a/{index}", title=f"T{index}")

    def test_put_and_get(self) -> None:
        cache = SearchCache()
        token = cache.put(1, [self.make_meta(0)])
        entry = cache.get(1, token)
        assert entry is not None
        assert entry.items[0].title == "T0"

    def test_isolated_by_user(self) -> None:
        cache = SearchCache()
        token = cache.put(1, [self.make_meta(0)])
        assert cache.get(2, token) is None

    def test_expires(self, monkeypatch: pytest.MonkeyPatch) -> None:
        now = [0.0]
        monkeypatch.setattr(cache_module.time, "monotonic", lambda: now[0])
        cache = SearchCache(ttl=10)
        token = cache.put(1, [self.make_meta(0)])
        now[0] = 11
        assert cache.get(1, token) is None

    def test_capacity(self) -> None:
        cache = SearchCache(max_entries=3)
        tokens = [cache.put(1, [self.make_meta(i)]) for i in range(5)]
        assert len(cache) <= 3
        assert cache.get(1, tokens[-1]) is not None


@pytest.fixture
async def library(tmp_path: Path) -> Library:
    db = Database(tmp_path / "lib.db")
    await db.init()
    lib = Library(db, history_size=2)
    for index in range(4):
        await db.save_track(user_id=1, url=f"https://a/{index}", title=f"T{index}", duration=100)
    return lib


class TestLibrary:
    async def test_page_math(self, library: Library) -> None:
        tracks, page, total_pages = await library.page(1, 1, 2)
        assert len(tracks) == 2
        assert (page, total_pages) == (1, 2)

    async def test_page_clamped(self, library: Library) -> None:
        tracks, page, total_pages = await library.page(1, 99, 2)
        assert page == total_pages == 2
        assert len(tracks) == 2

    async def test_page_on_empty(self, library: Library) -> None:
        tracks, page, total_pages = await library.page(999, 1, 5)
        assert (tracks, page, total_pages) == ([], 1, 1)

    async def test_random_avoids_recent(self, library: Library) -> None:
        first = await library.pick_random(1)
        assert first is not None
        second = await library.pick_random(1)
        assert second is not None
        assert second.id != first.id

    async def test_history_is_bounded(self, library: Library) -> None:
        for _ in range(10):
            await library.pick_random(1)
        assert len(library.recent_ids(1)) <= 2

    async def test_history_never_empties_choice(self, library: Library) -> None:
        seen = set()
        for _ in range(20):
            track = await library.pick_random(1)
            assert track is not None
            seen.add(track.id)
        assert len(seen) == 4

    async def test_random_favorites_only_empty(self, library: Library) -> None:
        assert await library.pick_random(1, favorites_only=True) is None

    async def test_random_batch(self, library: Library) -> None:
        batch = await library.random_batch(1, limit=3)
        assert len(batch) == 3

    async def test_save_download_normalizes_url(self, library: Library) -> None:
        from bot.services.downloader import DownloadedTrack

        downloaded = DownloadedTrack(
            meta=TrackMeta(url="https://youtu.be/abc?si=share", title="Normalized"),
            file_path=Path("/tmp/none.mp3"),
        )
        track = await library.save_download(1, downloaded)
        assert track.url == "https://youtube.com/watch?v=abc"

    async def test_save_download(self, library: Library) -> None:
        from bot.services.downloader import DownloadedTrack

        downloaded = DownloadedTrack(
            meta=TrackMeta(
                url="https://new/1",
                title="Fresh",
                performer="Artist",
                duration=42,
                source="youtube",
            ),
            file_path=Path("/tmp/none.mp3"),
            file_size=1024,
        )
        track = await library.save_download(1, downloaded)
        assert track.title == "Fresh"
        assert track.source == "youtube"
        assert await library.db.count_tracks(1) == 5


class TestDownloaderStatic:
    def test_search_query_youtube_by_default(self) -> None:
        from bot.services.downloader import Downloader

        assert Downloader.build_search_query("lofi", 5) == "ytsearch5:lofi"

    def test_search_query_soundcloud(self) -> None:
        from bot.services.downloader import Downloader

        assert Downloader.build_search_query("sc:lofi hip hop", 3) == "scsearch3:lofi hip hop"

    def test_search_query_link_passthrough(self) -> None:
        from bot.services.downloader import Downloader

        link = "https://soundcloud.com/a/b"
        assert Downloader.build_search_query(link, 5) == link

    def test_search_query_yt_prefix(self) -> None:
        from bot.services.downloader import Downloader

        assert Downloader.build_search_query("yt:rock", 2) == "ytsearch2:rock"

    def test_parse_entry(self) -> None:
        from bot.services.downloader import Downloader

        meta = Downloader._parse_entry(
            {
                "webpage_url": "https://www.youtube.com/watch?v=abc",
                "title": "Daft Punk - One More Time (Official Video)",
                "duration": 320,
            }
        )
        assert meta is not None
        assert meta.performer == "Daft Punk"
        assert meta.title == "One More Time"
        assert meta.duration == 320
        assert meta.source == "youtube"

    def test_parse_entry_bare_id(self) -> None:
        from bot.services.downloader import Downloader

        meta = Downloader._parse_entry({"id": "xyz", "title": "Song"})
        assert meta is not None
        assert meta.url == "https://www.youtube.com/watch?v=xyz"

    def test_parse_entry_invalid(self) -> None:
        from bot.services.downloader import Downloader

        assert Downloader._parse_entry({}) is None
        assert Downloader._parse_entry("nope") is None  # type: ignore[arg-type]

    @pytest.mark.parametrize(
        "raw,expected_fragment",
        [
            ("ERROR: ffmpeg not found", "ffmpeg"),
            ("Sign in to confirm you're not a bot", "авторизации"),
            ("Private video", "недоступен"),
            ("Unsupported URL: foo", "Не понимаю"),
            ("Connection timed out", "сетевую"),
            ("HTTP Error 429: Too Many Requests", "Причина"),
        ],
    )
    def test_humanize_errors(self, raw: str, expected_fragment: str) -> None:
        from bot.services.downloader import _humanize_error

        error = _humanize_error(raw)
        assert expected_fragment in error.user_message


class TestProgress:
    def test_text_by_stage(self) -> None:
        from bot.services.downloader import Progress

        progress = Progress()
        assert "информацию" in progress.as_text()
        progress.stage = "download"
        progress.percent = 42
        assert "42%" in progress.as_text()
        progress.stage = "convert"
        assert "mp3" in progress.as_text()


class TestRunWithProgress:
    async def test_updates_and_cleans_up(self) -> None:
        from bot.services.delivery import run_with_progress
        from bot.services.downloader import Progress

        class FakeMessage:
            message_id = 1

        class FakeBot:
            def __init__(self) -> None:
                self.edits: list[str] = []
                self.deleted: list[int] = []

            async def send_message(self, chat_id: int, text: str) -> FakeMessage:
                return FakeMessage()

            async def edit_message_text(self, chat_id: int, message_id: int, text: str) -> None:
                self.edits.append(text)

            async def delete_message(self, chat_id: int, message_id: int) -> None:
                self.deleted.append(message_id)

        bot = FakeBot()
        progress = Progress()

        async def action() -> str:
            await asyncio.sleep(0.05)
            progress.stage = "download"
            progress.percent = 100
            await asyncio.sleep(0.05)
            return "ok"

        result = await run_with_progress(bot, 1, "ждём", action(), progress, interval=0.01)
        assert result == "ok"
        assert bot.edits
        assert bot.deleted == [1]

    async def test_error_propagates_and_placeholder_removed(self) -> None:
        from bot.services.delivery import run_with_progress
        from bot.services.downloader import Progress

        class FakeMessage:
            message_id = 7

        class FakeBot:
            def __init__(self) -> None:
                self.deleted: list[int] = []

            async def send_message(self, chat_id: int, text: str) -> FakeMessage:
                return FakeMessage()

            async def edit_message_text(self, chat_id: int, message_id: int, text: str) -> None:
                return None

            async def delete_message(self, chat_id: int, message_id: int) -> None:
                self.deleted.append(message_id)

        class Boom(RuntimeError):
            pass

        async def action() -> str:
            await asyncio.sleep(0.01)
            raise Boom("fail")

        bot = FakeBot()
        with pytest.raises(Boom):
            await run_with_progress(bot, 1, "ждём", action(), Progress(), interval=0.01)
        assert bot.deleted == [7]
