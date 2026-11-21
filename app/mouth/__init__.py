"""Stream: mouth. Gawah's voice on the deal call, and the one-to-one call-back.

On the deal call it listens to call.started, call.ended, judge.speak, checklist.updated,
transcript.line, fact.recorded and fact.conflict, and sends judge.spoke (an empty one with
no start time for a question it dropped, so the brain stops waiting), fact.changed for a
change agreed by voice, and agent.note for the dashboard. With JUDGE_MODE=live Gawah is
an agent with tools over memory (app.state.memory); with wrapup it is the plain voice. On the call-back it sends call.started and call.ended (kind
callback), record.confirmed, terms.confirmed and terms.disputed.

- tuning.py     every delay, threshold and persona
- room.py       LiveKit: Gawah's seat in a room, tokens, opening and closing rooms
- realtime.py   OpenAI: the connection to the realtime voice model
- hearing.py    who is talking, from loudness
- player.py     speech into the room at the speed it is spoken
- voice.py      one instruction in, one spoken reply out (the deal call, JUDGE_MODE=wrapup)
- agent.py      Gawah the agent: the call as text, a turn per moment, tool calls (JUDGE_MODE=live)
- tools.py      the agent's tools: memory lookups, clips, changes agreed by voice
- moments.py    the words the agent is given: lines, facts, moments to speak
- deal_call.py  one deal call: pick the moment, speak, stop if talked over (the plain voice)
- agent_call.py the same, with Gawah as the agent: follows the call, answers when spoken to
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
from app.contracts import (
    MEMORY_STATE, CallEnded, CallKind, CallStarted, ChecklistUpdated, Event, FactConflict, FactRecorded, JudgeSpeak,
    MemoryQueries, TranscriptLine,
)
from app.mouth import callback
from app.mouth.agent_call import AgentCall
from app.mouth.deal_call import DealCall
from app.mouth.realtime import Realtime
from app.mouth.room import Rooms, Seat

log = logging.getLogger("gawah.mouth")

PRACTICE = ("replay-", "fake-")


class Mouth:
    """The deal calls Gawah is on, by deal."""

    def __init__(
        self, bus: Bus, make_seat: Callable, make_link: Callable, mode: str = "live",
        memory: Callable[[], MemoryQueries | None] = lambda: None,
    ) -> None:
        self.bus, self.make_seat, self.make_link = bus, make_seat, make_link
        self.mode, self.memory = mode, memory  # mode is JUDGE_MODE: "live" makes Gawah an agent
        self.rooms: Callable = lambda: None  # the call-back's rooms; set by register
        self.calls: dict[str, DealCall] = {}
        self._seen: set[str] = set()  # deal-call rooms already started
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
        elif isinstance(event, TranscriptLine):
            await call.on_line(event)
        elif isinstance(event, (FactRecorded, FactConflict)):
            await call.on_fact(event)
        elif isinstance(event, CallEnded) and event.kind is CallKind.DEAL:
            await self._end(call)

    async def _start(self, started: CallStarted, running: DealCall | None) -> None:
        if not started.room or started.room.startswith(PRACTICE):
            return
        if started.room in self._seen:
            # The brain sends call.started again when it learns a name: take the name, never rejoin.
            if running and running.room_name == started.room:
                running.meet(started.people)
            return
        self._seen.add(started.room)
        if running:
            await self._end(running)
        try:
            if self.mode == "live":
                call = AgentCall(started, self.bus, self.make_seat, self.make_link, memory=self.memory)
            else:
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

    mouth = Mouth(bus, make_seat, make_link, settings.judge_mode, lambda: getattr(app.state, MEMORY_STATE, None))
    mouth.rooms = rooms
    app.state.mouth = mouth
    app.state.on_shutdown.append(mouth.close)
    # Through the Mouth, so tests/offline.py can swap all three for fakes once the app is built.
    callback.register(
        app, bus, lambda: mouth.rooms(), lambda log: mouth.make_seat(log),
        lambda config, on_event, log: mouth.make_link(config, on_event, log),
    )
