from __future__ import annotations

from pathlib import Path

import pytest

from bot.config import Config, ConfigError


def make_env(**overrides: str) -> dict[str, str]:
    env = {"BOT_TOKEN": "123456789:AAExampleToken"}
    env.update(overrides)
    return env


class TestConfig:
    def test_defaults(self) -> None:
        config = Config.from_env(make_env(), load_env_file=False)
        assert config.bot_token == "123456789:AAExampleToken"
        assert config.max_file_size_mb == 50
        assert config.max_file_size_bytes == 50 * 1024 * 1024
        assert config.search_results == 5
        assert config.download_dir == Path("data/downloads")
        assert config.allowed_users == frozenset()
        assert config.cookies_file is None
        assert config.proxy is None

    def test_overrides(self) -> None:
        config = Config.from_env(
            make_env(
                MAX_FILE_SIZE_MB="200",
                SEARCH_RESULTS="3",
                AUDIO_QUALITY="320",
                DB_PATH="/tmp/x.sqlite",
                COOKIES_FILE="/tmp/cookies.txt",
                PROXY="http://proxy:8080",
                ALLOWED_USERS="1, 2,3",
                LOG_LEVEL="debug",
            ),
            load_env_file=False,
        )
        assert config.max_file_size_mb == 200
        assert config.search_results == 3
        assert config.audio_quality == "320"
        assert config.db_path == Path("/tmp/x.sqlite")
        assert config.cookies_file == Path("/tmp/cookies.txt")
        assert config.proxy == "http://proxy:8080"
        assert config.allowed_users == frozenset({1, 2, 3})
        assert config.log_level == "DEBUG"

    def test_missing_token(self) -> None:
        with pytest.raises(ConfigError, match="BOT_TOKEN"):
            Config.from_env({}, load_env_file=False)

    def test_malformed_token(self) -> None:
        with pytest.raises(ConfigError, match="подозрительно"):
            Config.from_env({"BOT_TOKEN": "no-colon-here"}, load_env_file=False)

    @pytest.mark.parametrize(
        "key,value",
        [
            ("MAX_FILE_SIZE_MB", "abc"),
            ("MAX_FILE_SIZE_MB", "0"),
            ("MAX_CONCURRENT_DOWNLOADS", "0"),
            ("SEARCH_RESULTS", "50"),
            ("AUDIO_QUALITY", "high"),
            ("RATE_LIMIT_WINDOW", "0"),
        ],
    )
    def test_invalid_values(self, key: str, value: str) -> None:
        with pytest.raises(ConfigError):
            Config.from_env(make_env(**{key: value}), load_env_file=False)

    def test_invalid_allowed_users(self) -> None:
        with pytest.raises(ConfigError, match="ALLOWED_USERS"):
            Config.from_env(make_env(ALLOWED_USERS="1,not-an-id"), load_env_file=False)

    def test_cookies_content_written_to_file(self, tmp_path: Path) -> None:
        from bot.main import resolve_cookies_file

        config = Config.from_env(
            make_env(
                DB_PATH=str(tmp_path / "data" / "m.db"),
                COOKIES_CONTENT="# Netscape HTTP Cookie File\n.example.com\tTRUE\t/\tFALSE\t0\tk\tv",
            ),
            load_env_file=False,
        )
        config.prepare_dirs()
        resolved = resolve_cookies_file(config)

        assert resolved.cookies_file is not None
        assert resolved.cookies_file.exists()
        assert "Netscape" in resolved.cookies_file.read_text()
        assert resolved.cookies_content is None
        assert oct(resolved.cookies_file.stat().st_mode)[-3:] == "600"

    def test_cookies_content_empty_is_ignored(self) -> None:
        from bot.main import resolve_cookies_file

        config = Config.from_env(make_env(COOKIES_CONTENT="  "), load_env_file=False)
        assert resolve_cookies_file(config).cookies_file is None

    def test_prepare_dirs(self, tmp_path: Path) -> None:
        config = Config.from_env(
            make_env(DB_PATH=str(tmp_path / "db" / "m.db"), DOWNLOAD_DIR=str(tmp_path / "dl")),
            load_env_file=False,
        )
        config.prepare_dirs()
        assert config.db_path.parent.is_dir()
        assert config.download_dir.is_dir()
