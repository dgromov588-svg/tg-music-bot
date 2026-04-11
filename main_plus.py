import asyncio
import os

from bot_plus import close_resources, process_update, setup_bot
from bot_core import tg

POLL = int(os.getenv("POLLING_TIMEOUT", "30"))


async def main():
    await setup_bot()
    offset = None
    while True:
        try:
            updates = await tg(
                "getUpdates",
                {
                    "offset": offset,
                    "timeout": POLL,
                    "allowed_updates": ["message", "callback_query"],
                },
            )
            for update in updates:
                offset = update["update_id"] + 1
                await process_update(update)
        except Exception:
            await asyncio.sleep(3)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    finally:
        try:
            asyncio.run(close_resources())
        except Exception:
            pass
