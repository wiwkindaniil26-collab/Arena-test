"""Конфигурация бота: читается из переменных окружения (и .env в разработке)."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

MB = 1024 * 1024


RUN_MODES = ("polling", "webhook")


class ConfigError(RuntimeError):
    """Конфигурация заполнена некорректно."""


def _get_int(
    env: Mapping[str, str],
    key: str,
    default: int,
    *,
    minimum: int = 0,
    maximum: int | None = None,
) -> int:
    raw = env.get(key, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(f"{key} должен быть целым числом, получено: {raw!r}") from exc
    if value < minimum:
        raise ConfigError(f"{key} должен быть >= {minimum}, получено: {value}")
    if maximum is not None and value > maximum:
        raise ConfigError(f"{key} должен быть <= {maximum}, получено: {value}")
    return value


def _get_optional_path(env: Mapping[str, str], key: str) -> Path | None:
    raw = env.get(key, "").strip()
    return Path(raw).expanduser() if raw else None


def _get_allowed_users(env: Mapping[str, str], key: str) -> frozenset[int]:
    raw = env.get(key, "").strip()
    if not raw:
        return frozenset()
    ids: set[int] = set()
    for chunk in raw.replace(";", ",").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            ids.add(int(chunk))
        except ValueError as exc:
            raise ConfigError(f"{key}: {chunk!r} не похоже на Telegram user id") from exc
    return frozenset(ids)


@dataclass(frozen=True, slots=True)
class Config:
    """Все настройки приложения в одном неизменяемом объекте."""

    bot_token: str
    run_mode: str = "polling"
    db_path: Path = Path("data/music.db")
    download_dir: Path = Path("data/downloads")
    max_file_size_mb: int = 50
    max_concurrent_downloads: int = 3
    search_results: int = 5
    rate_limit_count: int = 10
    rate_limit_window: int = 60
    audio_quality: str = "192"
    cookies_file: Path | None = None
    #: содержимое cookies.txt из переменной окружения (для хостингов без volume)
    cookies_content: str | None = None
    proxy: str | None = None
    allowed_users: frozenset[int] = field(default_factory=frozenset)
    log_level: str = "INFO"
    # webhook-режим: нужен для хостингов без долгоживущего процесса
    # (Cloudflare Containers, некоторые PaaS)
    webhook_base_url: str = ""
    webhook_path: str = "/webhook"
    webhook_secret: str = ""
    host: str = "0.0.0.0"
    port: int = 8080

    @property
    def max_file_size_bytes(self) -> int:
        return self.max_file_size_mb * MB

    @property
    def webhook_url(self) -> str:
        """Полный публичный URL, который отдаём Telegram."""
        base = self.webhook_base_url.rstrip("/")
        path = self.webhook_path if self.webhook_path.startswith("/") else f"/{self.webhook_path}"
        return f"{base}{path}"

    @classmethod
    def from_env(
        cls,
        env: Mapping[str, str] | None = None,
        *,
        load_env_file: bool = True,
    ) -> Config:
        """Собирает конфиг из окружения. Бросает ConfigError с понятным текстом."""
        if env is None:
            if load_env_file:
                load_dotenv()
            env = os.environ

        token = env.get("BOT_TOKEN", "").strip()
        if not token:
            raise ConfigError(
                "BOT_TOKEN не задан. Скопируй .env.example в .env и вставь токен от @BotFather."
            )
        if ":" not in token:
            raise ConfigError(
                "BOT_TOKEN выглядит подозрительно (нет ':' между id и секретом). Проверь токен."
            )

        run_mode = (env.get("RUN_MODE", "polling").strip() or "polling").lower()
        if run_mode not in RUN_MODES:
            raise ConfigError(
                f"RUN_MODE должен быть одним из {', '.join(RUN_MODES)}, получено: {run_mode!r}"
            )

        webhook_base_url = env.get("WEBHOOK_BASE_URL", "").strip().rstrip("/")
        if run_mode == "webhook":
            if not webhook_base_url:
                raise ConfigError(
                    "В режиме webhook нужен WEBHOOK_BASE_URL — публичный адрес бота "
                    "(например https://my-bot.example.workers.dev)."
                )
            if not webhook_base_url.startswith(("http://", "https://")):
                raise ConfigError(
                    "WEBHOOK_BASE_URL должен начинаться с http(s)://, "
                    f"получено: {webhook_base_url!r}"
                )

        webhook_path = env.get("WEBHOOK_PATH", "/webhook").strip() or "/webhook"
        if not webhook_path.startswith("/"):
            webhook_path = "/" + webhook_path

        max_file_size_mb = _get_int(env, "MAX_FILE_SIZE_MB", 50, minimum=1, maximum=2000)
        quality = env.get("AUDIO_QUALITY", "192").strip() or "192"
        if not quality.isdigit():
            raise ConfigError(f"AUDIO_QUALITY должен быть числом (кбит/с), получено: {quality!r}")

        return cls(
            bot_token=token,
            run_mode=run_mode,
            webhook_base_url=webhook_base_url,
            webhook_path=webhook_path,
            webhook_secret=env.get("WEBHOOK_SECRET", "").strip(),
            host=env.get("HOST", "0.0.0.0").strip() or "0.0.0.0",
            port=_get_int(env, "PORT", 8080, minimum=1, maximum=65535),
            db_path=Path(env.get("DB_PATH", "data/music.db").strip() or "data/music.db"),
            download_dir=Path(
                env.get("DOWNLOAD_DIR", "data/downloads").strip() or "data/downloads"
            ),
            max_file_size_mb=max_file_size_mb,
            max_concurrent_downloads=_get_int(
                env, "MAX_CONCURRENT_DOWNLOADS", 3, minimum=1, maximum=32
            ),
            search_results=_get_int(env, "SEARCH_RESULTS", 5, minimum=1, maximum=10),
            rate_limit_count=_get_int(env, "RATE_LIMIT_COUNT", 10, minimum=1),
            rate_limit_window=_get_int(env, "RATE_LIMIT_WINDOW", 60, minimum=1),
            audio_quality=quality,
            cookies_file=_get_optional_path(env, "COOKIES_FILE"),
            cookies_content=env.get("COOKIES_CONTENT", "").strip() or None,
            proxy=env.get("PROXY", "").strip() or None,
            allowed_users=_get_allowed_users(env, "ALLOWED_USERS"),
            log_level=env.get("LOG_LEVEL", "INFO").strip().upper() or "INFO",
        )

    def prepare_dirs(self) -> None:
        """Создаёт каталоги под базу и загрузки."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.download_dir.mkdir(parents=True, exist_ok=True)
