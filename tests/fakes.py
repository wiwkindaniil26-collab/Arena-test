"""Фейки Telegram для тестов: подменяют сетевую сессию aiogram."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.base import BaseSession
from aiogram.enums import ParseMode
from aiogram.methods import TelegramMethod
from aiogram.types import CallbackQuery, Chat, Message, Update, User

USER_ID = 42
CHAT_ID = 42

TOKEN = "123456789:AAExampleToken"


class FakeSession(BaseSession):
    """Записывает вызовы Bot API и отвечает заглушками."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[TelegramMethod[Any]] = []
        self._message_id = 100

    async def close(self) -> None:  # pragma: no cover - интерфейс
        return None

    async def stream_content(self, *args: Any, **kwargs: Any):  # pragma: no cover
        raise NotImplementedError

    async def make_request(self, bot: Bot, method: TelegramMethod[Any], timeout: int | None = None):
        self.calls.append(method)
        name = type(method).__name__
        if name in {"SendMessage", "EditMessageText"}:
            self._message_id += 1
            return Message(
                message_id=self._message_id,
                date=datetime.now(UTC),
                chat=Chat(id=getattr(method, "chat_id", CHAT_ID), type="private"),
                text=getattr(method, "text", None),
            )
        return True

    def sent_texts(self, method_name: str = "SendMessage") -> list[str]:
        return [
            call.text
            for call in self.calls
            if type(call).__name__ == method_name and getattr(call, "text", None)
        ]

    def sent_markups(self, method_name: str = "SendMessage") -> list[Any]:
        return [
            getattr(call, "reply_markup", None)
            for call in self.calls
            if type(call).__name__ == method_name
        ]

    def calls_named(self, method_name: str) -> list[Any]:
        return [call for call in self.calls if type(call).__name__ == method_name]


def make_bot(session: FakeSession | None = None, token: str = TOKEN) -> Bot:
    return Bot(
        token=token,
        session=session or FakeSession(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


def user(user_id: int = USER_ID) -> User:
    return User(id=user_id, is_bot=False, first_name="Тест", username="tester")


def text_update(text: str, update_id: int = 1, user_id: int = USER_ID) -> Update:
    return Update(
        update_id=update_id,
        message=Message(
            message_id=update_id,
            date=datetime.now(UTC),
            chat=Chat(id=user_id, type="private"),
            from_user=user(user_id),
            text=text,
        ),
    )


def callback_update(data: str, update_id: int = 2) -> Update:
    return Update(
        update_id=update_id,
        callback_query=CallbackQuery(
            id=str(update_id),
            from_user=user(),
            chat_instance="1",
            data=data,
            message=Message(
                message_id=50,
                date=datetime.now(UTC),
                chat=Chat(id=CHAT_ID, type="private"),
                text="старое сообщение",
            ),
        ),
    )
