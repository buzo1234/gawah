"""The bot. Decides what each inbound message is - an answer, a new deal, a record, or
something it cannot use - and sends the links and the contract when other streams'
events call for them."""

import asyncio
import logging
import mimetypes
import re
from collections.abc import Awaitable, Callable
from functools import partial
from urllib.parse import urlsplit

from app.bus import Bus
from app.config import Settings
from app.contracts import (
    NO_DEAL, AgentNote, CallEnded, CallKind, CallOpened, ContractReady, CrewAgent, Deal, DealRequested,
    Direction, Person, ReplyTimeout, Role, WhatsAppMessage, call_path, callback_path, new_id,
)
from app.log import deal_log, mask_phone
from app.records import words as record_words
from app.records.intake import Intake, read_button
from app.records.sentinel import Sentinel
from app.store import Store
from app.whatsapp import phone, words
from app.whatsapp.inbound import Inbound, asks_to_delete
from app.whatsapp.outbox import Outbox, Provider

LOCAL_BASE_URL = "http://localhost:8000"  # used for links until PUBLIC_BASE_URL is set

def link_for(settings: Settings) -> Callable[[str], str]:
    """A path on this server as a link a person can open."""
    return lambda path: (settings.public_base_url or LOCAL_BASE_URL).rstrip("/") + path


class Bot:
    def __init__(
        self, settings: Settings, bus: Bus, store: Store, provider: Provider, outbox: Outbox,
        intake: Intake, sign: Callable[[str], Awaitable[str]], sentinel: Sentinel | None = None,
    ) -> None:
        self.settings, self.bus, self.store = settings, bus, store
        self.provider, self.outbox, self.intake = provider, outbox, intake
        self._sign = sign  # S3 key -> short-lived link
        self._inbox: asyncio.Queue[Inbound] = asyncio.Queue()
        self._worker: asyncio.Task | None = None
        self._followed_up: set[tuple[str, str | None]] = set()
        self._opened: set[tuple[str, int]] = set()
        self.sentinel = sentinel
        self._link = link_for(settings)

    # ---------- inbound ----------

    def receive(self, message: Inbound) -> None:
        """Queue a message and return at once, so the webhook answers the provider straight away.
        Messages are handled one at a time, in the order they arrived."""
        self._inbox.put_nowait(message)

    async def start(self) -> None:
        self._worker = asyncio.create_task(self._work())
        if self.sentinel:
            self.sentinel.reminders.load()

    async def stop(self) -> None:
        if self._worker:
            self._worker.cancel()
            await asyncio.gather(self._worker, return_exceptions=True)
        await self.intake.close()
        if self.sentinel:
            await self.sentinel.reminders.close()
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

        if message.kind == "reaction":
            return  # logged above; a reaction asks for no answer
        self.outbox.typing(message.phone, message.sid)
        if asks_to_delete(message.text):
            self._delete_asked(message, deal_id, role)
            return
        if not message.media_url and self.intake.answer(message.phone, message.text, message.name, message.button):
            return
        if read_button(message.button):  # a yes or no tapped on a question already answered
            reply(record_words.ALREADY_ANSWERED)
            return
        if message.kind == "other":
            reply(words.HELP if deal else words.HELP_NO_DEAL)
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

    def _delete_asked(self, message: Inbound, deal_id: str, role: Role | None) -> None:
        """Say the request is received, and leave it where a person will act on it: the log
        and the event log. Nothing is deleted here."""
        deal_log("gawah.whatsapp", deal_id).warning(
            "DATA DELETION ASKED by %s (%s): remove by hand, see tools/DELETE-DATA.md",
            mask_phone(message.phone), role.value if role else "no deal",
        )
        self.bus.publish(AgentNote(
            deal_id=deal_id, agent=CrewAgent.SENTINEL,
            text=f"{role.value if role else 'someone with no deal'} ({mask_phone(message.phone)}) asked for "
                 "this deal's data to be deleted: to be removed by hand (tools/DELETE-DATA.md)",
        ))
        self.outbox.send(deal_id, message.phone, role, words.DELETE_RECEIVED)

    def _start_deal(self, message: Inbound, other_phone: str) -> None:
        role = Role.WORKER if phone.says_worker(message.text) else Role.HIRER
        me = Person(role=role, name=message.name, phone=message.phone)
        other = Person(role=role.other, phone=other_phone, name=message.other_name)
        deal_id = new_id()
        deal_log("gawah.whatsapp", deal_id).info(
            "deal asked by %s (%s) with %s", mask_phone(me.phone), role.value, mask_phone(other.phone)
        )
        self.bus.publish(DealRequested(deal_id=deal_id, requested_by=me, other=other, text=message.text))
        mine, theirs = self._link(call_path(deal_id, me.role)), self._link(call_path(deal_id, other.role))
        self.outbox.send(deal_id, me.phone, me.role, words.call_link(mine), link=mine, link_label=words.CALL_BUTTON)
        self.outbox.send(
            deal_id, other.phone, other.role, words.call_link_for_other(me, theirs),
            link=theirs, link_label=words.CALL_BUTTON,
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
                image, image_type = await self.provider.fetch_media(message.media_url)
            return await self.intake.take(
                deal, sender, message.text, message.media_url, image, message.media_type or image_type,
                message_id=message.sid,
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

    # ---------- other streams' events ----------

    async def on_call_opened(self, event: CallOpened) -> None:
        """One person opened a second (or later) call: tell the other, with their link."""
        once = (event.deal_id, event.call_no)
        deal = await self.store.deal(event.deal_id)
        if once in self._opened or deal is None:
            return
        self._opened.add(once)
        opener, other = deal.person(event.opened_by), deal.person(event.opened_by.other)
        if other is None or not other.phone:
            return
        url = self._link(call_path(event.deal_id, other.role))
        self.outbox.send(
            event.deal_id, other.phone, other.role, words.call_opened(opener or Person(role=event.opened_by), url),
            link=url, link_label=words.CALL_BUTTON,
        )
        self.bus.publish(AgentNote(
            deal_id=event.deal_id, agent=CrewAgent.SENTINEL,
            text=f"call {event.call_no} opened by the {event.opened_by.value}: told the {other.role.value}, with their link",
        ))

    async def on_call_ended(self, event: CallEnded) -> None:
        if event.kind is not CallKind.DEAL:
            return
        # After a second call, the call-back again only for a term it changed that both have
        # not confirmed. Without memory there is no telling, so everyone gets it, as before.
        needed = set(Role)
        if event.call_no > 1 and self.sentinel:
            needed = await self.sentinel.callback_roles(event.deal_id, event.call_no)
        for person in await self._people(event.deal_id, event.people):
            if person.role not in needed:
                continue
            url = self._link(callback_path(event.deal_id, person.role))
            self.outbox.send(
                event.deal_id, person.phone, person.role, words.callback_link(url),
                link=url, link_label=words.CALLBACK_BUTTON,
            )

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
        pdf, voice = files
        version = _version(event.pdf_key or (urlsplit(pdf[0]).path if pdf else ""))
        for person in await self._people(event.deal_id, []):
            send = partial(self.outbox.send, event.deal_id, person.phone, person.role)
            if self.outbox.rich and pdf:
                # Meta shows a caption under a document, so the line goes there.
                send(words.contract_caption(version, voice=voice is not None), *pdf,
                     filename=f"Gawah-contract{f'-v{version}' if version else ''}.pdf")
            else:
                # Twilio's sandbox gives a document no caption: the line goes first, on its own.
                send(words.contract(pdf=pdf is not None, voice=voice is not None))
                if pdf:
                    send(None, *pdf)
            if voice:
                send(None, *voice)

    async def on_reply_timeout(self, event: ReplyTimeout) -> None:
        once = (event.deal_id, event.record_id)
        if once in self._followed_up:
            return
        self._followed_up.add(once)
        for person in await self._people(event.deal_id, []):
            if person.role is event.person:
                url = self._link(callback_path(event.deal_id, person.role))
                self.outbox.send(
                    event.deal_id, person.phone, person.role, words.follow_up(url),
                    link=url, link_label=words.CALLBACK_BUTTON,
                )

    async def _people(self, deal_id: str, fallback: list[Person]) -> list[Person]:
        deal = await self.store.deal(deal_id)
        people = [p for p in (deal.people if deal else []) if p.phone]
        return people or [p for p in fallback if p.phone]


def _version(path: str) -> int | None:
    """The contract's version, from its file name (contracts/<deal>-v2.pdf)."""
    found = re.search(r"-v(\d+)\.pdf$", path)
    return int(found.group(1)) if found else None
