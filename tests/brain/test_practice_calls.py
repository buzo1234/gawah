"""The brain on both practice calls, on answers recorded from the real Sage2 and the
real OpenAI model (tests/brain/recordings/). No outside calls."""

from pathlib import Path

import pytest

from app.brain import tuning
from app.bus import Bus
from app.contracts import ChecklistUpdated, ItemKey, ItemState, JudgeSpeak
from tests.brain.replaying import run_call

CALLS = sorted(Path("fixtures").glob("call_*.json"))
MODES = ["live", "wrapup"]
both = pytest.mark.parametrize("path", CALLS, ids=lambda p: p.stem)
modes = pytest.mark.parametrize("mode", MODES)


@both
@modes
async def test_judge_speaks_when_expected_and_only_then(bus, path, mode):
    run = await run_call(bus, path, mode)
    expected = [e for e in run.fixture["expected"] if mode in e["modes"]]
    assert expected, "the fixture expects something in every mode"

    unmatched = list(run.speaks)
    for want in expected:
        hit = next(
            (
                s for s in unmatched
                if s.item == want["item"] and s.reason == want["reason"] and s.to == want["to"]
                and want["after_line"] <= s.after_line <= want["by_line"]
            ),
            None,
        )
        assert hit, f"{mode}: no judge.speak for {want}; got {run.spoken}"
        unmatched.remove(hit)
    assert not unmatched, f"{mode}: unexpected judge.speak {[(s.after_line, s.reason, s.item) for s in unmatched]}"
    assert run.values.missing == []


@both
@modes
async def test_judge_stays_polite(bus, path, mode):
    run = await run_call(bus, path, mode)
    items = {key: ItemState.PENDING for key in ItemKey}
    asked: dict[ItemKey, int] = {}
    last_speak_at = None
    for event in run.events:
        if isinstance(event, ChecklistUpdated):
            items = {item.key: item.state for item in event.items}
            continue
        assert event.instruction.strip()
        if event.item:
            assert items[event.item] is ItemState.PENDING, f"asked about an agreed item: {event.item}"
            asked[event.item] = asked.get(event.item, 0) + 1
        # Nothing answers judge.speak here, so the next one has to wait out the timeout.
        at = run.end_of_line[event.after_line]
        if last_speak_at is not None:
            assert at - last_speak_at >= tuning.SPEAK_TIMEOUT_S, "two questions at once"
        last_speak_at = at
    assert all(count <= tuning.MAX_ASKS_PER_ITEM for count in asked.values())


@both
async def test_checklist_always_carries_all_six_items(bus, path):
    run = await run_call(bus, path, "live")
    assert run.checklists
    for update in run.checklists:
        assert [item.key for item in update.items] == list(ItemKey)
        assert set(update.changed) <= set(ItemKey)


async def test_missing_balance_checklist(bus):
    run = await run_call(bus, "fixtures/call_missing_balance.json", "live")
    final = run.final
    assert final["balance"].state is ItemState.PENDING and final["balance"].value is None
    for key in ("work", "amount", "advance", "dates", "late_or_unfinished"):
        assert final[key].state is ItemState.AGREED and final[key].value and final[key].source_text and final[key].line_no
    assert "24,000 rupees" in final["amount"].value and final["amount"].line_no == 14
    assert "8,000 rupees" in final["advance"].value
    assert final["dates"].value == "Monday 23 November 2026 to Friday 27 November 2026"
    assert "500 rupees" in final["late_or_unfinished"].value
    assert run.speaks[0].instruction == "Ask Sunita when the balance will be paid."
    assert run.speaks[1].instruction == "They are about to hang up. Ask Sunita when the balance will be paid."


async def test_two_amounts_checklist_notes_both_figures(bus):
    run = await run_call(bus, "fixtures/call_two_amounts.json", "live")
    amount_by_update = [
        (item.state, item.value, item.note) for update in run.checklists for item in update.items
        if item.key is ItemKey.AMOUNT and ItemKey.AMOUNT in update.changed
    ]
    assert amount_by_update[0] == (ItemState.AGREED, None, None)
    assert amount_by_update[1][0] is ItemState.AGREED and "13,000 rupees" in amount_by_update[1][1]
    assert amount_by_update[2] == (ItemState.PENDING, None, "two figures said: 13,000 rupees and 14,000 rupees")
    assert len(amount_by_update) == 3, "nobody settled it, so it stays open"

    final = run.final
    for key in ("work", "advance", "balance", "dates", "late_or_unfinished"):
        assert final[key].state is ItemState.AGREED and final[key].value
    assert "300 rupees" in final["late_or_unfinished"].value, "the late term said after the item was first agreed"
    assert run.speaks[0].instruction == (
        "Two different figures were said for the total amount: 13,000 rupees and 14,000 rupees. "
        "Ask Sunita and Ramesh which one is right."
    )
    assert run.speaks[1].instruction.startswith("They are about to hang up. Two different figures were said")


@both
@modes
async def test_same_call_gives_the_same_events_every_time(path, mode):
    runs = []
    for _ in range(3):
        bus = Bus()
        bus.start()
        runs.append((await run_call(bus, path, mode)).comparable())
        await bus.stop()
    assert runs[0] == runs[1] == runs[2]
    assert any(e["name"] == JudgeSpeak.model_fields["name"].default for e in runs[0])
