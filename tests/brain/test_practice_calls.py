"""The brain on the practice calls, the dry run's call and the demo's script, on answers
recorded from the real Sage2 and the real OpenAI model (tests/brain/recorded/). No outside calls."""

from pathlib import Path

import pytest

from app.brain import tuning
from app.bus import Bus
from app.contracts import ChecklistUpdated, ItemKey, ItemState, JudgeSpeak
from tests.brain.replaying import run_call

CALLS = sorted(Path("fixtures").glob("call_*.json")) + [Path("tests/brain/dry_run_call.json"), Path("tests/brain/demo_script_call.json")]
ALL = CALLS + [Path("tests/brain/spike_painter_call.json")]
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


async def test_spike_call_covers_a_dodged_question_and_speaking_to_gawah(bus):
    """Sage2's answers here are the spike's saved run of its 30-line call."""
    run = await run_call(bus, "tests/brain/spike_painter_call.json", "live")
    assert run.spoken == [
        (18, "term_unclear", "balance", "hirer"),  # asked at 17, brushed off at 18
        (23, "addressed_directly", None, "hirer"),  # "Gawah, aapne sab note kar liya na?"
        # 43 thousand is said at 24; the Judge is still waiting on its answer to line 23.
        (26, "conflicting_figures", "amount", "both"),
        (29, "wrapping_up", "late_or_unfinished", "both"),  # never discussed, and not yet asked
    ]
    assert 'said: "Gawah, aapne sab note kar liya na?"' in run.speaks[1].instruction
    assert run.final["amount"].note == "two figures said: 42,000 rupees and 43,000 rupees"
    assert run.values.missing == []


async def test_spike_call_in_wrapup_mode_only_speaks_at_the_end(bus):
    run = await run_call(bus, "tests/brain/spike_painter_call.json", "wrapup")
    assert run.spoken == [(27, "wrapping_up", "amount", "both")]


# The first line on which wrap-up may fire without being mid-call (the first closing words:
# a meeting time, thanks or goodbye), and the last line it may fire on: two lines before
# the end, or the last line where that is the only closing line and a silence follows.
WRAP = {
    "call_missing_balance": (29, 30),  # "Chalo theek hai phir. Monday subah 9 baje aa jana" ... 32 lines
    "call_two_amounts": (30, 31),  # "Chalo theek hai. To Wednesday subah aa jao, 10 baje." ... 33
    "spike_painter_call": (27, 28),  # "Chalo theek hai phir, kal advance bhej deti hoon. Ab rakhti hoon." ... 30
    "dry_run_call": (24, 24),  # its one closing line is its last, then 25 seconds of silence
    "demo_script_call": (12, 13),  # "चलो ठीक है फिर। सब तय हो गया।" ... then the late-work question
}


async def fresh_run(path, mode: str, drop: set[int] = frozenset()):
    """A run on its own bus: a brain stays subscribed to the bus it was made on."""
    bus = Bus()
    bus.start()
    try:
        return await run_call(bus, path, mode, drop)
    finally:
        await bus.stop()


@pytest.mark.parametrize("path", ALL, ids=lambda p: p.stem)
async def test_wrap_up_comes_at_the_closing_words_never_before(path):
    # In wrapup mode the Judge's first word is the moment it saw wrap-up (every call has something pending).
    run = await fresh_run(path, "wrapup")
    first, last = WRAP[run.fixture["id"]]
    assert run.speaks and run.speaks[0].reason == "wrapping_up"
    assert first <= run.speaks[0].after_line <= last, run.spoken
    live = await fresh_run(path, "live")
    assert all(s.after_line >= first for s in live.speaks if s.reason == "wrapping_up"), live.spoken


@pytest.mark.parametrize(
    ("path", "first", "again"),
    [
        ("fixtures/call_missing_balance.json", (19, "term_unclear", "balance", "hirer"), 20),
        ("fixtures/call_two_amounts.json", (19, "conflicting_figures", "amount", "both"), 20),
        ("tests/brain/spike_painter_call.json", (18, "term_unclear", "balance", "hirer"), 19),
        ("tests/brain/demo_script_call.json", (8, "term_unclear", "balance", "hirer"), 9),
    ],
    ids=lambda v: Path(v).stem if isinstance(v, str) else None,
)
async def test_a_dropped_question_is_asked_again_and_wrap_up_still_asks(path, first, again):
    plain = await fresh_run(path, "live")
    dropped = await fresh_run(path, "live", drop={0})
    assert dropped.spoken[0] == first
    assert dropped.spoken[1] == (again, *first[1:]), "asked again on the next line"
    wrapups = {s.item for s in dropped.speaks if s.reason == "wrapping_up"}
    plain_wrapups = {s.item for s in plain.speaks if s.reason == "wrapping_up"}
    assert wrapups == plain_wrapups

    twice = await fresh_run(path, "live", drop={0, 1})
    mid_call = [s for s in twice.speaks if s.item == first[2] and s.reason != "wrapping_up"]
    assert len(mid_call) == 2, "asked again once, not on every line"
    assert {s.item for s in twice.speaks if s.reason == "wrapping_up"} == plain_wrapups


@pytest.mark.parametrize(
    ("path", "worker"), [("tests/brain/dry_run_call.json", "Ravesh"), ("tests/brain/demo_script_call.json", "Ramesh")]
)
async def test_a_name_said_on_the_call_is_learned_and_used(bus, path, worker):
    # Both deals were started on WhatsApp, which knows only the worker's phone.
    # On the dry run line 1 was heard as "रवेश जी": the name is as good as the transcription.
    run = await run_call(bus, path, "live")
    started, again = run.started
    assert [p.name for p in started.people] == ["Sunita", None]
    assert again.room == started.room and [(p.role, p.name, p.phone) for p in again.people] == [
        ("hirer", "Sunita", "+919000000001"), ("worker", worker, "+919000000002"),
    ]
    both = [s.instruction for s in run.speaks if s.to == "both"]
    assert both and all(f"Sunita and {worker}" in text for text in both)
    assert not any("Worker" in s.instruction for s in run.speaks)


@pytest.mark.parametrize("path", ALL[:2] + ALL[-1:], ids=lambda p: p.stem)
async def test_a_call_that_starts_with_both_names_never_looks_them_up(bus, path):
    run = await run_call(bus, path, "live")
    assert all(p.name for p in run.started[0].people) and len(run.started) == 1
