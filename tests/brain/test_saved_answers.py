"""How the brain, wired as the server wires it, picks its answers for a call: saved ones
for a practice call, by what is said; none, and no error, when it cannot follow a call."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import brain
from app.brain import sage
from app.contracts import CallStarted, ChecklistUpdated, JudgeSpeak, Person, Role, TranscriptLine
from fakes.replayer import load, play

events_memory: dict = {}  # bus -> the memory the fixture put beside the brain
from tests.brain.replaying import RECORDINGS, memory_on

CALL = "fixtures/call_missing_balance.json"


@pytest.fixture
async def heard(bus, settings):
    """The brain registered on the bus with no keys, the memory beside it on its saved
    replies, as the server has them; returns what the brain publishes."""
    memory = memory_on(bus)
    brain.register(SimpleNamespace(state=SimpleNamespace(settings=settings, on_shutdown=[], memory=memory)), bus)
    events: list = []
    events_memory[id(bus)] = memory

    async def keep(event) -> None:
        if isinstance(event, (JudgeSpeak, ChecklistUpdated)):
            events.append(event)

    bus.subscribe_all(keep)
    return events


@pytest.mark.parametrize("path", sorted(RECORDINGS.glob("*.sage.json")), ids=lambda p: p.name)
def test_each_recording_holds_the_lines_of_its_call(path):
    """Change a practice call and its saved answers no longer fit: record it again."""
    saved = json.loads(path.read_text())
    fixture = next(p for p in (Path("fixtures"), Path("fixtures/demo"), Path("tests/brain")) if (p / f"{saved["fixture"]}.json").exists())
    fixture = load(fixture / f"{saved['fixture']}.json")
    people = [Person(**p) for p in fixture["people"]]
    assert saved["lines"] == {
        str(line["line_no"]): sage.line_text(sage.speaker_name(people, Role(line["speaker"])), line["text"])
        for line in fixture["lines"]
    }


async def line_by_line(bus, fixture, deal_id=None) -> None:
    """The replayer, waiting after each event for the memory and the brain, as time between
    lines allows on a real call. At speed 0 the brain would hear the whole call, and its end,
    before the memory's first fact."""
    memory = events_memory[id(bus)]

    async def emit(event) -> None:
        bus.publish(event)
        for _ in range(3):
            await bus.drain()
            await memory.settle()

    await play(fixture if isinstance(fixture, dict) else load(fixture), emit, speed=0, deal_id=deal_id)


async def test_a_practice_call_gets_its_saved_answers_whatever_the_deal_id(bus, heard):
    await line_by_line(bus, CALL, deal_id="a-deal-made-on-whatsapp")
    speaks = [(e.item, e.reason) for e in heard if isinstance(e, JudgeSpeak)]
    assert speaks == [(e["item"], e["reason"]) for e in load(CALL)["expected"] if "live" in e["modes"]]


async def test_saved_answers_stop_where_the_call_stops_being_the_recorded_one(bus, heard, caplog):
    fixture = load(CALL)
    fixture["lines"][24]["text"] = "Ek minute, darwaze pe koi hai."
    await line_by_line(bus, fixture)
    await bus.drain()
    speaks = [e for e in heard if isinstance(e, JudgeSpeak)]
    assert [s.reason for s in speaks] == ["term_unclear"] and speaks[0].after_line < 25
    assert "line 25 is in no recorded practice call" in caplog.text


async def test_a_real_call_with_no_keys_leaves_the_brain_quiet_not_broken(bus, heard, caplog):
    bus.publish(CallStarted(deal_id="d-real", room="deal-d-real"))
    bus.publish(TranscriptLine(deal_id="d-real", speaker=Role.HIRER, text="Hello", start=0.0, end=1.0))
    await bus.drain()
    assert [type(e) for e in heard] == [ChecklistUpdated] and heard[0].changed == []
    assert "failed on" not in caplog.text
    assert "SAGE_API_KEY is not set in .env: the brain cannot follow this call" in caplog.text
