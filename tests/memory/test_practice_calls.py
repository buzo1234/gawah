"""Both practice calls replayed through the Scribe on the live model's saved replies
(tests/memory/recorded/, made with tests/memory/record.py)."""

from app.contracts import FactConflict, FactRecorded, FactStatus, ItemKey
from app.memory import Memory
from app.memory.extract import RecordedExtractor, Routed
from app.memory.vectors import WordHashEmbedder
from fakes.replayer import replay


async def play(bus, tmp_path, fixture: str):
    memory = Memory(bus, Routed(None, RecordedExtractor()), WordHashEmbedder(), root=tmp_path, embed_model="hash")
    memory.attach(bus)
    seen = []

    async def keep(event):
        seen.append(event)

    bus.subscribe_all(keep)
    deal = await replay(bus, fixture, speed=0)
    for _ in range(3):
        await bus.drain()
        await memory.settle()
    return memory, deal, seen


async def test_two_amounts_gives_the_13000_agreement_and_catches_the_14000(bus, tmp_path):
    memory, deal, seen = await play(bus, tmp_path, "fixtures/call_two_amounts.json")
    amount = await memory.get_term(deal, ItemKey.AMOUNT)
    assert (amount.current.value_rupees, amount.current.status, amount.current.line_no) == (13000, FactStatus.AGREED, 11)
    assert set(amount.current.agreed_by) | {amount.current.said_by} == {"hirer", "worker"}
    offers = [f.value_rupees for f in amount.history if f.status == FactStatus.SAID and f.line_no in (7, 9, 10)]
    assert offers == [15000, 14000, 12000]
    assert (await memory.get_term(deal, ItemKey.ADVANCE)).current.value_rupees == 3000

    conflicts = [e for e in seen if isinstance(e, FactConflict)]
    assert [(c.line_no, c.fact_ids) for c in conflicts] == [(19, [amount.current.id])]
    assert "14,000 rupees" in conflicts[0].explanation and "13,000 rupees" in conflicts[0].explanation
    assert all(e.fact.quote for e in seen if isinstance(e, FactRecorded))
    assert memory.chain_break(deal) is None


async def test_missing_balance_leaves_the_balance_open_and_raises_nothing(bus, tmp_path):
    memory, deal, seen = await play(bus, tmp_path, "fixtures/call_missing_balance.json")
    rows = {r.item: r for r in await memory.owed(deal)}
    assert (rows[ItemKey.AMOUNT].agreed_rupees, rows[ItemKey.ADVANCE].agreed_rupees) == (24000, 8000)
    assert (await memory.get_term(deal, ItemKey.BALANCE)).current is None
    assert rows[ItemKey.BALANCE].agreed_rupees == 16000  # amount less advance: arithmetic, not a term
    assert [e for e in seen if isinstance(e, FactConflict)] == []
