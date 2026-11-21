from collections.abc import Awaitable, Callable
from pathlib import Path

from app.brain import Brain, tuning
from app.brain.sage import RecordedDecisions
from app.brain.values import RecordedValues
from app.contracts import CallEnded, CallStarted, ChecklistUpdated, Event, JudgeSpeak, JudgeSpoke, Person, TranscriptLine
from fakes.replayer import load

RECORDINGS = Path(__file__).parent / "recorded"


class Run:
    """One practice call replayed through the brain on recorded answers."""

    def __init__(self, fixture: dict, events: list, values: RecordedValues) -> None:
        self.fixture, self.events, self.values = fixture, events, values
        self.speaks = [e for e in events if isinstance(e, JudgeSpeak)]
        self.checklists = [e for e in events if isinstance(e, ChecklistUpdated)]
        self.started: list[CallStarted] = []  # every call.started: the replayer's, and any the brain sent again
        self.end_of_line = {line["line_no"]: line["end"] for line in fixture["lines"]}

    @property
    def spoken(self) -> list[tuple]:
        return [(s.after_line, s.reason.value, s.item.value if s.item else None, s.to.value) for s in self.speaks]

    @property
    def final(self) -> dict:
        return {item.key.value: item for item in self.checklists[-1].items}

    def comparable(self) -> list[dict]:
        return [e.model_dump(exclude={"ts", "event_id", "deal_id"}) for e in self.events]


async def play(
    fixture: dict, brain: Brain, emit: Callable[[Event | None], Awaitable[None]], deal_id: str, silence_s: float | None = None
) -> None:
    """The call's events in order, each handled before the next. Where the next line (or the
    end of the call, `ended_at`) comes CLOSING_SILENCE_S or more after a line, in call
    seconds, the brain is told that silence passed, as its own timer would on a real call."""
    silence_s = silence_s or tuning.CLOSING_SILENCE_S
    people = [Person(**p) for p in fixture["people"]]
    room = f"replay-{deal_id}"
    await emit(CallStarted(deal_id=deal_id, people=people, room=room))
    lines = fixture["lines"]
    ended_at = fixture.get("ended_at", lines[-1]["end"] + 1.0)
    for i, line in enumerate(lines):
        await emit(TranscriptLine(deal_id=deal_id, **line))
        next_at = lines[i + 1]["end"] if i + 1 < len(lines) else ended_at
        session = brain.sessions.get(deal_id)
        if session and next_at - line["end"] >= silence_s and session.ending.waiting:
            session.silence_passed()
            await emit(None)
    await emit(CallEnded(deal_id=deal_id, people=people, room=room, duration=ended_at, reason="replay"))


async def run_call(bus, fixture_path: str | Path, mode: str, drop: set[int] = frozenset()) -> Run:
    """drop: which judge.speaks (0 for the first) the mouth lets pass unsaid. Nothing answers the others."""
    fixture = load(fixture_path)
    values = RecordedValues(RECORDINGS / f"{fixture['id']}.values.json")
    brain = Brain(bus, mode, lambda started: (RecordedDecisions(RECORDINGS / f"{fixture['id']}.sage.json"), values))
    events: list = []
    started: list = []

    async def collect(event) -> None:
        if isinstance(event, (JudgeSpeak, ChecklistUpdated)):
            events.append(event)
        if isinstance(event, JudgeSpeak) and sum(isinstance(e, JudgeSpeak) for e in events) - 1 in drop:
            bus.publish(JudgeSpoke(deal_id=event.deal_id, text="", speak_id=event.event_id, reason=event.reason, item=event.item))
        if isinstance(event, CallStarted):
            started.append(event)

    async def emit(event: Event | None) -> None:
        if event:
            bus.publish(event)
        await bus.drain()

    bus.subscribe_all(collect)
    await play(fixture, brain, emit, f"{fixture['id']}-test")
    run = Run(fixture, events, values)
    run.started = started
    return run
