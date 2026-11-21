"""Status moved forward by events that already exist. No model: these are instant.

checklist.updated   a term the brain heard agreed: a said fact becomes agreed
terms.confirmed     confirmed on the call-back
terms.disputed      disputed on the call-back
record.received     a payment or work record from WhatsApp, linked to the term it counts towards
record.confirmed    the other person's yes or no to that record
fact.changed        an amendment both confirmed: a new fact that replaces the old one
"""

import logging

from app.contracts import (
    Backing, ChangeStatus, ChecklistUpdated, Fact, FactChanged, FactKind, FactSource, FactStatus, ItemKey,
    ItemState, Record, RecordConfirmed, RecordKind, RecordReceived, Role, TermsConfirmed, TermsDisputed,
)
from app.memory.dates import pin_date
from app.memory.normalise import format_rupees, one_amount

log = logging.getLogger("gawah.memory")

_RECORD_KIND = {
    RecordKind.ADVANCE: (FactKind.PAYMENT, ItemKey.ADVANCE),
    RecordKind.PAYMENT: (FactKind.PAYMENT, ItemKey.BALANCE),
    RecordKind.WORK_DAY: (FactKind.WORK, ItemKey.WORK),
    RecordKind.MILESTONE: (FactKind.WORK, ItemKey.WORK),
    RecordKind.WORK_DONE: (FactKind.WORK, ItemKey.WORK),
    RecordKind.OTHER: (FactKind.OTHER, None),
}


class Status:
    def __init__(self, memory) -> None:
        self.m = memory

    async def on_checklist(self, event: ChecklistUpdated) -> None:
        await self.m.scribe.settle()
        deal = self.m.book.deal(event.deal_id)
        call_no = deal.last_call_no
        for item in event.items:
            if item.state != ItemState.AGREED or (event.changed and item.key not in event.changed):
                continue
            if deal.current(item.key):
                continue  # agreed already; a different figure is the scribe's conflict to raise
            rupees = one_amount(item.value)
            said = [
                f for f in deal.standing()
                if f.item == item.key and f.kind == FactKind.TERM and f.status == FactStatus.SAID and f.call_no == call_no
            ]
            match = [f for f in said if rupees is not None and f.value_rupees == rupees] or [
                f for f in said if item.line_no is not None and f.line_no == item.line_no
            ]
            line = deal.lines.get((call_no, item.line_no or -1))
            if match:
                fact = match[-1]
                yes = (line.speaker if line and line.speaker != fact.said_by else None) or (fact.said_by.other if fact.said_by else None)
                self.m.record(fact.model_copy(update={
                    "status": FactStatus.AGREED, "agreed_by": [yes] if yes else fact.agreed_by,
                }))
                self.m.note("memory", f"{item.key.value} agreed, as the judge heard it", fact)
            elif item.source_text and item.value:
                fact = self.m.record(Fact(
                    deal_id=event.deal_id, text=f"The {item.key.value.replace('_', ' ')} is {item.value}.",
                    item=item.key, kind=FactKind.TERM, value=item.value, value_rupees=rupees,
                    value_date=pin_date(item.source_text, deal.call_date(call_no), None),
                    said_by=line.speaker if line else None, agreed_by=[line.speaker.other] if line else [],
                    status=FactStatus.AGREED, quote=item.source_text, call_no=call_no, line_no=item.line_no,
                    start=line.start if line else None, end=line.end if line else None,
                    valid_from=deal.at(call_no, line.start) if line else event.ts,
                ))
                self.m.note("memory", f"{item.key.value} agreed: {item.value}", fact)

    async def on_confirmed(self, event: TermsConfirmed) -> None:
        await self.m.scribe.settle()
        deal = self.m.book.deal(event.deal_id)
        for key in [event.item] if event.item else list(ItemKey):
            current = deal.current(key)
            if current is None:
                if event.item and event.value:
                    self._from_callback(event, key, FactStatus.CONFIRMED)
                continue
            if event.person in current.confirmed_by and current.status == FactStatus.CONFIRMED:
                continue
            fact = self.m.record(current.model_copy(update={
                "status": FactStatus.CONFIRMED, "confirmed_by": sorted({*current.confirmed_by, event.person}),
            }))
            self.m.note("memory", f"{key.value} confirmed by {deal.name(event.person)}", fact)

    async def on_disputed(self, event: TermsDisputed) -> None:
        await self.m.scribe.settle()
        deal = self.m.book.deal(event.deal_id)
        for key in [event.item] if event.item else list(ItemKey):
            current = deal.current(key)
            if current is not None:
                fact = self.m.record(current.model_copy(update={"status": FactStatus.DISPUTED}))
                self.m.note("memory", f"{key.value} disputed by {deal.name(event.person)}", fact)

    def _from_callback(self, event: TermsConfirmed, key: ItemKey, status: FactStatus) -> None:
        deal = self.m.book.deal(event.deal_id)
        quote = event.said or event.value
        self.m.record(Fact(
            deal_id=event.deal_id, text=f"The {key.value.replace('_', ' ')} is {event.value}.", item=key,
            kind=FactKind.TERM, value=event.value, value_rupees=one_amount(event.value),
            said_by=event.person, confirmed_by=[event.person], status=status, source=FactSource.CALLBACK,
            quote=quote, call_no=deal.last_call_no, valid_from=event.ts,
        ))

    async def on_record(self, event: RecordReceived) -> None:
        self._record_fact(event.deal_id, event.record, event.ts)

    def _record_fact(self, deal_id: str, record: Record, ts) -> Fact | None:
        deal = self.m.book.deal(deal_id)
        if deal.by_record(record.id):
            return deal.by_record(record.id)
        kind, item = _RECORD_KIND[record.kind]
        rupees = round(record.amount) if record.amount is not None else None
        if kind == FactKind.PAYMENT and rupees is None:
            kind, item = FactKind.OTHER, None
        quote = record.text or ("screenshot" if record.media_url else None)
        if not quote:
            return None
        backed = record.backing == Backing.BACKED or record.confirmed is True
        who = deal.name(record.sender)
        proof = " (screenshot sent)" if record.media_url else ""
        if kind == FactKind.PAYMENT:
            text = f"{who} paid {format_rupees(rupees)} towards the {item.value}{proof}."
        elif kind == FactKind.WORK:
            text = f"{who} reported work: {record.text or record.kind.value}{proof}."
        else:
            text = f"{who} sent: {record.text or 'a screenshot'}{proof}."
        target = self.m.target_for(deal, kind, item)
        fact = self.m.record(Fact(
            deal_id=deal_id, text=text, item=item, kind=kind, value=format_rupees(rupees) if rupees is not None else record.text,
            value_rupees=rupees, said_by=record.sender, confirmed_by=[record.sender.other] if record.confirmed else [],
            status=FactStatus.CONFIRMED if backed else FactStatus.SAID,
            source=FactSource.SCREENSHOT if record.media_url else FactSource.TEXT, quote=quote,
            record_id=record.id, media_url=record.media_url, valid_from=ts,
            counts_towards=target.id if target and kind != FactKind.OTHER else None,
        ))
        towards = f", counted towards {target.item.value}" if target and target.item else ""
        self.m.note("memory", f"record: {fact.value or kind.value}{towards}", fact)
        return fact

    async def on_record_confirmed(self, event: RecordConfirmed) -> None:
        deal = self.m.book.deal(event.deal_id)
        fact = deal.by_record(event.record_id)
        if fact is None and event.record:
            fact = self._record_fact(event.deal_id, event.record.model_copy(update={"confirmed": None}), event.ts)
        if fact is None:
            return
        update = (
            {"status": FactStatus.CONFIRMED, "confirmed_by": sorted({*fact.confirmed_by, event.confirmed_by})}
            if event.confirmed else {"status": FactStatus.DISPUTED}
        )
        fact = self.m.record(fact.model_copy(update=update))
        self.m.note("memory", f"record {'confirmed' if event.confirmed else 'denied'} by {deal.name(event.confirmed_by)}", fact)

    async def on_changed(self, event: FactChanged) -> None:
        if event.status != ChangeStatus.CONFIRMED_BOTH:
            return
        await self.m.scribe.settle()
        deal = self.m.book.deal(event.deal_id)
        old = deal.latest.get(event.fact_id)
        if old is None:
            log.warning("deal=%s fact.changed for unknown fact %s", event.deal_id, event.fact_id)
            return
        item = event.item or old.item
        rupees = one_amount(event.new_value)
        new = self.m.record(Fact(
            deal_id=event.deal_id, text=f"The {item.value.replace('_', ' ') if item else 'term'} is now {event.new_value}.",
            item=item, kind=old.kind, value=event.new_value, value_rupees=rupees,
            value_date=pin_date(event.new_value, deal.call_date(deal.last_call_no), None),
            said_by=event.proposed_by, agreed_by=[r for r in Role if r != event.proposed_by],
            confirmed_by=sorted(event.confirmed_by or list(Role)), status=FactStatus.CONFIRMED,
            quote=event.said or event.new_value, call_no=deal.last_call_no, valid_from=event.ts, replaces=old.id,
        ))
        self.m.record(old.model_copy(update={"status": FactStatus.SUPERSEDED, "superseded_at": event.ts}))
        self.m.note("memory", f"{item.value if item else 'term'} changed to {event.new_value}, confirmed by both", new)
