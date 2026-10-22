"""Общие хендлеры: старт, справка, меню, служебные callback-и."""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message

from bot.keyboards import back_to_menu, main_menu
from bot.texts import GREETING, HELP, MENU_HINT

logger = logging.getLogger(__name__)
router = Router(name="common")


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    await message.answer(GREETING, reply_markup=main_menu())
    await message.answer(MENU_HINT)


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(HELP, reply_markup=main_menu())


@router.message(F.text == "❓ Помощь")
async def btn_help(message: Message) -> None:
    await message.answer(HELP, reply_markup=main_menu())


@router.message(Command("menu"))
@router.message(F.text == "🏠 Меню")
async def cmd_menu(message: Message) -> None:
    await message.answer("Главное меню 👇", reply_markup=main_menu())


@router.callback_query(F.data == "menu")
async def cb_menu(callback: CallbackQuery) -> None:
    await callback.answer()
    if isinstance(callback.message, Message):
        await callback.message.answer("Главное меню 👇", reply_markup=main_menu())


@router.callback_query(F.data == "close")
async def cb_close(callback: CallbackQuery) -> None:
    await callback.answer()
    if isinstance(callback.message, Message):
        try:
            await callback.message.delete()
        except Exception:  # noqa: BLE001 - сообщение могло быть уже удалено
            await callback.message.edit_reply_markup(reply_markup=None)


@router.callback_query(F.data == "noop")
async def cb_noop(callback: CallbackQuery) -> None:
    await callback.answer()


@router.callback_query(F.data == "hint_search")
async def cb_hint_search(callback: CallbackQuery) -> None:
    await callback.answer("Пришли название песни сообщением 🎵", show_alert=False)
    if isinstance(callback.message, Message):
        await callback.message.edit_reply_markup(reply_markup=back_to_menu())
