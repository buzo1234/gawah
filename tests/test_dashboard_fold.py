"""The dashboard's fold (app/dashboard/static/state.js) run in Node on the sample events and
a second call: what a reload rebuilds the page from. Skipped where Node is not installed."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from app.contracts import (
    AgentNote, CallEnded, CallKind, CallStarted, ChangeStatus, ChecklistItem, ChecklistUpdated, CrewAgent, Fact, FactChanged,
    FactConflict, FactKind, FactRecorded, FactStatus, ItemKey, ItemState, Role, TermsConfirmed, TermsDisputed, TranscriptLine,
    empty_checklist,
)
from fakes import RAMESH, SUNITA
from fakes.samples import sample_events

STATIC = Path(__file__).parent.parent / "app" / "dashboard" / "static"
FOLD = """
import { readFileSync } from "node:fs";
import { ITEMS, apply, emptyState, lineAt, termView } from "%s";
const events = JSON.parse(readFileSync(process.argv[2], "utf8"));
const state = emptyState(events[0].deal_id);
const moved = [];
for (const e of events) moved.push(...apply(state, e).moved);
console.log(JSON.stringify({
  calls: state.calls, line14call1: lineAt(state, 14, 1)?.text, line14call2: lineAt(state, 14, 2)?.text,
  facts: state.factOrder.map((id) => state.facts[id].status),
  conflicts: state.conflicts.map((c) => [c.factIds, c.callNo, c.lineNo]),
  changes: state.changeOrder.map((id) => [state.changes[id].status, state.changes[id].confirmed_by]),
  chain: state.chain.links, sealed: state.chain.list.map((l) => l.where),
  earlier: Object.keys(state.earlier), items: state.items.map((i) => i.state),
  terms: Object.fromEntries(ITEMS.map(([key]) => [key, termView(state, key)])), moved,
}));
"""


def fold(events, tmp_path: Path) -> dict:
    data = tmp_path / "events.json"
    data.write_text(json.dumps([e.model_dump(mode="json") for e in events]))
    script = tmp_path / "fold.mjs"
    script.write_text(FOLD % (STATIC / "state.js").as_uri())
    run = subprocess.run(["node", script, data], capture_output=True, text=True, timeout=30)
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)


@pytest.mark.skipif(not shutil.which("node"), reason="needs Node to run the page's own fold")
def test_the_fold_keeps_calls_apart_and_follows_the_crew(tmp_path):
    deal = "d-fold"
    events = sample_events(deal)
    advance = next(e for e in events if isinstance(e, FactRecorded)).fact
    pending = empty_checklist()
    call2 = [
        CallStarted(deal_id=deal, people=[SUNITA, RAMESH], room=f"deal-{deal}-2", call_no=2),
        ChecklistUpdated(deal_id=deal, items=pending),  # the brain starts each call afresh
        TranscriptLine(deal_id=deal, speaker=Role.HIRER, text="Doosri call ki line 14", start=30.0, end=33.0, line_no=14, call_no=2),
        FactChanged(deal_id=deal, change_id="c1", fact_id=advance.id, new_value="9,000 rupees", status=ChangeStatus.CONFIRMED_BOTH, item=ItemKey.ADVANCE, confirmed_by=[Role.WORKER, Role.HIRER]),
        FactRecorded(deal_id=deal, fact=advance.model_copy(update={"status": FactStatus.SUPERSEDED, "hash": "ab" * 32})),
        AgentNote(deal_id=deal, agent=CrewAgent.MEMORY, text="advance: 9,000 replaces 8,000"),
        CallEnded(deal_id=deal, people=[SUNITA, RAMESH], room=f"deal-{deal}-2", duration=41.0, call_no=2),
    ]
    got = fold([*events, *call2], tmp_path)

    assert got["calls"] == [1, 2]
    assert got["line14call1"] == "Theek hai ji, 24 hazaar final."  # not overwritten by call 2's line 14
    assert got["line14call2"] == "Doosri call ki line 14"
    assert got["facts"] == ["superseded"]  # one fact, its latest version
    assert got["conflicts"] == [[[advance.id], 2, 7]]
    assert got["changes"] == [["confirmed_one", ["worker"]], ["confirmed_both", ["worker", "hirer"]]]
    assert got["chain"] == 2  # links; memory checks them (/memory/chain), not the page
    assert got["sealed"] == ["Call 1", "Call 2"]  # the advance said on call 1 was replaced on call 2
    assert got["earlier"] == ["amount"] and got["items"] == ["pending"] * 6  # kept in view, not hidden
    terms = got["terms"]
    # Agreed on call 1 at line 14 (0:41), kept through call 2's fresh checklist; one of
    # the two has confirmed it on a call-back.
    assert terms["amount"] == {
        "state": "agreed", "value": "24,000 rupees, labour and material", "when": "Call 1 · 0:41",
        "note": "Ramesh confirmed", "contradicted": None,
    }
    assert terms["advance"]["state"] == "changed" and terms["advance"]["value"] == "9,000 rupees"
    assert terms["dates"]["state"] == "disputed" and terms["dates"]["note"] == "Ramesh disputes this: “nahi, Saturday tak bola tha”"
    assert terms["balance"] == {"state": "pending", "value": None, "when": "", "note": None, "contradicted": None}
    assert set(got["moved"]) >= {"amount", "advance", "dates"}


@pytest.mark.skipif(not shutil.which("node"), reason="needs Node to run the page's own fold")
def test_the_term_stands_on_the_newest_version_as_in_memory(tmp_path):
    """Memory's current(): of the agreed facts, the one with the newest version, even if it
    was first said before the others (a said date agreed only at the end of the call)."""
    monday = Fact(deal_id="d-st", text="Starts Monday.", item=ItemKey.DATES, kind=FactKind.TERM, value="Monday", status=FactStatus.SAID)
    friday = Fact(deal_id="d-st", text="Ends Friday.", item=ItemKey.DATES, kind=FactKind.TERM, value="Friday", status=FactStatus.AGREED)
    note = Fact(deal_id="d-st", text="Asks about dates.", item=ItemKey.DATES, kind=FactKind.OTHER, status=FactStatus.AGREED)
    events = [FactRecorded(deal_id="d-st", fact=f) for f in (monday, friday, monday.model_copy(update={"status": FactStatus.AGREED}), note)]
    script = tmp_path / "standing.mjs"
    script.write_text(STANDING % ((STATIC / "state.js").as_uri(), (STATIC / "crew-state.js").as_uri()))
    data = tmp_path / "events.json"
    data.write_text(json.dumps([e.model_dump(mode="json") for e in events]))
    run = subprocess.run(["node", script, data], capture_output=True, text=True, timeout=30)
    assert run.returncode == 0, run.stderr
    assert run.stdout.strip() == monday.id


@pytest.mark.skipif(not shutil.which("node"), reason="needs Node to run the page's own fold")
def test_each_checklist_state_reads_as_the_room_should_see_it(tmp_path):
    """Pending, agreed with where it was said, contradicted on this call, confirmed by
    both, changed by both (the new value, and what it was), and a dispute over all."""
    deal = "d-cl"
    amount = Fact(deal_id=deal, text="The amount is 13,000.", item=ItemKey.AMOUNT, kind=FactKind.TERM, value="13,000 rupees",
                  value_rupees=13000, status=FactStatus.AGREED, call_no=1, line_no=11, start=55.0)
    items = empty_checklist()
    items[1] = ChecklistItem(key=ItemKey.AMOUNT, state=ItemState.AGREED, value="13,000 rupees", line_no=11)
    items[2] = ChecklistItem(key=ItemKey.ADVANCE, state=ItemState.AGREED, value="3,000 rupees", line_no=15)
    items[4] = ChecklistItem(key=ItemKey.DATES, state=ItemState.AGREED, value="Monday to Friday", line_no=20)
    lines = [TranscriptLine(deal_id=deal, speaker=Role.HIRER, text=f"line {n}", start=s, end=s + 2, line_no=n, call_no=1)
             for n, s in ((11, 55.0), (15, 66.0), (19, 82.0), (20, 90.0))]
    mid = [
        CallStarted(deal_id=deal, people=[], room=f"deal-{deal}-1", call_no=1), *lines,
        FactRecorded(deal_id=deal, fact=amount),
        ChecklistUpdated(deal_id=deal, items=items, changed=[ItemKey.AMOUNT, ItemKey.ADVANCE, ItemKey.DATES]),
        FactConflict(deal_id=deal, fact_ids=[amount.id], explanation="Says 14,000.", speaker=Role.WORKER, call_no=1, line_no=19),
    ]
    got = fold(mid, tmp_path)["terms"]
    assert got["work"]["state"] == "pending" and got["work"]["value"] is None
    assert got["advance"] == {"state": "agreed", "value": "3,000 rupees", "when": "Call 1 · 1:06", "note": None, "contradicted": None}
    assert got["amount"]["state"] == "agreed" and got["amount"]["contradicted"] == "Call 1 · 1:22"

    after = [
        *mid,
        CallEnded(deal_id=deal, people=[], room=f"deal-{deal}-1", call_no=1),
        CallStarted(deal_id=deal, people=[], room=f"callback-{deal}-worker", kind=CallKind.CALLBACK),
        TermsConfirmed(deal_id=deal, person=Role.WORKER),
        TermsConfirmed(deal_id=deal, person=Role.HIRER, item=ItemKey.ADVANCE),
        TermsDisputed(deal_id=deal, person=Role.HIRER, item=ItemKey.DATES, said="Saturday tak"),
        FactChanged(deal_id=deal, fact_id=amount.id, new_value="26,000 rupees", item=ItemKey.AMOUNT, status=ChangeStatus.CONFIRMED_BOTH,
                    confirmed_by=[Role.WORKER, Role.HIRER]),
    ]
    got = fold(after, tmp_path)["terms"]
    assert got["advance"]["state"] == "confirmed" and got["advance"]["when"] == "Call 1 · 1:06"
    assert got["amount"] == {"state": "changed", "value": "26,000 rupees", "when": "Call 1", "note": "Was 13,000 rupees", "contradicted": None}
    assert got["dates"]["state"] == "disputed" and got["dates"]["note"] == "Hirer disputes this: “Saturday tak”"
    assert got["balance"]["state"] == "pending"


STANDING = """
import { readFileSync } from "node:fs";
import { apply, emptyState } from "%s";
import { standing } from "%s";
const state = emptyState("d-st");
for (const e of JSON.parse(readFileSync(process.argv[2], "utf8"))) apply(state, e);
console.log(standing(state, "dates").id);
"""


LABELS = """
import { phoneLabel } from "%s";
const ramesh = { role: "worker", name: "Ramesh", phone: "+91 00000 00002" };
const people = { hirer: { name: "Sunita", phone: "+910000000001" }, worker: ramesh };
console.log(JSON.stringify([
  phoneLabel(people, "+910000000002", "d1"),
  phoneLabel(people, "+910000000001", "d1"),
  phoneLabel({ hirer: { name: "Paras", phone: "+910000000001" } }, "+910000000001", "d1"),
  phoneLabel({ worker: { phone: "+910000000002" } }, "+910000000002", "d1"),
  phoneLabel({ hirer: { name: null, phone: "+910000000001" } }, "+910000000001", "d1"),
  phoneLabel(people, "+919999999999", "d1"),
  phoneLabel(people, "+910000000002", null),
  phoneLabel({}, "+910000000002", "no-deal"),
  phoneLabel(people, null, "d1"),
]));
"""


@pytest.mark.skipif(not shutil.which("node"), reason="needs Node to run the page's own rule")
def test_the_second_phone_is_named_for_whose_phone_it_is(tmp_path):
    script = tmp_path / "labels.mjs"
    script.write_text(LABELS % (STATIC / "state.js").as_uri())
    run = subprocess.run(["node", script], capture_output=True, text=True, timeout=30)
    assert run.returncode == 0, run.stderr
    assert json.loads(run.stdout) == [
        "Ramesh's phone",  # the number matched in any spacing
        "Sunita's phone",
        "Paras's phone",  # a name ending in s still takes 's
        "The worker's phone",  # no name known yet: the role
        "The hirer's phone",
        "Second phone",  # a number no one on the deal has
        "Second phone",  # no deal
        "Second phone",
        "Second phone",
    ]
