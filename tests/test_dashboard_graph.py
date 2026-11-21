"""The knowledge graph's layout (app/dashboard/static/graph-layout.js, run in Node) on what
the real memory sends for call_two_amounts, then an advance and a payment on WhatsApp:
every fact is placed once, the fact each term stands on sits in the term, tied to both
people, payments sit with the term they count towards, the contradiction is a red edge
with its card open under the amount, nothing overlaps, and the same state always gives
the same layout. Skipped where Node is not installed."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from app.contracts import (
    CallStarted, Fact, FactConflict, FactKind, FactRecorded, FactSource, FactStatus, ItemKey, Record, RecordKind,
    RecordReceived, Role,
)
from app.memory import Memory
from app.memory.extract import RecordedExtractor, Routed
from app.memory.vectors import WordHashEmbedder
from fakes.replayer import replay

STATIC = Path(__file__).parent.parent / "app" / "dashboard" / "static"
LAYOUT = """
import { readFileSync } from "node:fs";
import { apply, emptyState, ITEMS } from "%s";
import { standing } from "%s";
import { layout } from "%s";
const events = JSON.parse(readFileSync(process.argv[2], "utf8"));
const fold = (upTo) => {
  const state = emptyState(process.argv[3]);
  for (const e of events.slice(0, upTo)) apply(state, e);
  return state;
};
const state = fold(events.length);
const L = layout(state);
const before = layout(fold(Number(process.argv[4])));
console.log(JSON.stringify({
  L, again: JSON.stringify(layout(state)) === JSON.stringify(L), before,
  facts: state.factOrder, links: state.chain.links, chain: state.chain.list.map((l) => l.where),
  standing: Object.fromEntries(ITEMS.map(([k]) => [k, standing(state, k)?.id ?? null])),
  towards: Object.fromEntries(state.factOrder.map((id) => [id, state.facts[state.facts[id].counts_towards]?.item ?? null])),
}));
"""


def run_layout(events, deal: str, before: int, tmp_path: Path) -> dict:
    data = tmp_path / "events.json"
    data.write_text(json.dumps([e.model_dump(mode="json") for e in events]))
    script = tmp_path / "layout.mjs"
    script.write_text(LAYOUT % tuple((STATIC / name).as_uri() for name in ("state.js", "crew-state.js", "graph-layout.js")))
    run = subprocess.run(["node", script, data, deal, str(before)], capture_output=True, text=True, timeout=30)
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)


def overlap(a: dict, b: dict) -> bool:
    return a["x"] < b["x"] + b["w"] and b["x"] < a["x"] + a["w"] and abs(a["y"] - b["y"]) < (a["h"] + b["h"]) / 2


@pytest.mark.skipif(not shutil.which("node"), reason="needs Node to run the page's own layout")
async def test_the_graph_places_every_fact_once_and_ties_agreements_to_both(bus, tmp_path):
    memory = Memory(bus, Routed(None, RecordedExtractor()), WordHashEmbedder(), root=tmp_path, embed_model="hash")
    memory.attach(bus)
    seen = []

    async def keep(event):
        seen.append(event)

    bus.subscribe_all(keep)
    deal = await replay(bus, "fixtures/call_two_amounts.json", speed=0)
    for _ in range(3):
        await bus.drain()
        await memory.settle()
    before_payments = len(seen)
    bus.publish(RecordReceived(deal_id=deal, record=Record(sender=Role.HIRER, kind=RecordKind.ADVANCE, amount=3000, text="3000 advance diya")))
    bus.publish(RecordReceived(deal_id=deal, record=Record(sender=Role.HIRER, kind=RecordKind.PAYMENT, amount=5000, text="5000 aur diye")))
    for _ in range(3):
        await bus.drain()
        await memory.settle()

    got = run_layout(seen, deal, before_payments, tmp_path)
    L = got["L"]
    placed = [n["id"] for n in L["nodes"] if n["id"].startswith("fact-")]
    assert sorted(placed) == sorted(f"fact-{i}" for i in got["facts"])  # every fact, once
    assert got["again"]  # the same state, the same layout: nothing jitters on a redraw

    hubs = {n["item"]: n["id"][5:] for n in L["nodes"] if n["place"] == "hub"}
    assert hubs == {k: v for k, v in got["standing"].items() if v}
    ties = {e["key"] for e in L["edges"] if e["cls"].startswith("tie")}
    assert ties == {f"tie:{item}:{who}" for item in hubs for who in ("hirer", "worker")}

    payments = [n for n in L["nodes"] if n.get("kind") == "money"]
    assert len(payments) == 2
    for n in payments:
        assert n["item"] == got["towards"][n["id"][5:]] and n["side"] == "hirer"

    # The contradiction: what Ramesh said on line 19 is red, with a red edge to the agreed
    # 13,000 in the amount, and its card open under the amount; the rows below make room.
    conflict = [e for e in L["edges"] if e["cls"] == "conflict"]
    assert len(conflict) == 1 and conflict[0]["key"].endswith(hubs[ItemKey.AMOUNT])
    hot = [n for n in L["nodes"] if n.get("hot")]
    assert len(hot) == 1 and hot[0]["side"] == "worker" and hot[0]["item"] == "amount"
    card = L["card"]
    assert card["item"] == "amount"
    assert L["rows"]["amount"]["top"] + 96 < card["top"] < card["top"] + 168 < L["rows"]["advance"]["top"]

    pills = [n for n in L["nodes"] if n["place"] == "pill"]
    for a in pills:
        assert 188 <= a["x"] and a["x"] + a["w"] <= 1268, a["label"]
        assert not (508 - 40 < a["x"] + a["w"] and a["x"] < 948 + 40), a["label"]  # clear of the terms
        for b in pills:
            assert a is b or not overlap(a, b), (a["label"], b["label"])

    # Every link of the chain is drawn, grouped by where it was sealed.
    assert len(got["chain"]) == got["links"]
    assert got["chain"][0] == "Call 1" and got["chain"][-1].startswith("WhatsApp")

    # A node stays where it was while later facts arrive on other terms.
    earlier = {n["id"]: (n["x"], n["y"]) for n in got["before"]["nodes"] if n["item"] == "work"}
    now = {n["id"]: (n["x"], n["y"]) for n in L["nodes"] if n["id"] in earlier}
    assert now == earlier


CARD = """
import { readFileSync } from "node:fs";
import { apply, emptyState } from "%s";
import { layout } from "%s";
const events = JSON.parse(readFileSync(process.argv[2], "utf8"));
const state = emptyState("d-card");
const open = [];
for (const e of events) { apply(state, e); open.push(layout(state).card?.item ?? null); }
console.log(JSON.stringify(open));
"""


@pytest.mark.skipif(not shutil.which("node"), reason="needs Node to run the page's own layout")
def test_a_contradiction_of_a_confirmed_term_opens_its_card_until_a_change_replaces_it(tmp_path):
    deal = "d-card"
    amount = Fact(deal_id=deal, text="The amount is 22,000.", item=ItemKey.AMOUNT, kind=FactKind.TERM, value="22,000 rupees",
                  value_rupees=22000, status=FactStatus.CONFIRMED, said_by=Role.WORKER, agreed_by=[Role.HIRER],
                  confirmed_by=[Role.HIRER, Role.WORKER], call_no=1, line_no=11, start=55.0)
    said = Fact(deal_id=deal, text="Says 25,000.", item=ItemKey.AMOUNT, kind=FactKind.TERM, value="25,000 rupees",
                value_rupees=25000, said_by=Role.WORKER, call_no=2, line_no=3, start=9.0)
    new = Fact(deal_id=deal, text="The amount is 24,000.", item=ItemKey.AMOUNT, kind=FactKind.TERM, value="24,000 rupees",
               value_rupees=24000, status=FactStatus.CONFIRMED, said_by=Role.HIRER, confirmed_by=[Role.HIRER, Role.WORKER],
               call_no=2, source=FactSource.CALL, replaces=amount.id)
    events = [
        CallStarted(deal_id=deal, people=[], room=f"deal-{deal}-1", call_no=1),
        FactRecorded(deal_id=deal, fact=amount),
        CallStarted(deal_id=deal, people=[], room=f"deal-{deal}-2", call_no=2),
        FactRecorded(deal_id=deal, fact=said),
        FactConflict(deal_id=deal, fact_ids=[amount.id], explanation="Says 25,000; both confirmed 22,000.", said="25 hazaar",
                     speaker=Role.WORKER, call_no=2, line_no=3),
        FactRecorded(deal_id=deal, fact=new),
        FactRecorded(deal_id=deal, fact=amount.model_copy(update={"status": FactStatus.SUPERSEDED})),
    ]
    data = tmp_path / "events.json"
    data.write_text(json.dumps([e.model_dump(mode="json") for e in events]))
    script = tmp_path / "card.mjs"
    script.write_text(CARD % tuple((STATIC / name).as_uri() for name in ("state.js", "graph-layout.js")))
    run = subprocess.run(["node", script, data], capture_output=True, text=True, timeout=30)
    assert run.returncode == 0, run.stderr
    assert json.loads(run.stdout) == [None, None, None, None, "amount", None, None]
