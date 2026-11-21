"""Stream: brain. Follows the deal call, keeps the checklist of six contract items,
and decides when the Judge speaks and what about.

Listens to call.started, transcript.line, call.ended, judge.spoke (deal calls only).
Sends checklist.updated and judge.speak.

- sage.py     the fast yes/no decisions (Sage2 stream), live or recorded
- values.py   the value of an agreed term (a small OpenAI model), live or recorded
- session.py  one call: transcript in, checklist out
- judge.py    the rules for when to speak, and the instruction text
- tuning.py   every gap and limit

A real call uses live Sage2 and OpenAI. A replayed or fake call (room "replay-..." or
"fake-...") never does: it uses the answers saved in tests/brain/recordings/ when the
deal id starts with a recorded call's name, and otherwise the brain stays quiet. That
keeps `fakes.replayer` free for every stream. To send a replay to the live services,
start the server with BRAIN_LIVE_REPLAYS=1 - each replayed line is one billed Sage2 update.
"""

import logging
import os
from collections.abc import Callable
from pathlib import Path

from fastapi import FastAPI

from app.brain.sage import Decisions, RecordedDecisions, SageStream
from app.brain.session import Session
from app.brain.values import OpenAIValues, RecordedValues, Values
from app.bus import Bus
from app.contracts import CallEnded, CallKind, CallStarted, Event, JudgeSpoke, TranscriptLine

log = logging.getLogger("gawah.brain")

RECORDINGS = Path(__file__).resolve().parents[2] / "tests" / "brain" / "recordings"

Sources = Callable[[CallStarted], tuple[Decisions, Values]]


class Brain:
    def __init__(self, bus: Bus, mode: str, sources: Sources) -> None:
        self.bus, self.mode, self.sources = bus, mode, sources
        self.sessions: dict[str, Session] = {}
        # One subscription for everything, so a call's events are handled in order.
        bus.subscribe_all(self.on_event)

    async def on_event(self, event: Event) -> None:
        session = self.sessions.get(event.deal_id)
        if isinstance(event, CallStarted) and event.kind is CallKind.DEAL:
            if session:
                await session.end()
            decisions, values = self.sources(event)
            session = self.sessions[event.deal_id] = Session(event, self.bus, decisions, values, self.mode)
            await session.start()
        elif session is None:
            return
        elif isinstance(event, TranscriptLine) and event.kind is CallKind.DEAL:
            await session.on_line(event)
        elif isinstance(event, JudgeSpoke):
            session.on_spoke(event)
        elif isinstance(event, CallEnded) and event.kind is CallKind.DEAL:
            del self.sessions[event.deal_id]
            await session.end()

    async def idle(self) -> None:
        """Wait for values still on their way. For tests and the recorder."""
        for session in list(self.sessions.values()):
            await session.idle()


class _Quiet:
    """No decisions and no values: the brain follows the call and says nothing."""

    async def open(self, preamble: str) -> None: ...
    async def append(self, seq: int, text: str) -> None: ...
    async def close(self) -> None: ...
    async def lookup(self, kind, item, transcript: str, at_line: int) -> None: ...


def recorded(name: str) -> tuple[Decisions, Values] | None:
    """The saved answers for a practice call, by the call's name or a deal id that starts with it."""
    for path in sorted(RECORDINGS.glob("*.sage.json")):
        call = path.name.removesuffix(".sage.json")
        if name.startswith(call):
            return RecordedDecisions(path), RecordedValues(RECORDINGS / f"{call}.values.json")
    return None


def register(app: FastAPI, bus: Bus) -> None:
    settings = app.state.settings
    live_replays = os.environ.get("BRAIN_LIVE_REPLAYS") == "1"
    openai: list[OpenAIValues] = []

    def sources(started: CallStarted) -> tuple[Decisions, Values]:
        practice = (started.room or "").startswith(("replay-", "fake-"))
        if practice and not live_replays:
            found = recorded(started.deal_id)
            if found is None:
                log.warning("deal=%s practice call with no recording: the brain stays quiet", started.deal_id)
            return found or (_Quiet(), _Quiet())
        if not openai:
            openai.append(OpenAIValues(settings.require("openai_api_key")))
        return SageStream(settings.require("sage_api_key")), openai[0]

    async def close() -> None:
        for client in openai:
            await client.close()

    Brain(bus, settings.judge_mode, sources)
    app.state.on_shutdown.append(close)
