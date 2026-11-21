import asyncio
import io
import wave

import numpy as np
from bridge_world import SILENT_FRAME, recorded, world  # noqa: F401

from app.contracts import CallKind, Role
from app.ears.vad import RATE
from fakes import RAMESH, SUNITA


def samples(wav_bytes: bytes) -> np.ndarray:
    with wave.open(io.BytesIO(wav_bytes)) as w:
        assert (w.getframerate(), w.getnchannels(), w.getsampwidth()) == (RATE, 1, 2)
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)


def loud(audio: np.ndarray, start: float, end: float) -> bool:
    return bool(np.abs(audio[int(start * RATE) : int(end * RATE)]).max() > 500)


async def test_call_starts_only_when_both_people_are_in_the_room(world):
    await world.deal()
    await world.join(role=Role.HIRER)
    world.talk(hirer=recorded("paint-12"))  # alone in the room, talking to nobody
    await world.settle()
    assert world.livekit.created == ["deal-d1"]
    assert world.named("call.started") == [] and world.named("transcript.line") == []

    await world.join(role=Role.WORKER)
    await world.settle()
    [started] = world.named("call.started")
    assert (started.deal_id, started.room, started.kind) == ("d1", "deal-d1", CallKind.DEAL)
    assert started.people == [SUNITA, RAMESH]
    assert world.livekit.created == ["deal-d1"]  # the second person joined the same room


async def test_someone_who_is_not_one_of_the_two_people_does_not_start_or_hold_the_call(world):
    await world.deal()
    await world.join(role=Role.HIRER)
    world.room().joined("gawah")  # the mouth stream's participant
    await world.settle()
    assert world.named("call.started") == []
    world.room().audio("gawah", SILENT_FRAME)  # and its audio is not anyone's line
    world.room().left("hirer")
    await asyncio.sleep(0.15)
    assert world.livekit.deleted == ["deal-d1"]  # Gawah alone does not keep the room open
    assert world.named("call.ended") == []  # a call that never started does not end


async def test_drop_and_rejoin_under_the_same_identity_keeps_one_call_and_one_timeline(world):
    await world.deal()
    await world.join(role=Role.HIRER)
    await world.join(role=Role.WORKER)
    world.talk(worker=recorded("paint-23"), seconds=3)
    world.room().left("worker")  # LiveKit reports the drop
    world.talk(seconds=4)  # four seconds with only the hirer's track
    world.room().joined("worker")  # same identity, new participant and track underneath
    await asyncio.sleep(0.3)  # longer than the "gone" limit: the rejoin must have cancelled it
    world.talk(worker=recorded("paint-23"), seconds=3)
    await world.settle()
    assert len(world.named("call.started")) == 1 and world.named("call.ended") == []

    first, second = world.named("transcript.line")
    assert (first.speaker, second.speaker) == (Role.WORKER, Role.WORKER)
    assert second.start - first.start == 7.0  # the same word, 3 s + 4 s later on the timeline

    world.room().left("hirer"), world.room().left("worker")
    ended = await world.ended()
    worker = samples(world.uploads[ended.recording_keys["worker"]])
    assert len(worker) == len(samples(world.uploads[ended.recording_keys["hirer"]])) == round(ended.duration * RATE)
    assert loud(worker, first.start, first.end) and loud(worker, second.start, second.end)
    assert not loud(worker, 3.0, 7.0)  # silence where the worker was away
    # The word is at the same place in the file as in the transcript, both times.
    word = slice(int(first.start * RATE), int(first.end * RATE))
    again = slice(int(second.start * RATE), int(second.start * RATE) + word.stop - word.start)
    assert np.array_equal(worker[word], worker[again])


async def test_call_ends_when_both_have_left(world):
    await world.deal()
    await world.join(role=Role.HIRER)
    await world.join(role=Role.WORKER)
    world.talk(hirer=recorded("paint-22"), worker=recorded("paint-23"), seconds=4)
    world.room().left("worker"), world.room().left("hirer")
    ended = await world.ended()
    assert (ended.reason, ended.room, ended.people) == ("both_left", "deal-d1", [SUNITA, RAMESH])
    assert ended.duration == 4.0
    assert ended.recording_keys == {"hirer": "recordings/d1/hirer.wav", "worker": "recordings/d1/worker.wav"}
    assert set(world.uploads) == set(ended.recording_keys.values())
    assert world.livekit.deleted == ["deal-d1"] and world.livekit.listeners[0].disconnected
    assert world.calls.sessions == {}
    # Every line was published before the call ended, so whoever acts on call.ended has them all.
    names = [e.name for e in world.events]
    assert names.index("call.ended") > max(i for i, n in enumerate(names) if n == "transcript.line")


async def test_call_ends_when_one_person_has_been_gone_for_a_while(world):
    await world.deal()
    await world.join(role=Role.HIRER)
    await world.join(role=Role.WORKER)
    world.talk(seconds=2)
    world.room().left("worker")
    await asyncio.sleep(0.05)
    assert world.named("call.ended") == [] and world.livekit.deleted == []  # not yet: they may come back
    ended = await world.ended()
    assert ended.reason == "one_left" and len(ended.recording_keys) == 2
    assert world.livekit.deleted == ["deal-d1"] and world.livekit.listeners[0].disconnected


async def test_call_ends_at_our_own_time_limit(world):
    world.calls.limits.max_age = 0.1
    await world.deal()
    await world.join(role=Role.HIRER)
    await world.join(role=Role.WORKER)
    world.talk(seconds=2)
    ended = await world.ended()
    assert ended.reason == "time_limit" and len(ended.recording_keys) == 2
    assert world.livekit.deleted == ["deal-d1"] and world.livekit.listeners[0].disconnected


async def test_call_ends_if_the_listener_loses_the_room(world):
    await world.deal()
    await world.join(role=Role.HIRER)
    await world.join(role=Role.WORKER)
    world.talk(seconds=2)
    world.room().lost()
    ended = await world.ended()
    assert ended.reason == "listener_lost" and len(ended.recording_keys) == 2
    assert world.livekit.deleted == ["deal-d1"]


async def test_a_room_where_the_other_person_never_comes_is_closed_at_the_time_limit(world):
    world.calls.limits.max_age = 0.1
    await world.deal()
    await world.join(role=Role.HIRER)
    await asyncio.sleep(0.2)
    assert world.livekit.deleted == ["deal-d1"] and world.livekit.listeners[0].disconnected
    assert world.named("call.started") == [] and world.named("call.ended") == []
    assert await world.join(role=Role.HIRER)  # the call never happened, so the link still works
    assert world.livekit.created == ["deal-d1", "deal-d1"]


async def test_the_link_stops_working_once_the_call_has_ended(world):
    await world.deal()
    await world.join(role=Role.HIRER)
    await world.join(role=Role.WORKER)
    world.room().left("worker"), world.room().left("hirer")
    await world.ended()
    assert await world.join(role=Role.HIRER) is None
    assert world.livekit.created == ["deal-d1"]


async def test_a_failed_upload_still_ends_the_call(world):
    async def broken(path, key, content_type):
        raise RuntimeError("expired AWS keys")

    world.calls.upload = broken
    await world.deal()
    await world.join(role=Role.HIRER)
    await world.join(role=Role.WORKER)
    world.room().left("worker"), world.room().left("hirer")
    ended = await world.ended()
    assert ended.recording_keys == {} and world.livekit.deleted == ["deal-d1"]
    assert (world.calls.folder / "d1" / "hirer.wav").exists()  # the audio is not lost


async def test_two_deals_at_once_do_not_get_tangled(world):
    geeta, mohan = SUNITA.model_copy(update={"name": "Geeta"}), RAMESH.model_copy(update={"name": "Mohan"})
    await world.deal("d1")
    await world.deal("d2", hirer=geeta, worker=mohan)
    for deal_id in ("d1", "d2"):
        await world.join(deal_id, Role.HIRER)
    await world.join("d2", Role.WORKER)
    await world.settle()
    assert [e.deal_id for e in world.named("call.started")] == ["d2"]  # d1 is still waiting
    await world.join("d1", Role.WORKER)
    world.talk("d1", hirer=recorded("paint-22"), seconds=4)
    world.talk("d2", worker=recorded("paint-23"), seconds=4)
    await world.settle()

    lines = {e.deal_id: e for e in world.named("transcript.line")}
    assert (lines["d1"].speaker, lines["d1"].line_no) == (Role.HIRER, 1)
    assert (lines["d2"].speaker, lines["d2"].line_no) == (Role.WORKER, 1)  # each call counts its own lines
    assert world.livekit.created == ["deal-d1", "deal-d2"]

    world.room("d2").left("hirer"), world.room("d2").left("worker")
    ended = await world.ended("d2")
    assert ended.people == [geeta, mohan] and set(ended.recording_keys.values()) == {
        "recordings/d2/hirer.wav", "recordings/d2/worker.wav"}
    assert world.livekit.deleted == ["deal-d2"] and "d1" in world.calls.sessions
    assert [e.deal_id for e in world.named("call.ended")] == ["d2"]
    await world.calls.close_all()  # server shutdown closes what is left
    assert world.livekit.deleted == ["deal-d2", "deal-d1"]
