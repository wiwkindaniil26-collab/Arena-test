"""Docker healthcheck: в webhook-режиме проверяем, что порт слушается.

В polling-режиме HTTP-сервера нет, поэтому проверка сразу успешна.
"""

from __future__ import annotations

import os
import socket
import sys


def main() -> int:
    if os.getenv("RUN_MODE", "polling").lower() != "webhook":
        return 0
    port = int(os.getenv("PORT", "8080"))
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=2):
            return 0
    except OSError:
        return 1


if __name__ == "__main__":
    sys.exit(main())
