"""Клавиатуры бота."""

from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from bot.db import Track

BTN_SEARCH = "🔍 Поиск"
BTN_RANDOM = "🎲 Случайный"
BTN_LIBRARY = "📚 Библиотека"
BTN_FAVORITES = "⭐ Избранное"
BTN_HELP = "❓ Помощь"

MENU_BUTTONS = [BTN_SEARCH, BTN_RANDOM, BTN_LIBRARY, BTN_FAVORITES, BTN_HELP]

#: тексты кнопок, которые нельзя трактовать как поисковый запрос
MENU_TEXTS = frozenset({*MENU_BUTTONS, "🏠 Меню"})


def main_menu() -> ReplyKeyboardMarkup:
    """Постоянная клавиатура внизу экрана."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_SEARCH), KeyboardButton(text=BTN_RANDOM)],
            [KeyboardButton(text=BTN_LIBRARY), KeyboardButton(text=BTN_FAVORITES)],
            [KeyboardButton(text=BTN_HELP)],
        ],
        resize_keyboard=True,
        input_field_placeholder="Ссылка или название трека…",
    )


def search_results(token: str, count: int) -> InlineKeyboardMarkup:
    numbers = [
        InlineKeyboardButton(text=str(index), callback_data=f"dl:{token}:{index - 1}")
        for index in range(1, count + 1)
    ]
    rows = [numbers[index : index + 5] for index in range(0, len(numbers), 5)]
    rows.append([InlineKeyboardButton(text="✖️ Закрыть", callback_data="close")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def player(track: Track, *, show_delete: bool = True) -> InlineKeyboardMarkup:
    """Кнопки под отправленным аудио."""
    heart = "💔 Убрать из избранного" if track.is_favorite else "⭐ В избранное"
    rows = [
        [
            InlineKeyboardButton(text=heart, callback_data=f"fav:{track.id}"),
            InlineKeyboardButton(text="🎲 Ещё случайный", callback_data="rnd:0"),
        ],
    ]
    if show_delete:
        rows.append(
            [
                InlineKeyboardButton(text="🗑 Удалить", callback_data=f"del:{track.id}"),
                InlineKeyboardButton(text="📚 Библиотека", callback_data="lib:1:0"),
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def library(
    tracks: list[Track],
    page: int,
    total_pages: int,
    *,
    favorites_only: bool = False,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if tracks:
        start = (page - 1) * len(tracks)
        play_row = [
            InlineKeyboardButton(
                text=f"{start + offset + 1}",
                callback_data=f"p:{track.id}",
            )
            for offset, track in enumerate(tracks)
        ]
        rows.extend(play_row[index : index + 5] for index in range(0, len(play_row), 5))

    nav: list[InlineKeyboardButton] = []
    flag = 1 if favorites_only else 0
    if page > 1:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"lib:{page - 1}:{flag}"))
    nav.append(InlineKeyboardButton(text=f"{page}/{total_pages}", callback_data="noop"))
    if page < total_pages:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"lib:{page + 1}:{flag}"))
    rows.append(nav)

    switch = (
        InlineKeyboardButton(text="📚 Вся библиотека", callback_data="lib:1:0")
        if favorites_only
        else InlineKeyboardButton(text="⭐ Избранное", callback_data="lib:1:1")
    )
    rows.append([switch, InlineKeyboardButton(text="🎲 Случайный", callback_data="rnd:0")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def after_save(track: Track) -> InlineKeyboardMarkup:
    """Предложение после сохранения нового трека."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🎲 Ещё случайный", callback_data="rnd:0"),
                InlineKeyboardButton(text="📚 Библиотека", callback_data="lib:1:0"),
            ]
        ]
    )


def back_to_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="🏠 Меню", callback_data="menu")]]
    )
