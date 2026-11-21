"""Prints every event from a running server, one JSON object per line. It reads the
same websocket the dashboard page does, so it is the dashboard for a terminal.

    uv run python -m fakes.tail
    uv run python -m fakes.tail --url http://localhost:8000
"""

import argparse
import asyncio
from urllib.parse import urlsplit, urlunsplit

from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed, WebSocketException

SOCKET_PATH = "/dashboard/ws"


def socket_url(url: str) -> str:
    """The dashboard websocket for a server, given the same http address the replayer
    takes, or a ws address with or without the path."""
    parts = urlsplit(url)
    scheme = {"http": "ws", "https": "wss"}.get(parts.scheme, parts.scheme)
    path = parts.path.rstrip("/")
    if not path.endswith(SOCKET_PATH):
        path += SOCKET_PATH
    return urlunsplit((scheme, parts.netloc, path, "", ""))


async def tail(url: str) -> None:
    try:
        async with connect(socket_url(url)) as ws:
            async for message in ws:
                print(message, flush=True)
    except ConnectionClosed:
        pass
    except OSError:
        raise SystemExit(f"No server at {url}. Start it: uv run uvicorn app.main:app --reload --port 8000")
    except WebSocketException as e:
        raise SystemExit(f"Could not open the event socket at {url}: {e}")
    raise SystemExit("The server closed the connection (it stopped or reloaded). Run the tail again.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Print every event from a running server.")
    parser.add_argument("--url", default="http://localhost:8000", help="the server, as for fakes.replayer")
    try:
        asyncio.run(tail(parser.parse_args().url))
    except KeyboardInterrupt:
        pass
