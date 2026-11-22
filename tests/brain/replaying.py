import tempfile
from collections.abc import Awaitable, Callable
from pathlib import Path

from app.brain import Brain, tuning
from app.brain.sage import RecordedDecisions
from app.brain.values import RecordedValues
from app.bus import Bus
from app.contracts import (
    CallEnded, CallStarted, ChecklistUpdated, Event, FactConflict, JudgeSpeak, JudgeSpoke, Person, TranscriptLine,
)
from app.memory import Memory
from app.memory.extract import RECORDED as SCRIBE_RECORDED
from app.memory.extract import RecordedExtractor, Routed
from app.memory.vectors import WordHashEmbedder
from fakes.replayer import load

RECORDINGS = Path(__file__).parent / "recorded"


def memory_on(bus: Bus, scribe: Path = SCRIBE_RECORDED, extractor=None) -> Memory:
    """The memory stream on this bus, its Scribe answering from saved replies (no model call)."""
    memory = Memory(
        bus, extractor or Routed(None, RecordedExtractor(scribe)), WordHashEmbedder(),
        root=Path(tempfile.mkdtemp(prefix="gawah-brain-")), embed_model="hash",
    )
    memory.attach(bus)
    return memory


def settling(bus: Bus, memory: Memory, brain: Brain, timeout: float = 5.0) -> Callable[[Event | None], Awaitable[None]]:
    """emit for play(): one event, then wait until the bus, the Scribe and the brain's model
    replies have all finished with it, so a replay gives the same events every time."""

    async def emit(event: Event | None) -> None:
        if event:
            bus.publish(event)
        for _ in range(3):
            await bus.drain(timeout)
            await memory.settle()
            await brain.idle()
        await bus.drain(timeout)

    return emit


class Run:
    """One practice call replayed through the brain on recorded answers."""

    def __init__(self, fixture: dict, events: list, values: RecordedValues) -> None:
        self.fixture, self.events, self.values = fixture, events, values
        self.speaks = [e for e in events if isinstance(e, JudgeSpeak)]
        self.checklists = [e for e in events if isinstance(e, ChecklistUpdated)]
        self.conflicts = [e for e in events if isinstance(e, FactConflict)]
        self.started: list[CallStarted] = []  # every call.started: the replayer's, and any the brain sent again
        self.end_of_line = {line["line_no"]: line["end"] for line in fixture["lines"]}

    @property
    def spoken(self) -> list[tuple]:
        return [(s.after_line, s.reason.value, s.item.value if s.item else None, s.to.value) for s in self.speaks]

    @property
    def final(self) -> dict:
        return {item.key.value: item for item in self.checklists[-1].items}

    def comparable(self) -> list[dict]:
        # Fact ids are random in every run.
        return [e.model_dump(exclude={"ts", "event_id", "deal_id", "fact_ids"}) for e in self.events]


async def play(
    fixture: dict, brain: Brain, emit: Callable[[Event | None], Awaitable[None]], deal_id: str, silence_s: float | None = None,
    call_no: int = 1,
) -> None:
    """The call's events in order, each handled before the next. Where the next line (or the
    end of the call, `ended_at`) comes CLOSING_SILENCE_S or more after a line, in call
    seconds, the brain is told that silence passed, as its own timer would on a real call; and
    where nobody speaks for PAUSE_S after a line, that a pause passed.""" 
    silence_s = silence_s or tuning.CLOSING_SILENCE_S
    people = [Person(**p) for p in fixture["people"]]
    room = f"replay-{deal_id}-{call_no}"
    await emit(CallStarted(deal_id=deal_id, people=people, room=room, call_no=call_no))
    lines = fixture["lines"]
    ended_at = fixture.get("ended_at", lines[-1]["end"] + 1.0)
    for i, line in enumerate(lines):
        await emit(TranscriptLine(deal_id=deal_id, call_no=call_no, **line))
        next_at = lines[i + 1]["end"] if i + 1 < len(lines) else ended_at
        session = brain.sessions.get(deal_id)
        if session:
            session.pause_timer = False  # the fixture's times say where the pauses are
            # A pause: nobody speaks for PAUSE_S after this line ends (by when the next line starts).
            next_start = min((later["start"] for later in lines[i + 1:]), default=ended_at)
            if next_start - line["end"] >= tuning.PAUSE_S:
                session.pause_passed()
                await emit(None)
        if session and next_at - line["end"] >= silence_s and session.ending.waiting:
            session.silence_passed()
            await emit(None)
    await emit(CallEnded(deal_id=deal_id, people=people, room=room, duration=ended_at, reason="replay", call_no=call_no))


async def run_call(bus, fixture_path: str | Path, mode: str, drop: set[int] = frozenset()) -> Run:
    """drop: which judge.speaks (0 for the first) the mouth lets pass unsaid. Nothing answers the others."""
    fixture = load(fixture_path)
    values = RecordedValues(RECORDINGS / f"{fixture['id']}.values.json")
    memory = memory_on(bus)
    brain = Brain(bus, mode, lambda started: (RecordedDecisions(RECORDINGS / f"{fixture['id']}.sage.json"), values), memory)
    events: list = []
    started: list = []

    async def collect(event) -> None:
        if isinstance(event, (JudgeSpeak, ChecklistUpdated, FactConflict)):
            events.append(event)
        if isinstance(event, JudgeSpeak) and sum(isinstance(e, JudgeSpeak) for e in events) - 1 in drop:
            bus.publish(JudgeSpoke(deal_id=event.deal_id, text="", speak_id=event.event_id, reason=event.reason, item=event.item))
        if isinstance(event, CallStarted):
            started.append(event)

    bus.subscribe_all(collect)
    await play(fixture, brain, settling(bus, memory, brain), f"{fixture['id']}-test")
    run = Run(fixture, events, values)
    run.started = started
    return run


async def run_followup(bus, fixture_path: str | Path, mode: str = "live", values2=None) -> tuple[Run, Run]:
    """A second call on a deal: call 1 (the fixture's "follows") replayed, then the fixture as
    call 2 on the same deal, through one brain and one memory. Returns each call's run."""
    second = load(fixture_path)
    first = load(Path("fixtures") / f"{second['follows']}.json")
    memory = memory_on(bus)
    values = {1: RecordedValues(RECORDINGS / f"{first['id']}.values.json")}
    values[2] = values2 or RecordedValues(RECORDINGS / f"{second['id']}.values.json")
    sage = {1: RECORDINGS / f"{first['id']}.sage.json", 2: RECORDINGS / f"{second['id']}.sage.json"}
    brain = Brain(bus, mode, lambda started: (RecordedDecisions(sage[started.call_no]), values[started.call_no]), memory)
    events: list = []

    async def collect(event) -> None:
        if isinstance(event, (JudgeSpeak, ChecklistUpdated, FactConflict, CallStarted)):
            events.append(event)

    bus.subscribe_all(collect)
    emit = settling(bus, memory, brain)
    deal = f"{second['id']}-test"
    await play(first, brain, emit, deal)
    split = len(events)
    await play(second, brain, emit, deal, call_no=second["call_no"])
    runs = []
    for fixture, part, call_values in ((first, events[:split], values[1]), (second, events[split:], values[2])):
        run = Run(fixture, [e for e in part if not isinstance(e, CallStarted)], call_values)
        run.started = [e for e in part if isinstance(e, CallStarted)]
        runs.append(run)
    return runs[0], runs[1]
