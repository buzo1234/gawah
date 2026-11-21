"""The call-back, with a fake room and the test playing the voice model's part."""

import asyncio

import httpx
import pytest
from fastapi import FastAPI

from app.contracts import (
    Backing, CallEnded, CallKind, CallStarted, ChecklistItem, ChecklistUpdated, DealRequested, ItemKey,
    ItemState, Record, RecordConfirmed, RecordConfirmRequested, RecordKind, RecordReceived, Role, TermsConfirmed,
    TermsDisputed, callback_path,
)
from app.mouth import callback, tuning
from app.store import Store
from fakes import RAMESH, SUNITA
from tests.mouth.world import LOUD, FakeLink, FakeSeat, until

AGREED = {
    ItemKey.WORK: "painting the 2BHK flat, two coats",
    ItemKey.AMOUNT: "22,000 rupees with material",
    ItemKey.DATES: "Monday to Friday",
}


class FakeRooms:
    url = "wss://livekit.invalid"

    def __init__(self) -> None:
        self.made: list[str] = []
        self.deleted: list[str] = []

    async def create(self, name: str, empty_timeout: int, max_participants: int) -> None:
        self.made.append(name)

    async def delete(self, name: str) -> None:
        self.deleted.append(name)

    def token(self, room: str, identity: str, name: str | None = None) -> str:
        return f"token:{room}:{identity}"


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
        seat.hears(role.value, LOUD, 100)
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
    assert page.status_code == 200 and "Baat shuru karein" in page.text
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
    assert link.config["audio"]["input"]["turn_detection"]["create_response"]  # here the model does reply by itself
    assert {t["name"] for t in link.config["tools"]} == {"record_answer", "term_answer", "end_call"}

    then = await link.calls("term_answer", item="work", agrees=True, said="haan theek hai")
    assert "the total amount: 22,000 rupees with material" in then
    then = await link.calls("term_answer", item="amount", agrees=True, said="haan")
    assert "the dates: Monday to Friday" in then and not desk.of(TermsConfirmed)
    then = await link.calls("term_answer", item="dates", agrees=True, said="haan sahi hai")
    confirmed = (await until(lambda: desk.of(TermsConfirmed)))[0]
    assert (confirmed.person, confirmed.item, confirmed.said) == (Role.WORKER, None, "haan sahi hai")
    # The terms that were never agreed are said plainly, and not confirmed.
    assert "never agreed" in then and "the advance, the balance, what happens if the work is late" in then
    assert "end_call" in then and not desk.of(TermsDisputed)

    await link.says("Dhanyavaad Ramesh ji. Namaste.", calls=[("end_call", {})])
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
    await link.says("Theek hai. Namaste.", calls=[("end_call", {})])
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
        ("end_call", {}),
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


async def test_the_person_talking_over_gawah_stops_it(desk):
    await desk.deal()
    seat, link = await desk.join()
    await until(lambda: link.sent and not desk.app.state.callbacks[("d1", Role.WORKER)].player.active)
    item = await link.says("Pehli shart: poore flat ki painting, do coat ...", ms=3000)
    call = desk.app.state.callbacks[("d1", Role.WORKER)]
    await until(lambda: call.player.given_ms >= 200)
    await link.on_event({"type": "input_audio_buffer.speech_started"})
    assert not call.player.active and seat.cleared
    cut = link.of("conversation.item.truncate")[0]
    assert cut["item_id"] == item and 200 <= cut["audio_end_ms"] < 3000  # the model is told how much was heard
    # The person's audio reaches the model, which is how it hears the answer.
    seat.hears("worker", LOUD, 100)
    await until(lambda: link.of("input_audio_buffer.append"))


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
