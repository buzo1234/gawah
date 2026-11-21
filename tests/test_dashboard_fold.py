"""The dashboard's fold (app/dashboard/static/state.js) run in Node on the sample events and
a second call: what a reload rebuilds the page from. Skipped where Node is not installed."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from app.contracts import (
    AgentNote, Audience, CallEnded, CallStarted, ChangeStatus, ChecklistUpdated, CrewAgent, Fact, FactChanged, FactKind, FactRecorded,
    FactStatus, ItemKey, JudgeSpeak, Role, SpeakReason, TranscriptLine, empty_checklist,
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
  question: state.decisions.map((d) => d.question),
  changes: state.changeOrder.map((id) => [state.changes[id].status, state.changes[id].confirmed_by]),
  chain: state.chain.links,
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
    assert got["chain"] == 2  # links; memory checks them (/memory/chain), not the page
    assert got["notes"] == ["advance: 9,000 replaces 8,000", "found 1 fact about the advance"]
    assert got["earlier"] == ["amount"] and got["items"] == ["pending"] * 6  # kept in view, not hidden
    assert got["view"] == "graph"


@pytest.mark.skipif(not shutil.which("node"), reason="needs Node to run the page's own fold")
def test_a_question_put_to_gawah_is_kept_with_its_decision(tmp_path):
    asked = JudgeSpeak(
        deal_id="d-ask", instruction="Read back the advance.", to=Audience.HIRER, reason=SpeakReason.ADDRESSED_DIRECTLY,
        item=ItemKey.ADVANCE, question="Gawah, advance kitna tay hua?",
    )
    plain = JudgeSpeak(deal_id="d-ask", instruction="Ask when the balance is paid.", to=Audience.HIRER, reason=SpeakReason.TERM_UNCLEAR)
    assert fold([asked, plain], tmp_path)["question"] == ["Gawah, advance kitna tay hua?", None]


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


STANDING = """
import { readFileSync } from "node:fs";
import { apply, emptyState } from "%s";
import { standing } from "%s";
const state = emptyState("d-st");
for (const e of JSON.parse(readFileSync(process.argv[2], "utf8"))) apply(state, e);
console.log(standing(state, "dates").id);
"""
