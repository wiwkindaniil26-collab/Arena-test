"""Загрузка и поиск музыки через yt-dlp.

yt-dlp умеет сотни источников: YouTube/YouTube Music, SoundCloud, Bandcamp,
VK-видео, прямые ссылки на медиа и т.д. Всё, что требует установленного
``ffmpeg`` (перекодирование в mp3 и теги), выполняется во временном каталоге.
"""

from __future__ import annotations

import asyncio
import logging
import re
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

import yt_dlp

from bot.config import Config
from bot.utils import (
    clean_title,
    detect_source,
    guess_artist,
    is_probably_link,
)

logger = logging.getLogger(__name__)

AUDIO_EXTENSIONS = (".mp3", ".m4a", ".opus", ".ogg", ".flac", ".wav", ".webm")
THUMBNAIL_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")


class DownloadError(RuntimeError):
    """Ошибка, текст которой можно показать пользователю."""

    def __init__(self, message: str, *, hint: str | None = None) -> None:
        super().__init__(message)
        self.user_message = message
        self.hint = hint


class TrackTooLarge(DownloadError):
    """Трек не влезает в лимит Telegram Bot API."""


@dataclass(slots=True)
class TrackMeta:
    """Метаданные трека без скачивания файла."""

    url: str
    title: str
    performer: str = ""
    duration: int | None = None
    source: str = "link"
    video_id: str | None = None
    thumbnail_url: str | None = None

    @property
    def display(self) -> str:
        artist = f"{self.performer} — " if self.performer else ""
        return f"{artist}{self.title}"


@dataclass(slots=True)
class DownloadedTrack:
    """Скачанный mp3 + обложка во временном каталоге."""

    meta: TrackMeta
    file_path: Path
    thumbnail_path: Path | None = None
    file_size: int = 0

    def cleanup(self) -> None:
        """Удаляет временный каталог с файлом и обложкой."""
        shutil.rmtree(self.file_path.parent, ignore_errors=True)


@dataclass(slots=True)
class Progress:
    """Разделяемое между потоком yt-dlp и event loop состояние прогресса."""

    percent: float = 0.0
    stage: str = "pending"  # pending | download | convert | done
    started_at: float = field(default_factory=time.monotonic)

    def as_text(self) -> str:
        if self.stage == "convert":
            return "🎧 Конвертирую в mp3…"
        if self.stage == "pending":
            return "🔎 Получаю информацию о треке…"
        if self.percent <= 0:
            return "⬇️ Скачиваю…"
        return f"⬇️ Скачиваю… {self.percent:.0f}%"


class _YdlLogger:
    """Глушим вывод yt-dlp в консоль, но сохраняем предупреждения для логов."""

    def __init__(self) -> None:
        self.messages: list[str] = []

    def debug(self, msg: str) -> None:  # noqa: D102
        pass

    def info(self, msg: str) -> None:  # noqa: D102
        pass

    def warning(self, msg: str) -> None:  # noqa: D102
        self.messages.append(msg)
        logger.debug("yt-dlp: %s", msg)

    def error(self, msg: str) -> None:  # noqa: D102
        self.messages.append(msg)
        logger.debug("yt-dlp error: %s", msg)


def _humanize_error(raw: str) -> DownloadError:
    """Переводит типовые ошибки yt-dlp в понятный пользователю текст."""
    text = (raw or "").strip()
    lowered = text.lower()

    if "ffmpeg" in lowered or "ffprobe" in lowered:
        return DownloadError(
            "На сервере не установлен ffmpeg — без него нельзя собрать mp3.",
            hint="Установи ffmpeg (в Docker-образе он уже есть) и перезапусти бота.",
        )
    if "sign in" in lowered or "confirm you're not a bot" in lowered or "cookies" in lowered:
        return DownloadError(
            "Источник требует авторизации и не отдаёт трек анонимно.",
            hint="Укажи COOKIES_FILE с cookies своего аккаунта или используй другую ссылку.",
        )
    if "private" in lowered or "unavailable" in lowered or "not available" in lowered:
        return DownloadError("Трек недоступен: приватный, удалён или заблокирован.")
    if "unsupported url" in lowered or "no suitable" in lowered:
        return DownloadError(
            "Не понимаю такую ссылку. Пришли прямую ссылку на трек или название песни."
        )
    if "timed out" in lowered or "timeout" in lowered or "connection" in lowered:
        return DownloadError(
            "Не удалось связаться с источником — похоже на сетевую ошибку.",
            hint="Повтори позже или настрой PROXY.",
        )
    if "requested format" in lowered:
        return DownloadError("У этого трека нет доступного аудиоформата.")
    if "copyright" in lowered or "blocked" in lowered:
        return DownloadError("Трек заблокирован правообладателем на этом источнике.")
    if "too large" in lowered:
        return DownloadError("Файл слишком большой для отправки в Telegram.")

    short = re.sub(r"\s+", " ", text)[:200]
    return DownloadError(f"Не получилось скачать трек. Причина: {short}")


class Downloader:
    """Асинхронная обёртка над yt-dlp."""

    def __init__(self, config: Config) -> None:
        self._config = config

    # ------------------------------------------------------------------ опции

    def _common_opts(self) -> dict:
        opts: dict = {
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "socket_timeout": 25,
            "retries": 2,
            "logger": _YdlLogger(),
            "cachedir": False,
        }
        if self._config.cookies_file:
            opts["cookiefile"] = str(self._config.cookies_file)
        if self._config.proxy:
            opts["proxy"] = self._config.proxy
        return opts

    def _download_opts(self, workdir: Path, progress: Progress | None) -> dict:
        opts = self._common_opts()
        opts.update(
            {
                "format": "bestaudio/best",
                "outtmpl": {"default": str(workdir / "%(title).80s-%(id)s.%(ext)s")},
                "restrictfilenames": True,
                "noplaylist": True,
                "playlist_items": "1",
                "writethumbnail": True,
                "convert_thumbnails": "jpg",
                "postprocessors": [
                    {
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": "mp3",
                        "preferredquality": self._config.audio_quality,
                    },
                    {"key": "FFmpegMetadata", "add_metadata": True, "add_chapters": False},
                ],
                "progress_hooks": [self._make_progress_hook(progress)],
            }
        )
        return opts

    @staticmethod
    def _make_progress_hook(progress: Progress | None):
        def hook(data: dict) -> None:
            if progress is None:
                return
            status = data.get("status")
            if status == "downloading":
                total = data.get("total_bytes") or data.get("total_bytes_estimate")
                downloaded = data.get("downloaded_bytes") or 0
                if total:
                    # оставляем 2% на постобработку
                    progress.percent = min(downloaded / total * 98, 98)
                progress.stage = "download"
            elif status == "finished":
                progress.percent = 100
                progress.stage = "convert"

        return hook

    # ------------------------------------------------------------------ поиск

    @staticmethod
    def build_search_query(query: str, limit: int) -> str:
        """``sc:lofi`` → поиск в SoundCloud, ссылка → сама ссылка, иначе YouTube."""
        query = (query or "").strip()
        if query.lower().startswith("sc:"):
            return f"scsearch{limit}:{query[3:].strip()}"
        if is_probably_link(query):
            return query
        if query.lower().startswith("yt:"):
            query = query[3:].strip()
        return f"ytsearch{limit}:{query}"

    @staticmethod
    def _parse_entry(entry: dict) -> TrackMeta | None:
        if not isinstance(entry, dict):
            return None
        url = entry.get("webpage_url") or entry.get("original_url") or entry.get("url") or ""
        if not url:
            video_id = entry.get("id")
            if not video_id:
                return None
            url = f"https://www.youtube.com/watch?v={video_id}"
        elif not str(url).startswith("http"):
            url = f"https://www.youtube.com/watch?v={url}"

        raw_title = entry.get("track") or entry.get("title") or ""
        uploader = entry.get("artist") or entry.get("uploader") or entry.get("channel") or ""
        artist = guess_artist(raw_title, uploader)
        duration = entry.get("duration")
        return TrackMeta(
            url=url,
            title=clean_title(raw_title, artist),
            performer=artist,
            duration=int(duration) if duration else None,
            source=detect_source(url, fallback=entry.get("extractor_key", "link").lower()),
            video_id=entry.get("id"),
            thumbnail_url=entry.get("thumbnail"),
        )

    async def search(self, query: str, limit: int) -> list[TrackMeta]:
        """Ищет треки без скачивания. Возвращает до ``limit`` результатов."""
        target = self.build_search_query(query, limit)
        opts = self._common_opts()
        opts.update(
            {
                "skip_download": True,
                "extract_flat": "in_playlist",
                "noplaylist": False,
            }
        )

        def _search() -> list[TrackMeta]:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(target, download=False)
            if not info:
                return []
            entries = info.get("entries") if "entries" in info else [info]
            results: list[TrackMeta] = []
            for entry in entries or []:
                meta = self._parse_entry(entry)
                if meta is not None:
                    results.append(meta)
                if len(results) >= limit:
                    break
            return results

        try:
            return await asyncio.to_thread(_search)
        except Exception as exc:  # noqa: BLE001 - yt-dlp кидает чем попало
            raw = str(exc)
            logger.warning("Поиск %r не удался: %s", query, raw[:300])
            raise _humanize_error(raw) from exc

    # ---------------------------------------------------------------- загрузка

    async def download(self, url: str, progress: Progress | None = None) -> DownloadedTrack:
        """Скачивает трек во временный каталог и возвращает пути к файлам."""
        workdir = Path(tempfile.mkdtemp(prefix="dl-", dir=self._config.download_dir))
        opts = self._download_opts(workdir, progress)
        if progress is not None:
            progress.stage = "download"

        def _download() -> dict:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
            if not info:
                raise DownloadError("Источник не вернул информацию о треке.")
            if "entries" in info:
                entries = [e for e in (info.get("entries") or []) if e]
                if not entries:
                    raise DownloadError("В этой ссылке нет треков.")
                info = entries[0]
            return info

        try:
            info = await asyncio.to_thread(_download)
        except DownloadError:
            shutil.rmtree(workdir, ignore_errors=True)
            raise
        except Exception as exc:  # noqa: BLE001
            shutil.rmtree(workdir, ignore_errors=True)
            raw = str(exc)
            logger.warning("Загрузка %s не удалась: %s", url, raw[:500])
            raise _humanize_error(raw) from exc

        try:
            audio_path = self._find_audio_file(workdir)
            if audio_path is None:
                raise DownloadError("Не удалось получить аудиофайл из источника.")

            file_size = audio_path.stat().st_size
            if file_size > self._config.max_file_size_bytes:
                raise TrackTooLarge(
                    "Трек весит больше "
                    f"{self._config.max_file_size_mb} МБ — Telegram не пропустит такой файл.",
                    hint="Попробуй другое исполнение/источник или подними MAX_FILE_SIZE_MB "
                    "при локальном Bot API server.",
                )

            meta = self._meta_from_info(info, url)
            if not meta.title or meta.title == "Без названия":
                meta.title = clean_title(audio_path.stem)
            thumbnail = self._find_thumbnail(workdir)
            if progress is not None:
                progress.percent = 100
                progress.stage = "done"
            return DownloadedTrack(
                meta=meta,
                file_path=audio_path,
                thumbnail_path=thumbnail,
                file_size=file_size,
            )
        except Exception:
            shutil.rmtree(workdir, ignore_errors=True)
            raise

    def _meta_from_info(self, info: dict, url: str) -> TrackMeta:
        raw_title = info.get("track") or info.get("title") or ""
        uploader = info.get("artist") or info.get("creator") or info.get("uploader") or ""
        artist = guess_artist(raw_title, uploader) or (info.get("artist") or "")
        duration = info.get("duration")
        webpage_url = info.get("webpage_url") or url
        return TrackMeta(
            url=webpage_url,
            title=clean_title(raw_title, artist),
            performer=artist or "",
            duration=int(duration) if duration else None,
            source=detect_source(webpage_url, fallback="link"),
            video_id=info.get("id"),
            thumbnail_url=info.get("thumbnail"),
        )

    @staticmethod
    def _find_audio_file(workdir: Path) -> Path | None:
        files = [p for p in workdir.iterdir() if p.is_file()]
        for extension in AUDIO_EXTENSIONS:
            for path in files:
                if path.suffix.lower() == extension:
                    return path
        return None

    @staticmethod
    def _find_thumbnail(workdir: Path) -> Path | None:
        for path in workdir.iterdir():
            if path.is_file() and path.suffix.lower() in THUMBNAIL_EXTENSIONS:
                return path
        return None
