"""``python -m bot`` — тот же запуск, что и ``python -m bot.main``."""

from bot.main import main

if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
