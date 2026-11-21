"""Record intake. A message from a person with an open deal comes here.

Backed means a payment screenshot with a transaction id: it is logged and nobody is
asked. Everything else is one person's word, so the other person is asked yes or no,
and reply.timeout is raised once if they do not answer in time.

A voice note is a record only when it says money was paid or work was done; those are
always one person's word. Anything else it says is memory's to read (the Scribe). A change
to an agreed term asked for in a voice note is put to the other person here too, as
fact.changed: their yes makes it hold, their no withdraws it."""

import asyncio
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from app.bus import Bus
from app.contracts import (
    Backing, ChangeStatus, Deal, FactChanged, Person, Record, RecordConfirmed, RecordConfirmRequested, RecordKind,
    RecordReceived, ReplyTimeout, Role, new_id,
)
from app.log import deal_log, mask_phone
from app.records import words
from app.records.reader import Reader

if TYPE_CHECKING:  # app.whatsapp imports this package, never the other way round
    from app.records.sentinel import Sentinel
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


VOICE_KINDS = {"advance", "payment", "work_done"}  # what a voice note can be as a record


def buttons_for(asked_id: str) -> tuple[tuple[str, str], ...]:
    """The yes and no buttons under a question. Each id names the record (or the change), so
    a tap answers that question even when the person has more than one open."""
    return (f"yes:{asked_id}", words.YES_BUTTON), (f"no:{asked_id}", words.NO_BUTTON)


def read_button(button: str | None) -> tuple[bool, str] | None:
    """(yes or no, record id) for a tapped yes or no button; None for anything else."""
    said, _, record_id = (button or "").partition(":")
    return (said == "yes", record_id) if said in ("yes", "no") and record_id else None


@dataclass
class Ask:
    """A question put to one person about the other person's record, or a change they asked
    for, not yet answered."""

    deal_id: str
    record: Record | None
    sender: Person
    answerer: Person
    question: str
    message_id: str | None = None  # the provider's id of the sender's message, to react to
    timer: asyncio.Task | None = None
    change: FactChanged | None = None

    @property
    def id(self) -> str:
        return self.change.change_id if self.change else self.record.id


class Intake:
    def __init__(
        self, bus: Bus, outbox: "Outbox", reader: Reader, clock: "Clock", timeout_seconds: float,
        sentinel: "Sentinel | None" = None,
    ) -> None:
        self.bus, self.outbox, self.reader, self.clock = bus, outbox, reader, clock
        self.sentinel = sentinel  # checks records against the deal; None when there is no memory
        self.timeout_seconds = timeout_seconds
        self._asks: dict[str, list[Ask]] = {}  # the answerer's phone -> their open questions, oldest first

    async def take(
        self, deal: Deal, sender: Person, text: str, media_url: str | None = None,
        image: bytes | None = None, image_type: str | None = None, message_id: str | None = None,
        voice: dict | None = None,
    ) -> Record | None:
        """Log one message as a record and return it. None if it is not a record at all.
        Raises if the message could not be read. message_id is the provider's id of the
        message, so Gawah can react to it where the provider has reactions. voice: for a
        voice note, what is known of it (kept on the record as extra); text is its words."""
        reading = await self.reader.read(text, image, image_type)
        if reading.kind == "unclear" or (voice is not None and reading.kind not in VOICE_KINDS):
            return None
        backed = bool(image and reading.payment_screenshot and reading.transaction_id)
        kind = RecordKind(reading.kind)
        if backed and kind not in (RecordKind.ADVANCE, RecordKind.PAYMENT):
            kind = RecordKind.PAYMENT
        record = Record(
            sender=sender.role, kind=kind, backing=Backing.BACKED if backed else Backing.UNBACKED,
            text=text or None, media_url=media_url, amount=reading.amount, date=reading.date,
            transaction_id=reading.transaction_id, extra={"voice_note": voice} if voice is not None else {},
        )
        deal_log("gawah.records", deal.id).info(
            "record %s from %s: %s, %s", record.id, mask_phone(sender.phone), record.kind.value, record.backing.value
        )
        check = await self.sentinel.check(deal.id, record) if self.sentinel else None
        self.bus.publish(RecordReceived(deal_id=deal.id, record=record))
        other = deal.person(sender.role.other)
        if backed or other is None or not other.phone:
            if backed:
                self.outbox.react(deal.id, sender.phone, sender.role, message_id, "✅")
            self.outbox.send(deal.id, sender.phone, sender.role, words.logged(record))
            if check:
                await self.sentinel.logged(deal.id, record, check)
            return record

        question = words.confirm_question(sender, record)
        self.bus.publish(
            RecordConfirmRequested(
                deal_id=deal.id, record_id=record.id, confirm_by=other.role, record=record, question=question
            )
        )
        if check and check.line:
            await self.sentinel.disagrees(deal.id, record, check, other.role)
        self.outbox.send(deal.id, other.phone, other.role, question, buttons=buttons_for(record.id))
        self.outbox.send(deal.id, sender.phone, sender.role, words.asking_other(other, record))
        ask = Ask(deal.id, record, sender, other, question, message_id)
        ask.timer = asyncio.create_task(self._wait(ask))
        self._asks.setdefault(other.phone, []).append(ask)
        return record

    def ask_change(self, change: FactChanged, sender: Person, answerer: Person, question: str) -> None:
        """Put a change one person asked for to the other, yes or no. The change is sent as
        fact.changed now, with the asker's yes; the answer sends its next step. No timer:
        the call-back confirms terms, not a change still being asked."""
        self.bus.publish(change)
        self.outbox.send(change.deal_id, answerer.phone, answerer.role, question, buttons=buttons_for(change.change_id))
        self.outbox.send(change.deal_id, sender.phone, sender.role, words.change_asked(answerer))
        self._asks.setdefault(answerer.phone, []).append(Ask(change.deal_id, None, sender, answerer, question, change=change))

    def answer(self, phone: str, text: str, name: str | None = None, button: str | None = None) -> bool:
        """Take a yes or no as the answer to this person's oldest open question, or a tapped
        yes or no button as the answer to its own question. False if there is no such open
        question or the message is not a yes or no."""
        asks = self._asks.get(phone) or []
        tapped = read_button(button)
        if tapped:
            confirmed, record_id = tapped
            ask = next((a for a in asks if a.id == record_id), None)
        else:
            confirmed = yes_or_no(text) if asks else None
            ask = asks[0] if confirmed is not None else None
        if ask is None:
            return False
        asks.remove(ask)
        if ask.timer:
            ask.timer.cancel()
        ask.answerer.name = ask.answerer.name or name
        if ask.change:
            self._answer_change(ask, confirmed, text)
            return True
        # A copy: the record inside the events already published must stay as it was sent.
        record = ask.record.model_copy(update={"confirmed": confirmed})
        self.bus.publish(
            RecordConfirmed(
                deal_id=ask.deal_id, record_id=record.id, confirmed_by=ask.answerer.role,
                confirmed=confirmed, record=record,
            )
        )
        self._tell_sender(ask, record, confirmed)
        self.outbox.send(ask.deal_id, ask.answerer.phone, ask.answerer.role, words.ANSWER_NOTED)
        return True

    def _answer_change(self, ask: Ask, confirmed: bool, said: str) -> None:
        change = ask.change
        self.bus.publish(change.model_copy(update={
            "event_id": new_id(), "ts": datetime.now(UTC), "said": said or None,
            "status": ChangeStatus.CONFIRMED_BOTH if confirmed else ChangeStatus.WITHDRAWN,
            "confirmed_by": sorted({*change.confirmed_by, ask.answerer.role}, key=list(Role).index)
            if confirmed else change.confirmed_by,
        }))
        self.outbox.send(ask.deal_id, ask.sender.phone, ask.sender.role,
                         words.change_answered(ask.answerer, change.item, change.new_value, confirmed))
        self.outbox.send(ask.deal_id, ask.answerer.phone, ask.answerer.role, words.ANSWER_NOTED)

    def _tell_sender(self, ask: Ask, record: Record, confirmed: bool) -> None:
        if confirmed:
            self.outbox.react(ask.deal_id, ask.sender.phone, ask.sender.role, ask.message_id, "👍")
        self.outbox.send(
            ask.deal_id, ask.sender.phone, ask.sender.role, words.answer_for_sender(ask.answerer, record, confirmed)
        )

    async def on_confirmed(self, event: RecordConfirmed) -> None:
        """An answer given somewhere else (the call-back): close the question and tell the
        sender, as a yes or no on WhatsApp does. An answer taken here has already closed it."""
        for asks in self._asks.values():
            ask = next((a for a in asks if a.deal_id == event.deal_id and a.record and a.id == event.record_id), None)
            if ask:
                asks.remove(ask)
                ask.timer.cancel()
                record = ask.record.model_copy(update={"confirmed": event.confirmed})
                self._tell_sender(ask, record, event.confirmed)
                return

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
        timers = [ask.timer for asks in self._asks.values() for ask in asks if ask.timer]
        for timer in timers:
            timer.cancel()
        await asyncio.gather(*timers, return_exceptions=True)
