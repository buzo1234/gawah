"""Fakes for the whatsapp stream's tests: a fake Twilio, a fake image reader, a fake
clock, and a World that wires the real bot to them on a real bus and store."""

import asyncio

import pytest

from app.bus import Bus
from app.config import Settings
from app.contracts import Direction, Event, WhatsAppMessage
from app.records.reader import Reading
from app.store import Store
from app.whatsapp import wire
from app.whatsapp.bot import Inbound

REAL = "+919999900000"  # the one number in VERIFIED_NUMBERS
SUNITA, RAMESH, GEETA, MOHAN = "+919811100001", "+919822200002", "+919833300003", "+919844400004"
BASE = "https://gawah.example"
SCREENSHOT = "https://api.twilio.com/2010-04-01/Accounts/AC0/Messages/MM0/Media/ME0"


async def _let_tasks_run() -> None:
    for _ in range(10):
        await asyncio.sleep(0)


class FakeClock:
    def __init__(self) -> None:
        self.time = 0.0
        self._sleepers: list[tuple[float, asyncio.Future]] = []

    def now(self) -> float:
        return self.time

    async def sleep(self, seconds: float) -> None:
        future = asyncio.get_running_loop().create_future()
        self._sleepers.append((self.time + seconds, future))
        await future

    async def advance(self, seconds: float) -> None:
        """Move time forward, waking each sleeper at the moment it asked for."""
        end = self.time + seconds
        while True:
            await _let_tasks_run()
            self._sleepers = [s for s in self._sleepers if not s[1].done()]
            due = [s for s in self._sleepers if s[0] <= end]
            if not due:
                break
            wake_at, future = min(due, key=lambda s: s[0])
            self.time = max(self.time, wake_at)
            future.set_result(None)
        self.time = end


class FakeTwilio:
    def __init__(self, clock: FakeClock) -> None:
        self.clock = clock
        self.sent: list[tuple[float, str, str | None, str | None]] = []  # time, to, text, media
        self.fetched: list[str] = []
        self.fail = False

    async def send(self, to: str, text: str | None = None, media_url: str | None = None) -> str:
        if self.fail:
            raise RuntimeError("twilio said no")
        self.sent.append((self.clock.now(), to, text, media_url))
        return f"SM{len(self.sent)}"

    async def fetch_media(self, url: str) -> tuple[bytes, str | None]:
        self.fetched.append(url)
        return b"png bytes", "image/png"


class FakeReader:
    """Reads by lookup: the message text, or IMAGE for any message with a picture."""

    IMAGE = object()

    def __init__(self) -> None:
        self.readings: dict[object, Reading] = {
            self.IMAGE: Reading(
                kind="advance", amount=8000, date="21 Nov 2026", transaction_id="632514789023",
                payment_screenshot=True,
            ),
            "2000 cash diya": Reading(kind="payment", amount=2000),
            "kaam poora ho gaya": Reading(kind="work_done"),
            "8000 bheja, UPI ref 632514789023": Reading(kind="payment", amount=8000, transaction_id="632514789023"),
        }
        self.calls: list[tuple[str, bool]] = []
        self.fail = False

    async def read(self, text: str | None, image: bytes | None = None, image_type: str | None = None) -> Reading:
        self.calls.append((text or "", image is not None))
        if self.fail:
            raise RuntimeError("openai is down")
        return self.readings.get(self.IMAGE if image else text, Reading(kind="unclear"))


class World:
    def __init__(self, bus: Bus, store: Store, settings: Settings) -> None:
        self.bus, self.store = bus, store
        self.clock = FakeClock()
        self.twilio = FakeTwilio(self.clock)
        self.reader = FakeReader()
        self.events: list[Event] = []
        bus.subscribe_all(store.record_event)
        bus.subscribe_all(self._collect)
        self.bot = wire(settings, bus, store, twilio=self.twilio, reader=self.reader, clock=self.clock)

    async def _collect(self, event: Event) -> None:
        self.events.append(event)

    async def settle(self) -> None:
        await _let_tasks_run()
        await self.bus.drain()

    async def say(self, phone: str, text: str = "", media: str | None = None, name: str | None = None) -> None:
        """One inbound WhatsApp message, handled to the end."""
        message = Inbound(phone=phone, text=text, media_url=media, media_type="image/png" if media else None, name=name)
        await self.bot.on_message(message)
        await self.settle()

    async def start_deal(self, hirer: str = SUNITA, worker: str = RAMESH) -> str:
        await self.say(hirer, worker.removeprefix("+91"))
        return self.named("deal.requested")[-1].deal_id

    def named(self, name: str) -> list[Event]:
        return [e for e in self.events if e.name == name]

    def sent_to(self, phone: str) -> list[WhatsAppMessage]:
        return [e for e in self.named("whatsapp.message") if e.direction is Direction.OUT and e.phone == phone]

    def texts_to(self, phone: str) -> list[str | None]:
        return [e.text for e in self.sent_to(phone)]


@pytest.fixture
async def world(bus, tmp_path):
    settings = Settings(
        _env_file=None, database_path=str(tmp_path / "test.db"), verified_numbers=REAL,
        public_base_url=BASE, reply_timeout_seconds=120,
    )
    store = Store(settings.database_path)
    await store.open()
    world = World(bus, store, settings)
    yield world
    await world.bot.stop()
    await bus.drain()  # the store writes on a thread: let it finish before the file closes
    await store.close()
