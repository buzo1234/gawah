"""Plays a practice-call fixture as events: call.started, each transcript.line at the
moment its speaker finishes, then call.ended.

In a test:    await replay(bus, "fixtures/call_missing_balance.json", speed=0)
From a shell: uv run python -m fakes.replayer fixtures/call_missing_balance.json --speed 10
"""

import argparse
import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from pathlib import Path

import httpx

from app.bus import Bus
from app.contracts import CallEnded, CallStarted, Event, Person, TranscriptLine, new_id

Emit = Callable[[Event], Awaitable[None]]


def load(path: str | Path) -> dict:
    return json.loads(Path(path).read_text())


async def play(fixture: dict, emit: Emit, speed: float = 1.0, deal_id: str | None = None) -> str:
    """Send the fixture's events through emit and return the deal id.
    speed=1 is real time, 10 is ten times faster, 0 does not wait at all."""
    deal_id = deal_id or f"{fixture['id']}-{new_id()[:4]}"
    people = [Person(**p) for p in fixture["people"]]
    t0 = time.monotonic()

    async def wait_until(seconds: float) -> None:
        if speed > 0:
            await asyncio.sleep(max(0.0, t0 + seconds / speed - time.monotonic()))

    await emit(CallStarted(deal_id=deal_id, people=people, room=f"replay-{deal_id}"))
    end = 0.0
    for line in fixture["lines"]:
        end = line["end"]
        await wait_until(end)
        await emit(TranscriptLine(deal_id=deal_id, **line))
    await wait_until(end + 1.0)
    await emit(CallEnded(deal_id=deal_id, people=people, room=f"replay-{deal_id}", duration=end, reason="replay"))
    return deal_id


async def replay(bus: Bus, fixture: str | Path | dict, speed: float = 1.0, deal_id: str | None = None) -> str:
    """Play a fixture (a path or an already loaded one) straight onto a bus."""

    async def emit(event: Event) -> None:
        bus.publish(event)

    return await play(fixture if isinstance(fixture, dict) else load(fixture), emit, speed, deal_id)


async def _replay_to_server(path: str, url: str, speed: float, deal_id: str | None) -> None:
    async with httpx.AsyncClient(base_url=url, timeout=5.0) as client:

        async def emit(event: Event) -> None:
            response = await client.post(
                "/dev/publish", content=event.model_dump_json(), headers={"content-type": "application/json"}
            )
            response.raise_for_status()
            text = f"{event.speaker}: {event.text}" if isinstance(event, TranscriptLine) else ""
            print(f"deal={event.deal_id} {event.name} {text}".rstrip(), flush=True)

        try:
            await play(load(path), emit, speed, deal_id)
        except httpx.ConnectError:
            raise SystemExit(f"No server at {url}. Start it: uv run uvicorn app.main:app --reload --port 8000")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Replay a practice call into a running server.")
    parser.add_argument("fixture", help="fixtures/<call>.json")
    parser.add_argument("--speed", type=float, default=1.0, help="1 = real time, 10 = ten times faster, 0 = no waiting")
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument("--deal-id", default=None)
    args = parser.parse_args()
    asyncio.run(_replay_to_server(args.fixture, args.url, args.speed, args.deal_id))
