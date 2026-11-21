"""Gawah's voice on the deal call, with a fake room and a fake voice model."""

import asyncio
from datetime import UTC, datetime, timedelta

from app.contracts import (
    Audience, CallEnded, CallStarted, ChecklistItem, ChecklistUpdated, ItemKey, ItemState, JudgeSpeak,
    JudgeSpoke, SpeakReason, empty_checklist,
)
from app.mouth import tuning
from fakes import RAMESH, SUNITA
from tests.mouth.world import LOUD, until


def speak(deal_id="d1", item=ItemKey.BALANCE, reason=SpeakReason.TERM_UNCLEAR, to=Audience.HIRER) -> JudgeSpeak:
    return JudgeSpeak(deal_id=deal_id, instruction="Ask Sunita when the balance will be paid.", to=to, reason=reason, item=item)


def answers(world, deal_id="d1") -> list[JudgeSpoke]:
    """Everything Gawah said after its opening line."""
    return [e for e in world.of(JudgeSpoke, deal_id) if e.speak_id]


async def test_opening_line_is_the_only_thing_said_unasked(world):
    seat, link = await world.call()
    assert seat.room == "deal-d1" and link.open_
    opening = world.of(JudgeSpoke)[0]
    assert opening.speak_id is None and opening.reason is None and not opening.interrupted
    said = link.of("response.create")[0]["response"]
    assert "record ho rahi hai" in said["instructions"] and "Sunita ji aur Ramesh ji" in said["instructions"]
    assert said["conversation"] == "none" and said["input"] == []  # one reply per instruction, nothing remembered
    await asyncio.sleep(0.2)
    assert len(world.of(JudgeSpoke)) == 1 and len(link.of("response.create")) == 1


async def test_the_model_never_hears_the_room_and_never_replies_by_itself(world):
    seat, link = await world.call()
    seat.hears("hirer", LOUD, 1000)
    assert link.config["audio"]["input"]["turn_detection"] is None
    assert not link.of("input_audio_buffer.append")


async def test_speaks_only_in_a_pause(world):
    seat, link = await world.call()
    played = len(seat.played)
    seat.talks("hirer")
    world.bus.publish(speak())
    await asyncio.sleep(0.15)
    assert len(seat.played) == played and not answers(world)  # the words are ready, Sunita is still talking
    seat.stops("hirer")
    spoke = (await until(lambda: answers(world)))[0]
    assert len(seat.played) > played and not spoke.interrupted


async def test_drops_a_question_whose_item_was_agreed_meanwhile(world):
    seat, link = await world.call()
    played = len(seat.played)
    seat.talks("hirer")
    world.bus.publish(speak(item=ItemKey.BALANCE))
    await asyncio.sleep(0.05)
    items = [ChecklistItem(key=k, state=ItemState.AGREED if k is ItemKey.BALANCE else ItemState.PENDING) for k in ItemKey]
    world.bus.publish(ChecklistUpdated(deal_id="d1", items=items, changed=[ItemKey.BALANCE]))
    seat.stops("hirer")
    await asyncio.sleep(tuning.PAUSE_WAIT_S + 0.2)
    assert not answers(world) and len(seat.played) == played
    assert world.mouth.calls["d1"].outcomes[-1]["why"] == "agreed in the meantime"


async def test_an_item_still_pending_is_asked(world):
    seat, link = await world.call()
    world.bus.publish(ChecklistUpdated(deal_id="d1", items=empty_checklist()))
    world.bus.publish(speak(item=ItemKey.BALANCE))
    assert (await until(lambda: answers(world)))[0].item is ItemKey.BALANCE


async def test_drops_a_question_when_no_pause_comes(world):
    seat, link = await world.call()
    played = len(seat.played)
    seat.talks("hirer")
    world.bus.publish(speak(reason=SpeakReason.TERM_UNCLEAR))
    await asyncio.sleep(tuning.PAUSE_WAIT_S + 0.15)
    seat.stops("hirer")  # too late: the moment has gone
    await asyncio.sleep(0.15)
    assert not answers(world) and len(seat.played) == played
    assert world.mouth.calls["d1"].outcomes[-1]["why"] == "no pause came"


async def test_says_a_wrapup_question_even_when_no_pause_comes(world):
    seat, link = await world.call()
    seat.talks("hirer")
    world.bus.publish(speak(reason=SpeakReason.WRAPPING_UP))
    await asyncio.sleep(tuning.PAUSE_WAIT_S / 2)
    assert not answers(world)  # it still waits for a pause first
    spoke = (await until(lambda: answers(world)))[0]
    assert spoke.reason is SpeakReason.WRAPPING_UP and not spoke.interrupted
    assert world.mouth.calls["d1"].outcomes[-1]["spoken_over"] == ["hirer"]


async def test_stops_when_talked_over_and_says_so(world):
    seat, link = await world.call()
    link.pieces, link.text = [3000], "Sunita ji, kya aap bata sakti hain ki balance ka paisa kab diya jayega?"
    world.bus.publish(speak())
    call = world.mouth.calls["d1"]
    await until(lambda: call.player.active and call.player.given_ms >= 300)
    seat.hears("worker", LOUD, 200)
    spoke = (await until(lambda: answers(world)))[0]
    assert spoke.interrupted and seat.cleared
    assert spoke.end - spoke.start < 1.0  # three seconds of speech, cut short
    assert spoke.text.endswith("...") and spoke.text.startswith("Sunita") and len(spoke.text) < len(link.text)
    played = len(seat.played)
    await asyncio.sleep(0.1)
    assert len(seat.played) == played  # and it stays silent


async def test_one_question_at_a_time(world):
    seat, link = await world.call()
    first, second = speak(item=ItemKey.BALANCE), speak(item=ItemKey.DATES, reason=SpeakReason.WRAPPING_UP)
    world.bus.publish(first)
    world.bus.publish(second)
    spoke = await until(lambda: len(answers(world)) == 2 and answers(world))
    assert [s.speak_id for s in spoke] == [first.event_id, second.event_id]
    assert spoke[1].start >= spoke[0].end


async def test_judge_spoke_carries_the_id_and_the_times(world):
    started = datetime.now(UTC) - timedelta(seconds=100)
    seat, link = await world.call(ts=started)
    asked = speak(item=ItemKey.DATES, reason=SpeakReason.CONFLICTING_FIGURES, to=Audience.BOTH)
    world.bus.publish(asked)
    spoke = (await until(lambda: answers(world)))[0]
    assert (spoke.speak_id, spoke.to, spoke.reason, spoke.item) == (asked.event_id, Audience.BOTH, asked.reason, ItemKey.DATES)
    assert spoke.text == link.text and not spoke.interrupted
    now = (datetime.now(UTC) - started).total_seconds()
    assert 100 < spoke.start < spoke.end <= now  # seconds from call.started
    assert 0.25 <= spoke.end - spoke.start <= 1.0  # 300 ms of speech, played at the speed of speech


async def test_waits_for_the_second_piece_so_playback_does_not_run_dry(world, monkeypatch):
    monkeypatch.setattr(tuning, "PREBUFFER_HOLD_MS", 300)
    seat, link = await world.call()
    link.pieces, link.gap = [400, 400, 400], 0.5  # as measured: the second piece comes half a second after the first
    world.bus.publish(speak())
    await until(lambda: answers(world))
    said = world.mouth.calls["d1"].outcomes[-1]
    assert said["dry_ms"] == 0 and said["speech_ms"] == 1200
    assert said["wait_ms"] >= 300  # it held back instead of starting on the first 400 ms


async def test_a_voice_model_that_gives_nothing_is_dropped_not_waited_for(world):
    seat, link = await world.call()
    link.silent = True
    world.bus.publish(speak(reason=SpeakReason.WRAPPING_UP))
    await until(lambda: len(world.mouth.calls["d1"].outcomes) == 2)
    assert not answers(world)
    link.silent = False
    world.bus.publish(speak())
    assert await until(lambda: answers(world))  # and the next one still works


async def test_two_deals_at_once(world, monkeypatch):
    monkeypatch.setattr(tuning, "PAUSE_WAIT_S", 2.0)
    seat1, link1 = await world.call("d1")
    seat2, link2 = await world.call("d2")
    played1 = len(seat1.played)
    seat1.talks("hirer")  # d1 is mid-sentence; that must not hold d2 back
    asked1, asked2 = speak("d1"), speak("d2")
    world.bus.publish(asked1)
    world.bus.publish(asked2)
    spoke2 = (await until(lambda: answers(world, "d2")))[0]
    assert spoke2.speak_id == asked2.event_id and len(seat1.played) == played1 and not answers(world, "d1")
    played2 = len(seat2.played)
    seat1.stops("hirer")
    assert (await until(lambda: answers(world, "d1")))[0].speak_id == asked1.event_id
    assert len(seat2.played) == played2 and len(answers(world, "d2")) == 1


async def test_leaves_the_room_when_the_call_ends(world):
    seat, link = await world.call()
    world.bus.publish(CallEnded(deal_id="d1", room="deal-d1"))
    await until(lambda: seat.gone and link.closed)
    assert "d1" not in world.mouth.calls
    world.bus.publish(speak())
    await world.bus.drain()
    assert not answers(world)


async def test_leaves_when_the_room_closes_or_the_call_runs_too_long(world, monkeypatch):
    seat, link = await world.call("d1")
    seat.on_closed()  # bridge deleted the room and call.ended never came
    await until(lambda: seat.gone and "d1" not in world.mouth.calls)
    monkeypatch.setattr(tuning, "DEAL_CALL_MAX_S", 0.1)
    seat2, _ = await world.call("d2", opening=False)
    await until(lambda: seat2.gone and "d2" not in world.mouth.calls)


async def test_stays_out_of_replayed_and_fake_calls(world):
    for room in ("replay-call_missing_balance", "fake-d9", None):
        world.bus.publish(CallStarted(deal_id="d9", people=[SUNITA, RAMESH], room=room))
    world.bus.publish(speak("d9"))
    await world.bus.drain()
    assert not world.seats and not world.links and not world.of(JudgeSpoke)
