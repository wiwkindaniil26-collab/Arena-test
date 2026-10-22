"""Все тексты интерфейса в одном месте — проще переводить и править тон."""

from __future__ import annotations

from bot.db import Track
from bot.services.downloader import TrackMeta
from bot.utils import escape_html, format_duration, plural_ru, truncate

SOURCE_LABELS = {
    "youtube": "YouTube",
    "soundcloud": "SoundCloud",
    "vk": "VK",
    "yandex": "Яндекс Музыка",
    "bandcamp": "Bandcamp",
    "link": "ссылка",
}

GREETING = (
    "Привет! Я <b>музыкальный бот</b> 🎧\n\n"
    "Кидай ссылку на трек — скачаю и пришлю mp3.\n"
    "Умею искать по названию, хранить библиотеку и включать случайный трек.\n\n"
    "<b>Как пользоваться</b>\n"
    "• <code>https://...</code> — скачать по ссылке\n"
    "• просто напиши <i>название песни</i> — найду варианты\n"
    "• кнопка 🎲 — случайный трек из твоей библиотеки"
)

HELP = (
    "<b>Команды</b>\n"
    "/start — меню\n"
    "/search &lt;запрос&gt; — поиск\n"
    "/random — случайный трек\n"
    "/random_fav — случайный из избранного\n"
    "/library [страница] — библиотека\n"
    "/favorites — избранное\n"
    "/stats — статистика\n"
    "/help — эта справка\n\n"
    "<b>Примеры</b>\n"
    "• <code>https://soundcloud.com/artist/track</code>\n"
    "• <code>https://www.youtube.com/watch?v=...</code>\n"
    "• <code>sc:lofi hip hop</code> — искать только в SoundCloud\n\n"
    "Скачивай только тот контент, на который у тебя есть права."
)

MENU_HINT = "Выбирай кнопку ниже или пришли ссылку 👇"

DRM_MESSAGE = (
    "🔒 {service} отдаёт музыку только защищённым потоком (DRM) — файл оттуда "
    "скачать нельзя, это ограничение самого сервиса, а не бота.\n\n"
    "Пришли <b>название и исполнителя</b> — найду трек на площадках, которые "
    "отдают аудио (YouTube, SoundCloud, Bandcamp), и пришлю mp3."
)


def source_label(source: str) -> str:
    return SOURCE_LABELS.get(source, source or "ссылка")


def track_line(track: Track, index: int | None = None) -> str:
    prefix = f"{index}. " if index else ""
    title = escape_html(truncate(track.title, 60))
    performer = escape_html(truncate(track.performer, 40))
    name = f"{performer} — {title}" if performer else title
    duration = format_duration(track.duration)
    heart = " ⭐" if track.is_favorite else ""
    return f"{prefix}{name} <i>({duration})</i>{heart}"


def search_card(meta: TrackMeta, index: int) -> str:
    title = escape_html(truncate(meta.title, 70))
    performer = escape_html(truncate(meta.performer, 50))
    name = f"{performer} — {title}" if performer else title
    return (
        f"<b>{index}.</b> {name}\n"
        f"     ⏱ {format_duration(meta.duration)} · {source_label(meta.source)}"
    )


def search_results_text(query: str, items: list[TrackMeta]) -> str:
    if not items:
        return (
            f"По запросу «{escape_html(truncate(query, 80))}» ничего не нашлось 🤷\n"
            "Попробуй другое написание или пришли прямую ссылку."
        )
    lines = [f"🔍 <b>Результаты:</b> {escape_html(truncate(query, 80))}\n"]
    lines.extend(search_card(item, number) for number, item in enumerate(items, start=1))
    lines.append("\nЖми номер, чтобы скачать.")
    return "\n".join(lines)


def library_text(
    tracks: list[Track],
    page: int,
    total_pages: int,
    total: int,
    *,
    favorites_only: bool = False,
) -> str:
    header = "⭐ <b>Избранное</b>" if favorites_only else "📚 <b>Библиотека</b>"
    if not tracks:
        if favorites_only:
            return f"{header}\n\nПока пусто. Скачай трек и нажми ⭐ под ним — он появится здесь."
        return f"{header}\n\nЗдесь пока пусто. Пришли ссылку на трек или найди его по названию."

    start = (page - 1) * len(tracks) + 1
    lines = [f"{header} <i>({total} {plural_ru(total, 'трек', 'трека', 'треков')})</i>\n"]
    for offset, track in enumerate(tracks):
        lines.append(track_line(track, start + offset))
    lines.append(f"\nСтраница {page} из {total_pages}")
    return "\n".join(lines)


def stats_text(total: int, favorites: int, duration: int) -> str:
    hours = duration // 3600
    minutes = (duration % 3600) // 60
    listened = f"{hours} ч {minutes} мин" if hours else f"{minutes} мин"
    return (
        "📊 <b>Твоя статистика</b>\n\n"
        f"Треков в библиотеке: <b>{total}</b>\n"
        f"В избранном: <b>{favorites}</b>\n"
        f"Суммарная длительность: <b>{listened}</b>"
    )


def queue_text() -> str:
    return "⏳ Все слоты загрузки заняты — трек в очереди."
