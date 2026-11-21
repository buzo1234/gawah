"""The bot. Decides what each inbound message is - an answer, a new deal, a record, or
something it cannot use - and sends the links and the contract when other streams'
events call for them."""

import asyncio
import logging
import mimetypes
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from urllib.parse import urlsplit

from app.bus import Bus
from app.config import Settings
from app.contracts import (
    NO_DEAL, CallEnded, CallKind, ContractReady, Deal, DealRequested, Direction, Person,
    ReplyTimeout, Role, WhatsAppMessage, call_path, callback_path, new_id,
)
from app.log import deal_log, mask_phone
from app.records.intake import Intake
from app.store import Store
from app.whatsapp import phone, words
from app.whatsapp.outbox import Outbox
from app.whatsapp.twilio import Twilio

LOCAL_BASE_URL = "http://localhost:8000"  # used for links until PUBLIC_BASE_URL is set


@dataclass
class Inbound:
    phone: str
    text: str = ""
    media_url: str | None = None
    media_type: str | None = None
    name: str | None = None  # the person's WhatsApp profile name
    sid: str | None = None


def parse_inbound(form: dict[str, str]) -> Inbound | None:
    """The fields Twilio posts for an inbound WhatsApp message. None if there is no sender."""
    # An unescaped + in a form body decodes to a space, so put it back.
    digits = form.get("From", "").removeprefix("whatsapp:").strip().lstrip("+")
    if not digits.isdigit():
        return None
    has_media = (form.get("NumMedia") or "0") != "0" and form.get("MediaUrl0")
    return Inbound(
        phone=f"+{digits}",
        text=form.get("Body", "").strip(),
        media_url=form["MediaUrl0"] if has_media else None,
        media_type=form.get("MediaContentType0") if has_media else None,
        name=form.get("ProfileName") or None,
        sid=form.get("MessageSid") or None,
    )


class Bot:
    def __init__(
        self, settings: Settings, bus: Bus, store: Store, twilio: Twilio, outbox: Outbox,
        intake: Intake, sign: Callable[[str], Awaitable[str]],
    ) -> None:
        self.settings, self.bus, self.store = settings, bus, store
        self.twilio, self.outbox, self.intake = twilio, outbox, intake
        self._sign = sign  # S3 key -> short-lived link
        self._inbox: asyncio.Queue[Inbound] = asyncio.Queue()
        self._worker: asyncio.Task | None = None
        self._followed_up: set[tuple[str, str | None]] = set()

    # ---------- inbound ----------

    def receive(self, message: Inbound) -> None:
        """Queue a message and return at once, so the webhook answers Twilio straight away.
        Messages are handled one at a time, in the order they arrived."""
        self._inbox.put_nowait(message)

    async def start(self) -> None:
        self._worker = asyncio.create_task(self._work())

    async def stop(self) -> None:
        if self._worker:
            self._worker.cancel()
            await asyncio.gather(self._worker, return_exceptions=True)
        await self.intake.close()
        await self.outbox.close()

    async def idle(self) -> None:
        """Wait until every queued inbound message has been handled. For tests."""
        await self._inbox.join()

    async def _work(self) -> None:
        while True:
            message = await self._inbox.get()
            try:
                await self.on_message(message)
            except Exception:
                logging.getLogger("gawah.whatsapp").exception(
                    "deal=%s failed on a message from %s", NO_DEAL, mask_phone(message.phone)
                )
            finally:
                self._inbox.task_done()

    async def on_message(self, message: Inbound) -> None:
        found = await self._deal_of(message.phone)
        deal, role = found if found else (None, None)
        deal_id = deal.id if deal else NO_DEAL
        deal_log("gawah.whatsapp", deal_id).info("message from %s", mask_phone(message.phone))
        self.bus.publish(
            WhatsAppMessage(
                deal_id=deal_id, direction=Direction.IN, phone=message.phone, role=role,
                text=message.text or None, media_url=message.media_url, media_type=message.media_type,
                simulated=self.outbox.is_simulated(message.phone), provider_id=message.sid,
            )
        )

        def reply(text: str) -> None:
            self.outbox.send(deal_id, message.phone, role, text)

        if not message.media_url and self.intake.answer(message.phone, message.text, message.name):
            return
        numbers = [] if message.media_url else phone.find_numbers(message.text)
        if numbers == [message.phone]:
            reply(words.OWN_NUMBER)
        elif len(numbers) > 1:
            reply(words.MANY_NUMBERS)
        elif numbers:
            self._start_deal(message, numbers[0])
        elif deal and await self._take_record(deal, role, message):
            pass
        elif deal:
            reply(words.HELP)
        else:
            reply(words.HELP_NO_DEAL)

    def _start_deal(self, message: Inbound, other_phone: str) -> None:
        role = Role.WORKER if phone.says_worker(message.text) else Role.HIRER
        me = Person(role=role, name=message.name, phone=message.phone)
        other = Person(role=role.other, phone=other_phone)
        deal_id = new_id()
        deal_log("gawah.whatsapp", deal_id).info(
            "deal asked by %s (%s) with %s", mask_phone(me.phone), role.value, mask_phone(other.phone)
        )
        self.bus.publish(DealRequested(deal_id=deal_id, requested_by=me, other=other, text=message.text))
        self.outbox.send(deal_id, me.phone, me.role, words.call_link(self._link(call_path(deal_id, me.role))))
        self.outbox.send(
            deal_id, other.phone, other.role,
            words.call_link_for_other(me, self._link(call_path(deal_id, other.role))),
        )

    async def _take_record(self, deal: Deal, role: Role, message: Inbound) -> bool:
        """True if the message was dealt with: logged as a record, or the sender was told
        it could not be read. False if it is not a record."""
        if message.media_url and not (message.media_type or "").startswith("image/"):
            return False
        sender = deal.person(role)
        sender = sender.model_copy(update={"phone": message.phone, "name": sender.name or message.name})
        try:
            image, image_type = None, None
            if message.media_url:
                image, image_type = await self.twilio.fetch_media(message.media_url)
            return await self.intake.take(
                deal, sender, message.text, message.media_url, image, message.media_type or image_type
            )
        except Exception as error:
            deal_log("gawah.whatsapp", deal.id).error("could not read a message: %s", error)
            self.outbox.send(deal.id, message.phone, role, words.READ_FAILED)
            return True

    async def _deal_of(self, number: str) -> tuple[Deal, Role] | None:
        """The person's most recent deal and their role in it, read from the store.
        Deals have no closed state yet, so every deal counts as open."""
        for event in reversed(await self.store.events(name="deal.requested")):
            for person in (event.requested_by, event.other):
                if person.phone == number:
                    deal = await self.store.deal(event.deal_id)
                    if deal:
                        return deal, person.role
        return None

    def _link(self, path: str) -> str:
        return (self.settings.public_base_url or LOCAL_BASE_URL).rstrip("/") + path

    # ---------- other streams' events ----------

    async def on_call_ended(self, event: CallEnded) -> None:
        if event.kind is not CallKind.DEAL:
            return
        for person in await self._people(event.deal_id, event.people):
            url = self._link(callback_path(event.deal_id, person.role))
            self.outbox.send(event.deal_id, person.phone, person.role, words.callback_link(url))

    async def on_contract_ready(self, event: ContractReady) -> None:
        log = deal_log("gawah.whatsapp", event.deal_id)
        files = []
        for url, key, kind in (
            (event.pdf_url, event.pdf_key, "application/pdf"),
            (event.voice_summary_url, event.voice_summary_key, None),
        ):
            try:
                url = url or (await self._sign(key) if key else None)
            except Exception as error:
                log.error("could not make a link for %s: %s", key, type(error).__name__)
            files.append((url, kind or mimetypes.guess_type(urlsplit(url).path)[0]) if url else None)
        if not any(files):
            log.warning("contract.ready carried no file to send")
        line = words.contract(pdf=files[0] is not None, voice=files[1] is not None)
        files = [f for f in files if f]
        for person in await self._people(event.deal_id, []):
            self.outbox.send(event.deal_id, person.phone, person.role, line)
            # Sent as separate messages: WhatsApp gives a document or a voice note no caption.
            for url, media_type in files:
                self.outbox.send(event.deal_id, person.phone, person.role, media_url=url, media_type=media_type)

    async def on_reply_timeout(self, event: ReplyTimeout) -> None:
        once = (event.deal_id, event.record_id)
        if once in self._followed_up:
            return
        self._followed_up.add(once)
        for person in await self._people(event.deal_id, []):
            if person.role is event.person:
                url = self._link(callback_path(event.deal_id, person.role))
                self.outbox.send(event.deal_id, person.phone, person.role, words.follow_up(url))

    async def _people(self, deal_id: str, fallback: list[Person]) -> list[Person]:
        deal = await self.store.deal(deal_id)
        people = [p for p in (deal.people if deal else []) if p.phone]
        return people or [p for p in fallback if p.phone]
