"""A claim the other person said no to. Gawah's record stands up for the "no": the person
who denies a payment has nothing to show but what was agreed and what was logged.

- Both are told who said no, that the amount is not counted, every payment the record holds
  and how it stands, and what is still owed.
- Both hear what the record holds about it (memory's answers only): the term the claim
  counts towards as agreed, and anything either person said about this payment, found by
  memory's search (a promise is quoted as a promise). At most three, newest first, each
  with its clip. Never who is right.
- The claimer is asked once for proof. A screenshot with a transaction id and the same
  amount, or a UPI reference, puts the claim to the other person again with the proof;
  their yes counts it. Anything else leaves it disputed and out of the totals.
- Every later owed message and reminder names what is still disputed (still_disputed).

The payments themselves are read from the event log (fact.recorded, memory's own events):
MemoryQueries lists terms and totals, not each payment."""

import re
from dataclasses import dataclass
from datetime import timedelta, timezone
from typing import TYPE_CHECKING

from app.contracts import (
    Backing, Deal, Fact, FactKind, FactStatus, ItemKey, OwedRow, Person, Record, RecordConfirmed, RecordKind, Role,
)
from app.records import words
from app.records.reader import Reading

if TYPE_CHECKING:
    from app.records.sentinel import Sentinel

IST = timezone(timedelta(hours=5, minutes=30))
MONEY = (RecordKind.ADVANCE, RecordKind.PAYMENT)
DISPUTABLE = (*MONEY, RecordKind.WORK_DONE)
QUOTED = 3


@dataclass
class Dispute:
    deal_id: str
    record: Record
    proof_asked: bool = False
    proof: str | None = None  # "Screenshot" or "UPI reference", once sent


class Disputes:
    def __init__(self, sentinel: "Sentinel") -> None:
        self.s = sentinel
        self.open: dict[str, Dispute] = {}  # record id -> its dispute, until a yes counts it

    # ---------- the answer ----------

    async def answered(self, event: RecordConfirmed) -> None:
        record = event.record
        if record is None or record.kind not in DISPUTABLE:
            return
        if event.confirmed:
            if self.open.pop(record.id, None):
                self.s._note(event.deal_id, f"the {_claim(record)} disputed before is confirmed by the "
                             f"{event.confirmed_by.value}: it counts now")
            return
        people = {p.role: p for p in await self.s._people(event.deal_id)}
        answerer = people.get(event.confirmed_by) or Person(role=event.confirmed_by)
        claimer = people.get(record.sender) or Person(role=record.sender)
        payments = await self.payments(event.deal_id, denied=record.id)
        mine = next((f for f in payments if f.record_id == record.id), None)
        rows = _without(await self.s._rows(event.deal_id), mine)
        total = total_row(rows)
        advance = rows.get(ItemKey.ADVANCE) if record.kind is RecordKind.ADVANCE else None
        owed = words.owed_now(advance.owed_rupees if advance else None, total.owed_rupees if total else None)
        others = await self.still_disputed(event.deal_id, skip=record.id)
        dispute = self.open.get(record.id)
        if dispute and dispute.proof:  # the second no, after proof: nothing more is asked
            self._both(event.deal_id, people, words.denied_again(answerer, record, dispute.proof, owed, others))
            self.s._note(event.deal_id, f"the {event.confirmed_by.value} said no again to the {_claim(record)}, "
                         f"after the {dispute.proof.lower()}: still disputed, not counted", mine)
            return
        dispute = self.open[record.id] = Dispute(event.deal_id, record)
        paid = [(f.value_rupees, self._how(f)) for f in payments if f.status in COUNTED]
        self._both(event.deal_id, people, words.denied(answerer, record, paid, owed, others))
        self.s._note(event.deal_id, f"the {event.confirmed_by.value} said no to the {_claim(record)}: not counted"
                     + (f", {words.rupees(total.owed_rupees)} owed" if total and total.owed_rupees is not None else ""), mine)
        await self._quote(event.deal_id, record, people)
        if record.kind in MONEY and claimer.phone:
            self.s.outbox.send(event.deal_id, claimer.phone, claimer.role, words.proof_ask(record, answerer))
            dispute.proof_asked = True
            self.s._note(event.deal_id, f"asked the {claimer.role.value} once for proof of the {_claim(record)}", mine)

    # ---------- the record, quoted ----------

    async def _quote(self, deal_id: str, record: Record, people: dict[Role, Person]) -> None:
        """What the record holds about the claim, to both: the term it counts towards and
        what either person said about it, newest first, each with its clip."""
        terms = await self._terms(deal_id, record)
        item = terms[0].item if terms else _item(record)
        figure = words.rupees(round(record.amount)) if record.amount is not None else ""
        query = " ".join(filter(None, [words.term_name(item), figure, _plain(record.amount), record.text]))
        used = {t.id for t in terms}
        said = [
            f for f in await self.s.memory.search(deal_id, query, k=8)
            if f.id not in used and f.record_id != record.id and f.kind not in (FactKind.TERM, FactKind.PAYMENT, FactKind.WORK)
            and f.status is not FactStatus.SUPERSEDED and f.quote and f.said_by
            and (_mentions(f.quote, record.amount) or (words.is_promise(f.quote) and f.item in (item, ItemKey.AMOUNT, None)))
        ]
        chosen = sorted(terms + said, key=lambda f: f.valid_from.timestamp() if f.valid_from else 0, reverse=True)[:QUOTED]
        if not chosen:
            return
        name = lambda role: words.who(people.get(role) or Person(role=role)) if role else None  # noqa: E731
        lines, first_clip = [], None
        for fact in chosen:
            clip = await self.s._clip(fact)
            first_clip = first_clip or clip
            if fact.id in used:
                yes = next((r for r in [*fact.agreed_by, *fact.confirmed_by] if r != fact.said_by), None)
                shown = words.rupees(fact.value_rupees) if fact.value_rupees is not None else None
                lines.append(words.quote_term(fact.item, shown, self.s.when(fact), name(fact.said_by), name(yes), fact.quote, clip))
            else:
                lines.append(words.quote_said(name(fact.said_by), fact.quote, self.s.when(fact), clip))
        about = "Kaam" if record.kind is RecordKind.WORK_DONE else f"Is {words.payment_kind(record.kind)}"
        text = words.quoted(about, lines)
        for person in people.values():
            self.s.outbox.send(deal_id, person.phone, person.role, text, link=first_clip, link_label=words.CLIP_BUTTON)
        kinds = ", ".join(("the agreed " + f.item.value) if f.id in used else
                          ("a promise" if words.is_promise(f.quote) else "a line said") for f in chosen)
        self.s._note(deal_id, f"quoted the record to both: {kinds}", facts=chosen)

    async def _terms(self, deal_id: str, record: Record) -> list[Fact]:
        """The term the claim counts towards, as it stands; the whole amount too when that
        term has no figure; for work, when it is due."""
        first = _item(record)
        also = {ItemKey.ADVANCE: [ItemKey.AMOUNT], ItemKey.BALANCE: [ItemKey.AMOUNT], ItemKey.WORK: [ItemKey.DATES]}[first]
        found = []
        for item in [first, *also]:
            term = (await self.s.memory.get_term(deal_id, item)).current
            if term and (item is first or not found or found[0].value_rupees is None or first is ItemKey.WORK):
                found.append(term)
        return found

    # ---------- proof ----------

    async def proof(
        self, deal: Deal, sender: Person, reading: Reading, image: bytes | None, image_type: str | None,
        media_url: str | None,
    ) -> Record | None:
        """A message from someone asked for proof. The disputed record, now with its proof,
        when it is proof of that claim; None when it is not (the message goes on as usual)."""
        dispute = next((d for d in self.open.values() if d.deal_id == deal.id and d.record.sender is sender.role
                        and d.proof_asked and d.proof is None), None)
        if dispute is None or not reading.transaction_id and not (image and reading.payment_screenshot):
            return None
        record = dispute.record
        same = reading.amount is None and not image or (
            reading.amount is not None and record.amount is not None and round(reading.amount) == round(record.amount))
        if image and not (reading.payment_screenshot and reading.transaction_id and same):
            self.s.outbox.send(deal.id, sender.phone, sender.role,
                               words.proof_mismatch(record, reading.amount, bool(reading.transaction_id)))
            self.s._note(deal.id, f"a screenshot came for the disputed {_claim(record)} and does not match it: "
                         "still disputed")
            # The same amount with no transaction id is this proof, failed; another amount is its own payment.
            return record if same else None
        if not same:
            return None
        other = deal.person(sender.role.other)
        if other is None or not other.phone or self.s.ask_again is None:
            return None
        dispute.proof = "Screenshot" if image else "UPI reference"
        link = None
        if image:
            link = await self.s.keep_proof(deal.id, record.id, image, image_type) if self.s.keep_proof else None
            link = link or media_url
        record = dispute.record = record.model_copy(update={
            "backing": Backing.BACKED if image else record.backing, "transaction_id": reading.transaction_id,
            "media_url": record.media_url or media_url, "confirmed": None,
            "extra": record.extra | {"proof": {"kind": dispute.proof.lower(), "transaction_id": reading.transaction_id,
                                               "media_url": media_url}},
        })
        if link and self.s.outbox.rich:
            self.s.outbox.send(deal.id, other.phone, other.role, words.proof_caption(sender), link, image_type or "image/png")
        elif link:
            self.s.outbox.send(deal.id, other.phone, other.role, words.proof_link(sender, link),
                               link=link, link_label=words.PROOF_BUTTON)
        self.s.ask_again(deal.id, record, sender, other, words.proof_question(sender, record, image is not None))
        self.s.outbox.send(deal.id, sender.phone, sender.role, words.proof_taken(other))
        self.s._note(deal.id, f"{dispute.proof.lower()} {reading.transaction_id} sent for the disputed {_claim(record)}: "
                     f"it matches, the {other.role.value} is asked again")
        return record

    # ---------- what the record holds ----------

    async def _latest(self, deal_id: str) -> list[Fact]:
        latest: dict[str, Fact] = {}
        for event in await self.s.store.events(deal_id, "fact.recorded"):
            latest[event.fact.id] = event.fact
        return list(latest.values())

    async def payments(self, deal_id: str, denied: str | None = None) -> list[Fact]:
        """Every payment fact as it stands, oldest first; the one just denied as disputed,
        whether or not memory has marked it yet."""
        found = []
        for fact in await self._latest(deal_id):
            if fact.kind is not FactKind.PAYMENT or not fact.value_rupees or fact.status is FactStatus.SUPERSEDED:
                continue
            if denied and fact.record_id == denied:
                fact = fact.model_copy(update={"status": FactStatus.DISPUTED})
            found.append(fact)
        return found

    async def still_disputed(self, deal_id: str, items: set[ItemKey] | None = None, skip: str | None = None) -> str:
        """What stays disputed, said under an owed message or a reminder: payments (towards
        these terms, or any), and a work claim denied when no work claim was confirmed after it."""
        facts = [f for f in await self._latest(deal_id) if f.record_id and f.record_id != skip]
        amounts = [
            f.value_rupees for f in facts if f.kind is FactKind.PAYMENT and f.value_rupees
            and f.status is FactStatus.DISPUTED and (items is None or f.item in items)
        ]
        work = [f.status for f in facts if f.kind is FactKind.WORK]
        denied = items is None and FactStatus.DISPUTED in work and FactStatus.CONFIRMED not in work[work.index(FactStatus.DISPUTED):]
        return words.still_disputed(amounts, denied and deal_id not in self.s._work_done)

    def _how(self, fact: Fact) -> str:
        on = words.day(fact.valid_from.astimezone(IST).date()) if fact.valid_from else None
        if fact.status is FactStatus.SAID:
            how = "abhi confirm nahi hua"
        elif fact.confirmed_by and fact.said_by and any(r != fact.said_by for r in fact.confirmed_by):
            how = "dono ne confirm kiya"
        else:
            how = "screenshot se pakka" if fact.media_url else "record mein pakka"
        kind = "advance" if fact.item is ItemKey.ADVANCE else "payment"
        return ", ".join(filter(None, [kind, on, how]))

    def _both(self, deal_id: str, people: dict[Role, Person], text: str) -> None:
        for person in people.values():
            self.s.outbox.send(deal_id, person.phone, person.role, text)


COUNTED = (FactStatus.SAID, FactStatus.AGREED, FactStatus.CONFIRMED)


def _item(record: Record) -> ItemKey:
    return {RecordKind.ADVANCE: ItemKey.ADVANCE, RecordKind.WORK_DONE: ItemKey.WORK}.get(record.kind, ItemKey.BALANCE)


def _claim(record: Record) -> str:
    if record.kind is RecordKind.WORK_DONE:
        return f"{record.sender.value}'s work-done claim"
    amount = f"{words.rupees(round(record.amount))} " if record.amount is not None else ""
    return f"{record.sender.value}'s {amount}{record.kind.value} claim"


def _plain(amount: float | None) -> str | None:
    return None if amount is None else str(round(amount))


def _mentions(said: str, amount: float | None) -> bool:
    """The words name this amount: 2000, 2,000, or 2 hazaar."""
    if amount is None:
        return False
    rupees = round(amount)
    figures = {str(rupees), f"{rupees:,}"}
    if rupees % 1000 == 0:
        figures.add(f"{rupees // 1000} hazaar")
    return any(re.search(rf"(?<![\d,]){re.escape(f)}(?![\d,])", said.lower()) for f in figures)


def _without(rows: dict[ItemKey, OwedRow], fact: Fact | None) -> dict[ItemKey, OwedRow]:
    """The rows once the denied payment no longer counts, if memory still counts it."""
    if fact is None or not fact.value_rupees:
        return rows
    paid = fact.value_rupees
    return {
        item: row.model_copy(update={
            "paid_rupees": row.paid_rupees - paid, "payment_fact_ids": [i for i in row.payment_fact_ids if i != fact.id],
            "owed_rupees": None if row.owed_rupees is None else row.owed_rupees + paid,
        }) if fact.id in row.payment_fact_ids else row
        for item, row in rows.items()
    }


def total_row(rows: dict[ItemKey, OwedRow]) -> OwedRow | None:
    """The whole deal: the amount if one is agreed, else the balance."""
    for item in (ItemKey.AMOUNT, ItemKey.BALANCE):
        row = rows.get(item)
        if row and row.owed_rupees is not None:
            return row
    return None

