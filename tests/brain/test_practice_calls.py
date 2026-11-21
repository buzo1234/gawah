"""The brain on the practice calls, the dry run's call and the demo's script, on answers
recorded from the real Sage2 and the real OpenAI model (tests/brain/recorded/), with the
memory's Scribe on its saved replies (tests/memory/recorded/). No outside calls."""

from pathlib import Path

import pytest

from app.brain import tuning
from app.bus import Bus
from app.contracts import ChecklistUpdated, ItemKey, ItemState, JudgeSpeak, SpeakReason
from tests.brain.replaying import run_call, run_followup

CALLS = sorted(Path("fixtures").glob("call_*.json")) + [Path("tests/brain/dry_run_call.json"), Path("tests/brain/demo_script_call.json")]
ALL = CALLS + [Path("tests/brain/spike_painter_call.json")]
MODES = ["live", "wrapup"]
modes = pytest.mark.parametrize("mode", MODES)

both = pytest.mark.parametrize("path", CALLS, ids=lambda p: p.stem)


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
        if not isinstance(event, JudgeSpeak):
            continue
        assert event.instruction.strip()
        about_the_record = event.reason in (SpeakReason.CONTRADICTS_RECORD, SpeakReason.AMBIGUOUS) or event.fact_ids
        if event.item and not about_the_record:
            assert items[event.item] is ItemState.PENDING, f"asked about an agreed item: {event.item}"
        if event.item:
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


async def test_missing_balance_checklist_comes_from_the_facts(bus):
    run = await run_call(bus, "fixtures/call_missing_balance.json", "live")
    final = run.final
    assert final["balance"].state is ItemState.PENDING and final["balance"].value is None
    for key in ("work", "amount", "advance", "dates", "late_or_unfinished"):
        assert final[key].state is ItemState.AGREED and final[key].value and final[key].source_text and final[key].line_no
    # The offers before it (28,000, 20,000, 25,000) never show: only what both accepted.
    assert [i.value for u in run.checklists for i in u.items if i.key is ItemKey.AMOUNT and i.value] == ["24,000 rupees"] * len(
        [u for u in run.checklists if any(i.key is ItemKey.AMOUNT and i.value for i in u.items)]
    )
    assert final["amount"].line_no == 13 and final["amount"].source_text == "24 final karo, aur kaam achha hona chahiye."
    assert final["advance"].value == "8,000 rupees"
    # The model now hears line 24 ("Pakka madam, Friday shaam tak") as the finish both agreed; the
    # Monday start (line 22) stays the worker's statement.
    assert "Friday evening" in final["dates"].value
    assert final["late_or_unfinished"].value.startswith("500 rupees") and "per day" in final["late_or_unfinished"].value
    assert "2BHK" in final["work"].value, "the work as described before the price was agreed"
    assert run.speaks[0].instruction == "Ask Sunita when the balance will be paid."
    assert run.speaks[1].instruction == "They are about to hang up. Ask Sunita when the balance will be paid."


async def test_two_amounts_the_14000_is_a_contradiction_of_the_13000_agreed(bus):
    run = await run_call(bus, "fixtures/call_two_amounts.json", "live")
    amounts = [
        (item.state, item.value) for update in run.checklists for item in update.items
        if item.key is ItemKey.AMOUNT and ItemKey.AMOUNT in update.changed
    ]
    assert amounts[0] == (ItemState.AGREED, "13,000 rupees"), "15,000, 14,000 and 12,000 were offers"
    assert all(a == (ItemState.AGREED, "13,000 rupees") for a in amounts), "a figure said later does not replace it"
    final = run.final
    assert final["amount"].note.startswith("contradicted at line 19: Says 14,000 rupees; the amount was agreed at 13,000")

    [conflict] = run.conflicts
    first, wrap = run.speaks
    assert (first.after_line, first.reason, first.item, first.to) == (19, "contradicts_record", "amount", "both")
    assert first.fact_ids == conflict.fact_ids
    assert 'Ramesh said: "Theek hai madam, kaam dekh ke hi dena. To total 14 hazaar' in first.instruction
    assert "Do not say which one is right." in first.instruction
    assert first.instruction.count("Says 14,000 rupees") == 1
    # Wrap-up: only the contradiction is still open. Both agreed everything else: the balance
    # ("Theek hai madam, kaam dekh ke hi dena", line 19) and the 300 a day ("Chalo theek hai.
    # To Wednesday...", line 30, a yes that opens a line and goes on).
    assert (wrap.after_line, wrap.reason, wrap.item, wrap.to) == (31, "wrapping_up", "amount", "both")
    assert wrap.instruction.startswith("They are about to hang up. Ramesh said:")
    assert "Says 14,000 rupees" in wrap.instruction and "(2)" not in wrap.instruction
    assert final["balance"].state is ItemState.AGREED and final["late_or_unfinished"].state is ItemState.AGREED
    assert "300 rupees per day" in final["late_or_unfinished"].value


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
        # "Total 43 hazaar hua na" at 24 is, to the memory, a change to the 42,000 agreed: one
        # person's word, and a bare "haan theek hai" does not agree it. A change being offered is
        # not raised mid-call; still unaccepted at the goodbye, it leads the one wrap-up turn.
        (27, "wrapping_up", "amount", "both"),
    ]
    assert 'said: "Gawah, aapne sab note kar liya na?"' in run.speaks[1].instruction
    assert run.speaks[1].question == "Gawah, aapne sab note kar liya na?"
    assert "the total amount: 42,000 rupees" in run.speaks[1].instruction
    assert "(1) Ramesh said" in run.speaks[2].instruction
    assert "agreed as 42,000 rupees (call 1, line 10); now said as 43,000 rupees" in run.speaks[2].instruction
    assert "whether they both agree to this change" in run.speaks[2].instruction
    assert run.final["amount"].value == "42,000 rupees"
    assert run.values.missing == []


async def test_spike_call_in_wrapup_mode_answers_gawah_and_otherwise_speaks_only_at_the_end(bus):
    run = await run_call(bus, "tests/brain/spike_painter_call.json", "wrapup")
    assert run.spoken == [(23, "addressed_directly", None, "hirer"), (27, "wrapping_up", "amount", "both")]
    assert "(1) Ramesh said" in run.speaks[1].instruction


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
    # In wrapup mode the Judge's first word, past answering a question, is the moment it saw wrap-up.
    run = await fresh_run(path, "wrapup")
    first, last = WRAP[run.fixture["id"]]
    wraps = [s for s in run.speaks if s.reason != "addressed_directly"]  # wrapup mode answers questions too
    assert wraps and wraps[0].reason == "wrapping_up"
    assert first <= wraps[0].after_line <= last, run.spoken
    live = await fresh_run(path, "live")
    assert all(s.after_line >= first for s in live.speaks if s.reason == "wrapping_up"), live.spoken


@pytest.mark.parametrize(
    ("path", "first", "again"),
    [
        ("fixtures/call_missing_balance.json", (19, "term_unclear", "balance", "hirer"), 20),
        ("fixtures/call_two_amounts.json", (19, "contradicts_record", "amount", "both"), 20),
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


async def test_a_second_call_replayed_keeps_the_checklist_and_catches_the_contradiction(bus):
    """call_two_amounts, then tests/brain/second_call.json as call 2 of the same deal, with the
    memory's Scribe on its saved replies: Ramesh says 14,000 again on call 2."""
    first, second = await run_followup(bus, "tests/brain/second_call.json")
    end_of_one = {i.key: (i.state, i.value) for i in first.checklists[-1].items}
    assert {i.key: (i.state, i.value) for i in second.checklists[0].items} == end_of_one, "not restarted"
    agreed = {k for k, (state, _) in end_of_one.items() if state is ItemState.AGREED}
    assert agreed == set(ItemKey)

    [conflict] = second.conflicts
    contradiction, wrap = second.speaks
    assert (contradiction.after_line, contradiction.reason, contradiction.item, contradiction.to) == (
        3, "contradicts_record", "amount", "both",
    )
    assert contradiction.fact_ids == conflict.fact_ids
    assert 'Ramesh said: "Achha madam, ek baat. Labour ka total 14 hazaar tay hua tha na?"' in contradiction.instruction
    assert "the amount was agreed at 13,000 rupees by both" in contradiction.instruction
    # Nothing agreed on call 1 is asked again. What wrap-up raises: the contradiction, still
    # unconfirmed, and nothing else. No read-back of the whole deal.
    assert all(s.reason != "term_unclear" for s in second.speaks)
    assert (wrap.after_line, wrap.reason, wrap.item) == (8, "wrapping_up", "amount")
    assert "Says 14,000 rupees" in wrap.instruction and "Ask Sunita and Ramesh to confirm" not in wrap.instruction
    assert second.values.missing == [] and first.values.missing == []
