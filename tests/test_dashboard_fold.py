"""The dashboard's fold (app/dashboard/static/state.js) run in Node on the sample events and
a second call: what a reload rebuilds the page from. Skipped where Node is not installed."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from app.contracts import (
    AgentNote, CallEnded, CallStarted, ChangeStatus, ChecklistUpdated, CrewAgent, FactChanged, FactRecorded,
    FactStatus, ItemKey, Role, TranscriptLine, empty_checklist,
)
from fakes import RAMESH, SUNITA
from fakes.samples import sample_events

STATIC = Path(__file__).parent.parent / "app" / "dashboard" / "static"
FOLD = """
import { readFileSync } from "node:fs";
import { apply, emptyState, lineAt } from "%s";
const events = JSON.parse(readFileSync(process.argv[2], "utf8"));
const state = emptyState(events[0].deal_id);
for (const e of events) apply(state, e);
console.log(JSON.stringify({
  calls: state.calls, status: state.status, view: state.view,
  line14call1: lineAt(state, 14, 1)?.text, line14call2: lineAt(state, 14, 2)?.text,
  marks: state.flow.filter((f) => f.type === "call" || f.type === "mark").map((f) => f.type === "call" ? `call ${f.callNo}` : f.text),
  facts: state.factOrder.map((id) => state.facts[id].status),
  conflicts: state.conflicts.map((c) => [c.factIds, c.callNo, c.lineNo]),
  changes: state.changeOrder.map((id) => [state.changes[id].status, state.changes[id].confirmed_by]),
  chain: { links: state.chain.links, latest: state.chain.latest, problem: state.chain.problem },
  notes: state.notes.memory.map((n) => n.text),
  earlier: Object.keys(state.earlier), items: state.items.map((i) => i.state),
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

    assert got["calls"] == {"1": {"ended": True, "duration": 155.4}, "2": {"ended": True, "duration": 41.0}}
    assert got["marks"] == ["call 1", "Call 1 ended after 2:35", "call 2", "Call 2 ended after 0:41"]
    assert got["line14call1"] == "Theek hai ji, 24 hazaar final."  # not overwritten by call 2's line 14
    assert got["line14call2"] == "Doosri call ki line 14"
    assert got["status"] == "contract_ready"  # the contract from call 1 still stands after call 2
    assert got["facts"] == ["superseded"]  # one fact, its latest version
    assert got["conflicts"] == [[[advance.id], 2, 7]]
    assert got["changes"] == [["confirmed_one", ["worker"]], ["confirmed_both", ["worker", "hirer"]]]
    assert got["chain"] == {"links": 2, "latest": "ab" * 32, "problem": None}
    assert got["notes"] == ["advance: 9,000 replaces 8,000", "found 1 fact about the advance"]
    assert got["earlier"] == ["amount"] and got["items"] == ["pending"] * 6  # kept in view, not hidden
    assert got["view"] == "graph"


@pytest.mark.skipif(not shutil.which("node"), reason="needs Node to run the page's own fold")
def test_a_link_without_a_fingerprint_breaks_the_chain(tmp_path):
    fact = next(e for e in sample_events("d-chain") if isinstance(e, FactRecorded)).fact
    events = [
        FactRecorded(deal_id="d-chain", fact=fact),
        FactRecorded(deal_id="d-chain", fact=fact.model_copy(update={"status": FactStatus.CONFIRMED, "hash": None})),
        FactRecorded(deal_id="d-chain", fact=fact.model_copy(update={"status": FactStatus.DISPUTED})),
    ]
    assert fold(events, tmp_path)["chain"]["problem"] == "link 2 has no fingerprint"
    events[1] = FactRecorded(deal_id="d-chain", fact=fact.model_copy(update={"status": FactStatus.CONFIRMED}))
    assert fold(events, tmp_path)["chain"]["problem"] == "link 2 repeats an earlier fingerprint"
