"""Fake WhatsApp: publishes what the whatsapp stream would publish. Sends no messages."""

from typing import Any

from app.bus import Bus
from app.contracts import (
    Backing, DealRequested, Person, Record, RecordConfirmed, RecordConfirmRequested,
    RecordKind, RecordReceived, ReplyTimeout, Role, new_id,
)
from fakes import RAMESH, SUNITA


def request_deal(
    bus: Bus, requested_by: Person = SUNITA, other_phone: str | None = RAMESH.phone,
    deal_id: str | None = None,
) -> DealRequested:
    event = DealRequested(
        deal_id=deal_id or new_id(),
        requested_by=requested_by,
        other=Person(role=requested_by.role.other, phone=other_phone),
        text=f"Deal with {other_phone}",
    )
    bus.publish(event)
    return event


def send_record(
    bus: Bus, deal_id: str, sender: Role, text: str | None = None,
    kind: RecordKind = RecordKind.PAYMENT, backing: Backing = Backing.UNBACKED, **fields: Any,
) -> RecordReceived:
    """fields are Record fields: amount, date, transaction_id, media_url, extra."""
    event = RecordReceived(
        deal_id=deal_id, record=Record(sender=sender, kind=kind, backing=backing, text=text, **fields)
    )
    bus.publish(event)
    return event


def ask_to_confirm(bus: Bus, deal_id: str, record: Record, question: str | None = None) -> RecordConfirmRequested:
    event = RecordConfirmRequested(
        deal_id=deal_id, record_id=record.id, record=record, confirm_by=record.sender.other, question=question
    )
    bus.publish(event)
    return event


def confirm_record(
    bus: Bus, deal_id: str, record_id: str, confirmed_by: Role, confirmed: bool = True
) -> RecordConfirmed:
    event = RecordConfirmed(deal_id=deal_id, record_id=record_id, confirmed_by=confirmed_by, confirmed=confirmed)
    bus.publish(event)
    return event


def reply_timed_out(
    bus: Bus, deal_id: str, person: Role, ask: str, record_id: str | None = None, waited_seconds: float = 120
) -> ReplyTimeout:
    event = ReplyTimeout(deal_id=deal_id, person=person, ask=ask, record_id=record_id, waited_seconds=waited_seconds)
    bus.publish(event)
    return event
