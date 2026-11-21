"""Everything Gawah sends on WhatsApp leaves through here.

A number that is not in VERIFIED_NUMBERS is a simulated phone: nothing goes to Twilio,
and the message is published as whatsapp.message with simulated=True. A real message
waits its turn (the sandbox allows one every three seconds) and is published only after
Twilio accepts it."""

import asyncio

from app.bus import Bus
from app.contracts import Direction, Role, WhatsAppMessage
from app.log import deal_log, mask_phone
from app.whatsapp.clock import Clock
from app.whatsapp.twilio import Twilio

SPACING_SECONDS = 3.0


class Outbox:
    def __init__(self, bus: Bus, twilio: Twilio, clock: Clock, verified: list[str]) -> None:
        self.bus, self.twilio, self.clock = bus, twilio, clock
        self.verified = set(verified)
        # asyncio.Lock hands itself over in the order it was asked for, so it is the queue.
        self._turn = asyncio.Lock()
        self._next_at = 0.0
        self._tasks: set[asyncio.Task] = set()

    def is_simulated(self, phone: str) -> bool:
        return phone not in self.verified

    def send(
        self, deal_id: str, phone: str, role: Role | None, text: str | None = None,
        media_url: str | None = None, media_type: str | None = None,
    ) -> None:
        message = WhatsAppMessage(
            deal_id=deal_id, direction=Direction.OUT, phone=phone, role=role, text=text,
            media_url=media_url, media_type=media_type, simulated=self.is_simulated(phone),
        )
        if message.simulated:
            self.bus.publish(message)
            return
        task = asyncio.create_task(self._deliver(message))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _deliver(self, message: WhatsAppMessage) -> None:
        log = deal_log("gawah.whatsapp", message.deal_id)
        async with self._turn:
            wait = self._next_at - self.clock.now()
            if wait > 0:
                await self.clock.sleep(wait)
            try:
                sid = await self.twilio.send(message.phone, message.text, message.media_url)
            except Exception as error:
                log.error("not sent to %s: %s", mask_phone(message.phone), error)
                return
            finally:
                self._next_at = self.clock.now() + SPACING_SECONDS
        log.info("sent to %s as %s", mask_phone(message.phone), sid)
        self.bus.publish(message.model_copy(update={"provider_id": sid}))

    async def drain(self) -> None:
        """Wait until every queued message has gone out. For tests."""
        while self._tasks:
            await asyncio.gather(*list(self._tasks))

    async def close(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        await asyncio.gather(*list(self._tasks), return_exceptions=True)

