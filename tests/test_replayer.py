import time
from pathlib import Path

import pytest

from app.contracts import ItemKey, SpeakReason
from fakes.replayer import load, replay

FIXTURES = sorted(Path("fixtures").glob("call_*.json"))


def test_both_practice_calls_exist():
    assert [f.name for f in FIXTURES] == ["call_missing_balance.json", "call_two_amounts.json"]


@pytest.mark.parametrize("path", FIXTURES, ids=lambda p: p.stem)
async def test_replay_delivers_the_call_in_order(bus, path):
    fixture, seen = load(path), []

    async def on_any(event):
        seen.append(event)

    bus.subscribe_all(on_any)
    deal_id = await replay(bus, path, speed=0)
    await bus.drain()

    assert [e.name for e in seen] == ["call.started"] + ["transcript.line"] * len(fixture["lines"]) + ["call.ended"]
    assert {e.deal_id for e in seen} == {deal_id}
    assert [p.name for p in seen[0].people] == ["Sunita", "Ramesh"]
    lines = seen[1:-1]
    assert [e.line_no for e in lines] == list(range(1, len(lines) + 1))
    assert [(e.speaker, e.text, e.start, e.end) for e in lines] == [
        (line["speaker"], line["text"], line["start"], line["end"]) for line in fixture["lines"]
    ]


@pytest.mark.parametrize("path", FIXTURES, ids=lambda p: p.stem)
def test_fixture_is_a_two_to_three_minute_call_with_usable_expectations(path):
    fixture = load(path)
    lines = fixture["lines"]
    assert 120 <= lines[-1]["end"] <= 180
    assert all(a["end"] <= b["start"] for a, b in zip(lines, lines[1:]))
    assert all(line["start"] < line["end"] for line in lines)
    assert fixture["expected"]
    for expected in fixture["expected"]:
        assert 1 <= expected["after_line"] <= expected["by_line"] <= len(lines)
        ItemKey(expected["item"])
        SpeakReason(expected["reason"])
        assert expected["to"] in {"hirer", "worker", "both"}
        assert set(expected["modes"]) <= {"live", "wrapup"}


async def test_speed_scales_the_wait(bus):
    fixture = load(FIXTURES[0])
    fixture["lines"] = fixture["lines"][:3]
    started = time.monotonic()
    await replay(bus, fixture, speed=100)
    took = time.monotonic() - started
    assert (fixture["lines"][-1]["end"] + 1.0) / 100 <= took < 1.0
