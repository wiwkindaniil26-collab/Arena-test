"""Интеграционные тесты: апдейты идут через реальный Dispatcher и роутеры.

Telegram заменён фейковой сессией, поэтому тесты не ходят в сеть.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fakes import FakeSession, callback_update, make_bot, text_update

from bot.config import Config
from bot.db import Database
from bot.main import build_dispatcher
from bot.services.cache import SearchCache
from bot.services.downloader import Downloader, TrackMeta
from bot.services.library import Library
from bot.services.limiter import RateLimiter
from bot.services.music import MusicService

USER_ID = 42


@pytest.fixture
async def env(tmp_path: Path):
    config = Config.from_env(
        {
            "BOT_TOKEN": "123456789:AAExampleToken",
            "DB_PATH": str(tmp_path / "int.db"),
            "DOWNLOAD_DIR": str(tmp_path / "dl"),
        },
        load_env_file=False,
    )
    config.prepare_dirs()
    db = Database(config.db_path)
    await db.init()
    downloader = Downloader(config)
    library = Library(db)
    cache = SearchCache()
    limiter = RateLimiter(limit=100, window=60)
    music = MusicService(config, db, downloader, library, cache)
    dp = build_dispatcher(config, db, music, library, limiter, downloader, cache)

    session = FakeSession()
    bot = make_bot(session)
    try:
        yield {
            "dp": dp,
            "bot": bot,
            "session": session,
            "db": db,
            "music": music,
            "downloader": downloader,
            "config": config,
        }
    finally:
        await bot.session.close()


class TestBasicCommands:
    async def test_start(self, env) -> None:
        await env["dp"].feed_update(env["bot"], text_update("/start"))
        texts = env["session"].sent_texts()
        assert any("музыкальный бот" in text for text in texts)
        markup = env["session"].sent_markups()[0]
        assert markup is not None

    async def test_help(self, env) -> None:
        await env["dp"].feed_update(env["bot"], text_update("/help"))
        assert any("/random_fav" in text for text in env["session"].sent_texts())

    async def test_unknown_command_is_ignored(self, env) -> None:
        await env["dp"].feed_update(env["bot"], text_update("/unknown"))
        assert env["session"].calls == []

    async def test_empty_library(self, env) -> None:
        await env["dp"].feed_update(env["bot"], text_update("/library"))
        assert any("Здесь пока пусто" in text for text in env["session"].sent_texts())

    async def test_empty_favorites(self, env) -> None:
        await env["dp"].feed_update(env["bot"], text_update("/favorites"))
        assert any("Пока пусто" in text for text in env["session"].sent_texts())

    async def test_random_on_empty_library(self, env) -> None:
        await env["dp"].feed_update(env["bot"], text_update("/random"))
        assert any("Библиотека пуста" in text for text in env["session"].sent_texts())

    async def test_stats(self, env) -> None:
        await env["dp"].feed_update(env["bot"], text_update("/stats"))
        assert any("Треков в библиотеке" in text for text in env["session"].sent_texts())


class TestSearchFlow:
    async def test_text_triggers_search(self, env, monkeypatch: pytest.MonkeyPatch) -> None:
        async def fake_search(self, query: str, limit: int) -> list[TrackMeta]:
            assert query == "lofi"
            assert limit == 5
            return [
                TrackMeta(url="https://youtu.be/a", title="A", performer="X", duration=100),
                TrackMeta(url="https://youtu.be/b", title="B", performer="Y", duration=200),
            ]

        monkeypatch.setattr(Downloader, "search", fake_search)
        await env["dp"].feed_update(env["bot"], text_update("lofi"))

        texts = env["session"].sent_texts()
        assert any("Результаты" in text for text in texts)
        markup = env["session"].sent_markups()[0]
        data = [button.callback_data for row in markup.inline_keyboard for button in row]
        assert any(item.startswith("dl:") for item in data)

    async def test_search_command_without_query(self, env) -> None:
        await env["dp"].feed_update(env["bot"], text_update("/search"))
        assert any("название песни" in text for text in env["session"].sent_texts())

    async def test_search_command_with_query(self, env, monkeypatch: pytest.MonkeyPatch) -> None:
        async def fake_search(self, query: str, limit: int) -> list[TrackMeta]:
            return [TrackMeta(url="https://youtu.be/a", title=query)]

        monkeypatch.setattr(Downloader, "search", fake_search)
        await env["dp"].feed_update(env["bot"], text_update("/search кино группа крови"))
        assert any("кино группа крови" in text for text in env["session"].sent_texts())

    async def test_no_results(self, env, monkeypatch: pytest.MonkeyPatch) -> None:
        async def fake_search(self, query: str, limit: int) -> list[TrackMeta]:
            return []

        monkeypatch.setattr(Downloader, "search", fake_search)
        await env["dp"].feed_update(env["bot"], text_update("абракадабра"))
        assert any("ничего не нашлось" in text for text in env["session"].sent_texts())

    async def test_search_error_is_reported(self, env, monkeypatch: pytest.MonkeyPatch) -> None:
        from bot.services.downloader import DownloadError

        async def fake_search(self, query: str, limit: int) -> list[TrackMeta]:
            raise DownloadError("Источник недоступен.")

        monkeypatch.setattr(Downloader, "search", fake_search)
        await env["dp"].feed_update(env["bot"], text_update("что-нибудь"))
        assert any("Источник недоступен" in text for text in env["session"].sent_texts())


class TestDownloadFlow:
    async def test_link_triggers_download(self, env, monkeypatch: pytest.MonkeyPatch) -> None:
        from bot.db import Track

        calls: list[str] = []

        async def fake_download_and_send(self, bot, chat_id, user_id, url, *, reply_markup=None):
            calls.append(url)
            return (
                Track(
                    id=1,
                    user_id=user_id,
                    url=url,
                    title="T",
                    performer="P",
                    duration=1,
                    source="youtube",
                    file_id="F",
                    file_unique_id="U",
                    file_size=1,
                    is_favorite=False,
                    created_at="2026-01-01T00:00:00+00:00",
                ),
                False,
            )

        monkeypatch.setattr(MusicService, "download_and_send", fake_download_and_send)
        await env["dp"].feed_update(
            env["bot"], text_update("вот https://youtu.be/dQw4w9WgXcQ?si=abc")
        )
        assert calls == ["https://youtu.be/dQw4w9WgXcQ?si=abc"]

    async def test_download_error_is_reported(self, env, monkeypatch: pytest.MonkeyPatch) -> None:
        from bot.services.downloader import DownloadError

        async def fake_download_and_send(self, *args, **kwargs):
            raise DownloadError("Трек недоступен.", hint="Попробуй другую ссылку")

        monkeypatch.setattr(MusicService, "download_and_send", fake_download_and_send)
        await env["dp"].feed_update(env["bot"], text_update("https://example.com/x"))
        texts = env["session"].sent_texts()
        assert any("Трек недоступен" in text for text in texts)
        assert any("Попробуй другую ссылку" in text for text in texts)

    async def test_stale_search_result(self, env) -> None:
        await env["dp"].feed_update(env["bot"], callback_update("dl:missing:0"))
        answered = [
            call for call in env["session"].calls if type(call).__name__ == "AnswerCallbackQuery"
        ]
        assert answered
        assert "устарели" in (answered[0].text or "")


class TestDrmLinks:
    async def test_spotify_link_gets_explanation(self, env) -> None:
        await env["dp"].feed_update(
            env["bot"], text_update("https://open.spotify.com/track/4uLU6hMCjMI75M1A2tKUQC")
        )
        texts = env["session"].sent_texts()
        assert any("Spotify" in text and "DRM" in text for text in texts)


class TestLibraryFlow:
    async def test_library_lists_saved_track(self, env) -> None:
        await env["db"].save_track(
            user_id=USER_ID, url="https://a/1", title="Кино", performer="Звезда", duration=90
        )
        await env["dp"].feed_update(env["bot"], text_update("/library"))
        texts = env["session"].sent_texts()
        assert any("Кино" in text and "Звезда" in text for text in texts)

    async def test_favorite_callback(self, env) -> None:
        track = await env["db"].save_track(user_id=USER_ID, url="https://a/1", title="T")
        await env["dp"].feed_update(env["bot"], callback_update(f"fav:{track.id}"))
        refreshed = await env["db"].get_track(track.id, USER_ID)
        assert refreshed is not None
        assert refreshed.is_favorite is True

    async def test_delete_callback(self, env) -> None:
        track = await env["db"].save_track(user_id=USER_ID, url="https://a/1", title="T")
        await env["dp"].feed_update(env["bot"], callback_update(f"del:{track.id}"))
        assert await env["db"].count_tracks(USER_ID) == 0

    async def test_play_missing_track(self, env) -> None:
        await env["dp"].feed_update(env["bot"], callback_update("p:999"))
        answered = [
            call for call in env["session"].calls if type(call).__name__ == "AnswerCallbackQuery"
        ]
        assert "не найден" in (answered[0].text or "")

    async def test_random_from_filled_library(self, env) -> None:
        await env["db"].save_track(user_id=USER_ID, url="https://a/1", title="T", file_id="FILE")
        await env["dp"].feed_update(env["bot"], text_update("/random"))
        audios = [call for call in env["session"].calls if type(call).__name__ == "SendAudio"]
        assert audios
        assert audios[0].audio == "FILE"


class TestAccessControl:
    async def test_stranger_is_blocked(self, tmp_path: Path) -> None:
        config = Config.from_env(
            {
                "BOT_TOKEN": "123456789:AAExampleToken",
                "DB_PATH": str(tmp_path / "acl.db"),
                "DOWNLOAD_DIR": str(tmp_path / "dl"),
                "ALLOWED_USERS": "777",
            },
            load_env_file=False,
        )
        config.prepare_dirs()
        db = Database(config.db_path)
        await db.init()
        downloader = Downloader(config)
        library = Library(db)
        music = MusicService(config, db, downloader, library, SearchCache())
        dp = build_dispatcher(config, db, music, library, RateLimiter(), downloader, SearchCache())

        session = FakeSession()
        bot = make_bot(session)
        await dp.feed_update(bot, text_update("/start"))
        assert any("закрытом режиме" in text for text in session.sent_texts())
