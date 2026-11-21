"""Stream: brain. Follows the deal call, keeps the checklist of six contract items,
and decides when the Judge speaks and what about.

Listens to call.started, transcript.line, call.ended, judge.spoke (deal calls only), and
fact.recorded and fact.conflict from the memory. Sends checklist.updated and judge.speak,
and call.started again (same room, same call_no) when it learns a name on the call that
the deal did not have.

- facts.py    the checklist from the memory's facts: an item is agreed when its current fact is
- sage.py     the fast yes/no signals (Sage2 stream), live or recorded: when to look
- values.py   names, the term left unclear, and two meanings of an agreed term (a small OpenAI model)
- session.py  one call: transcript and facts in, checklist and judge.speak out
- judge.py    the rules for when to speak, and the instruction text
- tuning.py   every gap and limit

Sage2 is asked only what the brain reads (sage.QUESTIONS): who spoke to Gawah, a term left
unclear or a balance skipped, and whether they are closing. Only the memory's facts make a
term agreed; recordings made when the term questions were also asked still replay, their
extra answers unread. With no memory (app.state.memory missing, as in the brain's own rule tests) the
brain takes facts only from fact.recorded events; with none of those either, every item
stays pending and the Judge, seeing the memory silent, asks nothing at wrap-up and only
answers people who speak to it. There is no fallback to Sage2's answers.

A deal's facts are kept across its calls. On a second call the checklist starts where the
first left it: agreed terms stay agreed and are not asked again, and the read-back at the
end covers only what changed on this call, if anything did.

A real call uses live Sage2 and OpenAI. A replayed or fake call (room "replay-..." or
"fake-...") never does: it uses the answers saved in tests/brain/recorded/ for the
practice call that says the same lines, whatever the deal id, and otherwise the brain
stays quiet. That keeps `fakes.replayer` free for every stream. To send a replay to the
live services, start the server with BRAIN_LIVE_REPLAYS=1 - each replayed line is one
billed Sage2 update.
"""

import logging
import os
from collections.abc import Callable
from pathlib import Path

from fastapi import FastAPI

from app.brain.facts import Terms
from app.brain.sage import Answers, Decisions, RecordedDecisions, SageStream
from app.brain.session import Session
from app.brain.values import OpenAIValues, RecordedValues, Values
from app.bus import Bus
from app.contracts import (
    MEMORY_STATE, CallEnded, CallKind, CallStarted, Event, FactConflict, FactRecorded, JudgeSpoke, MemoryQueries,
    TranscriptLine,
)
from app.log import deal_log

RECORDINGS = Path(__file__).resolve().parents[2] / "tests" / "brain" / "recorded"

Sources = Callable[[CallStarted], tuple[Decisions, Values]]


class Brain:
    def __init__(self, bus: Bus, mode: str, sources: Sources, memory: MemoryQueries | None = None) -> None:
        self.bus, self.mode, self.sources, self.memory = bus, mode, sources, memory
        self.sessions: dict[str, Session] = {}
        self.terms: dict[str, Terms] = {}  # deal id -> its facts, across calls
        self.checked: dict[str, set[str]] = {}  # deal id -> fact ids checked for two meanings
        # One subscription for everything, so a call's events are handled in order.
        bus.subscribe_all(self.on_event)

    async def on_event(self, event: Event) -> None:
        session = self.sessions.get(event.deal_id)
        if isinstance(event, FactRecorded):
            if self.terms.setdefault(event.deal_id, Terms()).add(event.fact) and session:
                session.on_fact(event.fact)
        elif isinstance(event, CallStarted) and event.kind is CallKind.DEAL:
            if session and session.room == event.room:
                session.meet(event.people)  # sent again with a name learned on the call
                return
            if session:
                await session.end()
            terms = self.terms.setdefault(event.deal_id, Terms())
            if self.memory is not None:
                await terms.seed(self.memory, event.deal_id)
            decisions, values = self.sources(event)
            session = self.sessions[event.deal_id] = Session(
                event, self.bus, decisions, values, self.mode, terms, self.checked.setdefault(event.deal_id, set()),
            )
            await session.start()
        elif session is None:
            return
        elif isinstance(event, TranscriptLine) and event.kind is CallKind.DEAL:
            await session.on_line(event)
        elif isinstance(event, FactConflict) and event.call_no == session.call_no:
            session.on_conflict(event)
        elif isinstance(event, JudgeSpoke):
            session.on_spoke(event)
        elif isinstance(event, CallEnded) and event.kind is CallKind.DEAL:
            del self.sessions[event.deal_id]
            await session.end()

    async def idle(self) -> None:
        """Wait for model replies still on their way. For tests and the recorder."""
        for session in list(self.sessions.values()):
            await session.idle()


class _Saved:
    """The practice calls' saved answers, given to a call for as long as it says the same
    lines: a saved call answers while every line so far is the line it was recorded on.
    Nothing else picks it, so a practice call can be replayed into any deal. Once no saved
    call fits, or with none to start from, the brain follows the call and says nothing."""

    def __init__(self, calls: list[tuple[RecordedDecisions, RecordedValues]], log: logging.LoggerAdapter) -> None:
        self.calls, self.log = calls, log

    async def open(self, preamble: str) -> None: ...

    async def append(self, seq: int, text: str) -> Answers | None:
        # By the words alone: a call from a WhatsApp deal may not know the worker's name yet.
        fits = [call for call in self.calls if _words(call[0].lines.get(str(seq))) == _words(text)]
        if self.calls and not fits:
            self.log.warning("line %s is in no recorded practice call: the brain stays quiet", seq)
        self.calls = fits
        return await fits[0][0].append(seq, text) if fits else None

    async def close(self) -> None: ...

    async def lookup(self, kind, item, transcript: str, at_line: int) -> dict | None:
        return await self.calls[0][1].lookup(kind, item, transcript, at_line) if self.calls else None


def _words(line: str | None) -> str | None:
    """A line as sent to Sage2 ("Name: words"), without the name."""
    return line.split(": ", 1)[-1] if line else None


def saved(started: CallStarted) -> tuple[Decisions, Values]:
    """The practice calls' saved answers, for a call in any room. The offline app gives every call these."""
    found = _Saved(recorded(), deal_log("gawah.brain", started.deal_id))
    return found, found


def recorded() -> list[tuple[RecordedDecisions, RecordedValues]]:
    """Every practice call's saved answers."""
    return [
        (RecordedDecisions(path), RecordedValues(path.with_name(path.name.replace(".sage.", ".values."))))
        for path in sorted(RECORDINGS.glob("*.sage.json"))
    ]


def register(app: FastAPI, bus: Bus) -> None:
    settings = app.state.settings
    live_replays = os.environ.get("BRAIN_LIVE_REPLAYS") == "1"
    openai: list[OpenAIValues] = []

    def sources(started: CallStarted) -> tuple[Decisions, Values]:
        log = deal_log("gawah.brain", started.deal_id)
        practice = (started.room or "").startswith(("replay-", "fake-"))
        if practice and not live_replays:
            return saved(started)
        try:
            sage_key, openai_key = settings.require("sage_api_key"), settings.require("openai_api_key")
        except RuntimeError as missing:
            log.error("%s: the brain cannot follow this call and stays quiet", missing)
            quiet = _Saved([], log)
            return quiet, quiet
        if not openai:
            openai.append(OpenAIValues(openai_key))
        return SageStream(sage_key, log=deal_log("gawah.brain.sage", started.deal_id)), openai[0]

    async def close() -> None:
        for client in openai:
            await client.close()

    # Memory registers before the brain (app/main.py), so it is there when it is wanted.
    app.state.brain = Brain(bus, settings.judge_mode, sources, getattr(app.state, MEMORY_STATE, None))
    app.state.on_shutdown.append(close)
