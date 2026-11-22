"""Changes to a term on record, made on a call. An offer while a change is bargained is a said
change and nothing more; once the other person accepts it, it is an agreed change, and still
not the term: a value on record changes only when both confirm the change through Gawah
(fact.changed, status.on_changed). Until then the old value stands."""

from app.contracts import Fact, FactKind, FactStatus, ItemKey, TranscriptLine
from app.memory.book import DealBook
from app.memory.claims import MONEY, Claim, schedule
from app.memory.normalise import format_rupees, normed, tokens

BARGAIN_LINES = 6  # a change offered this many lines back can still be accepted
CLIP_SPAN_S = 20.0


def offered(deal: DealBook, line: TranscriptLine, item: ItemKey | None, rupees: int | None, added: int | None = None) -> Fact | None:
    """The other person's latest said change to this term on this call, with this figure if one
    is given: the new value, or the extra it adds ("pandrah de dunga" to a total raised by 15,000)."""
    current = deal.record(item)
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


def turn_down(memory, deal: DealBook, line: TranscriptLine, claim: Claim, received: float) -> None:
    """The other person's change, said back with a complaint or put off ("1,200 wala baad mein"):
    it is no longer on the table."""
    offer = offered(deal, line, claim.item, claim.rupees)
    if offer is not None:
        memory.record(offer.model_copy(update={"status": FactStatus.DISPUTED}), received)
        memory.note("scribe", f"line {line.line_no}: change to {offer.item.value} turned down or put off", offer, line)


def carry(memory, deal: DealBook, line: TranscriptLine, claim: Claim, received: float) -> bool:
    """An extra agreed on this call goes into one payment of the balance when someone says so
    ("the last 50 becomes 65"): the schedule takes the new payment. True if it did."""
    current = deal.current(ItemKey.BALANCE)
    raised, old = _raised_total(deal, line)
    if current is None or not claim.rupees or old is None or None in (old.value_rupees, raised.value_rupees, current.value_rupees):
        return False
    added = raised.value_rupees - old.value_rupees
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
    agree(memory, deal, line.model_copy(update={"speaker": line.speaker.other}), offer, None, received)
    return True


def _raised_total(deal: DealBook, line: TranscriptLine) -> tuple[Fact | None, Fact | None]:
    """The total raised on this call, and the total it was raised from: a change agreed on the
    call (waiting for both to confirm it through Gawah), or one already confirmed."""
    raised = [
        f for f in deal.standing()
        if f.item == ItemKey.AMOUNT and f.call_no == line.call_no and f.value_rupees is not None and (
            (f.kind == FactKind.TERM and f.replaces and f.status in (FactStatus.AGREED, FactStatus.CONFIRMED))
            or (f.kind == FactKind.CHANGE and f.status == FactStatus.AGREED)
        )
    ]
    if not raised:
        return None, None
    new = raised[-1]
    return new, deal.latest.get(new.replaces or "") if new.kind == FactKind.TERM else deal.record(ItemKey.AMOUNT)


def shape(deal: DealBook, line: TranscriptLine, claim: Claim) -> None:
    """A rate is not the term's figure, only a detail; an addition makes the total the agreed
    one plus the extra."""
    if claim.item in MONEY and claim.figure == "rate":
        claim.rupees, claim.kind = None, FactKind.OTHER
        return
    base = deal.record(ItemKey.AMOUNT)
    if (
        claim.item == ItemKey.AMOUNT and claim.figure == "whole" and claim.kind in (FactKind.TERM, FactKind.CHANGE)
        and _bargaining_an_extra(deal, line, base, claim.rupees)
    ):
        claim.figure = "addition"  # "paanch kar lo" while an extra is bargained: the extra, not a new total
    if claim.item != ItemKey.AMOUNT or claim.figure != "addition" or not claim.rupees:
        return
    raised, before = _raised_total(deal, line)
    if raised is not None and before is not None and raised.value_rupees - (before.value_rupees or 0) == claim.rupees:
        claim.rupees = raised.value_rupees  # the extra just agreed, said again: the total as raised
        return
    if base is None or base.value_rupees is None or claim.stance == "recall":
        # No agreed total to add it to, or an extra recalled after it was added: a detail, no figure.
        claim.rupees, claim.kind = None, FactKind.OTHER if base is None else claim.kind
        return
    claim.added, claim.rupees = claim.rupees, base.value_rupees + claim.rupees
    claim.value = f"{format_rupees(claim.rupees)} ({base.value_rupees:,} agreed + {claim.added:,} extra)"
    if claim.kind == FactKind.TERM:
        claim.kind = FactKind.CHANGE


_EXTRA = normed({"extra", "एक्स्ट्रा", "alag", "अलग", "additional", "upar", "ऊपर"})


def _bargaining_an_extra(deal: DealBook, line: TranscriptLine, base: Fact | None, rupees: int | None) -> bool:
    """A figure far below the agreed total, while an extra on top of it is asked about ("kitna
    extra?"), offered, or agreed on this call: it is the extra, not a new total for the same job."""
    if not rupees or base is None or not base.value_rupees or rupees * 2 > base.value_rupees:
        return False
    talk = [deal.lines.get((line.call_no, n)) for n in range(line.line_no, max(0, line.line_no - 4), -1)]
    if any(t is not None and _EXTRA & set(tokens(t.text)) for t in talk):
        return True
    return any(
        f.item == ItemKey.AMOUNT and f.kind == FactKind.CHANGE and f.call_no == line.call_no and (f.value_rupees or 0) > base.value_rupees
        and (f.status == FactStatus.AGREED or (f.status == FactStatus.SAID and 0 < line.line_no - (f.line_no or 0) <= BARGAIN_LINES))
        for f in deal.standing()
    )


def agree(
    memory, deal: DealBook, line: TranscriptLine, offer: Fact | None, claim: Claim | None, received: float,
) -> Fact | None:
    """The other person's change (or, with no change fact, the claim's value they said) is accepted
    by this line's speaker. Both have now said it, and it is still only an agreed change: the term
    keeps its value until both confirm the change through Gawah. An offer not yet on record (from
    carry) is recorded here, agreed."""
    item = offer.item if offer else claim.item
    if deal.record(item) is None:
        return None
    rupees = offer.value_rupees if offer else claim.rupees
    same = [
        f for f in deal.open_changes(item)
        if f.status == FactStatus.AGREED and f.call_no == line.call_no and rupees is not None and f.value_rupees == rupees
    ]
    if same and (offer is None or offer.id != same[-1].id):
        return same[-1]  # agreed already on this call, said again
    src = offer or Fact(
        deal_id=line.deal_id, text=claim.text, item=item, value=claim.value, value_rupees=claim.rupees,
        said_by=line.speaker.other, quote=claim.quote, call_no=line.call_no, line_no=line.line_no, start=line.start, end=line.end,
    )
    end = max(src.end or 0, line.end) if src.start is not None and line.end - src.start <= CLIP_SPAN_S else src.end
    agreed_by = sorted({*src.agreed_by, line.speaker}, key=list(type(line.speaker)).index)
    accepted = memory.record(src.model_copy(update={
        "kind": FactKind.CHANGE, "status": FactStatus.AGREED, "agreed_by": agreed_by, "end": end,
    }), received)
    for earlier in deal.open_changes(item):
        if earlier.id != accepted.id and earlier.status == FactStatus.SAID and earlier.call_no == line.call_no:
            # The offers it was bargained from: the agreed one replaces them.
            memory.record(earlier.model_copy(update={"status": FactStatus.SUPERSEDED, "superseded_at": accepted.valid_from}), received)
    memory.note("scribe", f"line {line.line_no}: change to {item.value} agreed on the call, {accepted.value or accepted.text}; "
                "the term stands until both confirm it", accepted, line)
    return accepted
