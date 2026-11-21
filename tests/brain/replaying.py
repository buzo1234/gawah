from pathlib import Path

from app.brain import Brain
from app.brain.sage import RecordedDecisions
from app.brain.values import RecordedValues
from app.contracts import ChecklistUpdated, JudgeSpeak
from fakes.replayer import load, replay

RECORDINGS = Path(__file__).parent / "recordings"


class Run:
    """One practice call replayed through the brain on recorded answers."""

    def __init__(self, fixture: dict, events: list, values: RecordedValues) -> None:
        self.fixture, self.events, self.values = fixture, events, values
        self.speaks = [e for e in events if isinstance(e, JudgeSpeak)]
        self.checklists = [e for e in events if isinstance(e, ChecklistUpdated)]
        self.end_of_line = {line["line_no"]: line["end"] for line in fixture["lines"]}

    @property
    def spoken(self) -> list[tuple]:
        return [(s.after_line, s.reason.value, s.item.value if s.item else None, s.to.value) for s in self.speaks]

    @property
    def final(self) -> dict:
        return {item.key.value: item for item in self.checklists[-1].items}

    def comparable(self) -> list[dict]:
        return [e.model_dump(exclude={"ts", "event_id", "deal_id"}) for e in self.events]


async def run_call(bus, fixture_path: str | Path, mode: str, on_speak=None) -> Run:
    fixture = load(fixture_path)
    values = RecordedValues(RECORDINGS / f"{fixture['id']}.values.json")
    Brain(bus, mode, lambda started: (RecordedDecisions(RECORDINGS / f"{fixture['id']}.sage.json"), values))
    events: list = []

    async def collect(event) -> None:
        if isinstance(event, (JudgeSpeak, ChecklistUpdated)):
            events.append(event)

    bus.subscribe_all(collect)
    await replay(bus, fixture, speed=0)
    await bus.drain()
    return Run(fixture, events, values)
