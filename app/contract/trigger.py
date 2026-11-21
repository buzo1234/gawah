"""Who has confirmed what, for one deal. No I/O: events go in, should_write() comes out."""

from dataclasses import dataclass, field
from datetime import datetime

from app.contracts import (
    CallEnded,
    CallKind,
    ChecklistItem,
    ChecklistUpdated,
    ContractReady,
    Event,
    ItemKey,
    ItemState,
    Role,
    TermsConfirmed,
    TermsDisputed,
)

WATCHED = (TermsConfirmed, TermsDisputed, ChecklistUpdated, CallEnded)


@dataclass
class DealState:
    items: list[ChecklistItem] = field(default_factory=list)
    confirmed: dict[Role, set[ItemKey]] = field(default_factory=lambda: {r: set() for r in Role})
    confirmed_at: dict[Role, datetime] = field(default_factory=dict)
    confirmed_said: dict[Role, str | None] = field(default_factory=dict)  # their words, if the event has them
    call: CallEnded | None = None  # the deal call: when it ended, how long it was, its recordings
    written: bool = False
    # Goes up on every dispute, so a contract being written while one arrives is thrown away.
    version: int = 0

    def apply(self, event: Event) -> None:
        match event:
            case ChecklistUpdated():
                self.items = event.items
            case CallEnded(kind=CallKind.DEAL):
                self.call = event
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
                self.version += 1
            case ContractReady():
                self.written = True

    def agreed(self) -> set[ItemKey]:
        return {i.key for i in self.items if i.state is ItemState.AGREED}

    def both_confirmed(self) -> bool:
        return all(self.confirmed[role] >= set(ItemKey) or
                   (self.agreed() and self.confirmed[role] >= self.agreed()) for role in Role)

    def should_write(self) -> bool:
        return not self.written and bool(self.agreed()) and self.both_confirmed()
