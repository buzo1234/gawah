import asyncio

import pytest

from app.bus import Bus
from app.contracts import CallStarted, TranscriptLine
from fakes.call import say, start_call


async def test_delivers_to_the_matching_type_only(bus):
    lines, by_name = [], []

    async def on_line(event):
        lines.append(event)

    async def on_started(event):
        by_name.append(event)

    bus.subscribe(TranscriptLine, on_line)
    bus.subscribe("call.started", on_started)
    start_call(bus, "d1")
    sent = say(bus, "d1", "hirer", "Hello")
    await bus.drain()
    assert lines == [sent]
    assert [type(e) for e in by_name] == [CallStarted]


async def test_subscribe_all_sees_everything_in_order(bus):
    seen = []

    async def on_any(event):
        seen.append(event.name)

    bus.subscribe_all(on_any)
    start_call(bus, "d1")
    for i in range(20):
        say(bus, "d1", "worker", f"line {i}", line_no=i)
    await bus.drain()
    assert seen == ["call.started"] + ["transcript.line"] * 20


async def test_raising_handler_does_not_break_others_or_the_publisher(bus, caplog):
    good = []

    async def bad(event):
        raise RuntimeError("boom")

    async def ok(event):
        good.append(event.text)

    bus.subscribe(TranscriptLine, bad)
    bus.subscribe(TranscriptLine, ok)
    say(bus, "d1", "hirer", "one")
    say(bus, "d1", "hirer", "two")
    await bus.drain()
    assert good == ["one", "two"]
    assert "deal=d1" in caplog.text and "boom" in caplog.text


async def test_slow_handler_does_not_delay_others_or_the_publisher(bus):
    fast, release = [], asyncio.Event()

    async def slow(event):
        await release.wait()

    async def quick(event):
        fast.append(event.text)

    bus.subscribe(TranscriptLine, slow)
    bus.subscribe(TranscriptLine, quick)
    say(bus, "d1", "hirer", "one")
    say(bus, "d1", "hirer", "two")
    await asyncio.sleep(0.05)
    assert fast == ["one", "two"]
    release.set()
    await bus.drain()


async def test_events_published_before_start_are_delivered_and_unsubscribe_stops_delivery():
    bus, seen = Bus(), []

    async def on_line(event):
        seen.append(event.text)

    unsubscribe = bus.subscribe(TranscriptLine, on_line)
    say(bus, "d1", "hirer", "early")
    bus.start()
    await bus.drain()
    unsubscribe()
    say(bus, "d1", "hirer", "late")
    await bus.drain()
    await bus.stop()
    assert seen == ["early"]


def test_subscribing_to_a_misspelt_event_name_fails_at_once():
    async def handler(event):
        pass

    with pytest.raises(ValueError, match="transcript.lines"):
        Bus().subscribe("transcript.lines", handler)
