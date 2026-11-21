"""Changes to an agreed term, made on a call. An offer while a change is bargained is a said
change and nothing more; once the other person accepts it, the new value is the term and
the old one is superseded. A money term's value is replaced; for any other term the change
is an added detail, and what was agreed before still stands."""

from app.contracts import Fact, FactKind, FactStatus, ItemKey, TranscriptLine
from app.memory.book import DealBook
from app.memory.claims import MONEY, Claim, schedule
from app.memory.normalise import format_rupees

BARGAIN_LINES = 6  # a change offered this many lines back can still be accepted
CLIP_SPAN_S = 20.0


def offered(deal: DealBook, line: TranscriptLine, item: ItemKey | None, rupees: int | None, added: int | None = None) -> Fact | None:
    """The other person's latest said change to this term on this call, with this figure if one
    is given: the new value, or the extra it adds ("pandrah de dunga" to a total raised by 15,000)."""
    current = deal.current(item)
    was = current.value_rupees if current else None

    def fits(f: Fact) -> bool:
        if rupees is None or f.value_rupees == rupees:
            return True
        extra = f.value_rupees - was if f.value_rupees is not None and was is not None else None
        return extra is not None and extra in (rupees, added)

    found = [
        f for f in deal.standing()
        if f.item == item and f.kind == FactKind.CHANGE and f.status == FactStatus.SAID and f.said_by == line.speaker.other
        and f.call_no == line.call_no and 0 < line.line_no - (f.line_no or 0) <= BARGAIN_LINES and fits(f)
    ]
    return max(found, key=lambda f: f.line_no or 0) if found else None


def carry(memory, deal: DealBook, line: TranscriptLine, claim: Claim, received: float) -> bool:
    """An extra agreed on this call goes into one payment of the balance when someone says so
    ("the last 50 becomes 65"): the schedule takes the new payment. True if it did."""
    current = deal.current(ItemKey.BALANCE)
    raised = [
        f for f in deal.standing()
        if f.item == ItemKey.AMOUNT and f.kind == FactKind.TERM and f.replaces and f.call_no == line.call_no
        and f.status in (FactStatus.AGREED, FactStatus.CONFIRMED)
    ]
    old = deal.latest.get(raised[-1].replaces) if raised else None
    if current is None or not claim.rupees or old is None or None in (old.value_rupees, raised[-1].value_rupees, current.value_rupees):
        return False
    added = raised[-1].value_rupees - old.value_rupees
    payments = schedule(current)
    if added <= 0 or claim.rupees - added not in payments:
        return False
    before = claim.rupees - added
    value = (current.value or "").replace(f"{before:,}", f"{claim.rupees:,}", 1)
    claim.value, claim.rupees = value, current.value_rupees + added
    offer = Fact(
        deal_id=line.deal_id, text=claim.text, item=ItemKey.BALANCE, value=value, value_rupees=claim.rupees,
        said_by=line.speaker, quote=claim.quote, call_no=line.call_no, line_no=line.line_no, start=line.start, end=line.end,
    )
    agree(memory, deal, line.model_copy(update={"speaker": line.speaker.other}), offer, None, received, record_offer=False)
    return True


def shape(deal: DealBook, line: TranscriptLine, claim: Claim) -> None:
    """A rate is not the term's figure, only a detail; an addition makes the total the agreed
    one plus the extra."""
    if claim.item in MONEY and claim.figure == "rate":
        claim.rupees, claim.kind = None, FactKind.OTHER
        return
    base = deal.current(ItemKey.AMOUNT)
    if claim.item == ItemKey.AMOUNT and claim.figure == "whole" and _bargaining_an_extra(deal, line, base, claim.rupees):
        claim.figure = "addition"  # "paanch kar lo" while an extra is bargained: the extra, not a new total
    if claim.item != ItemKey.AMOUNT or claim.figure != "addition" or not claim.rupees:
        return
    if base is None or base.value_rupees is None or claim.stance == "recall":
        # No agreed total to add it to, or an extra recalled after it was added: a detail, no figure.
        claim.rupees, claim.kind = None, FactKind.OTHER if base is None else claim.kind
        return
    claim.added, claim.rupees = claim.rupees, base.value_rupees + claim.rupees
    claim.value = f"{format_rupees(claim.rupees)} ({base.value_rupees:,} agreed + {claim.added:,} extra)"
    if claim.kind == FactKind.TERM:
        claim.kind = FactKind.CHANGE


def _bargaining_an_extra(deal: DealBook, line: TranscriptLine, base: Fact | None, rupees: int | None) -> bool:
    """A figure far below the agreed total, while an extra on top of it is being offered."""
    if not rupees or base is None or not base.value_rupees or rupees * 2 > base.value_rupees:
        return False
    return any(
        f.item == ItemKey.AMOUNT and f.kind == FactKind.CHANGE and f.status == FactStatus.SAID and f.call_no == line.call_no
        and 0 < line.line_no - (f.line_no or 0) <= BARGAIN_LINES and (f.value_rupees or 0) > base.value_rupees
        for f in deal.standing()
    )


def agree(
    memory, deal: DealBook, line: TranscriptLine, offer: Fact | None, claim: Claim | None, received: float, record_offer: bool = True,
) -> Fact | None:
    """The other person's change (or, with no change fact, the claim's value they said) is accepted
    by this line's speaker: it becomes the term."""
    item = offer.item if offer else claim.item
    current = deal.current(item)
    if current is None:
        return None
    if offer is not None and record_offer:
        memory.record(offer.model_copy(update={"status": FactStatus.AGREED, "agreed_by": [line.speaker]}), received)
    src = offer or Fact(
        deal_id=line.deal_id, text=claim.text, item=item, value=claim.value, value_rupees=claim.rupees,
        said_by=line.speaker.other, quote=claim.quote, call_no=line.call_no, line_no=line.line_no, start=line.start, end=line.end,
    )
    money = item in MONEY and src.value_rupees is not None
    end = max(src.end or 0, line.end) if src.start is not None and line.end - src.start <= CLIP_SPAN_S else src.end
    new = memory.record(Fact(
        deal_id=line.deal_id, text=f"The {item.value.replace('_', ' ')} is now {src.value or src.text}.", item=item,
        kind=FactKind.TERM, value=src.value, value_rupees=src.value_rupees, value_date=src.value_date,
        said_by=src.said_by, agreed_by=[line.speaker], status=FactStatus.AGREED, quote=src.quote,
        call_no=src.call_no, line_no=src.line_no, start=src.start, end=end, valid_from=deal.at(line.call_no, line.start),
        replaces=current.id if money else None,
    ), received)
    if money:
        memory.record(current.model_copy(update={"status": FactStatus.SUPERSEDED, "superseded_at": new.valid_from}), received)
    memory.note("scribe", f"line {line.line_no}: {item.value} changed to {new.value or new.text}, agreed by both", new, line)
    return new
