"""Prints every event from a running server, one JSON object per line. It reads the
same websocket the dashboard page does, so it is the dashboard for a terminal.

    uv run python -m fakes.tail
"""

import argparse
import asyncio

from websockets.asyncio.client import connect


async def tail(url: str) -> None:
    async with connect(url) as ws:
        async for message in ws:
            print(message, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Print every event from a running server.")
    parser.add_argument("--url", default="ws://localhost:8000/dashboard/ws")
    try:
        asyncio.run(tail(parser.parse_args().url))
    except KeyboardInterrupt:
        pass
