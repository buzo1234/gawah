"""The board's view (app/dashboard/static/board.js, run in Node) on what the real memory
sends for call_two_amounts, then an advance and a payment on WhatsApp: every fact is in
the feed once, newest first; while the contradiction is open the fact layer shows the
amount, with the agreed 13,000 on its card, the 14,000 Ramesh said as the claim, and the
version before it dashed; the chain row is those versions; each fact knows how long after
its line it came; long values are cut at a word; and the same state always gives the same
view. Skipped where Node is not installed."""

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
import { apply, emptyState, ITEMS } from "%s";
import { standing } from "%s";
import { cut, factLayer, feed, focusItem, openConflict, tracks } from "%s";
const events = JSON.parse(readFileSync(process.argv[2], "utf8"));
const fold = (upTo) => {
  const state = emptyState(process.argv[3]);
  for (const e of events.slice(0, upTo)) apply(state, e);
  return state;
};
const at = (state) => {
  const focus = focusItem(state);
  return { focus, layer: factLayer(state, focus), open: openConflict(state), feed: feed(state), tracks: tracks(state) };
};
const state = fold(events.length);
const view = at(state);
const short = (f) => f && { id: f.id, value: f.value, status: f.status, said_by: f.said_by, line_no: f.line_no };
console.log(JSON.stringify({
  focus: view.focus, again: JSON.stringify(at(state)) === JSON.stringify(view),
  current: short(view.layer.current), version: view.layer.version, pill: view.layer.pill,
  previous: view.layer.previous && { ...short(view.layer.previous.fact), version: view.layer.previous.version },
  claim: view.layer.claim && { fact: short(view.layer.claim.fact), who: view.layer.claim.who },
  chain: view.layer.chain.map((l) => [l.label, l.fact.id]), latency: view.layer.latency,
  open: view.open && { item: view.open.item, agreed: view.open.agreed.id, claim: view.open.claim?.id },
  feed: view.feed.map((r) => ({ id: r.fact.id, latency: r.latency, item: r.item })),
  tracks: { lines: view.tracks.lines.length, end: view.tracks.end, callNo: view.tracks.callNo },
  facts: state.factOrder, standing: standing(state, "amount")?.id,
  towards: Object.fromEntries(state.factOrder.map((id) => [id, state.facts[state.facts[id].counts_towards]?.item ?? null])),
  cuts: ["paint the flat; Sunita says the job also includes the doors and the balcony railing", "a", "supercalifragilistic"].map((t) => cut(t, 130)),
}));
"""


def run_view(events, deal: str, tmp_path: Path) -> dict:
    data = tmp_path / "events.json"
    data.write_text(json.dumps([e.model_dump(mode="json") for e in events]))
    script = tmp_path / "view.mjs"
    script.write_text(VIEW % tuple((STATIC / name).as_uri() for name in ("state.js", "crew-state.js", "board.js")))
    run = subprocess.run(["node", script, data, deal], capture_output=True, text=True, timeout=30)
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)


@pytest.mark.skipif(not shutil.which("node"), reason="needs Node to run the page's own view")
async def test_the_fact_layer_holds_the_contradiction_and_the_feed_holds_every_fact(bus, tmp_path):
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

    # Every fact once in the feed, newest first; a payment listed under the term it counts towards.
    ids = [r["id"] for r in got["feed"]]
    assert sorted(ids) == sorted(got["facts"]) and ids == list(reversed(got["facts"]))
    for r in got["feed"]:
        if got["towards"][r["id"]]:
            assert r["item"] == got["towards"][r["id"]]
    # Each fact from a line knows how long after the line it came, by the events' own times.
    timed = [r["latency"] for r in got["feed"] if r["latency"] is not None]
    assert timed and all(0 <= t < 60 for t in timed)

    # The contradiction on line 19 is still open after the call, and the fact layer stays on
    # it: the agreed 13,000 on the card, Ramesh's 14,000 as the claim, the offer before dashed.
    assert got["focus"] == "amount"
    assert got["current"]["id"] == got["standing"] and got["current"]["value"] == "13,000 rupees" and got["pill"] == "Agreed"
    assert got["claim"]["fact"]["line_no"] == 19 and got["claim"]["fact"]["said_by"] == "worker" and got["claim"]["who"] == "Ramesh"
    assert got["open"] == {"item": "amount", "agreed": got["standing"], "claim": got["claim"]["fact"]["id"]}
    assert got["previous"] and got["previous"]["version"] < got["version"]
    assert got["chain"] == [[f"v{got['previous']['version']}", got["previous"]["id"]], [f"v{got['version']}", got["current"]["id"]], ["Claim", got["claim"]["fact"]["id"]]]

    # The tracks: every line of the call, on a scale that reaches the last one.
    lines = json.loads(Path("fixtures/call_two_amounts.json").read_text())["lines"]
    assert got["tracks"]["callNo"] == 1 and got["tracks"]["lines"] == len(lines) and got["tracks"]["end"] >= lines[-1]["end"]

    # Long values are cut at a word, never inside one; a first word too long is cut where it must be.
    assert got["cuts"][0] == "paint the flat…" and got["cuts"][1] == "a" and got["cuts"][2].endswith("…")


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
