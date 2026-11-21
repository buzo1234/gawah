"""The dashboard's fold on what the real memory sends: both practice calls through the
Scribe's saved replies, then an advance and a payment on WhatsApp and a change both people
agree to. The page's reading (state.js and crew-state.js, run in Node) must agree with
memory's own answers: each fact's latest version, the term each item stands on, what is
paid and owed, and the number of chain links. Skipped where Node is not installed."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from app.contracts import (
    ChangeStatus, FactChanged, ItemKey, Record, RecordKind, RecordReceived, Role,
)
from app.memory import Memory
from app.memory.extract import RecordedExtractor, Routed
from app.memory.vectors import WordHashEmbedder
from fakes.replayer import replay

STATIC = Path(__file__).parent.parent / "app" / "dashboard" / "static"
READ = """
import { readFileSync } from "node:fs";
import { apply, emptyState, ITEMS } from "%s";
import { owed, standing } from "%s";
const events = JSON.parse(readFileSync(process.argv[2], "utf8"));
const state = emptyState(process.argv[3]);
for (const e of events) apply(state, e);
console.log(JSON.stringify({
  facts: Object.fromEntries(state.factOrder.map((id) => [id, state.facts[id].status])),
  standing: Object.fromEntries(ITEMS.map(([key]) => [key, standing(state, key)?.id ?? null])),
  owed: owed(state), links: state.chain.links, conflicts: state.conflicts.map((c) => c.factIds),
}));
"""


def read(events, deal: str, tmp_path: Path) -> dict:
    data = tmp_path / "events.json"
    data.write_text(json.dumps([e.model_dump(mode="json") for e in events]))
    script = tmp_path / "read.mjs"
    script.write_text(READ % ((STATIC / "state.js").as_uri(), (STATIC / "crew-state.js").as_uri()))
    run = subprocess.run(["node", script, data, deal], capture_output=True, text=True, timeout=30)
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)


async def settle(bus, memory) -> None:
    for _ in range(3):
        await bus.drain()
        await memory.settle()


@pytest.mark.skipif(not shutil.which("node"), reason="needs Node to run the page's own fold")
@pytest.mark.parametrize("fixture", ["fixtures/call_two_amounts.json", "fixtures/call_missing_balance.json"])
async def test_the_page_reads_the_real_memory_as_memory_does(bus, tmp_path, fixture):
    memory = Memory(bus, Routed(None, RecordedExtractor()), WordHashEmbedder(), root=tmp_path, embed_model="hash")
    memory.attach(bus)
    seen = []

    async def keep(event):
        seen.append(event)

    bus.subscribe_all(keep)
    deal = await replay(bus, fixture, speed=0)
    await settle(bus, memory)
    bus.publish(RecordReceived(deal_id=deal, record=Record(sender=Role.HIRER, kind=RecordKind.ADVANCE, amount=2000, text="2000 advance diya")))
    bus.publish(RecordReceived(deal_id=deal, record=Record(sender=Role.HIRER, kind=RecordKind.PAYMENT, amount=5000, text="5000 aur diye")))
    await settle(bus, memory)
    amount = (await memory.get_term(deal, ItemKey.AMOUNT)).current
    bus.publish(FactChanged(
        deal_id=deal, fact_id=amount.id, new_value="26,000 rupees", item=ItemKey.AMOUNT, proposed_by=Role.HIRER,
        status=ChangeStatus.CONFIRMED_BOTH, confirmed_by=[Role.WORKER, Role.HIRER],
    ))
    await settle(bus, memory)

    page = read(seen, deal, tmp_path)
    book = memory.book.deal(deal)
    assert page["facts"] == {f.id: f.status.value for f in book.standing()}
    assert page["facts"][amount.id] == "superseded"
    assert page["links"] == len(book.versions)
    for item in ItemKey:
        current = (await memory.get_term(deal, item)).current
        assert page["standing"][item.value] == (current.id if current else None), item
    for row in await memory.owed(deal):
        shown = page["owed"][row.item.value]
        assert (shown["agreed"], shown["paid"], shown["owed"]) == (row.agreed_rupees, row.paid_rupees, row.owed_rupees), row.item
        assert shown["payments"] == row.payment_fact_ids, row.item
    assert page["conflicts"] == [c.fact_ids for c in memory.conflicts if c.deal_id == deal]
