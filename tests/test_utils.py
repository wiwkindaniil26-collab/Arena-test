from __future__ import annotations

import pytest

from bot.utils import (
    clean_title,
    detect_source,
    drm_service,
    escape_html,
    extract_url,
    format_duration,
    format_size,
    guess_artist,
    is_probably_link,
    normalize_url,
    plural_ru,
    sanitize_filename,
    truncate,
)


class TestExtractUrl:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("https://youtu.be/dQw4w9WgXcQ", "https://youtu.be/dQw4w9WgXcQ"),
            ("смотри https://soundcloud.com/a/b тут", "https://soundcloud.com/a/b"),
            ("(https://vk.com/music?z=audio_1)", "https://vk.com/music?z=audio_1"),
            ("https://example.com/track.", "https://example.com/track"),
        ],
    )
    def test_finds_link(self, text: str, expected: str) -> None:
        assert extract_url(text) == expected

    @pytest.mark.parametrize("text", ["просто текст", "", "ftp://nope", "www.example.com"])
    def test_no_link(self, text: str) -> None:
        assert extract_url(text) is None
        assert not is_probably_link(text)


class TestNormalizeUrl:
    def test_strips_tracking_and_www(self) -> None:
        url = "https://www.youtube.com/watch?v=abc123&si=tracking&utm_source=tg"
        assert normalize_url(url) == "https://youtube.com/watch?v=abc123"

    def test_short_youtube_becomes_watch(self) -> None:
        assert normalize_url("https://youtu.be/dQw4w9WgXcQ?t=42") == (
            "https://youtube.com/watch?v=dQw4w9WgXcQ"
        )

    def test_trailing_slash_removed(self) -> None:
        assert normalize_url("https://soundcloud.com/artist/") == "https://soundcloud.com/artist"

    def test_mobile_hosts_collapsed(self) -> None:
        assert normalize_url("https://m.vk.com/audio1_2") == "https://vk.com/audio1_2"

    def test_scheme_added(self) -> None:
        assert normalize_url("soundcloud.com/a/b") == "https://soundcloud.com/a/b"

    def test_idempotent(self) -> None:
        once = normalize_url("https://www.youtube.com/watch?v=abc&feature=share")
        assert normalize_url(once) == once

    def test_empty(self) -> None:
        assert normalize_url("") == ""


class TestDetectSource:
    @pytest.mark.parametrize(
        "url,expected",
        [
            ("https://youtu.be/x", "youtube"),
            ("https://music.youtube.com/watch?v=x", "youtube"),
            ("https://soundcloud.com/x", "soundcloud"),
            ("https://vk.com/audio-1_2", "vk"),
            ("https://music.yandex.ru/album/1", "yandex"),
            ("https://unknown.example/x", "link"),
        ],
    )
    def test_sources(self, url: str, expected: str) -> None:
        assert detect_source(url) == expected


class TestDrm:
    @pytest.mark.parametrize(
        "url,service",
        [
            ("https://open.spotify.com/track/abc", "Spotify"),
            ("https://spotify.link/abc", "Spotify"),
            ("https://music.apple.com/ru/album/x/1?i=2", "Apple Music"),
            ("https://deezer.com/track/1", "Deezer"),
            ("https://tidal.com/browse/track/1", "Tidal"),
        ],
    )
    def test_detects_streaming(self, url: str, service: str) -> None:
        assert drm_service(url) == service

    @pytest.mark.parametrize(
        "url",
        ["https://youtu.be/x", "https://soundcloud.com/a/b", "https://vk.com/audio1_2"],
    )
    def test_plain_sources_are_not_drm(self, url: str) -> None:
        assert drm_service(url) is None


class TestTitles:
    def test_clean_title_removes_brackets(self) -> None:
        assert clean_title("Bohemian Rhapsody (Official Video)") == "Bohemian Rhapsody"
        assert clean_title("Song [Lyrics]") == "Song"
        assert clean_title("Track (Remastered 2011)") == "Track"

    def test_clean_title_strips_artist_prefix(self) -> None:
        assert clean_title("Queen - Bohemian Rhapsody", "Queen") == "Bohemian Rhapsody"

    def test_clean_title_fallback(self) -> None:
        assert clean_title("") == "Без названия"

    def test_guess_artist_from_dash(self) -> None:
        assert guess_artist("Daft Punk - One More Time") == "Daft Punk"

    def test_guess_artist_from_uploader(self) -> None:
        assert guess_artist("One More Time", "Daft Punk - Topic") == "Daft Punk"
        assert guess_artist("Song", "SomeBandVEVO") == "SomeBand"

    def test_guess_artist_unknown(self) -> None:
        assert guess_artist("Just a song title") == ""


class TestFormatting:
    @pytest.mark.parametrize(
        "seconds,expected",
        [(None, "—"), (0, "—"), (59, "0:59"), (245, "4:05"), (3725, "1:02:05"), (-5, "—")],
    )
    def test_duration(self, seconds, expected: str) -> None:
        assert format_duration(seconds) == expected

    def test_size(self) -> None:
        assert format_size(None) == "—"
        assert format_size(0) == "—"
        assert format_size(900) == "900 Б"
        assert format_size(5 * 1024 * 1024) == "5.0 МБ"

    def test_truncate(self) -> None:
        assert truncate("abcdef", 10) == "abcdef"
        assert truncate("abcdef", 4) == "abc…"
        assert truncate("abcdef", 0) == ""

    def test_escape_html(self) -> None:
        assert escape_html("<b>&") == "&lt;b&gt;&amp;"

    @pytest.mark.parametrize(
        "count,expected",
        [(1, "трек"), (2, "трека"), (5, "треков"), (11, "треков"), (21, "трек"), (104, "трека")],
    )
    def test_plural(self, count: int, expected: str) -> None:
        assert plural_ru(count, "трек", "трека", "треков") == expected


class TestSanitizeFilename:
    def test_removes_forbidden_chars(self) -> None:
        assert "/" not in sanitize_filename('a/b\\c:d*e?f"g<h>i|j')
        assert sanitize_filename("  ...  ") == "track"

    def test_keeps_cyrillic(self) -> None:
        assert sanitize_filename("Кино — Звезда") == "Кино — Звезда"

    def test_limits_length(self) -> None:
        assert len(sanitize_filename("x" * 200, limit=40)) <= 40
