"""What each part of the agreement says, and where it was said: the six terms, the changes
made later, and the other things both agreed. No I/O: memory's facts and the checklist in,
the parts to write out.

A term is written in the checklist's words: the value read back to each person on their
call-back, which both confirmed. Memory's facts overrule those words in two cases: a change
both confirmed later (the new fact's value), and an amount where memory's agreed figure is
not the checklist's (memory keeps offers and agreements apart; the checklist has read a
turned-down offer as the agreed figure before). Where it was said comes from the same
source as the words.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import NamedTuple

from app.contract import check
from app.contracts import (
    ChecklistItem, Fact, FactChanged, FactSource, FactStatus, ItemKey, ItemState, Role, TranscriptLine,
)

MONEY = {ItemKey.AMOUNT, ItemKey.ADVANCE, ItemKey.BALANCE}
HELD = {FactStatus.AGREED, FactStatus.CONFIRMED}


class Bi(NamedTuple):
    hi: str
    en: str


class Said(NamedTuple):
    """Which deal call, and how far into it."""

    call_no: int
    seconds: float | None

    def label(self) -> str:
        if self.seconds is None:
            return str(self.call_no)
        return f"{self.call_no}, {int(self.seconds) // 60}:{int(self.seconds) % 60:02d}"


@dataclass
class Term:
    item: ChecklistItem  # the value to write, the words it came from
    at: Said | None
    changed: bool = False  # the value comes from a change both confirmed later


@dataclass
class Change:
    key: str  # change_1, change_2, ... in the order they were confirmed
    item: ItemKey
    before: str
    now: str
    at: Said | None
    when: datetime  # when the second person confirmed it
    said: str | None  # the words that proposed it
    confirmed_by: list[Role]


@dataclass
class AlsoAgreed:
    key: str
    text: str
    quote: str | None
    at: Said | None


def resolve(
    checklist: dict[ItemKey, tuple[ChecklistItem, int]],
    current: dict[ItemKey, Fact | None],
    changes: list[Change],
    changed_facts: dict[ItemKey, Fact],
    lines: dict[tuple[int, int], TranscriptLine],
    starts: dict[int, datetime],
) -> list[Term]:
    """checklist: each agreed item with the call it was agreed on; current: memory's get_term
    for each item; changed_facts: the fact each item was last changed to, if it still stands."""
    found = []
    for key in ItemKey:
        fact = changed_facts.get(key)
        if fact is not None:
            found.append(Term(_from_fact(key, fact), fact_at(fact, starts), changed=True))
            continue
        if key not in checklist:
            continue
        item, call_no = checklist[key]
        fact = current.get(key)
        if (
            key in MONEY and fact is not None and fact.value and fact.value_rupees is not None
            and fact.value_rupees not in check.numbers(item.value or "")
        ):
            found.append(Term(_from_fact(key, fact), fact_at(fact, starts)))
            continue
        line = lines.get((call_no, item.line_no or -1))
        found.append(Term(item, Said(call_no, line.start) if line else None))
    return found


def change_list(
    landed: list[tuple[FactChanged, Fact]], proposed: dict[str, str], latest: dict[str, Fact],
    starts: dict[int, datetime],
) -> tuple[list[Change], dict[ItemKey, Fact]]:
    """Every change both confirmed, oldest first, and the fact each item now stands at."""
    changes, now = [], {}
    for step, new in landed:
        old, item = latest.get(step.fact_id), step.item or new.item
        if old is None or item is None:
            continue
        changes.append(Change(
            key=f"change_{len(changes) + 1}", item=item, before=old.value or old.text, now=new.value or step.new_value,
            at=fact_at(new, starts), when=step.ts, said=proposed.get(step.change_id) or step.said or new.quote,
            confirmed_by=sorted(set(step.confirmed_by or new.confirmed_by)),
        ))
        standing = latest.get(new.id, new)
        if standing.status in HELD:
            now[item] = standing
        else:
            now.pop(item, None)
    return changes, now


def also_agreed(latest: dict[str, Fact], starts: dict[int, datetime]) -> list[AlsoAgreed]:
    """Facts said on a call that belong to none of the six terms, which both people agreed."""
    found = []
    for fact in latest.values():
        both = {fact.said_by, *fact.agreed_by, *fact.confirmed_by} >= set(Role)
        if fact.item is None and fact.source in (FactSource.CALL, FactSource.CALLBACK) and fact.status in HELD and both and fact.quote:
            found.append(AlsoAgreed(f"also_{len(found) + 1}", fact.text, fact.quote, fact_at(fact, starts)))
    return found


def fact_at(fact: Fact, starts: dict[int, datetime]) -> Said | None:
    if fact.call_no is None:
        return None
    seconds = fact.start
    if seconds is None and fact.valid_from and fact.call_no in starts:
        seconds = max(0.0, (fact.valid_from - starts[fact.call_no]).total_seconds())
    return Said(fact.call_no, seconds)


def _from_fact(key: ItemKey, fact: Fact) -> ChecklistItem:
    return ChecklistItem(key=key, state=ItemState.AGREED, value=fact.value, source_text=fact.quote, line_no=fact.line_no)
