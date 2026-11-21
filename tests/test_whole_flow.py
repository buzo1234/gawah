"""One deal, from the first WhatsApp message to a confirmed record, through the whole app
in one process with every outside service replaced by a fake (tests/offline.py).

Each stream's own tests pass with the other streams absent. This is the guard for what
happens between them. When a stream is merged, fill in its step below where the comment
marks it, and put the fake for its outside service in tests/offline.py.
"""

import logging

import httpx
import pytest

from app.contracts import (
    WHATSAPP_WEBHOOK_PATH, Backing, ChecklistUpdated, DealRequested, DealStatus, Direction, Event,
    ItemKey, ItemState, JudgeSpeak, RecordConfirmed, RecordConfirmRequested, RecordReceived, Role,
    TranscriptLine, WhatsAppMessage, call_path, callback_path,
)
from fakes.replayer import load, replay
from tests.offline import offline_app
from tests.whatsapp_world import FakeClock

# Neither number is in VERIFIED_NUMBERS, so both are simulated phones, like the dashboard's.
PHONE = {Role.HIRER: "+919000000001", Role.WORKER: "+919000000002"}
CALL = "fixtures/call_missing_balance.json"


class Flow:
    """The running app, every event it has published, and a way in for each person."""

    def __init__(self, app, client: httpx.AsyncClient, clock: FakeClock) -> None:
        self.app, self.client, self.clock = app, client, clock
        self.bus, self.store = app.state.bus, app.state.store
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

    def of(self, kind: type[Event]) -> list:
        return [e for e in self.events if isinstance(e, kind)]

    def sent_to(self, role: Role) -> list[str]:
        """What Gawah has sent this person on WhatsApp, oldest first."""
        return [
            m.text or "" for m in self.of(WhatsAppMessage)
            if m.direction is Direction.OUT and m.phone == PHONE[role]
        ]


@pytest.fixture
async def flow(tmp_path):
    clock = FakeClock()
    app = offline_app(tmp_path / "test.db", clock)
    transport = httpx.ASGITransport(app=app)
    async with app.router.lifespan_context(app), httpx.AsyncClient(transport=transport, base_url="http://gawah.test") as client:
        yield Flow(app, client, clock)


async def test_a_deal_from_the_first_message_to_a_confirmed_record(flow, caplog):
    # whatsapp: the hirer sends the worker's number. That makes the deal, and both get a call link.
    await flow.whatsapp(Role.HIRER, PHONE[Role.WORKER].removeprefix("+91"), name="Asha")
    [requested] = flow.of(DealRequested)
    deal_id = requested.deal_id
    assert (requested.requested_by.phone, requested.other.phone) == (PHONE[Role.HIRER], PHONE[Role.WORKER])
    for role in Role:
        assert call_path(deal_id, role) in flow.sent_to(role)[-1]

    # bridge (not merged): a practice call replayed into the deal stands in for the real call.
    # Once bridge is in, also check here that call_path(deal_id, role) serves its call page.
    await replay(flow.bus, CALL, speed=0, deal_id=deal_id)
    await flow.settle()
    assert {e.deal_id for e in flow.of(TranscriptLine)} == {deal_id}

    # brain: the checklist fills in, and the Judge asks about the balance nobody brought up.
    expected = [e for e in load(CALL)["expected"] if "live" in e["modes"]]
    speaks = flow.of(JudgeSpeak)
    assert [(s.item, s.reason, s.to) for s in speaks] == [(e["item"], e["reason"], e["to"]) for e in expected]
    assert all(e["after_line"] <= s.after_line <= e["by_line"] for s, e in zip(speaks, expected))
    final = {item.key: item for item in flow.of(ChecklistUpdated)[-1].items}
    assert final.pop(ItemKey.BALANCE).state is ItemState.PENDING
    assert all(item.state is ItemState.AGREED and item.value for item in final.values())

    # mouth (not merged): every judge.speak above should be answered by a judge.spoke, and the
    # call-back should end in terms.confirmed.
    # contract (not merged): contract.ready should follow, and both people get the PDF.

    # whatsapp: after call.ended both get their call-back link. The deal's people are still
    # the two who made it on WhatsApp, not the two named in the practice call.
    for role in Role:
        assert callback_path(deal_id, role) in flow.sent_to(role)[-1]
    assert {m.phone for m in flow.of(WhatsAppMessage)} == set(PHONE.values())
    deal = await flow.store.deal(deal_id)
    assert deal.status is DealStatus.CALL_ENDED
    assert {p.role: (p.name, p.phone) for p in deal.people} == {
        Role.HIRER: ("Asha", PHONE[Role.HIRER]), Role.WORKER: ("Ramesh", PHONE[Role.WORKER]),
    }

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
    assert [r.confirmed for r in await flow.store.records(deal_id)] == [True]

    # dashboard: a fresh page load gets the deal's people and every event above, in order.
    state = (await flow.client.get("/dashboard/state", params={"deal": deal_id})).json()
    assert state["deals"][0]["names"] == {"hirer": "Asha", "worker": "Ramesh"}
    assert state["events"] == [e.model_dump(mode="json") for e in flow.events]

    # No stream raised on an event or logged an error anywhere along the way.
    assert [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR] == []
