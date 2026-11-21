"""One deal, from the first WhatsApp message to a confirmed record, through the whole app
in one process with every outside service replaced by a fake (tests/offline.py).

Each stream's own tests pass with the other streams absent. This is the guard for what
happens between them: whatsapp, bridge, brain, memory, mouth (the deal call and the
call-back), contract, records, and the dashboard, each reached the way the real thing reaches it.
"""

import asyncio
import logging
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from app.call.session import Limits
from app.contracts import (
    MEMORY_STATE, WHATSAPP_WEBHOOK_PATH, Backing, CallEnded, CallKind, CallStarted, ChecklistUpdated, ContractReady,
    DealRequested, DealStatus, Direction, Event, FactRecorded, FactStatus, ItemKey, ItemState, JudgeSpeak, JudgeSpoke, RecordConfirmed,
    RecordConfirmRequested, RecordReceived, ReplyTimeout, Role, TermsConfirmed, TranscriptLine, WhatsAppMessage,
    call_path, callback_path,
)
from app.records import words as record_words
from app.whatsapp import words
from fakes.replayer import load
from tests.mouth import sounds
from tests.offline import offline_app
from tests.whatsapp_world import FakeClock

# Neither number is in VERIFIED_NUMBERS, so both are simulated phones, like the dashboard's.
PHONE = {Role.HIRER: "+919000000001", Role.WORKER: "+919000000002"}
CALL = "fixtures/call_missing_balance.json"


class Flow:
    """The running app, every event it has published, and a way in for each person."""

    def __init__(self, app, client: httpx.AsyncClient, clock: FakeClock) -> None:
        self.app, self.client, self.clock = app, client, clock
        self.bus, self.store, self.voice = app.state.bus, app.state.store, app.state.fake_voice
        self.events: list[Event] = []
        self.bus.subscribe_all(self._keep)

    async def _keep(self, event: Event) -> None:
        self.events.append(event)

    async def settle(self) -> None:
        """Wait until the app has finished reacting to what it was just given."""
        await self.app.state.whatsapp.idle()
        await self.bus.drain()

    async def whatsapp(self, role: Role, text: str, name: str = "") -> None:
        """One WhatsApp message from a person, posted to the webhook as the provider posts it."""
        form = {"From": f"whatsapp:{PHONE[role]}", "Body": text, "ProfileName": name, "NumMedia": "0"}
        response = await self.client.post(WHATSAPP_WEBHOOK_PATH, data=form)
        assert response.status_code == 200, response.text
        await self.settle()

    async def until(self, found, timeout: float = 5.0):
        """Wait for work a stream does in its own task. found: an event kind, or a test."""
        test = (lambda: self.of(found)) if isinstance(found, type) else found
        async with asyncio.timeout(timeout):
            while not test():
                await asyncio.sleep(0.01)
        await self.settle()
        return test()

    def of(self, event_type: type[Event], **match) -> list:
        return [e for e in self.events if isinstance(e, event_type) and all(getattr(e, k) == v for k, v in match.items())]

    def sent_to(self, role: Role) -> list[str]:
        """What Gawah has sent this person on WhatsApp, oldest first: each text, or a file's link."""
        return [
            m.text or m.media_url or "" for m in self.of(WhatsAppMessage)
            if m.direction is Direction.OUT and m.phone == PHONE[role]
        ]

    async def call_back(self, deal_id: str, role: Role, answers: list[tuple[str, dict]]) -> CallEnded:
        """The person opens their call-back link and taps join; the test plays the voice model,
        which greets them, reports each answer with a tool, and says goodbye."""
        page = await self.client.get(callback_path(deal_id, role))
        assert page.status_code == 200
        joined = await self.client.post(callback_path(deal_id, role) + "/join")
        assert joined.status_code == 200, joined.text
        seat, link = self.voice.seats[-1], self.voice.links[-1]
        assert joined.json()["token"] == f"token:{seat.room}:{role.value}"
        seat.hears(role.value, sounds.silence(0.1))  # their microphone comes on
        await self.until(lambda: link.of("response.create"))
        await link.says("Namaste, main Gawah hoon.")
        for name, args in answers:
            await link.calls(name, said="haan ji", **args)
        await link.says("Shukriya, namaste.")
        [ended] = await self.until(lambda: self.of(CallEnded, kind=CallKind.CALLBACK, room=seat.room))
        assert seat.gone and seat.room in self.voice.rooms.deleted
        return ended


@pytest.fixture
async def flow(tmp_path):
    clock = FakeClock()
    app = offline_app(tmp_path / "test.db", clock)
    app.state.calls.limits = Limits(gone=0.15, empty=0.05, max_age=30)  # real seconds, so short ones
    transport = httpx.ASGITransport(app=app)
    async with app.router.lifespan_context(app), httpx.AsyncClient(transport=transport, base_url="http://gawah.test") as client:
        yield Flow(app, client, clock)


async def test_a_deal_from_the_first_message_to_a_confirmed_record(flow, caplog):
    # whatsapp: the hirer sends the worker's number. That makes the deal, and both get a call link.
    await flow.whatsapp(Role.HIRER, PHONE[Role.WORKER].removeprefix("+91"), name="Sunita")
    [requested] = flow.of(DealRequested)
    deal_id = requested.deal_id
    assert (requested.requested_by.phone, requested.other.phone) == (PHONE[Role.HIRER], PHONE[Role.WORKER])
    for role in Role:
        assert call_path(deal_id, role) in flow.sent_to(role)[-1]

    # bridge: each opens their link and taps join. With both in the room the call starts.
    for role in Role:
        assert (await flow.client.get(call_path(deal_id, role))).status_code == 200
        joined = await flow.client.post(call_path(deal_id, role) + "/join")
        assert joined.status_code == 200, joined.text
        flow.app.state.calls.livekit.open[f"deal-{deal_id}-1"].joined(role.value)
    await flow.settle()
    [started] = flow.of(CallStarted)
    assert (started.kind, started.room) == (CallKind.DEAL, f"deal-{deal_id}-1")
    assert {p.role: p.phone for p in started.people} == PHONE

    # mouth: Gawah takes its seat in the same room and, once it hears both, says its opening line.
    seat = (await flow.until(lambda: flow.voice.seats))[0]
    assert seat.room == started.room
    for role in Role:
        seat.hears(role.value, sounds.room_noise(1.0, -50))
    [opening] = await flow.until(lambda: flow.of(JudgeSpoke))
    gawah = flow.voice.links[0]
    assert opening.speak_id is None and any("record ho rahi hai" in i for i in gawah.asked())

    # The practice call's lines, as the ears send them. Whenever the brain asks something,
    # the next line waits until Gawah has said it, as people do when Gawah speaks.
    for line in load(CALL)["lines"]:
        flow.bus.publish(TranscriptLine(deal_id=deal_id, **line))
        await flow.settle()
        for speak in flow.of(JudgeSpeak):
            await flow.until(lambda: flow.of(JudgeSpoke, speak_id=speak.event_id))

    # brain: the checklist fills in, and the Judge asks about the balance nobody brought up.
    expected = [e for e in load(CALL)["expected"] if "live" in e["modes"]]
    speaks = flow.of(JudgeSpeak)
    assert [(s.item, s.reason, s.to) for s in speaks] == [(e["item"], e["reason"], e["to"]) for e in expected]
    assert all(e["after_line"] <= s.after_line <= e["by_line"] for s, e in zip(speaks, expected))
    final = {item.key: item for item in flow.of(ChecklistUpdated)[-1].items}
    assert final.pop(ItemKey.BALANCE).state is ItemState.PENDING
    assert all(item.state is ItemState.AGREED and item.value for item in final.values())

    # memory: the Scribe turned the lines into facts (from its saved replies: no key, no live
    # call), each quoting its line; the amount stands at the 24,000 both agreed; the chain holds.
    memory = getattr(flow.app.state, MEMORY_STATE)
    await memory.settle()
    await flow.settle()
    facts = [e.fact for e in flow.of(FactRecorded)]
    assert facts and all(f.deal_id == deal_id and f.quote for f in facts)
    amount = (await memory.get_term(deal_id, ItemKey.AMOUNT)).current
    assert (amount.value_rupees, amount.status, amount.call_no) == (24000, FactStatus.AGREED, 1)
    assert amount.valid_from == started.ts + timedelta(seconds=amount.start)
    chain = (await flow.client.get(f"/memory/chain/{deal_id}")).json()
    assert chain["verified"] and chain["links"] == len(facts) and chain["head"] == facts[-1].hash

    # mouth: Gawah the agent followed the call as text, one labelled line per transcript line,
    # and each judge.speak was said in the room, in call seconds counted from call.started.
    assert len(gawah.items("user")) == len(load(CALL)["lines"]) and gawah.items("user")[0].startswith("Sunita (hirer), line 1:")
    since_start = (datetime.now(UTC) - started.ts).total_seconds()
    for speak in speaks:
        [spoke] = flow.of(JudgeSpoke, speak_id=speak.event_id)
        assert (spoke.item, spoke.reason, spoke.to, spoke.interrupted) == (speak.item, speak.reason, speak.to, False)
        assert spoke.text and 0 <= opening.end <= spoke.start < spoke.end <= since_start

    # bridge: both hang up, the room closes, and call.ended carries each person's recording.
    room = flow.app.state.calls.livekit.open[started.room]
    for role in Role:
        room.left(role.value)
    [ended] = await flow.until(lambda: flow.of(CallEnded, kind=CallKind.DEAL))
    assert set(ended.recording_keys) == {"hirer", "worker"}
    assert started.room in flow.app.state.calls.livekit.deleted
    await flow.until(lambda: seat.gone)  # and Gawah left with it

    # whatsapp: after call.ended both get their call-back link. The deal was made on WhatsApp
    # without the worker's name; the brain heard it on the call ("Hello, Ramesh ji?") and sent
    # call.started again for the same room, so the store has it and nothing was rejoined.
    for role in Role:
        assert callback_path(deal_id, role) in flow.sent_to(role)[-1]
    deal = await flow.store.deal(deal_id)
    assert deal.status is DealStatus.CALL_ENDED
    assert {p.role: (p.name, p.phone) for p in deal.people} == {
        Role.HIRER: ("Sunita", PHONE[Role.HIRER]), Role.WORKER: ("Ramesh", PHONE[Role.WORKER]),
    }
    [_, named] = flow.of(CallStarted, kind=CallKind.DEAL)
    assert named.room == started.room and len(flow.voice.seats) == 1

    # mouth: each person's call-back reads every agreed term, they agree, and it ends in terms.confirmed.
    agreed = [i.key.value for i in flow.of(ChecklistUpdated)[-1].items if i.state is ItemState.AGREED]
    for role in Role:
        await flow.call_back(deal_id, role, [("term_answer", {"item": key, "agrees": True}) for key in agreed])
    assert [(e.person, e.item) for e in flow.of(TermsConfirmed)] == [(Role.HIRER, None), (Role.WORKER, None)]

    # contract: both have confirmed, so the contract is written from the brain's checklist,
    # and whatsapp sends each person a line, the PDF and the spoken summary.
    [ready] = await flow.until(ContractReady)
    assert {i.key for i in ready.items if i.state is ItemState.AGREED} == set(ItemKey) - {ItemKey.BALANCE}
    assert ready.pdf_url and ready.voice_summary_url and ready.text
    for role in Role:
        assert flow.sent_to(role)[-3:] == [words.CONTRACT, ready.pdf_url, ready.voice_summary_url]
    assert (await flow.store.deal(deal_id)).status is DealStatus.CONTRACT_READY

    # records: cash is one person's word, so the worker is asked, and "haan" confirms it.
    await flow.whatsapp(Role.HIRER, "2000 cash diya")
    [received] = flow.of(RecordReceived)
    assert (received.record.sender, received.record.amount, received.record.backing) == (Role.HIRER, 2000, Backing.UNBACKED)
    [asked] = flow.of(RecordConfirmRequested)
    assert (asked.record_id, asked.confirm_by) == (received.record.id, Role.WORKER)
    assert flow.sent_to(Role.WORKER)[-1] == asked.question

    await flow.whatsapp(Role.WORKER, "haan")
    [confirmed] = flow.of(RecordConfirmed)
    assert (confirmed.record_id, confirmed.confirmed_by, confirmed.confirmed) == (received.record.id, Role.WORKER, True)

    # records and mouth: the worker says the work is done; the hirer does not answer, so she
    # gets a call-back link, and confirms it there. The worker is told on WhatsApp.
    await flow.whatsapp(Role.WORKER, "kaam poora ho gaya")
    [_, done] = flow.of(RecordConfirmRequested)
    assert done.confirm_by is Role.HIRER
    await flow.clock.advance(flow.app.state.settings.reply_timeout_seconds)
    await flow.until(ReplyTimeout)
    assert callback_path(deal_id, Role.HIRER) in flow.sent_to(Role.HIRER)[-1]
    await flow.call_back(deal_id, Role.HIRER, [("record_answer", {"confirmed": True})])
    [_, by_call] = flow.of(RecordConfirmed)
    assert (by_call.record_id, by_call.confirmed_by, by_call.confirmed) == (done.record_id, Role.HIRER, True)
    assert flow.sent_to(Role.WORKER)[-1] == record_words.answer_for_sender(
        deal.person(Role.HIRER), done.record.model_copy(update={"confirmed": True}), True
    )
    assert [r.confirmed for r in await flow.store.records(deal_id)] == [True, True]
    assert {m.phone for m in flow.of(WhatsAppMessage)} == set(PHONE.values())

    # dashboard: a fresh page load gets the deal's people and every event above, in order.
    await flow.settle()
    state = (await flow.client.get("/dashboard/state", params={"deal": deal_id})).json()
    assert state["deals"][0]["names"] == {"hirer": "Sunita", "worker": "Ramesh"}
    assert state["events"] == [e.model_dump(mode="json") for e in flow.events]

    # No stream raised on an event or logged an error anywhere along the way.
    assert [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR] == []


async def test_a_second_call_on_the_same_deal_from_the_same_links(flow, caplog):
    """Days after the first call, the two talk again on the deal. What the other streams do
    with call 2 today: the mouth joins its new room and greets them; the brain starts a fresh
    checklist; the dashboard gets every event. The Judge's follow-up behaviour is Phase 2."""
    await flow.whatsapp(Role.HIRER, PHONE[Role.WORKER].removeprefix("+91"), name="Sunita")
    [requested] = flow.of(DealRequested)
    deal_id = requested.deal_id
    livekit = flow.app.state.calls.livekit

    async def call(after: int, room: str) -> tuple[CallStarted, CallEnded]:
        for role in Role:
            joined = await flow.client.post(call_path(deal_id, role) + f"/join?after={after}")
            assert joined.status_code == 200, joined.text
            livekit.open[room].joined(role.value)
        [started] = await flow.until(lambda: flow.of(CallStarted, room=room))
        seat = (await flow.until(lambda: [s for s in flow.voice.seats if s.room == room]))[0]
        for role in Role:
            seat.hears(role.value, sounds.room_noise(1.0, -50))
        await flow.until(lambda: [s for s in flow.of(JudgeSpoke) if s.speak_id is None and s.ts > started.ts])
        flow.bus.publish(TranscriptLine(
            deal_id=deal_id, speaker=Role.WORKER, text="Madam, aapne 25 hazaar bola tha.", start=4.2, end=6.8,
            line_no=1, call_no=started.call_no,
        ))
        await flow.settle()
        for role in Role:
            livekit.open[room].left(role.value)
        [ended] = await flow.until(lambda: flow.of(CallEnded, kind=CallKind.DEAL, room=room))
        await flow.until(lambda: seat.gone)
        return started, ended

    first, _ = await call(0, f"deal-{deal_id}-1")
    page = (await flow.client.get(call_path(deal_id, Role.WORKER))).text
    assert '"ended": 1' in page and "Phir se baat karein" in page
    late = await flow.client.post(call_path(deal_id, Role.HIRER) + "/join?after=0")
    assert late.status_code == 410

    second, ended = await call(1, f"deal-{deal_id}-2")
    assert (first.call_no, second.call_no, ended.call_no) == (1, 2, 2)
    assert set(ended.recording_keys.values()) == {f"recordings/{deal_id}/2/{r.value}.wav" for r in Role}
    assert [s.room for s in flow.voice.seats] == [first.room, second.room]  # Gawah's voice joined both
    fresh = [c for c in flow.of(ChecklistUpdated) if c.ts >= second.ts]
    assert fresh and all(i.state is ItemState.PENDING for i in fresh[0].items)  # the brain starts afresh

    state = (await flow.client.get("/dashboard/state", params={"deal": deal_id})).json()
    lines = [e for e in state["events"] if e["name"] == "transcript.line"]
    assert [(e["call_no"], e["line_no"]) for e in lines] == [(1, 1), (2, 1)]
    assert [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR] == []
