from __future__ import annotations

import pytest

from bot.handlers import common
from bot.handlers import library as library_handlers
from bot.handlers import music as music_handlers
from bot.handlers import random_track as random_handlers

_ROUTER_MODULES = (common, random_handlers, library_handlers, music_handlers)


@pytest.fixture(autouse=True)
def _detach_routers():
    """Роутеры — модульные синглтоны; перед каждым тестом отвязываем их от
    предыдущего Dispatcher, чтобы можно было собрать новый."""
    for module in _ROUTER_MODULES:
        module.router._parent_router = None
    yield
