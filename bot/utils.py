"""Вспомогательные функции без зависимостей от Telegram и сети."""

from __future__ import annotations

import html
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

__all__ = [
    "clean_title",
    "detect_source",
    "drm_service",
    "escape_html",
    "extract_url",
    "format_duration",
    "format_size",
    "guess_artist",
    "is_probably_link",
    "normalize_url",
    "plural_ru",
    "sanitize_filename",
    "truncate",
]

URL_RE = re.compile(r"https?://[^\s<>\"'«»]+", re.IGNORECASE)

# Параметры, которые не влияют на сам трек и ломают дедупликацию.
TRACKING_PARAMS = frozenset(
    {
        "si",
        "feature",
        "ref",
        "ref_src",
        "ref_url",
        "fbclid",
        "gclid",
        "yclid",
        "share",
        "shared",
        "from",
        "from_search",
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_term",
        "utm_content",
        "spm",
        "t",
    }
)

_DOMAIN_LABELS = {
    "youtube.com": "youtube",
    "youtu.be": "youtube",
    "music.youtube.com": "youtube",
    "soundcloud.com": "soundcloud",
    "on.soundcloud.com": "soundcloud",
    "vk.com": "vk",
    "vk.ru": "vk",
    "vkvideo.ru": "vk",
    "music.yandex.ru": "yandex",
    "music.yandex.com": "yandex",
    "bandcamp.com": "bandcamp",
}


def extract_url(text: str) -> str | None:
    """Возвращает первую ссылку из текста или None."""
    match = URL_RE.search(text or "")
    return match.group(0).rstrip(".,;:!?)]}»") if match else None


def is_probably_link(text: str) -> bool:
    return extract_url(text) is not None


def normalize_url(url: str) -> str:
    """Приводит ссылку к стабильному виду для дедупликации.

    Убирает www, фрагмент, tracking-параметры и хвостовой слэш.
    """
    url = (url or "").strip()
    if not url:
        return ""
    if "://" not in url:
        url = "https://" + url

    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if host == "m.youtube.com":
        host = "youtube.com"
    if host == "m.vk.com":
        host = "vk.com"

    query_pairs = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key.lower() not in TRACKING_PARAMS
    ]
    query = urlencode(sorted(query_pairs))

    # у youtu.be путь — это id видео, в watch-ссылке id лежит в query
    path = parts.path
    if host == "youtu.be" and path.strip("/"):
        video_id = path.strip("/")
        host, path, query = "youtube.com", "/watch", f"v={video_id}"
    if path != "/":
        path = path.rstrip("/")

    return urlunsplit(("https", host, path, query, ""))


def detect_source(url: str, fallback: str = "link") -> str:
    """Определяет площадку по домену."""
    host = (urlsplit(url).hostname or "").lower()
    if not host:
        return fallback
    for domain, name in _DOMAIN_LABELS.items():
        if host == domain or host.endswith("." + domain):
            return name
    return fallback


_DRM_HOSTS = {
    "spotify.com": "Spotify",
    "spotify.link": "Spotify",
    "music.apple.com": "Apple Music",
    "deezer.com": "Deezer",
    "deezer.page.link": "Deezer",
    "tidal.com": "Tidal",
}


def drm_service(url: str) -> str | None:
    """Название стриминга, который не отдаёт файл (только поток с DRM).

    Такие ссылки бесполезно скармливать yt-dlp — пользователю нужен понятный ответ.
    """
    host = (urlsplit(url).hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    for domain, name in _DRM_HOSTS.items():
        if host == domain or host.endswith("." + domain):
            return name
    return None


_BRACKET_JUNK = re.compile(
    r"[\(\[\{][^\)\]\}]*(official|официальн|video|видео|audio|аудио|lyric|лирик|"
    r"lyrics|текст|clip|клип|remaster|ремастер|hd|hq|4k|8k|mv|m/v|visuali[sz]er|"
    r"premiere|премьер|live|концерт|prod\.?|prod by|explicit|clean)[^\)\]\}]*[\)\]\}]",
    re.IGNORECASE,
)
_ARTIST_SEPARATORS = (" - ", " – ", " — ", " — ", " | ")


def clean_title(raw: str, artist: str = "") -> str:
    """Чистит название от «(Official Video)», «[Lyrics]» и прочего шума."""
    title = html.unescape((raw or "").strip())
    title = _BRACKET_JUNK.sub(" ", title)
    title = re.sub(r"\s{2,}", " ", title).strip(" -–—|")
    if artist:
        prefix = f"{artist.strip().lower()} - ".lower()
        if title.lower().startswith(prefix):
            title = title[len(prefix) :].strip()
    return title or "Без названия"


def guess_artist(raw_title: str, uploader: str = "") -> str:
    """Пытается вытащить исполнителя из «Artist - Title» или из имени канала."""
    title = html.unescape((raw_title or "").strip())
    for separator in _ARTIST_SEPARATORS:
        if separator in title:
            candidate = title.split(separator, 1)[0].strip()
            if 0 < len(candidate) <= 60:
                return candidate
    channel = html.unescape((uploader or "").strip())
    channel = re.sub(r"\s*[-–—]\s*(topic|official|vevo|music)$", "", channel, flags=re.IGNORECASE)
    channel = re.sub(r"\s*vevo$", "", channel, flags=re.IGNORECASE)
    channel = channel.strip()
    return channel if 0 < len(channel) <= 60 else ""


def format_duration(seconds: float | int | None) -> str:
    """3:45 / 1:02:03 / — для неизвестной длительности."""
    if seconds is None:
        return "—"
    try:
        total = int(seconds)
    except (TypeError, ValueError):
        return "—"
    if total <= 0:
        return "—"
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def format_size(size: int | None) -> str:
    if not size:
        return "—"
    value = float(size)
    for unit in ("Б", "КБ", "МБ", "ГБ"):
        if value < 1024 or unit == "ГБ":
            return f"{value:.0f} {unit}" if unit == "Б" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} ГБ"


def truncate(text: str, limit: int, suffix: str = "…") -> str:
    text = text or ""
    if limit <= 0:
        return ""
    if len(text) <= limit:
        return text
    return text[: max(0, limit - len(suffix))].rstrip() + suffix


def escape_html(text: str) -> str:
    return html.escape(text or "", quote=False)


def plural_ru(count: int, one: str, few: str, many: str) -> str:
    """Русская плюрализация: 1 трек / 2 трека / 5 треков."""
    n = abs(int(count)) % 100
    if 11 <= n <= 19:
        return many
    n %= 10
    if n == 1:
        return one
    if 2 <= n <= 4:
        return few
    return many


_FILENAME_BAD = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
_FILENAME_ALLOWED = re.compile(r"[^\w\s.\-()\[\]—–«»'’]+", re.UNICODE)


def sanitize_filename(name: str, limit: int = 80) -> str:
    """Безопасное имя mp3-файла."""
    cleaned = _FILENAME_BAD.sub(" ", name or "")
    cleaned = _FILENAME_ALLOWED.sub(" ", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" .-")
    cleaned = cleaned[:limit].strip(" .-")
    return cleaned or "track"
