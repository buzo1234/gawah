"""The tuned Judge on held-out calls: record once, then score.

    uv run python -m tests.brain.holdout.run sage fixtures/holdout2/<call>.json     # live Sage2: one update per line plus one
    uv run python -m tests.brain.holdout.run scribe fixtures/holdout2/<call>.json   # live Scribe, the whole deal the call is in
    uv run python -m tests.brain.holdout.run values fixtures/holdout2/<call>.json   # live OpenAI lookups, the whole deal
    uv run python -m tests.brain.holdout.run score [seen|fresh|all] [report.json]   # no outside calls

Two sets: "seen" is fixtures/holdout/ (its failures guided later fixes, so its score is not
an honest one) and "fresh" is fixtures/holdout2/. Calls that share a `deal` (the mason pair)
are replayed as calls 1, 2, ... of one deal through one brain and one memory, so the memory
and the checklist carry over. Each call starts on its `call_date`, which anchors "kal" and
"Monday" for the memory and Sage2.

Recordings live in tests/brain/holdout/recorded/, not tests/brain/recorded/, so the offline
app and the practice-call tests never answer from them. The Scribe's replies for the seen set
are in recorded/scribe/ (all calls in one folder); for the fresh set in recorded/scribe2/<deal>/,
one folder per deal so a line said on two calls never borrows another call's reply. `values`
replays the deal three ways (live mode, wrapup mode, and live mode with no names known at the
start of call 1, as a WhatsApp deal starts) and saves every lookup each one makes. `score`
replays the same three on the saved answers and scores them against each fixture's `expected`
and `must_stay_silent`, and prints the memory's terms at the end of every call.
"""

import asyncio
import json
import sys
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from zoneinfo import ZoneInfo

from app.brain import Brain, sage, tuning
from app.brain.values import OpenAIValues, RecordedValues
from app.bus import Bus
from app.config import get_settings
from app.contracts import CallEnded, CallStarted, ChecklistUpdated, FactConflict, ItemKey, JudgeSpeak, Person, Role, TranscriptLine
from app.memory.extract import RecordedExtractor, Routed
from fakes.replayer import load
from tests.brain.record import _Saving
from tests.brain.replaying import Run, memory_on, play, settling

OUT = Path(__file__).parent / "recorded"
SETS = {"seen": Path("fixtures/holdout"), "fresh": Path("fixtures/holdout2")}
SAGE_BUDGET = 220  # Sage2 updates allowed for recording the fresh set
VARIANTS = {"live": ("live", True), "wrapup": ("wrapup", True), "unnamed": ("live", False)}
_PREAMBLE = sage.preamble


def people(fixture: dict, named: bool) -> list[Person]:
    return [Person(**(p if named else {**p, "name": None})) for p in fixture["people"]]


def deal_of(path: Path) -> list[Path]:
    """The calls of the deal this call is in, call 1 first."""
    fixture = load(path)
    if "deal" not in fixture:
        return [path]
    calls = [(load(p).get("call_no", 1), p) for p in sorted(path.parent.glob("*.json")) if load(p).get("deal") == fixture["deal"]]
    return [p for _, p in sorted(calls)]


def deals(folder: Path) -> list[list[Path]]:
    found: list[list[Path]] = []
    for path in sorted(folder.glob("*.json")):
        calls = deal_of(path)
        if calls not in found:
            found.append(calls)
    return found


def scribe_dir(fixture: dict) -> Path:
    return OUT / "scribe2" / fixture["deal"] if "deal" in fixture else OUT / "scribe"


def call_day(fixture: dict) -> datetime | None:
    day = fixture.get("call_date")
    return datetime.fromisoformat(day).replace(hour=11, tzinfo=ZoneInfo("Asia/Kolkata")) if day else None


def dated(emit, by_call: dict[int, dict]):
    """Start each call on its call_date: the memory reads dates from call.started's time, and
    Sage2 and the lookups are told today's date in the preamble."""

    async def wrapped(event) -> None:
        if isinstance(event, CallStarted):
            day = call_day(by_call[event.call_no])
            sage.preamble = partial(_PREAMBLE, today=day) if day else _PREAMBLE
            if day:
                event = event.model_copy(update={"ts": day.astimezone(UTC)})
        await emit(event)

    return wrapped


class CountingScribe(RecordedExtractor):
    """The saved Scribe replies, counting what a replay asked for that was not saved."""

    def __init__(self, folder: Path) -> None:
        super().__init__(folder)
        self.missing_checks: list[str] = []

    async def check(self, check):
        found = await super().check(check)
        if found is None:
            self.missing_checks.append(check.key)
        return found


# ---- recording ----


def _sage_spent() -> int:
    return sum(json.loads(p.read_text())["updates"] for p in OUT.glob("holdout2_*.sage.json"))


async def record_sage(path: str) -> None:
    fixture = load(path)
    out = OUT / f"{fixture['id']}.sage.json"
    if out.exists():
        raise SystemExit(f"{out} exists; recording again would cost the whole call again")
    spent, need = _sage_spent(), len(fixture["lines"]) + 1
    if fixture["id"].startswith("holdout2_") and spent + need > SAGE_BUDGET:
        raise SystemExit(f"over budget: {spent} spent, {need} needed, {SAGE_BUDGET} allowed")
    who = people(fixture, True)
    tuning.SAGE_TIMEOUT_S = 20.0
    stream = sage.SageStream(get_settings().require("sage_api_key"), sage.QUESTIONS)
    preamble = _PREAMBLE(who, call_day(fixture))
    answers, lines, holes = {"0": await stream.open(preamble)}, {}, []
    try:
        for line in fixture["lines"]:
            text = lines[str(line["line_no"])] = sage.line_text(sage.speaker_name(who, Role(line["speaker"])), line["text"])
            got = answers[str(line["line_no"])] = await stream.append(line["line_no"], text)
            if got is None:
                holes.append(line["line_no"])
            print(line["line_no"], "".join("-" if not got or got.get(q) is None else "Y" if sage.yes(got, q) else "n" for q in sage.QUESTIONS), flush=True)
    finally:
        await stream.close()
        OUT.mkdir(exist_ok=True)
        # Saved even with holes: a hole is a line Sage2 did not answer in time, which the brain
        # handles as on a real call. Recording again would cost the whole call again.
        out.write_text(json.dumps({
            "fixture": fixture["id"], "recorded_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "preamble": preamble, "questions": sage.QUESTIONS, "updates": stream.updates, "holes": holes,
            "lines": lines, "answers": answers,
        }, ensure_ascii=False, indent=1) + "\n")
        print(f"saved {out}; sage2 updates sent: {stream.updates} (fresh set so far {_sage_spent()}); holes: {holes}")


async def record_scribe(path: str) -> None:
    """The live Scribe over every call of the deal, in order, into one memory."""
    from app.memory import extract
    from app.memory.openai_client import OpenAIClient
    from tests.memory.record import Recorder

    fixtures = [load(p) for p in deal_of(Path(path))]
    by_call = {f.get("call_no", 1): f for f in fixtures}
    client = OpenAIClient(get_settings())
    recorder = Recorder(extract.LiveExtractor(client))
    bus = Bus()
    memory = memory_on(bus, extractor=recorder)
    bus.start()

    async def settle(event) -> None:
        bus.publish(event)
        for _ in range(3):
            await bus.drain(60)
            await memory.settle()

    emit = dated(settle, by_call)
    deal = f"record-{fixtures[0].get('deal', fixtures[0]['id'])}"
    for n, fixture in by_call.items():
        who = people(fixture, True)
        room = f"record-{deal}-{n}"
        await emit(CallStarted(deal_id=deal, people=who, room=room, call_no=n))
        for line in fixture["lines"]:
            await emit(TranscriptLine(deal_id=deal, call_no=n, **line))
        await emit(CallEnded(deal_id=deal, people=who, room=room, call_no=n))
        print(f"-- after call {n}:", json.dumps({k.value: _term(await memory.get_term(deal, k)) for k in ItemKey}, ensure_ascii=False))
    for c in memory.conflicts:
        print(f"  CONFLICT call {c.call_no} line {c.line_no}: {c.explanation}")
    out = scribe_dir(fixtures[0]) / f"{fixtures[0].get('deal', fixtures[0]['id'])}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(
        {"model": extract.MODEL, "effort": extract.EFFORT, "replies": recorder.replies, "checks": recorder.checks},
        indent=1, ensure_ascii=False,
    ) + "\n")
    print(f"saved {out}; openai calls: {dict(client.calls)}")
    await client.close()
    await bus.stop()


async def record_values(path: str) -> None:
    fixtures = [load(p) for p in deal_of(Path(path))]
    outs = {f.get("call_no", 1): OUT / f"{f['id']}.values.json" for f in fixtures}
    tuning.LOOKUP_WAIT_S = 30.0
    silence_s, tuning.CLOSING_SILENCE_S = tuning.CLOSING_SILENCE_S, 3600.0  # play() passes silences, in call seconds
    openai = OpenAIValues(get_settings().require("openai_api_key"))
    savings = {n: _Saving(openai, json.loads(o.read_text())["replies"] if o.exists() else None) for n, o in outs.items()}
    for variant in VARIANTS:
        print("--", variant, flush=True)
        await replay(deal_of(Path(path)), variant, savings, timeout=60, silence_s=silence_s)
        for s in savings.values():
            s.saved |= s.replies
    await openai.close()
    for n, out in outs.items():
        out.write_text(json.dumps({
            "fixture": out.name.removesuffix(".values.json"), "recorded_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "model": tuning.VALUES_MODEL, "replies": savings[n].saved,
        }, ensure_ascii=False, indent=1) + "\n")
        print(f"saved {out}")
    print(f"openai calls: {openai.calls}")


# ---- replaying ----


def _term(view) -> str | None:
    f = view.current
    return None if f is None else f"{f.value or f.text} [{f.status.value}, call {f.call_no} line {f.line_no}]"


async def replay(paths: list[Path], variant: str, values: dict | None = None, timeout: float = 5.0, silence_s: float | None = None) -> list[Run]:
    """Every call of one deal in order through one brain and one memory; one Run per call."""
    mode, named = VARIANTS[variant]
    fixtures = [load(p) for p in paths]
    by_call = {f.get("call_no", 1): f for f in fixtures}
    values = values or {n: RecordedValues(OUT / f"{f['id']}.values.json") for n, f in by_call.items()}
    scribe = CountingScribe(scribe_dir(fixtures[0]))
    bus = Bus()
    memory = memory_on(bus, extractor=Routed(None, scribe))
    bus.start()
    brain = Brain(bus, mode, lambda started: (sage.RecordedDecisions(OUT / f"{by_call[started.call_no]['id']}.sage.json"), values[started.call_no]), memory)
    events: list = []

    async def collect(event) -> None:
        if isinstance(event, (JudgeSpeak, ChecklistUpdated, FactConflict, CallStarted)):
            events.append(event)

    bus.subscribe_all(collect)
    emit = dated(settling(bus, memory, brain, timeout), by_call)
    deal = f"{fixtures[0].get('deal', fixtures[0]['id'])}-holdout"
    runs = []
    for n, fixture in by_call.items():
        start = len(events)
        # Names unknown applies to the first call only: by call 2 the deal knows them.
        who = people(fixture, named or n > 1)
        await play({**fixture, "people": [p.model_dump() for p in who]}, brain, emit, deal, silence_s, call_no=n)
        part = events[start:]
        run = Run(fixture, [e for e in part if not isinstance(e, CallStarted)], values[n])
        run.started = [e for e in part if isinstance(e, CallStarted)]
        run.terms = {k.value: _term(await memory.get_term(deal, k)) for k in ItemKey}
        run.memory_conflicts = [
            (c, memory.book.fact(c.fact_ids[0]) if c.fact_ids else None) for c in memory.conflicts if c.call_no == n
        ]
        run.missing_checks = list(scribe.missing_checks)
        scribe.missing_checks.clear()
        runs.append(run)
    await bus.stop()
    sage.preamble = _PREAMBLE
    return runs


if __name__ == "__main__":
    from tests.brain.holdout.score import score_main

    command = sys.argv[1]
    if command == "sage":
        asyncio.run(record_sage(sys.argv[2]))
    elif command == "scribe":
        asyncio.run(record_scribe(sys.argv[2]))
    elif command == "values":
        asyncio.run(record_values(sys.argv[2]))
    elif command == "score":
        score_main(sys.argv[2] if len(sys.argv) > 2 else "all", sys.argv[3] if len(sys.argv) > 3 else None)
    else:
        raise SystemExit(__doc__)
