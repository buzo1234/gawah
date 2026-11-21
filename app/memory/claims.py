"""A claim the Scribe's model gives, grounded in the line's words, and how a value compares
with the term as it stands."""

import logging
from dataclasses import dataclass, field
from datetime import date

from app.contracts import Fact, FactKind, FactStatus, ItemKey, TranscriptLine
from app.memory.book import DealBook
from app.memory.dates import Day, date_parts, meets, pin_date
from app.memory.normalise import normalise_rupees

log = logging.getLogger("gawah.memory")


@dataclass
class Claim:
    item: ItemKey | None
    kind: FactKind
    stance: str
    text: str
    value: str | None
    rupees: int | None
    date: date | None
    quote: str
    accepts_line: int | None
    contradicts: str | None
    parts: dict[str, Day] = field(default_factory=dict)  # dates only: the start and finish the words fix


def _squash(text: str) -> str:
    return "".join(ch for ch in text.lower() if ch.isalnum())


def parse_claim(raw: dict, line: TranscriptLine, today: date) -> Claim | None:
    """A claim the model gave, or None if it is not grounded in the line's words."""
    quote = (raw.get("quote") or "").strip()
    if not quote or _squash(quote) not in _squash(line.text):
        log.info("deal=%s line %s: dropped a claim whose quote is not in the line: %r", line.deal_id, line.line_no, quote)
        return None
    try:
        item = ItemKey(raw["item"]) if raw.get("item") else None
        kind = FactKind(raw.get("kind") or "other")
        model_date = date.fromisoformat(raw["date"]) if raw.get("date") else None
    except ValueError:
        return None
    rupees = normalise_rupees(raw.get("rupees"), raw.get("value"), quote)
    parts = date_parts(quote, today) if item == ItemKey.DATES else {}
    if item == ItemKey.DATES and not parts and meets(quote):
        log.info("deal=%s line %s: dropped a meeting time filed as the dates: %r", line.deal_id, line.line_no, quote)
        return None
    return Claim(
        item=item, kind=kind, stance=raw.get("stance") or "state", text=raw.get("text") or quote,
        value=raw.get("value"), rupees=rupees, date=pin_date(quote, today, model_date), quote=quote,
        accepts_line=raw.get("accepts_line"), contradicts=raw.get("contradicts"), parts=parts,
    )


def parts_of(deal: DealBook, fact: Fact) -> dict[str, Day]:
    return date_parts(fact.quote, deal.call_date(fact.call_no)) if fact.item == ItemKey.DATES else {}


def say_day(day: Day) -> str:
    return f"{day.day:%A}" if day.weekday_only else f"{day.day:%A %-d %B}"


def agreed_parts(deal: DealBook) -> dict[str, tuple[Fact, Day]]:
    """The start and the finish as they stand, each with the fact that holds it: the dates
    term is often agreed a part at a time."""
    held = [
        f for f in deal.standing()
        if f.item == ItemKey.DATES and f.kind == FactKind.TERM and f.status in (FactStatus.AGREED, FactStatus.CONFIRMED)
    ]
    out: dict[str, tuple[Fact, Day]] = {}
    for fact in sorted(held, key=lambda f: (f.status == FactStatus.CONFIRMED, deal._last_index(f.id))):
        out |= {part: (fact, day) for part, day in parts_of(deal, fact).items()}
    return out


def compare(
    deal: DealBook, item: ItemKey | None, rupees: int | None, day: date | None, parts: dict[str, Day],
) -> tuple[str | None, Fact | None, str | None]:
    """A value against the term as it stands: ("same" | "differs" | None when there is nothing
    to compare, the fact it was compared with, and for dates the part that differs). Dates
    compare a start with the start and a finish with the finish."""
    if item == ItemKey.DATES:
        verdict, against = None, deal.current(item)
        for part, (fact, agreed) in agreed_parts(deal).items():
            if part in parts:
                if not parts[part].same(agreed):
                    return "differs", fact, part
                verdict, against = "same", fact
        return verdict, against, None
    current = deal.current(item)
    if current is None:
        return None, None, None
    if rupees is not None and current.value_rupees is not None:
        return ("same" if rupees == current.value_rupees else "differs"), current, None
    if day is not None and current.value_date is not None:
        return ("same" if day == current.value_date else "differs"), current, None
    return None, current, None


def comparable(deal: DealBook, fact: Fact, claim: Claim) -> bool:
    if fact.item == ItemKey.DATES:
        return bool(set(parts_of(deal, fact)) & set(claim.parts))
    return (claim.rupees is not None and fact.value_rupees is not None) or (
        claim.date is not None and fact.value_date is not None
    )
