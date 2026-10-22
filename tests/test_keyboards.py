from __future__ import annotations

from pathlib import Path

from bot.db import Database, Track
from bot.keyboards import (
    MENU_TEXTS,
    after_save,
    back_to_menu,
    library,
    main_menu,
    player,
    search_results,
)


def make_track(track_id: int = 1, *, favorite: bool = False) -> Track:
    return Track(
        id=track_id,
        user_id=1,
        url=f"https://a/{track_id}",
        title="Song",
        performer="Artist",
        duration=100,
        source="youtube",
        file_id="FILE",
        file_unique_id="UNIQ",
        file_size=1000,
        is_favorite=favorite,
        created_at="2026-01-01T00:00:00+00:00",
    )


def all_callback_data(markup) -> list[str]:
    return [
        button.callback_data
        for row in markup.inline_keyboard
        for button in row
        if button.callback_data
    ]


async def make_library(tmp_path: Path, count: int = 3) -> tuple[list[Track], Database]:
    db = Database(tmp_path / "kb.db")
    await db.init()
    tracks = []
    for index in range(count):
        tracks.append(await db.save_track(user_id=1, url=f"https://a/{index}", title=f"T{index}"))
    return tracks, db


class TestMainMenu:
    def test_buttons_resize(self) -> None:
        markup = main_menu()
        assert markup.resize_keyboard is True
        texts = {button.text for row in markup.keyboard for button in row}
        assert texts <= MENU_TEXTS

    def test_menu_texts_include_home(self) -> None:
        assert "🏠 Меню" in MENU_TEXTS


class TestInlineMarkups:
    def test_search_results_numbering(self) -> None:
        markup = search_results("tok", 5)
        data = all_callback_data(markup)
        assert "dl:tok:0" in data
        assert "dl:tok:4" in data
        assert all(len(item.encode()) <= 64 for item in data)
        assert len(markup.inline_keyboard[0]) == 5

    def test_search_results_many(self) -> None:
        markup = search_results("tok", 10)
        rows = [row for row in markup.inline_keyboard if row[0].callback_data.startswith("dl:")]
        assert len(rows) == 2

    def test_player_favorite_label(self) -> None:
        data = all_callback_data(player(make_track()))
        assert "fav:1" in data
        labels = [b.text for row in player(make_track(favorite=True)).inline_keyboard for b in row]
        assert any("Убрать" in label for label in labels)

    def test_player_without_delete(self) -> None:
        data = all_callback_data(player(make_track(), show_delete=False))
        assert not any(item.startswith("del:") for item in data)

    async def test_library_markup(self, tmp_path: Path) -> None:
        tracks, _ = await make_library(tmp_path)
        markup = library(tracks, page=1, total_pages=2)
        data = all_callback_data(markup)
        assert "p:1" in data
        assert "lib:2:0" in data
        assert all(len(item.encode()) <= 64 for item in data)

    async def test_library_last_page_has_no_next(self, tmp_path: Path) -> None:
        tracks, _ = await make_library(tmp_path)
        data = all_callback_data(library(tracks, page=3, total_pages=3))
        assert not any(item.startswith("lib:4") for item in data)
        assert any(item.startswith("lib:2") for item in data)

    async def test_library_favorites_flag(self, tmp_path: Path) -> None:
        tracks, _ = await make_library(tmp_path)
        data = all_callback_data(library(tracks, page=2, total_pages=3, favorites_only=True))
        assert "lib:3:1" in data

    async def test_library_empty(self, tmp_path: Path) -> None:
        markup = library([], page=1, total_pages=1)
        data = all_callback_data(markup)
        assert not any(item.startswith("p:") for item in data)
        assert "noop" in data

    def test_after_save_and_back(self) -> None:
        assert all(len(item.encode()) <= 64 for item in all_callback_data(after_save(make_track())))
        assert "menu" in all_callback_data(back_to_menu())
