"""Everything Gawah sends on WhatsApp leaves through here.

A number that is not in VERIFIED_NUMBERS is a simulated phone: nothing goes to the
provider, and the message is published as whatsapp.message with simulated=True. A real
message waits its turn (one at a time, in order, spaced as the provider needs) and is
published only after the provider accepts it.

The provider decides what a message can carry. Twilio's sandbox sends text and media.
Meta also shows reply buttons, a link as a button, reactions, a caption on a document,
and 'typing...'. A simulated phone gets what the provider would send, logged as text."""

import asyncio
from typing import Protocol

from app.bus import Bus
from app.contracts import NO_DEAL, Direction, Role, WhatsAppMessage
from app.log import deal_log, mask_phone
from app.whatsapp.clock import Clock
from app.whatsapp.outgoing import Button, Outgoing


class Provider(Protocol):
    rich: bool
    spacing_seconds: float

    async def send(self, out: Outgoing) -> str: ...

    async def fetch_media(self, url: str) -> tuple[bytes, str | None]: ...


class Outbox:
    def __init__(self, bus: Bus, provider: Provider, clock: Clock, verified: list[str]) -> None:
        self.bus, self.provider, self.clock = bus, provider, clock
        self.verified = set(verified)
        self.rich = getattr(provider, "rich", False)
        self.spacing = getattr(provider, "spacing_seconds", 3.0)
        # asyncio.Lock hands itself over in the order it was asked for, so it is the queue.
        self._turn = asyncio.Lock()
        self._next_at = 0.0
        self._tasks: set[asyncio.Task] = set()
        self.deal_of: dict[str, str] = {}  # provider message id -> deal id, for delivery reports

    def is_simulated(self, phone: str) -> bool:
        return phone not in self.verified

    def send(
        self, deal_id: str, phone: str, role: Role | None, text: str | None = None,
        media_url: str | None = None, media_type: str | None = None, *, buttons: tuple[tuple[str, str], ...] = (),
        link: str | None = None, link_label: str | None = None, filename: str | None = None,
    ) -> None:
        """buttons ((id, title) pairs), link_label and filename are used only where the
        provider can show them; the text always holds the whole message, link included."""
        out = Outgoing(to=phone, text=text, media_url=media_url, media_type=media_type)
        if self.rich:
            out.buttons = tuple(Button(*b) for b in buttons)
            out.link, out.link_label, out.filename = link, link_label, filename
        self._queue(deal_id, role, out)

    def react(self, deal_id: str, phone: str, role: Role | None, message_id: str | None, emoji: str) -> None:
        """React to a message the person sent. Only where the provider has reactions."""
        if self.rich and message_id:
            self._queue(deal_id, role, Outgoing(to=phone, text=emoji, react_to=message_id))

    def typing(self, phone: str, message_id: str | None) -> None:
        """Mark the person's message read and show that Gawah is typing. Best effort: not a
        message, so it neither waits its turn nor goes in the event log."""
        if not (self.rich and message_id) or self.is_simulated(phone):
            return
        self._spawn(self._typing(phone, message_id))

    def _queue(self, deal_id: str, role: Role | None, out: Outgoing) -> None:
        message = WhatsAppMessage(
            deal_id=deal_id, direction=Direction.OUT, phone=out.to, role=role, text=out.logged_text(),
            media_url=out.media_url, media_type=out.media_type, simulated=self.is_simulated(out.to),
        )
        if message.simulated:
            self.bus.publish(message)
            return
        self._spawn(self._deliver(message, out))

    def _spawn(self, work) -> None:
        task = asyncio.create_task(work)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _deliver(self, message: WhatsAppMessage, out: Outgoing) -> None:
        log = deal_log("gawah.whatsapp", message.deal_id)
        async with self._turn:
            wait = self._next_at - self.clock.now()
            if wait > 0:
                await self.clock.sleep(wait)
            try:
                sid = await self.provider.send(out)
            except Exception as error:
                log.error("not sent to %s: %s", mask_phone(message.phone), error)
                return
            finally:
                self._next_at = self.clock.now() + self.spacing
        log.info("sent to %s as %s", mask_phone(message.phone), sid)
        self.deal_of[sid] = message.deal_id
        self.bus.publish(message.model_copy(update={"provider_id": sid}))

    async def _typing(self, phone: str, message_id: str) -> None:
        try:
            await self.provider.typing(message_id)
        except Exception as error:
            deal_log("gawah.whatsapp", NO_DEAL).warning("could not show typing to %s: %s", mask_phone(phone), error)

    async def drain(self) -> None:
        """Wait until every queued message has gone out. For tests."""
        # Only the unfinished: gather on finished tasks returns without yielding, so the
        # callbacks that remove them from the set would never get to run.
        while pending := [t for t in self._tasks if not t.done()]:
            await asyncio.gather(*pending)

    async def close(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        await asyncio.gather(*list(self._tasks), return_exceptions=True)
