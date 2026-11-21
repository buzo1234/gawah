"""Record intake. A message from a person with an open deal comes here.

Backed means a payment screenshot with a transaction id: it is logged and nobody is
asked. Everything else is one person's word, so the other person is asked yes or no,
and reply.timeout is raised once if they do not answer in time."""

import asyncio
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.bus import Bus
from app.contracts import (
    Backing, Deal, Person, Record, RecordConfirmed, RecordConfirmRequested, RecordKind,
    RecordReceived, ReplyTimeout, Role,
)
from app.log import deal_log, mask_phone
from app.records import words
from app.records.reader import Reader

if TYPE_CHECKING:  # app.whatsapp imports this package, never the other way round
    from app.whatsapp.clock import Clock
    from app.whatsapp.outbox import Outbox

_YES = {"haan", "han", "haa", "ha", "hanji", "haanji", "ji", "yes", "y", "sahi", "theek", "thik",
        "ok", "okay", "bilkul", "mila", "mil", "हाँ", "हां", "सही", "ठीक"}
_NO = {"nahi", "nahin", "nhi", "nai", "na", "no", "n", "galat", "jhooth", "नहीं", "नही", "गलत"}


def yes_or_no(text: str) -> bool | None:
    """True for yes, False for no, None when the message is not a short yes or no."""
    said = re.sub(r"[.,!?;:'\"()।-]", " ", text.lower()).split()
    if not said or len(said) > 4:
        return None
    if _NO.intersection(said):
        return False
    return True if _YES.intersection(said) else None


@dataclass
class Ask:
    """A question put to one person about the other person's record, not yet answered."""

    deal_id: str
    record: Record
    sender: Person
    answerer: Person
    question: str
    timer: asyncio.Task | None = None


class Intake:
    def __init__(
        self, bus: Bus, outbox: "Outbox", reader: Reader, clock: "Clock", timeout_seconds: float
    ) -> None:
        self.bus, self.outbox, self.reader, self.clock = bus, outbox, reader, clock
        self.timeout_seconds = timeout_seconds
        self._asks: dict[str, list[Ask]] = {}  # the answerer's phone -> their open questions, oldest first

    async def take(
        self, deal: Deal, sender: Person, text: str, media_url: str | None = None,
        image: bytes | None = None, image_type: str | None = None,
    ) -> bool:
        """Log one message as a record. False if it is not a record at all. Raises if the
        message could not be read."""
        reading = await self.reader.read(text, image, image_type)
        if reading.kind == "unclear":
            return False
        backed = bool(image and reading.payment_screenshot and reading.transaction_id)
        kind = RecordKind(reading.kind)
        if backed and kind not in (RecordKind.ADVANCE, RecordKind.PAYMENT):
            kind = RecordKind.PAYMENT
        record = Record(
            sender=sender.role, kind=kind, backing=Backing.BACKED if backed else Backing.UNBACKED,
            text=text or None, media_url=media_url, amount=reading.amount, date=reading.date,
            transaction_id=reading.transaction_id,
        )
        deal_log("gawah.records", deal.id).info(
            "record %s from %s: %s, %s", record.id, mask_phone(sender.phone), record.kind.value, record.backing.value
        )
        self.bus.publish(RecordReceived(deal_id=deal.id, record=record))
        other = deal.person(sender.role.other)
        if backed or other is None or not other.phone:
            self.outbox.send(deal.id, sender.phone, sender.role, words.logged(record))
            return True

        question = words.confirm_question(sender, record)
        self.bus.publish(
            RecordConfirmRequested(
                deal_id=deal.id, record_id=record.id, confirm_by=other.role, record=record, question=question
            )
        )
        self.outbox.send(deal.id, other.phone, other.role, question)
        self.outbox.send(deal.id, sender.phone, sender.role, words.asking_other(other))
        ask = Ask(deal.id, record, sender, other, question)
        ask.timer = asyncio.create_task(self._wait(ask))
        self._asks.setdefault(other.phone, []).append(ask)
        return True

    def answer(self, phone: str, text: str) -> bool:
        """Take a yes or no as the answer to this person's oldest open question.
        False if they have no open question or the message is not a yes or no."""
        asks = self._asks.get(phone)
        confirmed = yes_or_no(text) if asks else None
        if confirmed is None:
            return False
        ask = asks.pop(0)
        ask.timer.cancel()
        ask.record.confirmed = confirmed
        self.bus.publish(
            RecordConfirmed(
                deal_id=ask.deal_id, record_id=ask.record.id, confirmed_by=ask.answerer.role,
                confirmed=confirmed, record=ask.record,
            )
        )
        self.outbox.send(
            ask.deal_id, ask.sender.phone, ask.sender.role,
            words.answer_for_sender(ask.answerer, ask.record, confirmed),
        )
        self.outbox.send(ask.deal_id, ask.answerer.phone, ask.answerer.role, words.ANSWER_NOTED)
        return True

    async def _wait(self, ask: Ask) -> None:
        await self.clock.sleep(self.timeout_seconds)
        # The question stays open after this: a late yes or no still counts.
        self.bus.publish(
            ReplyTimeout(
                deal_id=ask.deal_id, person=ask.answerer.role, ask=ask.question,
                record_id=ask.record.id, waited_seconds=self.timeout_seconds,
            )
        )

    async def close(self) -> None:
        timers = [ask.timer for asks in self._asks.values() for ask in asks]
        for timer in timers:
            timer.cancel()
        await asyncio.gather(*timers, return_exceptions=True)
