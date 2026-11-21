import io
import wave

from app.contracts import FactStatus, ItemKey, MemoryQueries
from fakes.memory import FakeMemory, silent_wav, two_amounts_facts

DEAL = "replay-two-amounts"


async def test_the_fake_memory_answers_the_two_amounts_call():
    memory = FakeMemory(two_amounts_facts(), clips={"f-amount": silent_wav()})
    assert isinstance(memory, MemoryQueries)

    amount = await memory.get_term(DEAL, ItemKey.AMOUNT)
    assert (amount.current.id, amount.current.status, amount.current.value_rupees) == ("f-amount", FactStatus.CONFIRMED, 13000)
    assert [(f.id, f.status) for f in amount.history] == [
        ("f-offer", FactStatus.SAID), ("f-amount", FactStatus.AGREED),
        ("f-offer", FactStatus.SUPERSEDED), ("f-amount", FactStatus.CONFIRMED),
    ]
    assert (await memory.get_term(DEAL, ItemKey.DATES)).current is None

    rows = {r.item: r for r in await memory.owed(DEAL)}
    assert list(rows) == [ItemKey.AMOUNT, ItemKey.ADVANCE, ItemKey.BALANCE]
    advance = rows[ItemKey.ADVANCE]
    assert (advance.agreed_rupees, advance.paid_rupees, advance.owed_rupees, advance.payment_fact_ids) == (3000, 3000, 0, ["f-paid"])
    assert (rows[ItemKey.AMOUNT].owed_rupees, rows[ItemKey.BALANCE].agreed_rupees) == (13000, None)

    found = await memory.search(DEAL, "labour ka kitna tay hua, 15 ya 13?")
    assert [f.id for f in found] == ["f-amount", "f-offer"]  # confirmed above superseded
    assert await memory.search(DEAL, "advance", k=1) == [two_amounts_facts()[-1]]  # the confirmed payment
    assert await memory.search("other-deal", "advance") == []

    with wave.open(io.BytesIO(await memory.clip("f-amount"))) as wav:
        assert (wav.getframerate(), wav.getnchannels()) == (24000, 1)
    assert await memory.clip("f-offer") is None
