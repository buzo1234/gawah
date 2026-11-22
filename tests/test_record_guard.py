"""The record is guarded: a term on record never takes a new value because both people say one.
The user's call 3 (deal 6aae99c104d1), on fakes: memory with a scripted Scribe model and the
brain with no Sage2, on one bus.

Call 1 agreed 20,000 and the advance of 5,000; the hirer disputed the amount on the call-back.
(The world's people are Sunita and Ramesh; on the user's call the hirer was Karan.)
On call 3 the worker says "pachees hazaar tay hua tha na?", the hirer "nahi, baees hazaar hi tay
hua tha", the worker "haan ji, baees hi": memory recorded 22,000 as agreed by both and Gawah said
nothing about the record. Then a 2,000 extra was agreed and the call ended before it was put to
both, and on the call-back "Karan says he agrees with the advance terms" stood for the advance.
"""

from datetime import timedelta

import pytest

from app.brain import Brain, _Saved
from app.contracts import (
    CallStarted, ChangeStatus, ChecklistUpdated, Fact, FactChanged, FactKind, FactStatus, ItemKey, JudgeSpeak,
    JudgeSpoke, Role, SpeakReason, TermsDisputed, TranscriptLine,
)
from app.log import deal_log
from tests.memory.world import DAY1, DEAL, PEOPLE, World, claim

H, W = Role.HIRER, Role.WORKER

CALL_1 = [
    (W, "Do coat paint, pachees hazaar lagega."),
    (H, "Bees hazaar mein karo."),
    (W, "Theek hai, bees hazaar."),
    (W, "Advance paanch hazaar chahiye."),
    (H, "Theek hai, paanch hazaar advance."),
]
CALL_3 = [
    (W, "Main Ramesh. Main sehmat hoon."),
    (H, "Main Karan. Main bhi sehmat hoon."),
    (W, "Total pachees hazaar tay hua tha na?"),
    (H, "Nahi, baees hazaar hi tay hua tha."),
    (W, "Haan ji, baees hi."),
    (H, "Advance ki baat bhi theek hai."),
    (H, "Balcony bhi paint karni hai."),
    (W, "Uske do hazaar extra lagenge."),
    (H, "Theek hai, do hazaar extra."),
]
SCRIPT = {
    CALL_1[0][1]: [claim("amount", "offer", 25000, "pachees hazaar lagega")],
    CALL_1[1][1]: [claim("amount", "offer", 20000, "Bees hazaar mein karo")],
    CALL_1[2][1]: [claim("amount", "accept", 20000, "Theek hai, bees hazaar", accepts_line=2)],
    CALL_1[3][1]: [claim("advance", "offer", 5000, "Advance paanch hazaar chahiye")],
    CALL_1[4][1]: [claim("advance", "accept", 5000, "Theek hai, paanch hazaar advance", accepts_line=4)],
    # As the live model read the user's call 3.
    CALL_3[2][1]: [claim("amount", "recall", 25000, "Total pachees hazaar tay hua tha na?", kind="other")],
    CALL_3[3][1]: [claim("amount", "recall", 22000, "Nahi, baees hazaar hi tay hua tha.")],
    CALL_3[4][1]: [claim("amount", "accept", 22000, "Haan ji, baees hi.", accepts_line=4)],
    CALL_3[5][1]: [claim("advance", "accept", None, "Advance ki baat bhi theek hai.",
                         text="Sunita says she agrees with the advance terms.")],
    CALL_3[7][1]: [claim("amount", "offer", 2000, "do hazaar extra lagenge", kind="change", figure="addition")],
    CALL_3[8][1]: [claim("amount", "accept", 2000, "Theek hai, do hazaar extra", kind="change", figure="addition", accepts_line=8)],
}


class Mouth:
    """Says each judge.speak at once, and takes two seconds."""

    def __init__(self, bus) -> None:
        self.bus, self.speaks = bus, []
        bus.subscribe(JudgeSpeak, self.on_speak)

    async def on_speak(self, event: JudgeSpeak) -> None:
        self.speaks.append(event)
        self.bus.publish(JudgeSpoke(deal_id=DEAL, text="...", speak_id=event.event_id, end=999.0))


@pytest.fixture
async def world(bus, tmp_path):
    world = World(bus, tmp_path, SCRIPT)
    quiet = _Saved([], deal_log("gawah.brain", DEAL))  # no Sage2: the record is guarded by memory's facts alone
    world.brain = Brain(bus, "live", lambda started: (quiet, quiet), world.memory)
    world.mouth = Mouth(bus)
    world.call_1 = await world.call(CALL_1)
    await world.send(TermsDisputed(deal_id=DEAL, person=H, item=ItemKey.AMOUNT, value="20,000 rupees"))
    return world


async def call_3(world, upto: int) -> None:
    """Call 3 line by line, each read before the next is said, as on a real call; it stays open."""
    world.mouth.speaks.clear()
    at = DAY1 + timedelta(days=2)
    await world.send(CallStarted(deal_id=DEAL, people=PEOPLE, call_no=3, room="room-3", ts=at))
    for n, (role, text) in enumerate(CALL_3[:upto], 1):
        await world.send(TranscriptLine(
            deal_id=DEAL, speaker=role, text=text, start=1.0 + 4 * (n - 1), end=4.0 + 4 * (n - 1), line_no=n, call_no=3,
            ts=at + timedelta(seconds=4 * n),
        ))
        await world.brain.idle()
        await world.settle()


def standing(world, item: ItemKey):
    return world.memory.book.deal(DEAL).record(item)


async def test_both_saying_a_different_amount_as_what_was_agreed_is_a_contradiction_not_a_new_value(world):
    disputed = standing(world, ItemKey.AMOUNT)
    assert (disputed.value_rupees, disputed.status) == (20000, FactStatus.DISPUTED)
    await call_3(world, 5)
    amount = [f for f in world.versions if f.item == ItemKey.AMOUNT and f.call_no == 3]
    assert not [f for f in amount if f.status in (FactStatus.AGREED, FactStatus.CONFIRMED)], "nobody agreed 22,000 into the record"
    assert standing(world, ItemKey.AMOUNT).id == disputed.id
    conflicts = [c for c in world.conflicts if c.call_no == 3]
    assert [(c.line_no, c.fact_ids) for c in conflicts] == [(3, [disputed.id]), (4, [disputed.id])], "25,000, then 22,000"
    assert "the amount was disputed at 20,000 rupees, said by Sunita and agreed by Ramesh" in conflicts[0].explanation

    first = world.mouth.speaks[0]
    assert (first.reason, first.after_line, first.item, first.fact_ids) == (
        SpeakReason.CONTRADICTS_RECORD, 3, ItemKey.AMOUNT, [disputed.id]), "at the next pause, not later"
    assert "Tell Sunita and Ramesh what the record holds for the total amount" in first.instruction
    assert "Do not say which one is right." in first.instruction


async def test_a_yes_that_names_no_value_never_stands_for_the_advance(world):
    await call_3(world, 6)
    advance = standing(world, ItemKey.ADVANCE)
    assert (advance.value_rupees, advance.call_no) == (5000, 1)
    assert not [f for f in world.versions if f.item == ItemKey.ADVANCE and f.call_no == 3 and f.status == FactStatus.AGREED]
    checklist = [e for e in world.events if isinstance(e, ChecklistUpdated)][-1]
    item = next(i for i in checklist.items if i.key is ItemKey.ADVANCE)
    assert item.value == "5,000 rupees"


async def test_a_fact_with_no_value_that_slips_in_never_replaces_the_terms_value(world):
    """However it got there (a checklist, an old reading), a later agreed fact with no value does not stand."""
    world.memory.record(Fact(deal_id=DEAL, text="Sunita says she agrees with the advance terms.", item=ItemKey.ADVANCE,
                             kind=FactKind.TERM, said_by=W, agreed_by=[H], status=FactStatus.CONFIRMED, call_no=3, line_no=6))
    await world.settle()
    assert (await world.memory.get_term(DEAL, ItemKey.ADVANCE)).current.value_rupees == 5000
    await call_3(world, 1)
    checklist = [e for e in world.events if isinstance(e, ChecklistUpdated)][-1]
    assert next(i for i in checklist.items if i.key is ItemKey.ADVANCE).value == "5,000 rupees"


async def test_an_extra_both_agree_on_the_call_waits_for_gawah_and_is_put_to_both_at_once(world):
    await call_3(world, 9)
    [change] = world.open_changes(ItemKey.AMOUNT)
    assert (change.kind, change.status, change.value_rupees, change.agreed_by) == (FactKind.CHANGE, FactStatus.AGREED, 22000, [H])
    assert standing(world, ItemKey.AMOUNT).value_rupees == 20000, "the record stands until both confirm through Gawah"
    raised = [s for s in world.mouth.speaks if s.reason is SpeakReason.CHANGE_PROPOSED]
    assert [(s.after_line, s.item) for s in raised] == [(9, ItemKey.AMOUNT)], "at the next pause after it was agreed"
    assert "agreed on this call by both as" in raised[0].instruction

    # Gawah puts it to both; each says haan (confirm_change); only then is it the term.
    record = standing(world, ItemKey.AMOUNT)
    for status, by in ((ChangeStatus.PROPOSED, []), (ChangeStatus.CONFIRMED_ONE, [H]), (ChangeStatus.CONFIRMED_BOTH, [H, W])):
        await world.send(FactChanged(
            deal_id=DEAL, change_id="c1", fact_id=record.id, new_value="22,000 rupees", status=status,
            item=ItemKey.AMOUNT, proposed_by=W, confirmed_by=by, said="haan",
        ))
    new = standing(world, ItemKey.AMOUNT)
    assert (new.value_rupees, new.status, new.replaces) == (22000, FactStatus.CONFIRMED, record.id)
    assert world.memory.book.fact(record.id).status == FactStatus.SUPERSEDED
    assert world.open_changes(ItemKey.AMOUNT) == []
