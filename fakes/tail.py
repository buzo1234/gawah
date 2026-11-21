"""Prints every event from a running server, one JSON object per line. It reads the
same websocket the dashboard page does, so it is the dashboard for a terminal.

    uv run python -m fakes.tail
"""

import argparse
import asyncio

from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed


async def tail(url: str) -> None:
    try:
        async with connect(url) as ws:
            async for message in ws:
                print(message, flush=True)
    except ConnectionClosed:
        pass
    except OSError:
        raise SystemExit(f"No server at {url}. Start it: uv run uvicorn app.main:app --reload --port 8000")
    raise SystemExit("The server closed the connection (it stopped or reloaded). Run the tail again.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Print every event from a running server.")
    parser.add_argument("--url", default="ws://localhost:8000/dashboard/ws")
    try:
        asyncio.run(tail(parser.parse_args().url))
    except KeyboardInterrupt:
        pass
