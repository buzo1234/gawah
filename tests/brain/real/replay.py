"""Replay one of the user's real deals (a fixture made by extract.py) through the brain.

Each deal call's lines go in as they came, with what Gawah said on the real call (judge.spoke) and
memory's facts and conflicts as memory sent them then, so the brain sees the record as it stood.
The brain's model lookups answer from tests/brain/real/recorded/ (record them with
`uv run python -m tests.brain.real.replay record <deal>`: live OpenAI, a few small-model calls).

Sage2's answers were not kept on those calls. A stand-in gives the yeses the real brain acted on:
addressed_gawah on a line it answered as spoken to, wrapping_up on a line it wrapped up after,
balance_skipped on a line it asked the balance after; a test may add more, and says why.
Where the next line starts PAUSE_S or more after a line ends, the brain is told a pause passed.
Gawah's turns the brain asks for here are taken as said at once, as a quick mouth would.
"""

import asyncio
import json
import sys
from pathlib import Path

from app.brain import Brain, sage, tuning
from app.brain.values import OpenAIValues, RecordedValues
from app.bus import Bus
from app.config import get_settings
from app.contracts import (
    CallEnded, CallStarted, Fact, FactConflict, FactRecorded, JudgeSpeak, JudgeSpoke, Person, TranscriptLine,
)
from tests.brain.record import _Saving

HERE = Path(__file__).parent
RECORDED = HERE / "recorded"
FROM_REAL = {"addressed_directly": "addressed_gawah", "wrapping_up": "wrapping_up", "term_unclear": "balance_skipped"}


def load(deal: str) -> dict:
    return json.loads((HERE / f"{deal}.json").read_text())


class StandIn:
    """Sage2's yeses by line, for one call."""

    def __init__(self, yeses: dict[int, set[str]]) -> None:
        self.yeses = yeses

    async def open(self, preamble: str):
        return {}

    async def append(self, seq: int, text: str):
        return {q: 1.0 if q in self.yeses.get(seq, set()) else 0.0 for q in sage.QUESTIONS}

    async def close(self) -> None: ...


def yeses(fixture: dict, add: dict[tuple[int, int], set[str]] | None = None) -> dict[int, dict[int, set[str]]]:
    """(call no) -> line -> the questions Sage2 said yes to, as the real brain's actions show, plus `add`."""
    found: dict[int, dict[int, set[str]]] = {}
    call = 1
    for e in fixture["events"]:
        if e["kind"] == "started":
            call = e["call_no"]
        if e["kind"] == "speak" and e["reason"] in FROM_REAL and e["after_line"] is not None:
            if e["reason"] == "term_unclear" and e["item"] != "balance":
                continue
            found.setdefault(call, {}).setdefault(e["after_line"], set()).add(FROM_REAL[e["reason"]])
    for (n, line), qs in (add or {}).items():
        found.setdefault(n, {}).setdefault(line, set()).update(qs)
    return found


def values_path(deal: str, call_no: int) -> Path:
    return RECORDED / f"{deal}-{call_no}.values.json"


class Replay:
    def __init__(self, deal: str, add: dict | None = None, values: dict | None = None) -> None:
        self.fixture = load(deal)
        self.deal = deal
        self.people = [Person(**p) for p in self.fixture["people"]]
        self.yeses = yeses(self.fixture, add)
        self.values = values or {}
        self.speaks: list[tuple[int, JudgeSpeak]] = []  # (call no, judge.speak)
        self.bus = Bus()

    def _values(self, call_no: int):
        if call_no not in self.values:
            path = values_path(self.deal, call_no)
            self.values[call_no] = RecordedValues(path) if path.exists() else _Nothing()
        return self.values[call_no]

    async def run(self, upto: tuple[int, int] | None = None) -> "Replay":
        bus = self.bus
        brain = Brain(bus, "live", lambda started: (StandIn(self.yeses.get(started.call_no, {})), self._values(started.call_no)))
        call_no = 1

        async def collect(event) -> None:
            if isinstance(event, JudgeSpeak):
                self.speaks.append((call_no, event))
                bus.publish(JudgeSpoke(deal_id=event.deal_id, text="", speak_id=event.event_id, reason=event.reason,
                                       item=event.item, start=0.0, end=0.0))

        bus.subscribe(JudgeSpeak, collect)
        bus.start()
        events = self.fixture["events"]
        for i, e in enumerate(events):
            kind = e["kind"]
            if kind == "started":
                call_no = e["call_no"]
                await self._emit(brain, CallStarted(deal_id=self.deal, people=self.people, room=self._room(call_no), call_no=call_no))
                brain.sessions[self.deal].pause_timer = False
            elif kind == "ended":
                await self._emit(brain, CallEnded(deal_id=self.deal, people=self.people, room=self._room(e["call_no"]),
                                                   call_no=e["call_no"], reason="replay"))
            elif kind == "line":
                await self._emit(brain, TranscriptLine(deal_id=self.deal, **{k: e[k] for k in ("call_no", "line_no", "speaker", "text", "start", "end")}))
                if upto and (e["call_no"], e["line_no"]) >= upto:
                    break
                later = [x["start"] for x in events[i + 1:] if x["kind"] == "line" and x["call_no"] == e["call_no"]]
                ended = next((x for x in events[i + 1:] if x["kind"] in ("ended", "line")), None)
                gap = (min(later) if later else e["end"] + 1.0) - e["end"]
                session = brain.sessions.get(self.deal)
                if session and gap >= tuning.PAUSE_S and (ended is None or ended["kind"] == "line" or later):
                    # Facts that came in during the pause land first, as they would on the call.
                    for x in events[i + 1:]:
                        if x["kind"] == "line" or x["kind"] in ("started", "ended"):
                            break
                        if x["kind"] == "fact":
                            x["_sent"] = True
                            await self._emit(brain, FactRecorded(deal_id=self.deal, fact=Fact(**x["fact"])))
                    session.pause_passed()
                    await self._emit(brain, None)
            elif kind == "fact" and not e.pop("_sent", False):
                await self._emit(brain, FactRecorded(deal_id=self.deal, fact=Fact(**e["fact"])))
            elif kind == "conflict":
                await self._emit(brain, FactConflict(deal_id=self.deal, **{k: e[k] for k in ("fact_ids", "explanation", "said", "speaker", "call_no", "line_no")}))
            elif kind == "spoke":
                await self._emit(brain, JudgeSpoke(deal_id=self.deal, **{k: e[k] for k in ("text", "start", "end", "clip_fact_id")}))
        await bus.stop()
        for e in events:
            e.pop("_sent", None)
        return self

    def _room(self, call_no: int) -> str:
        return f"replay-real-{self.deal}-{call_no}"

    async def _emit(self, brain: Brain, event) -> None:
        if event is not None:
            self.bus.publish(event)
        for _ in range(3):
            await self.bus.drain(30)
            await brain.idle()

    def said(self, call_no: int) -> list[tuple]:
        return [(s.after_line, s.reason.value, s.item.value if s.item else None) for n, s in self.speaks if n == call_no]

    def speak(self, call_no: int, after_line: int) -> list[JudgeSpeak]:
        return [s for n, s in self.speaks if n == call_no and s.after_line == after_line]

    def missing(self) -> list[str]:
        return [k for v in self.values.values() for k in getattr(v, "missing", [])]


class _Nothing:
    missing: list[str] = []

    async def lookup(self, kind, item, transcript, at_line):
        raise LookupError("nothing recorded")


async def record(deal: str) -> None:
    """The brain's model lookups on every call of the deal, from the live model, saved."""
    tuning.LOOKUP_WAIT_S = 30.0
    openai = OpenAIValues(get_settings().require("openai_api_key"))
    fixture = load(deal)
    calls = sorted({e["call_no"] for e in fixture["events"] if e["kind"] == "started"})
    savings = {}
    for n in calls:
        path = values_path(deal, n)
        savings[n] = _Saving(openai, json.loads(path.read_text())["replies"] if path.exists() else None)
    replay = await Replay(deal, values=savings).run()
    RECORDED.mkdir(exist_ok=True)
    for n, saving in savings.items():
        values_path(deal, n).write_text(json.dumps({"fixture": f"{deal}-{n}", "model": tuning.VALUES_MODEL,
                                                    "replies": saving.saved | saving.replies}, ensure_ascii=False, indent=1) + "\n")
    await openai.close()
    for n in calls:
        print(f"call {n}:", replay.said(n))
    print(f"openai calls: {openai.calls}")


if __name__ == "__main__":
    if sys.argv[1] == "record":
        asyncio.run(record(sys.argv[2]))
    else:
        replay = asyncio.run(Replay(sys.argv[1]).run())
        for n in sorted({n for n, _ in replay.speaks}):
            for s in [s for m, s in replay.speaks if m == n]:
                print(f"call {n} after {s.after_line}: {s.reason.value} {s.item.value if s.item else '-'} | {s.instruction[:220]}")
