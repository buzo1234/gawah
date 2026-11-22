"""Changes a deal call left open: said or agreed on the call, never confirmed through Gawah,
read from memory's facts in the event log. The call-back puts each to the person as a change."""

import re
from dataclasses import dataclass

from app.contracts import ChangeStatus, Fact, FactChanged, FactKind, FactSource, FactStatus, ItemKey


@dataclass
class OpenChange:
    """A change said or agreed on a deal call and never confirmed through Gawah."""

    record: Fact  # the term as it stands on record
    change: Fact  # the change, as memory holds it
    change_id: str  # the fact.changed id both call-backs answer under


def open_changes(facts: dict[str, Fact], steps: dict[str, FactChanged]) -> dict[ItemKey, OpenChange]:
    """By term, from memory's facts (latest version each, in the order they last changed) and the
    fact.changed steps so far. A change Gawah already put on the call keeps its change id."""
    found = {}
    for item in ItemKey:
        terms = [f for f in facts.values() if f.item is item and f.kind is FactKind.TERM and _valued(f)]
        record = next((
            held[-1] for status in (FactStatus.CONFIRMED, FactStatus.AGREED, FactStatus.DISPUTED)
            if (held := [f for f in terms if f.status is status])
        ), None)
        said = [
            f for f in facts.values()
            if f.item is item and f.kind is FactKind.CHANGE and f.status in (FactStatus.SAID, FactStatus.AGREED)
            and f.source is FactSource.CALL and f.value_rupees is not None
        ]
        if record is None or not said or said[-1].value_rupees == record.value_rupees:
            continue
        put = [c for c in steps.values() if c.fact_id == record.id and _rupees(c.new_value) == said[-1].value_rupees]
        if any(c.status in (ChangeStatus.CONFIRMED_BOTH, ChangeStatus.WITHDRAWN) for c in put):
            continue  # settled through Gawah; memory is making the new term, or the record stands
        on_call = [c for c in put if c.status in (ChangeStatus.PROPOSED, ChangeStatus.CONFIRMED_ONE)]
        found[item] = OpenChange(record, said[-1], on_call[-1].change_id if on_call else f"callback-{said[-1].id}")
    return found


def _rupees(text: str | None) -> int | None:
    """The first figure in a change's new value ("24,000 rupees (22,000 agreed + 2,000 extra)")."""
    found = re.search(r"\d[\d,]*", text or "")
    return int(found.group().replace(",", "")) if found else None


def _valued(fact: Fact) -> bool:
    return fact.value_rupees is not None or fact.value_date is not None or bool((fact.value or "").strip())
