"""Мидлвари: белый список пользователей."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject, User

logger = logging.getLogger(__name__)


class AccessMiddleware(BaseMiddleware):
    """Если задан ALLOWED_USERS — пускаем только перечисленных.

    Пустой список означает «бот открыт для всех».
    """

    def __init__(self, allowed_users: frozenset[int] | set[int] | None = None) -> None:
        self.allowed_users = frozenset(allowed_users or ())

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not self.allowed_users:
            return await handler(event, data)

        user: User | None = data.get("event_from_user")
        if user is None:
            user = getattr(event, "from_user", None)

        if user is not None and user.id in self.allowed_users:
            return await handler(event, data)

        if isinstance(event, CallbackQuery):
            await event.answer("⛔ Бот в закрытом режиме.", show_alert=True)
        elif isinstance(event, Message):
            await event.answer("⛔ Бот в закрытом режиме. Попроси доступ у владельца.")
        if user is not None:
            logger.info("Отказано в доступе пользователю %s", user.id)
        return None
