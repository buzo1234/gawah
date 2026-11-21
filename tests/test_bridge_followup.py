"""A second deal call on the same deal, from the same links."""

import asyncio
import io
import wave

import numpy as np
from bridge_world import recorded, world  # noqa: F401

from app.call.livekit import call_of, deal_of, room_name
from app.contracts import AgentNote, CallEnded, CallStarted, CrewAgent, Role, TranscriptLine
from app.ears.vad import RATE
from fakes import RAMESH, SUNITA


def samples(wav_bytes: bytes) -> np.ndarray:
    with wave.open(io.BytesIO(wav_bytes)) as w:
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)


def loud(audio: np.ndarray, start: float, end: float) -> bool:
    return bool(np.abs(audio[int(start * RATE) : int(end * RATE)]).max() > 500)


async def one_call(world, after: int | None, **talk) -> CallEnded:
    before = len(world.named("call.ended"))
    await world.join(role=Role.HIRER, after=after)
    await world.join(role=Role.WORKER, after=after)
    for words in talk.get("lines", []):
        world.talk(**words)
    await world.settle()
    world.room().left("worker"), world.room().left("hirer")
    for _ in range(300):
        await world.bus.drain()
        if len(world.named("call.ended")) > before:
            return world.named("call.ended")[-1]
        await asyncio.sleep(0.01)
    raise TimeoutError("no call.ended")


def test_a_room_name_carries_the_deal_and_the_call():
    room = room_name("4f3a-b", 2)
    assert room == "deal-4f3a-b-2" and (deal_of(room), call_of(room)) == ("4f3a-b", 2)


async def test_a_second_call_has_its_own_room_recordings_and_line_numbers(world):
    await world.deal()
    first = await one_call(world, after=0, lines=[
        {"hirer": recorded("paint-01"), "seconds": 9},
        {"worker": recorded("paint-02"), "seconds": 6},
    ])
    # Days later, from the same links: the page knows one call is over.
    second = await one_call(world, after=1, lines=[
        {"seconds": 4},  # nobody talks for the first four seconds of the new call
        {"worker": recorded("paint-04"), "seconds": 7},
    ])

    started = world.named("call.started")
    assert [(s.call_no, s.room) for s in started] == [(1, "deal-d1-1"), (2, "deal-d1-2")]
    assert (first.call_no, first.room, second.call_no, second.room) == (1, "deal-d1-1", 2, "deal-d1-2")
    assert world.livekit.created == world.livekit.deleted == ["deal-d1-1", "deal-d1-2"]
    assert first.recording_keys == {r.value: f"recordings/d1/1/{r.value}.wav" for r in Role}
    assert second.recording_keys == {r.value: f"recordings/d1/2/{r.value}.wav" for r in Role}
    assert world.uploads["recordings/d1/1/worker.wav"] != world.uploads["recordings/d1/2/worker.wav"]

    lines: list[TranscriptLine] = world.named("transcript.line")
    assert [(line.call_no, line.line_no, line.speaker) for line in lines] == [
        (1, 1, Role.HIRER), (1, 2, Role.WORKER), (2, 1, Role.WORKER)]
    # Times count from each call's own start, and the line is where it says in that call's file.
    worker_2 = samples(world.uploads["recordings/d1/2/worker.wav"])
    line = lines[2]
    assert 4.0 <= line.start < line.end < 11.0
    assert loud(worker_2, line.start, line.end) and not loud(worker_2, 0, 3.9)
    hirer_1 = samples(world.uploads["recordings/d1/1/hirer.wav"])
    assert loud(hirer_1, lines[0].start, lines[0].end)
    assert len(worker_2) / RATE == second.duration  # the file is the call's full length

    notes = [n for n in world.named("agent.note") if isinstance(n, AgentNote)]
    assert all(n.agent is CrewAgent.EARS for n in notes)
    assert any("call 2" in n.text and "room open" in n.text for n in notes)
    assert any(n.text.startswith("call 2 over: 2 recordings") for n in notes)


async def test_the_call_number_comes_from_the_event_log_after_a_restart(world):
    await world.deal()
    # The server stopped during call 1: call.started is in the log and call.ended never came.
    # The brain's second call.started (a name learned) carries no number, so it says 1.
    world.bus.publish(CallStarted(deal_id="d1", people=[SUNITA, RAMESH], room="deal-d1-1", call_no=1))
    world.bus.publish(CallStarted(deal_id="d1", people=[SUNITA, RAMESH], room="deal-d1-1"))
    await world.bus.drain()
    assert await world.calls.ended_calls(await world.store.deal("d1")) == 0
    await world.join(role=Role.HIRER, after=0)
    assert world.livekit.created == ["deal-d1-2"]
