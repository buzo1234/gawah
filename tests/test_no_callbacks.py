"""CALLBACKS_ENABLED=false (app/records/no_callbacks.py): no call-back after a deal call.
What both agreed on the call counts as confirmed by both, and the agreement is written
right after the call. The whole app on its fakes (tests/offline.py), the real memory."""

import logging
from datetime import UTC, datetime

import httpx
import pytest

from app.contracts import (
    MEMORY_STATE, AgentNote, CallEnded, CallKind, CallStarted, ChangeStatus, ContractReady, CrewAgent, DealRequested, FactChanged,
    FactStatus, ItemKey, Role, TermsConfirmed, callback_path,
)
from app.contract.wording import CONFIRMED, ON_THE_CALL
from app.mouth import tuning as mouth_tuning
from app.records.no_callbacks import SAID
from fakes.replayer import replay
from tests.offline import offline_app
from tests.test_whole_flow import PHONE, Flow

CALL = "fixtures/call_missing_balance.json"  # the balance is never agreed on it


@pytest.fixture(params=["twilio", "meta"])
async def flow(tmp_path, request, monkeypatch):
    monkeypatch.setenv("CALLBACKS_ENABLED", "false")
    app = offline_app(tmp_path / "test.db", whatsapp=request.param)
    transport = httpx.ASGITransport(app=app)
    async with app.router.lifespan_context(app), httpx.AsyncClient(transport=transport, base_url="http://gawah.test") as client:
        yield Flow(app, client, None)


async def first_call(flow: Flow) -> str:
    """The hirer starts a deal on WhatsApp, and the practice call is replayed into it."""
    await flow.whatsapp(Role.HIRER, PHONE[Role.WORKER].removeprefix("+91"), name="Sunita")
    [requested] = flow.of(DealRequested)
    deal_id = await replay(flow.bus, CALL, speed=0, deal_id=requested.deal_id)
    await flow.until(ContractReady)
    return deal_id


def no_callback_link(flow: Flow, deal_id: str) -> None:
    for role in Role:
        assert not [t for t in flow.sent_to(role) if callback_path(deal_id, role) in t], flow.sent_to(role)


async def test_the_call_ends_with_what_both_agreed_confirmed_and_the_agreement_written(flow, caplog):
    deal_id = await first_call(flow)
    memory = getattr(flow.app.state, MEMORY_STATE)

    no_callback_link(flow, deal_id)
    agreed = {k for k in ItemKey if (await memory.get_term(deal_id, k)).current}
    assert agreed and ItemKey.BALANCE not in agreed
    confirmed = flow.of(TermsConfirmed)
    assert {(e.person, e.item) for e in confirmed} == {(r, k) for r in Role for k in agreed}
    assert all(e.said == SAID and e.value for e in confirmed)
    for key in agreed:  # memory has each confirmed by both
        term = (await memory.get_term(deal_id, key)).current
        assert (term.status, set(term.confirmed_by)) == (FactStatus.CONFIRMED, set(Role))
    assert (await memory.get_term(deal_id, ItemKey.BALANCE)).current is None  # not agreed stays not agreed

    [ready] = flow.of(ContractReady)
    assert ready.pdf_key.endswith("-v1.pdf")
    assert "These were not agreed on the call: when the balance is paid and against what." in ready.text
    accepted = ready.text.split("ACCEPTANCE")[1]  # no call-back to point to: the call itself is the acceptance
    assert accepted.count(ON_THE_CALL.en) == 2 and CONFIRMED.en not in accepted and SAID not in accepted
    for role in Role:  # the agreement went to both
        assert any(ready.pdf_url == t or ready.voice_summary_url == t for t in flow.sent_to(role))
    [note] = [n for n in flow.of(AgentNote) if n.agent is CrewAgent.SENTINEL and "call-backs off" in n.text]
    assert note.text.startswith("call 1: call-backs off, agreed on the call counts as confirmed")

    # The call-back page has nothing to ask, whoever opens it.
    for role in Role:
        joined = await flow.client.post(callback_path(deal_id, role) + "/join")
        assert (joined.status_code, joined.json()["message"]) == (404, mouth_tuning.PAGE_NOTHING)
    assert [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR] == []


async def test_a_change_both_confirmed_on_call_2_makes_version_2_with_no_call_back(flow, caplog):
    deal_id = await first_call(flow)
    memory = getattr(flow.app.state, MEMORY_STATE)
    amount = (await memory.get_term(deal_id, ItemKey.AMOUNT)).current
    before = len(flow.of(TermsConfirmed))

    started = datetime.now(UTC)
    flow.bus.publish(CallStarted(deal_id=deal_id, call_no=2, room=f"replay-{deal_id}-2", ts=started))
    for status, confirmed in ((ChangeStatus.PROPOSED, []), (ChangeStatus.CONFIRMED_ONE, [Role.HIRER]),
                              (ChangeStatus.CONFIRMED_BOTH, list(Role))):
        flow.bus.publish(FactChanged(  # as Gawah puts it to both on the call
            deal_id=deal_id, change_id="c-1", fact_id=amount.id, new_value="26,000", status=status,
            item=ItemKey.AMOUNT, proposed_by=Role.HIRER, confirmed_by=confirmed, said="haan ji",
        ))
    await flow.settle()
    flow.bus.publish(CallEnded(deal_id=deal_id, call_no=2, kind=CallKind.DEAL, room=f"replay-{deal_id}-2", duration=60.0))
    await flow.until(lambda: len(flow.of(ContractReady)) == 2)

    no_callback_link(flow, deal_id)
    assert len(flow.of(TermsConfirmed)) == before  # the change was confirmed on the call: nothing to add
    v2 = flow.of(ContractReady)[-1]
    assert v2.pdf_key.endswith("-v2.pdf") and "26,000" in v2.text
    now = (await memory.get_term(deal_id, ItemKey.AMOUNT)).current
    assert (now.value_rupees, set(now.confirmed_by)) == (26000, set(Role))
    assert [n.text for n in flow.of(AgentNote) if "call-backs off" in n.text][-1] == "call 2: call-backs off, nothing new to confirm"
    assert [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR] == []
