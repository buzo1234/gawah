"""Stream: mouth. Gawah's voice on the deal call, and the one-to-one call-back.

On the deal call it listens to call.started, call.ended, judge.speak and checklist.updated,
and sends judge.spoke (an empty one with no start time for a question it dropped, so the
brain stops waiting). On the call-back it sends call.started and call.ended (kind
callback), record.confirmed, terms.confirmed and terms.disputed.

- tuning.py     every delay, threshold and persona
- room.py       LiveKit: Gawah's seat in a room, tokens, opening and closing rooms
- realtime.py   OpenAI: the connection to the realtime voice model
- hearing.py    who is talking, from loudness
- player.py     speech into the room at the speed it is spoken
- voice.py      one instruction in, one spoken reply out (the deal call)
- deal_call.py  one deal call: pick the moment, speak, stop if talked over
- script.py     the call-back's steps and what came of them
- callback.py   one call-back: a real conversation, with tools to report the outcome

A replayed or fake call (room "replay-..." or "fake-...") has no room to join, so the
mouth stays out of it, as the brain stays off the live services for those.
"""

import asyncio
import logging
from collections.abc import Callable

from fastapi import FastAPI

from app.bus import Bus
from app.contracts import CallEnded, CallKind, CallStarted, ChecklistUpdated, Event, JudgeSpeak
from app.mouth import callback
from app.mouth.deal_call import DealCall
from app.mouth.realtime import Realtime
from app.mouth.room import Rooms, Seat

log = logging.getLogger("gawah.mouth")

PRACTICE = ("replay-", "fake-")


class Mouth:
    """The deal calls Gawah is on, by deal."""

    def __init__(self, bus: Bus, make_seat: Callable, make_link: Callable) -> None:
        self.bus, self.make_seat, self.make_link = bus, make_seat, make_link
        self.calls: dict[str, DealCall] = {}
        self._ending: set[asyncio.Task] = set()
        # One subscription for everything, so a call's events are handled in order.
        bus.subscribe_all(self.on_event)

    async def on_event(self, event: Event) -> None:
        call = self.calls.get(event.deal_id)
        if isinstance(event, CallStarted) and event.kind is CallKind.DEAL:
            await self._start(event, call)
        elif call is None:
            return
        elif isinstance(event, ChecklistUpdated):
            call.checklist = event
        elif isinstance(event, JudgeSpeak):
            call.on_speak(event)
        elif isinstance(event, CallEnded) and event.kind is CallKind.DEAL:
            await self._end(call)

    async def _start(self, started: CallStarted, running: DealCall | None) -> None:
        if not started.room or started.room.startswith(PRACTICE):
            return
        if running:
            if running.room_name == started.room:
                return
            await self._end(running)
        try:
            call = DealCall(started, self.bus, self.make_seat, self.make_link)
            call.on_over = self._over
            await call.start()
        except Exception as e:
            log.error("deal=%s Gawah has no voice on this call: %s: %s", started.deal_id, type(e).__name__, str(e)[:200])
            return
        self.calls[started.deal_id] = call

    def _over(self, call: DealCall, why: str) -> None:
        """The call is over without a call.ended: never stay sitting in a room."""
        call.log.warning("leaving: %s", why)
        task = asyncio.create_task(self._end(call))
        self._ending.add(task)
        task.add_done_callback(self._ending.discard)

    async def _end(self, call: DealCall) -> None:
        if self.calls.get(call.deal_id) is call:
            del self.calls[call.deal_id]
        await call.end()

    async def close(self) -> None:
        for call in list(self.calls.values()):
            await self._end(call)


def register(app: FastAPI, bus: Bus) -> None:
    settings = app.state.settings

    # Keys are read when a call starts, so a missing one stops that call and not the server.
    def rooms() -> Rooms:
        return Rooms(
            settings.require("livekit_url"), settings.require("livekit_api_key"), settings.require("livekit_api_secret")
        )

    def make_seat(call_log: logging.LoggerAdapter) -> Seat:
        return Seat(rooms(), call_log)

    def make_link(config: dict, on_event, call_log: logging.LoggerAdapter) -> Realtime:
        return Realtime(settings.require("openai_api_key"), config, on_event, call_log)

    mouth = Mouth(bus, make_seat, make_link)
    app.state.mouth = mouth
    app.state.on_shutdown.append(mouth.close)
    callback.register(app, bus, rooms, make_seat, make_link)
