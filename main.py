import asyncio

from bot_core import close_resources, process_update, setup_bot, tg


POLL = __import__("os").getenv("POLLING_TIMEOUT", "30")
POLL = int(POLL)


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
