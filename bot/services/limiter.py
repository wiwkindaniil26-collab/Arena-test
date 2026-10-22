"""Антифлуд: не больше N тяжёлых операций за окно времени на пользователя."""

from __future__ import annotations

import time
from collections import defaultdict, deque


class RateLimiter:
    """Скользящее окно в памяти процесса.

    Достаточно для одного инстанса бота; для нескольких — нужен Redis.
    """

    def __init__(self, limit: int = 10, window: int = 60) -> None:
        self.limit = max(1, limit)
        self.window = max(1, window)
        self._events: dict[int, deque[float]] = defaultdict(deque)

    def remaining(self, user_id: int) -> int:
        timestamps = self._prune(user_id)
        return max(0, self.limit - len(timestamps))

    def check(self, user_id: int) -> bool:
        """True, если операцию можно выполнять (и она сразу учитывается)."""
        timestamps = self._prune(user_id)
        if len(timestamps) >= self.limit:
            return False
        timestamps.append(time.monotonic())
        return True

    def retry_after(self, user_id: int) -> int:
        timestamps = self._prune(user_id)
        if len(timestamps) < self.limit:
            return 0
        oldest = timestamps[0]
        return max(1, int(self.window - (time.monotonic() - oldest)) + 1)

    def _prune(self, user_id: int) -> deque[float]:
        timestamps = self._events[user_id]
        threshold = time.monotonic() - self.window
        while timestamps and timestamps[0] <= threshold:
            timestamps.popleft()
        return timestamps
