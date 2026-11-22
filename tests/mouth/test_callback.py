"""The call-back, with a fake room and the test playing the voice model's part."""

import asyncio

import httpx
import pytest
from fastapi import FastAPI

from app.contracts import (
    Backing, CallEnded, CallKind, CallStarted, ChangeStatus, ChecklistItem, ChecklistUpdated, DealRequested, Fact, FactChanged,
    FactKind, FactRecorded, FactStatus, ItemKey,
    ItemState, Record, RecordConfirmed, RecordConfirmRequested, RecordKind, RecordReceived, Role, TermsConfirmed,
    TermsDisputed, callback_path,
)
from app.memory import Memory
from app.memory.vectors import WordHashEmbedder
from app.mouth import callback, tuning
from app.store import Store
from fakes import RAMESH, SUNITA
from tests.mouth import sounds
from tests.mouth.world import FakeLink, FakeRooms, FakeSeat, until

AGREED = {
    ItemKey.WORK: "painting the 2BHK flat, two coats",
    ItemKey.AMOUNT: "22,000 rupees with material",
    ItemKey.DATES: "Monday to Friday",
}


class Desk:
    """The app with only the call-back routes, a real store, and fakes for the outside."""

    def __init__(self, bus, store: Store) -> None:
        self.bus, self.store, self.rooms = bus, store, FakeRooms()
        self.seats: list[FakeSeat] = []
        self.links: list[FakeLink] = []
        self.events: list = []
        self.app = FastAPI()
        self.app.state.store, self.app.state.on_shutdown = store, []
        bus.subscribe_all(store.record_event)
        bus.subscribe_all(self._collect)
        callback.register(self.app, bus, lambda: self.rooms, self._seat, self._link)
        self.http = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://gawah")

    def _seat(self, log=None) -> FakeSeat:
        self.seats.append(FakeSeat())
        return self.seats[-1]

    def _link(self, config, on_event, log=None) -> FakeLink:
        self.links.append(FakeLink(config, on_event))
        return self.links[-1]

    async def _collect(self, event) -> None:
        self.events.append(event)

    def of(self, kind: type) -> list:
        return [e for e in self.events if isinstance(e, kind)]

    async def deal(self, deal_id="d1", agreed=AGREED, cash: bool | None = None) -> Record | None:
        """A deal whose call is over. cash: Sunita says she paid cash and Ramesh has not answered."""
        self.bus.publish(DealRequested(deal_id=deal_id, requested_by=SUNITA, other=RAMESH))
        items = [
            ChecklistItem(key=k, state=ItemState.AGREED if k in agreed else ItemState.PENDING, value=agreed.get(k))
            for k in ItemKey
        ]
        self.bus.publish(ChecklistUpdated(deal_id=deal_id, items=items))
        record = None
        if cash is not None:
            record = Record(sender=Role.HIRER, kind=RecordKind.PAYMENT, backing=Backing.UNBACKED, text="2000 cash diya", amount=2000)
            self.bus.publish(RecordReceived(deal_id=deal_id, record=record))
            self.bus.publish(RecordConfirmRequested(deal_id=deal_id, record_id=record.id, confirm_by=Role.WORKER, record=record))
            if cash:
                self.bus.publish(RecordConfirmed(deal_id=deal_id, record_id=record.id, confirmed_by=Role.WORKER))
        await self.bus.drain()
        return record

    async def join(self, deal_id="d1", role=Role.WORKER) -> tuple[FakeSeat, FakeLink]:
        """The person taps join, their microphone comes on, and Gawah greets them."""
        before = len(self.seats)
        response = await self.http.post(callback_path(deal_id, role) + "/join")
        assert response.status_code == 200, response.text
        seat, link = self.seats[before], self.links[before]
        assert response.json() == {"url": self.rooms.url, "token": f"token:{seat.room}:{role.value}"}
        seat.hears(role.value, sounds.silence(0.1))
        await until(lambda: link.of("response.create"))
        await link.says("Namaste Ramesh ji, main Gawah hoon.")
        return seat, link


@pytest.fixture
async def desk(bus, settings):
    store = Store(settings.database_path)
    await store.open()
    desk = Desk(bus, store)
    yield desk
    for hook in desk.app.state.on_shutdown:
        await hook()
    await desk.http.aclose()
    await bus.drain()
    await store.close()


async def test_the_page_is_served_at_the_agreed_path_with_our_own_copy_of_the_client(desk):
    page = await desk.http.get(callback_path("d1", Role.HIRER))
    assert page.status_code == 200 and ">Join<" in page.text
    assert 'src="/mouth/static/livekit-client.umd.min.js"' in page.text and "cdn." not in page.text
    script = await desk.http.get("/mouth/static/livekit-client.umd.min.js")
    assert script.status_code == 200 and len(script.content) > 100_000
    assert (await desk.http.get("/callback/d1/nobody")).status_code == 422


async def test_no_room_is_opened_when_there_is_nothing_to_ask(desk):
    for deal_id in ("no-such-deal", "d-empty"):
        desk.bus.publish(DealRequested(deal_id="d-empty", requested_by=SUNITA, other=RAMESH))
        await desk.bus.drain()
        response = await desk.http.post(callback_path(deal_id, Role.WORKER) + "/join")
        assert response.status_code == 404 and response.json()["message"] == tuning.PAGE_NOTHING
    assert not desk.rooms.made and not desk.seats


async def test_all_terms_confirmed(desk):
    await desk.deal()
    seat, link = await desk.join()
    started = desk.of(CallStarted)[0]
    assert (started.kind, started.room, started.people) == (CallKind.CALLBACK, seat.room, [RAMESH])
    opening = link.of("conversation.item.create")[0]["item"]["content"][0]["text"]
    assert "the work: painting the 2BHK flat, two coats" in opening and "22,000" not in opening  # one term at a time
    assert link.config["audio"]["input"]["turn_detection"]  # here the model hears the person (callback.py asks for each reply)
    assert {t["name"] for t in link.config["tools"]} == {"record_answer", "term_answer", "group_answer", "change_answer"}

    then = await link.calls("term_answer", item="work", agrees=True, said="haan theek hai")
    assert "the total amount: 22,000 rupees with material" in then
    then = await link.calls("term_answer", item="amount", agrees=True, said="haan")
    assert "the dates: Monday to Friday" in then and not desk.of(TermsConfirmed)
    then = await link.calls("term_answer", item="dates", agrees=True, said="haan sahi hai")
    confirmed = (await until(lambda: desk.of(TermsConfirmed)))[0]
    assert (confirmed.person, confirmed.item, confirmed.said) == (Role.WORKER, None, "haan sahi hai")
    # The terms that were never agreed are said plainly, and not confirmed.
    assert "never agreed" in then and "the advance, the balance, what happens if the work is late" in then
    assert "The call will end by itself" in then and not desk.of(TermsDisputed)

    await asyncio.sleep(0.3)
    assert not desk.of(CallEnded)  # not before the closing words
    await link.says("Advance ke baad ka balance aur der hone par kya hoga, yeh tay nahi hua tha. Dhanyavaad Ramesh ji. Namaste.")
    ended = (await until(lambda: desk.of(CallEnded)))[0]
    assert (ended.kind, ended.reason, ended.room) == (CallKind.CALLBACK, "done", seat.room)
    await until(lambda: desk.rooms.deleted == [seat.room] and seat.gone and link.closed)


async def test_a_disputed_term_is_reported_and_not_argued(desk):
    await desk.deal()
    seat, link = await desk.join()
    await link.calls("term_answer", item="work", agrees=True, said="haan")
    then = await link.calls("term_answer", item="amount", agrees=False, said="nahi, 25 hazaar bola tha")
    disputed = (await until(lambda: desk.of(TermsDisputed)))[0]
    assert (disputed.person, disputed.item, disputed.value) == (Role.WORKER, ItemKey.AMOUNT, AGREED[ItemKey.AMOUNT])
    assert disputed.said == "nahi, 25 hazaar bola tha"
    assert "raise this with Sunita" in then and "Do not discuss it" in then and "the dates: Monday to Friday" in then
    then = await link.calls("term_answer", item="dates", agrees=True, said="haan")
    assert "nothing is final until both agree" in then and "the total amount" in then
    await link.says("Theek hai. Namaste.")
    await until(lambda: desk.of(CallEnded))
    assert not desk.of(TermsConfirmed)


@pytest.mark.parametrize("answer", [True, False])
async def test_an_unanswered_record_question_comes_first(desk, answer):
    record = await desk.deal(cash=False)
    seat, link = await desk.join()
    opening = link.of("conversation.item.create")[0]["item"]["content"][0]["text"]
    assert 'Sunita told Gawah on WhatsApp: "2000 cash diya" (a payment of 2,000 rupees)' in opening
    assert "painting" not in opening
    then = await link.calls("record_answer", confirmed=answer, said="haan mila tha" if answer else "nahi mila")
    confirmed = (await until(lambda: desk.of(RecordConfirmed)))[0]
    assert (confirmed.record_id, confirmed.confirmed_by, confirmed.confirmed) == (record.id, Role.WORKER, answer)
    assert confirmed.record.confirmed is answer
    assert "the work: painting the 2BHK flat" in then  # then on to the terms
    await desk.bus.drain()
    assert (await desk.store.records("d1"))[0].confirmed is answer


async def test_a_record_already_answered_on_whatsapp_is_not_asked_again(desk):
    await desk.deal(cash=True)
    seat, link = await desk.join()
    assert "cash" not in link.of("conversation.item.create")[0]["item"]["content"][0]["text"]


async def test_terms_already_confirmed_are_not_read_again(desk):
    await desk.deal(cash=False)
    desk.bus.publish(TermsConfirmed(deal_id="d1", person=Role.WORKER))
    await desk.bus.drain()
    seat, link = await desk.join()
    then = await link.calls("record_answer", confirmed=True, said="haan")
    assert "That was all" in then and "painting" not in then
    await desk.bus.drain()
    assert len(desk.of(TermsConfirmed)) == 1
    # Sunita has not confirmed yet, so her call-back still reads the terms.
    seat, link = await desk.join(role=Role.HIRER)
    assert "painting" in link.of("conversation.item.create")[0]["item"]["content"][0]["text"]


async def test_an_answer_for_the_wrong_step_is_not_recorded(desk):
    await desk.deal(cash=False)
    seat, link = await desk.join()
    for name, args in (
        ("term_answer", {"item": "work", "agrees": True, "said": "haan"}),  # the record question comes first
        ("end_call", {}),  # no such tool: our code ends the call
        ("record_answer", {"confirmed": "yes", "said": "haan"}),  # not a yes or no
    ):
        then = await link.calls(name, **args)
        assert "2000 cash diya" in then  # sent back to the step it is on
    await link.calls("record_answer", confirmed=True, said="haan")
    then = await link.calls("term_answer", item="amount", agrees=True, said="haan")  # skipping the work
    assert "the work: painting" in then
    await desk.bus.drain()
    assert len(desk.of(RecordConfirmed)) == 1 and not desk.of(TermsConfirmed) and not desk.of(CallEnded)


async def test_the_person_leaving_ends_the_call_with_no_outcome(desk, monkeypatch):
    monkeypatch.setattr(tuning, "CALLBACK_LEFT_GRACE_S", 0.1)
    await desk.deal()
    seat, link = await desk.join()
    await link.calls("term_answer", item="work", agrees=True, said="haan")
    seat.on_left("worker")
    ended = (await until(lambda: desk.of(CallEnded)))[0]
    assert ended.reason == "the person left" and ended.duration is not None
    await until(lambda: desk.rooms.deleted == [seat.room])
    assert not desk.of(TermsConfirmed) and not desk.of(TermsDisputed)


async def test_our_own_limits_close_the_room(desk, monkeypatch):
    await desk.deal()
    monkeypatch.setattr(tuning, "CALLBACK_JOIN_WAIT_S", 0.1)
    await desk.http.post(callback_path("d1", Role.WORKER) + "/join")  # the page opened, the microphone never came
    await until(lambda: len(desk.rooms.deleted) == 1)
    assert not desk.of(CallStarted) and not desk.of(CallEnded)  # nobody was ever on the call
    monkeypatch.setattr(tuning, "CALLBACK_MAX_S", 0.3)
    seat, link = await desk.join()
    assert (await until(lambda: desk.of(CallEnded)))[0].reason == "time limit"
    await until(lambda: len(desk.rooms.deleted) == 2 and seat.gone)


async def test_a_second_tap_joins_the_same_room(desk):
    await desk.deal()
    seat, link = await desk.join()
    again = await desk.http.post(callback_path("d1", Role.WORKER) + "/join")
    assert again.json()["token"] == f"token:{seat.room}:worker" and len(desk.rooms.made) == 1


async def test_the_person_talking_over_gawah_stops_it(desk, monkeypatch):
    monkeypatch.setattr(tuning, "CALLBACK_TALKED_OVER_MS", 200)
    await desk.deal()
    seat, link = await desk.join()
    await until(lambda: link.sent and not desk.app.state.callbacks[("d1", Role.WORKER)].player.active)
    item = await link.says("Pehli shart: poore flat ki painting, do coat ...", ms=3000)
    call = desk.app.state.callbacks[("d1", Role.WORKER)]
    await until(lambda: call.player.given_ms >= 200)
    await link.on_event({"type": "input_audio_buffer.speech_started"})
    assert call.player.active  # not yet: it might be a cough
    await until(lambda: not call.player.active)
    assert seat.cleared
    cut = link.of("conversation.item.truncate")[0]
    assert cut["item_id"] == item and 200 <= cut["audio_end_ms"] < 3000  # the model is told how much was heard
    assert not link.of("response.create")[1:]  # no reply while they are still talking ...
    await link.on_event({"type": "input_audio_buffer.speech_stopped", "item_id": "their-answer"})
    await link.on_event({"type": "input_audio_buffer.committed", "item_id": "their-answer"})
    assert len(link.of("response.create")) == 2 and not link.of("conversation.item.delete")  # ... and one once they stop
    # The person's audio reaches the model, which is how it hears the answer.
    seat.says("worker", 100)
    await until(lambda: link.of("input_audio_buffer.append"))


async def test_a_short_sound_over_gawah_neither_stops_it_nor_gets_a_reply(desk):
    await desk.deal()
    seat, link = await desk.join()
    call = desk.app.state.callbacks[("d1", Role.WORKER)]
    await until(lambda: link.sent and not call.player.active)
    await link.says("Pehli shart: poore flat ki painting, do coat ...", ms=3000)
    await until(lambda: call.player.given_ms >= 200)
    asked = len(link.of("response.create"))
    await link.on_event({"type": "input_audio_buffer.speech_started"})  # a cough, a door, the TV
    await asyncio.sleep(0.3)
    await link.on_event({"type": "input_audio_buffer.speech_stopped", "item_id": "a-cough"})
    await link.on_event({"type": "input_audio_buffer.committed", "item_id": "a-cough"})
    await asyncio.sleep(tuning.CALLBACK_TALKED_OVER_MS / 1000)
    assert call.player.active and not seat.cleared and not link.of("conversation.item.truncate")
    assert len(link.of("response.create")) == asked  # the model is not asked to answer a cough
    assert link.of("conversation.item.delete") == [{"type": "conversation.item.delete", "item_id": "a-cough"}]


async def test_an_answer_after_gawah_has_finished_gets_a_reply(desk):
    await desk.deal()
    seat, link = await desk.join()
    call = desk.app.state.callbacks[("d1", Role.WORKER)]
    await until(lambda: link.sent and not call.player.active)
    asked = len(link.of("response.create"))
    await link.on_event({"type": "input_audio_buffer.speech_started"})
    await link.on_event({"type": "input_audio_buffer.speech_stopped", "item_id": "haan"})
    assert len(link.of("response.create")) == asked + 1 and not link.of("conversation.item.delete")


async def test_the_session_hears_speech_slowly_and_in_hindi_and_english(desk):
    await desk.deal()
    seat, link = await desk.join()
    heard = link.config["audio"]["input"]
    turns = heard["turn_detection"]
    assert turns["type"] == "server_vad" and turns["threshold"] >= 0.8 and turns["prefix_padding_ms"] >= 500
    assert not turns["interrupt_response"] and not turns["create_response"]  # callback.py decides both
    assert heard["transcription"]["languages"] == ["hi", "en"] and "Hinglish" in heard["transcription"]["prompt"]


async def test_two_call_backs_at_once(desk):
    await desk.deal("d1")
    await desk.deal("d2")
    seat1, link1 = await desk.join("d1", Role.WORKER)
    seat2, link2 = await desk.join("d2", Role.HIRER)
    assert seat1.room != seat2.room
    await link2.calls("term_answer", item="work", agrees=False, said="nahi")
    for item in ("work", "amount", "dates"):
        await link1.calls("term_answer", item=item, agrees=True, said="haan")
    await desk.bus.drain()
    assert [(e.deal_id, e.person) for e in desk.of(TermsConfirmed)] == [("d1", Role.WORKER)]
    assert [(e.deal_id, e.person, e.item) for e in desk.of(TermsDisputed)] == [("d2", Role.HIRER, ItemKey.WORK)]


async def test_no_room_and_a_plain_message_when_the_room_cannot_be_made(desk):
    await desk.deal()

    async def fails(*args, **kwargs):
        raise RuntimeError("LIVEKIT_URL is not set in .env")

    desk.rooms.create = fails
    response = await desk.http.post(callback_path("d1", Role.WORKER) + "/join")
    assert response.status_code == 503 and response.json() == {"message": tuning.PAGE_FAILED}
    await asyncio.sleep(0)
    assert not desk.seats


async def amount_left_open(desk, change_status=FactStatus.AGREED) -> tuple[Fact, Fact]:
    """Call 2 ended before Gawah could put the change to both: 22,000 on record, 24,000 agreed on the call."""
    await desk.deal()
    record = Fact(deal_id="d1", text="The amount is 22,000 rupees.", item=ItemKey.AMOUNT, kind=FactKind.TERM,
                  value="22,000 rupees with material", value_rupees=22000, said_by=Role.WORKER, agreed_by=[Role.HIRER],
                  confirmed_by=[Role.HIRER, Role.WORKER], status=FactStatus.CONFIRMED, call_no=1, line_no=6)
    change = Fact(deal_id="d1", text="Balcony 2,000 extra.", item=ItemKey.AMOUNT, kind=FactKind.CHANGE,
                  value="24,000 rupees (22,000 agreed + 2,000 extra)", value_rupees=24000, said_by=Role.WORKER,
                  agreed_by=[Role.HIRER], status=change_status, call_no=2, line_no=9)
    for fact in (record, change):
        desk.bus.publish(FactRecorded(deal_id="d1", fact=fact))
    await desk.bus.drain()
    return record, change


async def test_a_change_left_open_when_the_call_ended_is_put_to_each_person_as_a_change(desk):
    """The user's call 3: the 2,000 extra was never put to both on the call, and the call-back read
    "24,000, of which 22,000 agreed and 2,000 extra" as the amount. It is asked as a change."""
    record, change = await amount_left_open(desk)
    seat, link = await desk.join(role=Role.WORKER)
    then = await link.calls("term_answer", item="work", agrees=True, said="haan")
    assert "Record mein 22,000 rupees with material tha; call par 24,000 rupees (22,000 agreed + 2,000 extra) kaha gaya. " \
           "Kya aap ise 24,000 rupees (22,000 agreed + 2,000 extra) karna chahte hain?" in then
    assert "change_answer" in then and "the total amount: 24,000" not in then and "term_answer (item \"amount\")" not in then
    then = await link.calls("change_answer", agrees=True, said="haan ji, karna hai")
    await desk.bus.drain()
    assert "the dates: Monday to Friday" in then
    proposed, one = desk.of(FactChanged)
    assert (proposed.status, proposed.fact_id, proposed.item, proposed.proposed_by) == (
        ChangeStatus.PROPOSED, record.id, ItemKey.AMOUNT, Role.WORKER)
    assert (one.status, one.confirmed_by, one.change_id) == (ChangeStatus.CONFIRMED_ONE, [Role.WORKER], proposed.change_id)
    await link.calls("term_answer", item="dates", agrees=True, said="haan")
    assert [c.person for c in await until(lambda: desk.of(TermsConfirmed))] == [Role.WORKER]

    seat, link = await desk.join(role=Role.HIRER)
    opening = link.of("conversation.item.create")[0]["item"]["content"][0]["text"]
    assert "the work: painting" in opening
    await link.calls("term_answer", item="work", agrees=True, said="haan")
    await link.calls("change_answer", agrees=True, said="haan")
    await desk.bus.drain()
    both = desk.of(FactChanged)[-1]
    assert (both.status, both.confirmed_by, both.change_id, both.new_value) == (
        ChangeStatus.CONFIRMED_BOTH, [Role.HIRER, Role.WORKER], proposed.change_id, "24,000 rupees (22,000 agreed + 2,000 extra)")
    assert len(desk.of(FactChanged)) == 3, "proposed once, then one step per person"


async def test_a_no_on_the_call_back_withdraws_the_change_and_the_record_stands(desk):
    record, change = await amount_left_open(desk, FactStatus.SAID)
    seat, link = await desk.join(role=Role.HIRER)
    await link.calls("term_answer", item="work", agrees=True, said="haan")
    then = await link.calls("change_answer", agrees=False, said="nahi, 22 hi rahega")
    await desk.bus.drain()
    assert "the dates" in then
    withdrawn = desk.of(FactChanged)[-1]
    assert (withdrawn.status, withdrawn.fact_id) == (ChangeStatus.WITHDRAWN, record.id)
    assert not desk.of(TermsDisputed), "saying no to a change disputes nothing: the record stands"


async def test_a_change_one_person_already_confirmed_on_the_call_is_asked_only_of_the_other(desk):
    record, change = await amount_left_open(desk)
    common = dict(deal_id="d1", change_id="c-call", fact_id=record.id, new_value="24,000 rupees", item=ItemKey.AMOUNT,
                  proposed_by=Role.WORKER)
    desk.bus.publish(FactChanged(**common))
    desk.bus.publish(FactChanged(**common, status=ChangeStatus.CONFIRMED_ONE, confirmed_by=[Role.HIRER]))
    await desk.bus.drain()
    seat, link = await desk.join(role=Role.WORKER)
    await link.calls("term_answer", item="work", agrees=True, said="haan")
    await link.calls("change_answer", agrees=True, said="haan")
    await desk.bus.drain()
    both = desk.of(FactChanged)[-1]
    assert (both.status, both.change_id, both.confirmed_by) == (ChangeStatus.CONFIRMED_BOTH, "c-call", [Role.HIRER, Role.WORKER])
    seat, link = await desk.join(role=Role.HIRER)
    then = await link.calls("term_answer", item="work", agrees=True, said="haan")
    assert "change_answer" not in then and "the total amount" not in then, "both said yes: the old figure is not read to her"


async def balance_said_not_agreed(desk, tmp_path) -> tuple[Memory, Fact]:
    """The user's real call: the hirer said when the balance is paid, nobody was heard agreeing,
    and the checklist ended with the balance pending."""
    memory = Memory(desk.bus, None, WordHashEmbedder(), root=tmp_path, embed_model="hash")
    memory.attach(desk.bus)
    await desk.deal()
    said = Fact(deal_id="d1", text="Sunita will pay the rest after the work is done.", item=ItemKey.BALANCE,
                kind=FactKind.TERM, value="rest after completion", said_by=Role.HIRER,
                quote="बाकी का पैसा काम पूरे होने के बाद दूँगा।", call_no=1, line_no=12)
    memory.record(said)  # memory keeps it and sends fact.recorded, which the call-back reads from the log
    await desk.bus.drain()
    return memory, said


async def test_a_term_said_but_never_agreed_is_asked_and_both_yeses_confirm_it(desk, tmp_path):
    memory, said = await balance_said_not_agreed(desk, tmp_path)
    for role in (Role.WORKER, Role.HIRER):
        seat, link = await desk.join(role=role)
        await link.calls("term_answer", item="work", agrees=True, said="haan")
        then = await link.calls("term_answer", item="amount", agrees=True, said="haan")
        assert "Call par Sunita ji ne kaha: rest after completion. Kya yeh tay hua tha?" in then or (
            role is Role.HIRER and "Call par aap ne kaha: rest after completion" in then)
        assert "बाकी का पैसा काम पूरे होने के बाद दूँगा" in then and 'term_answer (item "balance")' in then
        await link.calls("term_answer", item="balance", agrees=True, said="haan ji, yahi tay hua tha")
        then = await link.calls("term_answer", item="dates", agrees=True, said="haan")
        # Only what nobody spoke of is called never agreed: never the balance.
        assert "never agreed on the call, so they are not on record: the advance, what happens" in then
        assert "the balance" not in then.split("never agreed")[1].split(".")[0]
        await link.says("Dhanyavaad. Namaste.")
        await until(lambda: [e for e in desk.of(CallEnded) if e.room == seat.room])
        await desk.bus.drain()
        await memory.settle()
        fact = memory.book.deal("d1").latest[said.id]
        if role is Role.WORKER:  # said by Sunita, agreed by Ramesh, confirmed by him alone so far
            assert (fact.agreed_by, fact.confirmed_by) == ([Role.WORKER], [Role.WORKER])
    assert (fact.status, fact.confirmed_by) == (FactStatus.CONFIRMED, [Role.HIRER, Role.WORKER])
    assert (await memory.get_term("d1", ItemKey.BALANCE)).current.id == said.id
    per_term = [e for e in desk.of(TermsConfirmed) if e.item is ItemKey.BALANCE]
    assert [(e.person, e.value) for e in per_term] == [(Role.WORKER, "rest after completion"), (Role.HIRER, "rest after completion")]
    assert [e.person for e in desk.of(TermsConfirmed) if e.item is None] == [Role.WORKER, Role.HIRER]


async def test_a_no_to_a_term_said_on_the_call_leaves_it_open_and_disputes_nothing(desk, tmp_path):
    memory, said = await balance_said_not_agreed(desk, tmp_path)
    seat, link = await desk.join(role=Role.WORKER)
    for item in ("work", "amount"):
        await link.calls("term_answer", item=item, agrees=True, said="haan")
    await link.calls("term_answer", item="balance", agrees=False, said="nahi, woh tay nahi hua tha")
    then = await link.calls("term_answer", item="dates", agrees=True, said="haan")
    assert "said on the call but not agreed" in then and "the balance" in then
    await desk.bus.drain()
    await memory.settle()
    assert memory.book.deal("d1").latest[said.id].status is FactStatus.SAID
    assert not desk.of(TermsDisputed) and not [e for e in desk.of(TermsConfirmed) if e.item]
    assert [e.person for e in desk.of(TermsConfirmed)] == [Role.WORKER]  # the agreed terms still stand confirmed


async def test_a_term_nobody_spoke_of_is_not_asked(desk):
    await desk.deal()
    seat, link = await desk.join(role=Role.WORKER)
    for item in ("work", "amount"):
        await link.calls("term_answer", item=item, agrees=True, said="haan")
    then = await link.calls("term_answer", item="dates", agrees=True, said="haan")
    assert "never agreed" in then and "the advance, the balance" in then and "Kya yeh tay hua tha" not in then


async def call_2_changed_the_amount(desk, tmp_path=None, confirmed_on_the_call: list[Role] = ()) -> tuple[Fact, Fact]:
    """After call 1 both confirmed every term on their call-backs. Call 2 agreed 24,000 for the
    amount and ended before Gawah put it to both; `confirmed_on_the_call` said yes to Gawah on it."""
    record, change = await amount_left_open(desk)
    for role in Role:
        desk.bus.publish(TermsConfirmed(deal_id="d1", person=role, said="haan"))
    items = [ChecklistItem(key=k, state=ItemState.AGREED if k in AGREED else ItemState.PENDING, value=AGREED.get(k))
             for k in ItemKey]
    desk.bus.publish(ChecklistUpdated(deal_id="d1", items=items))  # call 2's checklist: the record still stands
    if confirmed_on_the_call:
        common = dict(deal_id="d1", change_id="c-on-call", fact_id=record.id, new_value=change.value,
                      item=ItemKey.AMOUNT, proposed_by=Role.WORKER)
        desk.bus.publish(FactChanged(status=ChangeStatus.PROPOSED, **common))
        desk.bus.publish(FactChanged(status=ChangeStatus.CONFIRMED_ONE, confirmed_by=list(confirmed_on_the_call), **common))
    await desk.bus.drain()
    return record, change


async def test_after_a_second_call_the_call_back_asks_only_what_changed(desk):
    """The user: "it repeats all the terms that did not change; only new ones should happen"."""
    await call_2_changed_the_amount(desk)
    for role in Role:
        seat, link = await desk.join(role=role)
        opening = link.of("conversation.item.create")[0]["item"]["content"][0]["text"]
        assert "Record mein 22,000 rupees with material tha; call par 24,000" in opening
        assert "painting" not in opening and "Monday to Friday" not in opening  # confirmed before, unchanged
        then = await link.calls("change_answer", agrees=True, said="haan")
        assert "Baaki sab pehle jaisa hai" in then and "the work, the dates" in then and "Do not read those terms again" in then
        assert "never agreed" not in then  # told on the first call-back already
        await link.says("Theek hai. Namaste.")
        await until(lambda: [e for e in desk.of(CallEnded) if e.room == seat.room])
    assert [(c.status, c.confirmed_by) for c in desk.of(FactChanged)][-1] == (ChangeStatus.CONFIRMED_BOTH, [Role.HIRER, Role.WORKER])
    assert [e.item for e in desk.of(TermsConfirmed)] == [None, None]  # only call 1's confirmations: nothing read again


async def test_a_term_said_but_not_agreed_on_the_second_call_is_asked_with_the_change(desk, tmp_path):
    await call_2_changed_the_amount(desk)
    memory = Memory(desk.bus, None, WordHashEmbedder(), root=tmp_path, embed_model="hash")
    memory.attach(desk.bus)
    memory.record(Fact(deal_id="d1", text="Sunita will pay the rest after the work.", item=ItemKey.BALANCE,
                       kind=FactKind.TERM, value="rest after completion", said_by=Role.HIRER, call_no=2, line_no=5))
    await desk.bus.drain()
    seat, link = await desk.join(role=Role.WORKER)
    opening = link.of("conversation.item.create")[0]["item"]["content"][0]["text"]
    assert "Record mein 22,000" in opening and "painting" not in opening
    then = await link.calls("change_answer", agrees=True, said="haan")
    assert "Call par Sunita ji ne kaha: rest after completion. Kya yeh tay hua tha?" in then
    then = await link.calls("term_answer", item="balance", agrees=True, said="haan")
    assert "Baaki sab pehle jaisa hai" in then and "the work, the dates" in then


async def test_who_confirmed_the_change_on_the_call_has_nothing_left_to_confirm(desk):
    await call_2_changed_the_amount(desk, confirmed_on_the_call=[Role.HIRER])
    response = await desk.http.post(callback_path("d1", Role.HIRER) + "/join")  # an old link
    assert response.status_code == 404 and response.json()["message"] == tuning.PAGE_NOTHING
    seat, link = await desk.join(role=Role.WORKER)
    assert "Record mein 22,000" in link.of("conversation.item.create")[0]["item"]["content"][0]["text"]
    await link.calls("change_answer", agrees=True, said="haan")
    await desk.bus.drain()
    assert (desk.of(FactChanged)[-1].status, desk.of(FactChanged)[-1].change_id) == (ChangeStatus.CONFIRMED_BOTH, "c-on-call")


# ---- related terms asked together (the user: "group the questions related to each other together") ----

ALL_SIX = {
    ItemKey.WORK: "painting the 2BHK flat, two coats",
    ItemKey.AMOUNT: "22,000 rupees with material",
    ItemKey.ADVANCE: "5,000 rupees",
    ItemKey.BALANCE: "on the day the work is finished",
    ItemKey.DATES: "next Monday to Friday",
    ItemKey.LATE_OR_UNFINISHED: "500 rupees a day if late",
}


def speech_s(text: str) -> float:
    """A fake clock for one turn: Gawah reading the step's terms (2.5 words a second, the call-back's
    0.95 speed), the model's first sound (1 s), and the person's answer (2 s)."""
    terms = text.split("The terms - ")[-1].split("The term - ")[-1].split(". The shape")[0].split(". Report")[0]
    return len(terms.split()) / 2.5 / tuning.CALLBACK_SPEED + 1.0 + 2.0


async def test_a_full_call_back_is_three_questions_and_a_yes_to_each_confirms_all_six(desk):
    await desk.deal(agreed=ALL_SIX)
    seat, link = await desk.join()
    opening = link.of("conversation.item.create")[0]["item"]["content"][0]["text"]
    assert "the work: painting the 2BHK flat" in opening and "22,000" not in opening  # the work on its own
    steps = [opening]
    steps.append(await link.calls("term_answer", item="work", agrees=True, said="haan"))
    assert 'under the heading "Paise ki baat"' in steps[-1] and "the advance: 5,000 rupees" in steps[-1] and "the balance:" in steps[-1]
    assert "Kya yeh sab sahi hai?" in steps[-1]
    steps.append(await link.calls("group_answer", agrees=True, wrong=[], said="haan, sab sahi hai"))
    assert 'under the heading "Samay"' in steps[-1] and "next Monday to Friday" in steps[-1] and "500 rupees a day" in steps[-1]
    steps.append(await link.calls("group_answer", agrees=True, wrong=[], said="haan ji"))
    assert steps[-1].startswith("Noted. Last step") and "Every term is confirmed" in steps[-1]
    await desk.bus.drain()
    assert not desk.of(TermsDisputed) and [e.person for e in desk.of(TermsConfirmed)] == [Role.WORKER]
    asked = steps[:-1]
    print(f"\ncall-back: {len(asked)} questions, about {sum(speech_s(s) for s in asked):.0f} s (fake clock)")


async def test_a_no_naming_the_advance_disputes_only_the_advance(desk):
    await desk.deal(agreed=ALL_SIX)
    seat, link = await desk.join()
    await link.calls("term_answer", item="work", agrees=True, said="haan")
    then = await link.calls("group_answer", agrees=False, wrong=["advance"], said="advance galat hai, teen hazaar tha")
    assert "Gawah will raise this with Sunita" in then and 'heading "Samay"' in then
    await desk.bus.drain()
    assert [(e.item, e.value, e.said) for e in desk.of(TermsDisputed)] == [
        (ItemKey.ADVANCE, "5,000 rupees", "advance galat hai, teen hazaar tha")]
    then = await link.calls("group_answer", agrees=True, wrong=[], said="haan")
    assert "the advance" in then and "nothing is final until both agree" in then


async def test_a_no_naming_nothing_is_asked_about_once_and_the_named_term_is_disputed(desk):
    await desk.deal(agreed=ALL_SIX)
    seat, link = await desk.join()
    await link.calls("term_answer", item="work", agrees=True, said="haan")
    then = await link.calls("group_answer", agrees=False, wrong=[], said="nahi")
    assert "Kaunsi baat sahi nahi hai?" in then and not desk.of(TermsDisputed)  # asking which: nothing recorded yet
    then = await link.calls("group_answer", agrees=False, wrong=["balance"], said="baaki wala nahi, aadha beech mein tha")
    await desk.bus.drain()
    assert [e.item for e in desk.of(TermsDisputed)] == [ItemKey.BALANCE] and 'heading "Samay"' in then


async def test_only_the_amount_changed_is_one_question_and_the_summary_line(desk):
    await call_2_changed_the_amount(desk)
    seat, link = await desk.join(role=Role.WORKER)
    opening = link.of("conversation.item.create")[0]["item"]["content"][0]["text"]
    assert "Record mein 22,000 rupees with material tha; call par 24,000" in opening and "heading" not in opening
    then = await link.calls("change_answer", agrees=True, said="haan")
    assert then.startswith("Noted. Last step") and "Baaki sab pehle jaisa hai" in then


async def test_before_grouping_the_same_call_back_was_six_questions(desk):
    """The fake clock on the old shape: one term a step (STEP_TERM), for the comparison in the report."""
    steps = [tuning.STEP_TERM.format(label=tuning.LABEL[k], value=v, key=k.value) for k, v in ALL_SIX.items()]
    print(f"\nbefore: {len(steps)} questions, about {sum(speech_s(s) for s in steps):.0f} s (fake clock)")
    assert len(steps) == 6
