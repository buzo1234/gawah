"""Who has confirmed what, for one deal, and what memory has recorded. No I/O: events go
in, should_write() comes out."""

from dataclasses import dataclass, field
from datetime import datetime

from app.contracts import (
    CallEnded,
    CallKind,
    CallStarted,
    ChangeStatus,
    ChecklistItem,
    ChecklistUpdated,
    ContractReady,
    Event,
    Fact,
    FactChanged,
    FactRecorded,
    FactStatus,
    ItemKey,
    ItemState,
    Role,
    TermsConfirmed,
    TermsDisputed,
)

WATCHED = (TermsConfirmed, TermsDisputed, ChecklistUpdated, CallStarted, CallEnded, FactRecorded, FactChanged)


@dataclass
class Call:
    started: datetime | None = None
    ended: CallEnded | None = None  # when it ended, how long it was, its recordings


@dataclass
class DealState:
    checklists: dict[int, list[ChecklistItem]] = field(default_factory=dict)  # call no -> its latest checklist
    confirmed: dict[Role, set[ItemKey]] = field(default_factory=lambda: {r: set() for r in Role})
    confirmed_at: dict[Role, datetime] = field(default_factory=dict)
    confirmed_said: dict[Role, str | None] = field(default_factory=dict)  # their words, if the event has them
    calls: dict[int, Call] = field(default_factory=dict)  # the deal calls, by call no
    call_no: int = 1  # the deal call going on, or the last one
    facts: list[Fact] = field(default_factory=list)  # every fact.recorded, in order: the witness chain
    pending: dict[str, FactChanged] = field(default_factory=dict)  # fact id -> change both confirmed, not yet in memory
    proposed: dict[str, str] = field(default_factory=dict)  # change id -> the words that proposed it
    landed: dict[str, tuple[FactChanged, Fact]] = field(default_factory=dict)  # change id -> (step, new fact)
    written: bool = False
    written_changes: set[str] = field(default_factory=set)
    versions: int = 0  # contract versions written so far
    # Goes up on every dispute, so a contract being written while one arrives is thrown away.
    disputes: int = 0

    def apply(self, event: Event) -> None:
        match event:
            case ChecklistUpdated():
                self.checklists[self.call_no] = event.items
            case CallStarted(kind=CallKind.DEAL):
                call = self.calls.setdefault(event.call_no, Call())
                call.started = min(call.started or event.ts, event.ts)  # the brain sends it again with names
                self.call_no = event.call_no
            case CallEnded(kind=CallKind.DEAL):
                self.calls.setdefault(event.call_no, Call()).ended = event
            case FactRecorded():
                self.facts.append(event.fact)
                step = self.pending.get(event.fact.replaces or "")
                if step and event.fact.status is FactStatus.CONFIRMED:
                    del self.pending[event.fact.replaces]
                    self.landed[step.change_id] = (step, event.fact)
            case FactChanged():
                if event.said and event.change_id not in self.proposed:
                    self.proposed[event.change_id] = event.said
                if event.status is ChangeStatus.CONFIRMED_BOTH:
                    self.pending[event.fact_id] = event
            case TermsConfirmed():
                if event.item is None:
                    self.confirmed[event.person] = set(ItemKey)
                else:
                    self.confirmed[event.person].add(event.item)
                self.confirmed_at[event.person] = event.ts
                self.confirmed_said[event.person] = event.said
            case TermsDisputed():
                if event.item is None:
                    self.confirmed[event.person].clear()
                else:
                    self.confirmed[event.person].discard(event.item)
                self.written = False
                self.disputes += 1
            case ContractReady():
                self.wrote(set(self.landed))

    def wrote(self, changes: set[str]) -> None:
        self.written = True
        self.written_changes |= changes
        self.versions += 1

    def checklist(self) -> dict[ItemKey, tuple[ChecklistItem, int]]:
        """Each item as last agreed, with the call it was agreed on. A later call's checklist
        that has not reached an item yet leaves the earlier agreement standing."""
        found = {}
        for call_no in sorted(self.checklists):
            for item in self.checklists[call_no]:
                if item.state is ItemState.AGREED and item.value:
                    found[item.key] = (item, call_no)
        return {key: found[key] for key in ItemKey if key in found}

    def agreed(self) -> set[ItemKey]:
        return set(self.checklist())

    def latest(self) -> dict[str, Fact]:
        """Each fact as it stands now, oldest fact first."""
        found: dict[str, Fact] = {}
        for fact in self.facts:
            found[fact.id] = fact
        return found

    def both_confirmed(self) -> bool:
        return all(self.confirmed[role] >= set(ItemKey) or
                   (self.agreed() and self.confirmed[role] >= self.agreed()) for role in Role)

    def in_call(self) -> bool:
        """A deal call is going on: its length and recordings are not known yet."""
        return any(c.started and not c.ended for c in self.calls.values())

    def should_write(self) -> bool:
        new_changes = bool(set(self.landed) - self.written_changes)
        return (not self.written or new_changes) and bool(self.agreed()) and self.both_confirmed() and not self.in_call()
