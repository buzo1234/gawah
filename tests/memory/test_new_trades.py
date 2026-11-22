"""The Scribe's live model on calls written for these causes (tests/memory/calls/), in trades
Gawah was not built on, through its saved replies (tests/memory/recorded/robust_*.json).
Together with the code behind it:

1. Saying the other person's figure back with a complaint, a question, a hedge or a deferral accepts nothing.
2. A rate is not the total; a balance in parts is one schedule; an extra agreed goes on the total
   and into the payment it is put in.
3. The age of the thing repaired is not the work, leave is not the late term, a price that
   applies only if something turns up is not the amount.
"""

import tempfile
from pathlib import Path

from app.bus import Bus
from app.contracts import FactConflict, FactKind, FactRecorded, FactStatus, ItemKey
from app.memory import Memory
from app.memory.extract import RecordedExtractor
from app.memory.vectors import WordHashEmbedder
from fakes.replayer import replay

CALLS = Path(__file__).parent / "calls"


async def read(name: str):
    bus = Bus()
    memory = Memory(bus, RecordedExtractor(), WordHashEmbedder(), root=Path(tempfile.mkdtemp()), embed_model="hash")
    memory.attach(bus)
    seen = []

    async def keep(event):
        seen.append(event)

    bus.subscribe_all(keep)
    bus.start()
    deal = await replay(bus, CALLS / f"{name}.json", speed=0, deal_id=name)
    for _ in range(3):
        await bus.drain()
        await memory.settle()
    terms = {k: (await memory.get_term(deal, k)).current for k in ItemKey}
    await bus.stop()
    facts = [e.fact for e in seen if isinstance(e, FactRecorded)]
    return terms, facts, [e for e in seen if isinstance(e, FactConflict)]


def figure(term) -> int | None:
    return term.value_rupees if term else None


async def test_geyser_a_complaint_and_a_deferral_accept_nothing_and_a_conditional_price_is_no_term():
    terms, facts, conflicts = await read("robust_geyser")
    assert (figure(terms[ItemKey.AMOUNT]), terms[ItemKey.AMOUNT].status) == (650, FactStatus.AGREED)
    agreed = (FactStatus.AGREED, FactStatus.CONFIRMED)
    assert not [f for f in facts if f.value_rupees in (800, 1200, 1850) and f.status in agreed]
    assert not [f for f in facts if f.item == ItemKey.WORK and f.kind == FactKind.TERM and "year" in (f.value or f.text).lower()]
    assert conflicts == []


async def test_cook_monthly_pay_is_the_amount_and_leave_is_not_the_late_term():
    terms, facts, conflicts = await read("robust_cook")
    assert figure(terms[ItemKey.AMOUNT]) == 9000
    late = [f for f in facts if f.item == ItemKey.LATE_OR_UNFINISHED and f.kind == FactKind.TERM]
    assert late and all("leave" not in (f.value or "").lower() and "sunday" not in (f.value or "").lower() for f in late)
    assert conflicts == []


async def test_terrace_a_rate_a_schedule_and_an_extra_bargained_into_the_last_payment():
    terms, facts, conflicts = await read("robust_terrace")
    assert conflicts == []
    assert not [f for f in facts if f.item == ItemKey.AMOUNT and f.value_rupees == 28]
    amount, balance = terms[ItemKey.AMOUNT], terms[ItemKey.BALANCE]
    # The extra is agreed on the call and waits for both to confirm it through Gawah: the terms stand till then.
    assert (amount.value_rupees, amount.status) == (26000, FactStatus.AGREED)
    assert figure(terms[ItemKey.ADVANCE]) == 10000
    assert (balance.value_rupees, balance.status) == (16000, FactStatus.AGREED)
    latest = {f.id: f for f in facts}
    open_changes = {f.item: f for f in latest.values() if f.kind == FactKind.CHANGE and f.status == FactStatus.AGREED}
    assert open_changes[ItemKey.AMOUNT].value_rupees == 29500, "26,000 agreed + 3,500 extra"
    carried = open_changes[ItemKey.BALANCE]
    assert carried.value_rupees == 19500 and "9,500" in carried.value and "10,000" in carried.value


async def test_gate_a_hedge_before_a_counter_is_not_acceptance():
    terms, facts, conflicts = await read("robust_gate")
    assert (figure(terms[ItemKey.AMOUNT]), terms[ItemKey.AMOUNT].status) == (14000, FactStatus.AGREED)
    assert not [f for f in facts if f.value_rupees == 13000 and f.status != FactStatus.SAID]
    assert figure(terms[ItemKey.ADVANCE]) == 4000
    assert conflicts == []
