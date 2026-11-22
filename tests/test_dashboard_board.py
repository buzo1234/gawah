"""The board's view (lanes.js, moments.js and board.js in app/dashboard/static, run in Node)
on what the real memory sends for call_two_amounts, then an advance and a payment on
WhatsApp: every fact is in the timeline, newest first, a payment under the term it counts
towards; the open contradiction is the amount, with the agreed 13,000 and the 14,000 Ramesh
said as the claim; in the amount's lane the claim is its own chip with a red edge back to
the version the term stands on, and what both said with one value is one chip carrying
both; each fact knows how long after its line it came; long text is cut at a word in at
most two lines; and the same state always gives the same view. Skipped where Node is not
installed."""

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
VIEW = """
import { readFileSync } from "node:fs";
import { apply, emptyState } from "%s";
import { standing } from "%s";
import { cut, fit, openConflict } from "%s";
import { graph } from "%s";
import { moments } from "%s";
const events = JSON.parse(readFileSync(process.argv[2], "utf8"));
const state = emptyState(process.argv[3]);
for (const e of events) apply(state, e);
const at = (state) => ({ graph: graph(state), moments: moments(state), open: openConflict(state) });
const view = at(state);
const amount = view.graph.find((r) => r.key === "amount");
console.log(JSON.stringify({
  again: JSON.stringify(at(state)) === JSON.stringify(view),
  open: view.open && { item: view.open.item, agreed: view.open.agreed.id, claim: view.open.claim && { id: view.open.claim.id, line_no: view.open.claim.line_no, said_by: view.open.claim.said_by, value: view.open.claim.value } },
  lane: amount.chips.map((c) => ({ key: c.key, ids: c.ids, status: c.status, people: c.people, stands: c.stands, value: c.value })),
  edges: amount.edges,
  moments: view.moments.map((m) => ({ fact: m.factId, item: m.item, latency: m.latency, moment: m.moment, people: m.people.map((p) => p.role) })),
  facts: state.factOrder, standing: standing(state, "amount")?.id,
  towards: Object.fromEntries(state.factOrder.map((id) => [id, state.facts[state.facts[id].counts_towards]?.item ?? null])),
  cuts: ["paint the flat; Sunita says the job also includes the doors and the balcony railing", "a", "supercalifragilistic"].map((t) => cut(t, 130)),
  fits: [fit("paint the flat; Sunita says the job also includes the doors and the balcony railing", 130, 2), fit("Ramesh says ₹\\u202f22,000 is final", 160, 2), fit("Ramesh says ₹\\u202f22,000 is final, no more", 100, 2)],
}));
"""


def run_view(events, deal: str, tmp_path: Path) -> dict:
    data = tmp_path / "events.json"
    data.write_text(json.dumps([e.model_dump(mode="json") for e in events]))
    script = tmp_path / "view.mjs"
    script.write_text(VIEW % tuple((STATIC / name).as_uri() for name in ("state.js", "crew-state.js", "board.js", "lanes.js", "moments.js")))
    run = subprocess.run(["node", script, data, deal], capture_output=True, text=True, timeout=30)
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)


@pytest.mark.skipif(not shutil.which("node"), reason="needs Node to run the page's own view")
async def test_the_graph_holds_the_contradiction_and_the_timeline_holds_every_fact(bus, tmp_path):
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
    bus.publish(RecordReceived(deal_id=deal, record=Record(sender=Role.HIRER, kind=RecordKind.ADVANCE, amount=3000, text="3000 advance diya")))
    bus.publish(RecordReceived(deal_id=deal, record=Record(sender=Role.HIRER, kind=RecordKind.PAYMENT, amount=5000, text="5000 aur diye")))
    for _ in range(3):
        await bus.drain()
        await memory.settle()

    got = run_view(seen, deal, tmp_path)
    assert got["again"]  # the same state, the same view: nothing jitters on a redraw

    # Every fact memory wrote is in the timeline, newest first; a payment under the term it counts towards.
    shown = [m["fact"] for m in got["moments"]]
    assert set(shown) == set(got["facts"])
    first_seen = list(dict.fromkeys(reversed(shown)))
    assert first_seen == got["facts"]
    for m in got["moments"]:
        if got["towards"][m["fact"]]:
            assert m["item"] == got["towards"][m["fact"]]
    assert {m["moment"] for m in got["moments"]} <= {"Call 1", "WhatsApp · day 1"}
    # Each fact from a line knows how long after the line it came, by the events' own times.
    timed = [m["latency"] for m in got["moments"] if m["latency"] is not None]
    assert timed and all(0 <= t < 60 for t in timed)

    # The contradiction on line 19 is still open after the call: the agreed 13,000, and Ramesh's 14,000 as the claim.
    assert got["open"]["item"] == "amount" and got["open"]["agreed"] == got["standing"]
    claim = got["open"]["claim"]
    assert claim["line_no"] == 19 and claim["said_by"] == "worker" and claim["value"] == "14,000 rupees"

    # The amount's lane: the claim its own red chip, with the edge back to the chip the term stands on,
    # which both people's agreement made one chip carrying both.
    lane = {c["key"]: c for c in got["lane"]}
    stands = next(c for c in got["lane"] if got["standing"] in c["ids"])
    assert stands["stands"] and stands["status"] == "agreed" and set(stands["people"]) == {"hirer", "worker"}
    claimed = next(c for c in got["lane"] if claim["id"] in c["ids"])
    assert claimed["status"] == "claim" and claimed["ids"] == [claim["id"]]
    assert got["edges"] == [{"id": got["edges"][0]["id"], "from": claimed["key"], "to": stands["key"]}]
    assert all(lane[k]["value"] for k in lane) and len({c["value"] for c in got["lane"] if c["status"] != "claim"}) == len([c for c in got["lane"] if c["status"] != "claim"])

    # Long text is cut at a word, never inside one; a first word too long is cut where it must be;
    # in two lines a figure with its rupee sign stays whole.
    assert got["cuts"][0] == "paint the flat…" and got["cuts"][1] == "a" and got["cuts"][2].endswith("…")
    assert got["fits"][0].endswith("…") and got["fits"][0].removesuffix("…") in "paint the flat; Sunita says the job also"
    assert got["fits"][1] == "Ramesh says ₹\u202f22,000 is final" and "₹\u202f22,000" in got["fits"][2]


CARD = """
import { readFileSync } from "node:fs";
import { apply, emptyState } from "%s";
import { openConflict } from "%s";
const events = JSON.parse(readFileSync(process.argv[2], "utf8"));
const state = emptyState("d-card");
const open = [];
for (const e of events) { apply(state, e); open.push(openConflict(state)?.item ?? null); }
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
    script.write_text(CARD % tuple((STATIC / name).as_uri() for name in ("state.js", "board.js")))
    run = subprocess.run(["node", script, data], capture_output=True, text=True, timeout=30)
    assert run.returncode == 0, run.stderr
    assert json.loads(run.stdout) == [None, None, None, None, "amount", None, None]
