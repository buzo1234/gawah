"""Spike helpers: read .env, mint tokens, open and close LiveKit rooms, count minutes."""

import json
import secrets
import time
from datetime import timedelta
from pathlib import Path

from livekit import api

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
OUT = HERE / "out"
RESULTS = HERE / "results"
USAGE_LOG = RESULTS / "usage.jsonl"
T0 = time.monotonic()


def now() -> float:
    """Seconds since this process started. One clock for every measurement."""
    return round(time.monotonic() - T0, 4)


def env() -> dict[str, str]:
    values = {}
    for line in (ROOT / ".env").read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip().strip('"').strip("'")
    return values


ENV = env()
LIVEKIT_URL = ENV["LIVEKIT_URL"]


def token(room: str, identity: str, publish: bool = True) -> str:
    grants = api.VideoGrants(
        room_join=True, room=room, can_publish=publish, can_subscribe=True
    )
    return (
        api.AccessToken(ENV["LIVEKIT_API_KEY"], ENV["LIVEKIT_API_SECRET"])
        .with_identity(identity)
        .with_name(identity)
        .with_ttl(timedelta(minutes=15))
        .with_grants(grants)
        .to_jwt()
    )


def _api() -> api.LiveKitAPI:
    return api.LiveKitAPI(
        LIVEKIT_URL, ENV["LIVEKIT_API_KEY"], ENV["LIVEKIT_API_SECRET"]
    )


async def open_room(prefix: str) -> str:
    name = f"spike-{prefix}-{secrets.token_hex(3)}"
    lk = _api()
    try:
        await lk.room.create_room(
            api.CreateRoomRequest(
                name=name, empty_timeout=30, departure_timeout=15, max_participants=6
            )
        )
    finally:
        await lk.aclose()
    return name


async def close_room(name: str) -> None:
    lk = _api()
    try:
        await lk.room.delete_room(api.DeleteRoomRequest(room=name))
    except Exception as exc:  # already gone is fine
        print(f"close_room({name}): {type(exc).__name__}: {exc}")
    finally:
        await lk.aclose()


async def list_rooms() -> list[str]:
    lk = _api()
    try:
        rooms = await lk.room.list_rooms(api.ListRoomsRequest())
        return [f"{r.name} ({r.num_participants} in room)" for r in rooms.rooms]
    finally:
        await lk.aclose()


def log_usage(room: str, label: str, seconds_by_identity: dict[str, float]) -> float:
    """Append this room's participant-minutes to results/usage.jsonl and return them."""
    RESULTS.mkdir(exist_ok=True)
    minutes = round(sum(seconds_by_identity.values()) / 60, 2)
    with USAGE_LOG.open("a") as f:
        f.write(
            json.dumps(
                {
                    "room": room,
                    "label": label,
                    "participant_minutes": minutes,
                    "seconds": {k: round(v, 1) for k, v in seconds_by_identity.items()},
                }
            )
            + "\n"
        )
    return minutes
