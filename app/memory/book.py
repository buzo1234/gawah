"""The fact store, kept in memory and rebuilt from the event log: every fact version in
order (the chain), the transcript lines, and what is known about each call."""

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

from app.contracts import CallStarted, Fact, FactKind, FactStatus, ItemKey, Role, TranscriptLine
from app.memory import chain

IST = timedelta(hours=5, minutes=30)
# A term's value is held by these kinds; payments and work count towards a term.
TERM_KINDS = {FactKind.TERM}
LIVE = {FactStatus.SAID, FactStatus.AGREED, FactStatus.CONFIRMED}
OPEN = {FactStatus.SAID, FactStatus.AGREED}  # a change said, or agreed on the call, and not yet confirmed through Gawah


def valued(fact: Fact) -> bool:
    """The fact holds a value for its term: a figure, a day, or words for one."""
    return fact.value_rupees is not None or fact.value_date is not None or bool((fact.value or "").strip())


@dataclass
class Call:
    started_at: datetime | None = None
    room: str | None = None
    recordings: dict[Role, str] = field(default_factory=dict)  # role -> key, as in call.ended


@dataclass
class DealBook:
    deal_id: str
    versions: list[Fact] = field(default_factory=list)
    latest: dict[str, Fact] = field(default_factory=dict)  # insertion order: oldest fact first
    lines: dict[tuple[int, int], TranscriptLine] = field(default_factory=dict)  # (call_no, line_no)
    calls: dict[int, Call] = field(default_factory=dict)
    names: dict[Role, str] = field(default_factory=dict)

    def call(self, call_no: int) -> Call:
        return self.calls.setdefault(call_no, Call())

    @property
    def last_call_no(self) -> int:
        return max(self.calls, default=0) or 1  # call 0 holds voice notes, not a call

    def call_date(self, call_no: int | None) -> date:
        started = self.calls.get(call_no or 0, Call()).started_at or datetime.now(UTC)
        return (started + IST).date()

    def at(self, call_no: int, seconds: float) -> datetime:
        started = self.call(call_no).started_at or datetime.now(UTC)
        return started + timedelta(seconds=seconds)

    def name(self, role: Role | None) -> str:
        if role is None:
            return "someone"
        return self.names.get(role) or f"the {role.value}"

    def learn_people(self, started: CallStarted) -> None:
        for person in started.people:
            if person.name:
                self.names.setdefault(person.role, person.name)

    # ---------- reading ----------

    def standing(self) -> list[Fact]:
        return list(self.latest.values())

    def history(self, item: ItemKey) -> list[Fact]:
        """Every version of every fact about the term, oldest first; payments and work left out."""
        return [f for f in self.versions if f.item == item and f.kind not in (FactKind.PAYMENT, FactKind.WORK)]

    def current(self, item: ItemKey | None) -> Fact | None:
        """The confirmed value of the term if any, else the agreed one. A fact with no value ("he
        agrees with the advance terms") never stands in for one that has a value."""
        if item is None:
            return None
        standing = [f for f in self.standing() if f.item == item and f.kind in TERM_KINDS]
        standing = [f for f in standing if valued(f)] or standing
        for status in (FactStatus.CONFIRMED, FactStatus.AGREED):
            matches = [f for f in standing if f.status == status]
            if matches:
                return max(matches, key=lambda f: self._last_index(f.id))
        return None

    def record(self, item: ItemKey | None) -> Fact | None:
        """The value on record for the term: the current one, or failing that the last one in
        dispute. A disputed term still has a value on record; a new one is not agreed over it."""
        current = self.current(item)
        if current is not None or item is None:
            return current
        disputed = [
            f for f in self.standing() if f.item == item and f.kind in TERM_KINDS and f.status == FactStatus.DISPUTED and valued(f)
        ]
        return max(disputed, key=lambda f: self._last_index(f.id)) if disputed else None

    def open_changes(self, item: ItemKey | None) -> list[Fact]:
        """Changes to the term said on a call, or agreed there, that have not been confirmed
        through Gawah or closed: oldest first."""
        return [f for f in self.standing() if f.item == item and f.kind == FactKind.CHANGE and f.status in OPEN]

    def latest_term(self, item: ItemKey) -> Fact | None:
        """The term as it stands, or failing that the last thing said about it."""
        said = [f for f in self.standing() if f.item == item and f.kind in TERM_KINDS and f.status in LIVE]
        return self.current(item) or (said[-1] if said else None)

    def from_line(self, call_no: int, line_no: int) -> list[Fact]:
        return [f for f in self.standing() if f.call_no == call_no and f.line_no == line_no]

    def by_record(self, record_id: str) -> Fact | None:
        return next((f for f in self.standing() if f.record_id == record_id), None)

    def _last_index(self, fact_id: str) -> int:
        return max(i for i, f in enumerate(self.versions) if f.id == fact_id)


class Book:
    def __init__(self) -> None:
        self.deals: dict[str, DealBook] = {}
        self.owner: dict[str, str] = {}  # fact id -> deal id

    def deal(self, deal_id: str) -> DealBook:
        return self.deals.setdefault(deal_id, DealBook(deal_id))

    def append(self, fact: Fact) -> Fact:
        """Chain a new version onto its deal. Synchronous, so versions never interleave."""
        book = self.deal(fact.deal_id)
        linked = chain.link(fact, chain.fingerprint(book.versions))
        self.load(linked)
        return linked

    def load(self, fact: Fact) -> None:
        """Take a version as it is, hash and all: for a rebuild from the event log."""
        book = self.deal(fact.deal_id)
        book.versions.append(fact)
        book.latest[fact.id] = fact  # an existing key keeps its place: oldest fact first
        self.owner[fact.id] = fact.deal_id

    def fact(self, fact_id: str) -> Fact | None:
        deal_id = self.owner.get(fact_id)
        return self.deals[deal_id].latest.get(fact_id) if deal_id else None
