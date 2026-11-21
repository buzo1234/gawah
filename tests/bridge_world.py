"""A bridge with LiveKit, OpenAI and S3 replaced. Not a test: pytest does not collect it.

The fake LiveKit keeps the real token minting (it is local) and replaces everything that
would reach the network. A test plays the room by hand: who joins, who leaves, what audio
each person sends.
"""

import asyncio
import json
import wave
from pathlib import Path

import pytest

from app.bus import Bus
from app.call.livekit import LiveKit, deal_of
from app.call.session import Calls, CallSession, Limits
from app.config import Settings
from app.contracts import CallEnded, DealRequested, Event, Person, Role
from app.ears.vad import FRAME_BYTES, FRAME_SECONDS
from app.store import Store
from fakes import RAMESH, SUNITA

AUDIO = Path(__file__).parent.parent / "fixtures" / "audio"
SPOKEN = json.loads((AUDIO / "state.json").read_text())
SILENT_FRAME = bytes(FRAME_BYTES)
LIVEKIT_SETTINGS = Settings(
    _env_file=None, livekit_url="wss://fake.livekit.invalid", livekit_api_key="fake-key",
    livekit_api_secret="fake-secret-that-is-long-enough-to-sign",
)


def recorded(name: str) -> bytes:
    """One of the user's recorded lines as 16 kHz mono PCM."""
    with wave.open(str(AUDIO / f"{name}.wav")) as w:
        assert (w.getframerate(), w.getnchannels(), w.getsampwidth()) == (16000, 1, 2)
        return w.readframes(w.getnframes())


def frames(pcm: bytes) -> list[bytes]:
    return [pcm[i : i + FRAME_BYTES] for i in range(0, len(pcm) - FRAME_BYTES + 1, FRAME_BYTES)]


class FakeListener:
    def __init__(self) -> None:
        self.disconnected = False
        self.in_room: set[str] = set()  # what LiveKit itself would say

    def people(self) -> set[str]:
        return set(self.in_room)

    async def disconnect(self) -> None:
        self.disconnected = True


class FakeRoom:
    """One room as a test plays it. joined and left change who is in the room and then
    tell the call, as LiveKit does; everything else goes straight to the call."""

    def __init__(self, session: CallSession, listener: FakeListener) -> None:
        self.session, self.listener = session, listener

    def joined(self, identity: str) -> None:
        self.listener.in_room.add(identity)
        self.session.joined(identity)

    def left(self, identity: str) -> None:
        self.listener.in_room.discard(identity)
        self.session.left(identity)

    def __getattr__(self, name: str):
        return getattr(self.session, name)


class FakeLiveKit(LiveKit):
    def __init__(self) -> None:
        super().__init__(LIVEKIT_SETTINGS)
        self.created: list[str] = []
        self.deleted: list[str] = []
        self.open: dict[str, FakeRoom] = {}
        self.listeners: list[FakeListener] = []

    async def create_room(self, name: str) -> None:
        self.created.append(name)

    async def delete_room(self, name: str) -> None:
        self.deleted.append(name)
        self.open.pop(name, None)

    async def list_rooms(self) -> list[str]:
        return list(self.open)

    async def listen(self, room_name: str, events) -> FakeListener:
        self.listeners.append(FakeListener())
        self.open[room_name] = FakeRoom(events, self.listeners[-1])
        return self.listeners[-1]


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class World:
    def __init__(self, bus: Bus, store: Store, folder: Path) -> None:
        self.bus, self.store = bus, store
        self.events: list[Event] = []
        self.livekit = FakeLiveKit()
        self.clock = FakeClock()
        self.transcribed: list[bytes] = []
        self.uploads: dict[str, bytes] = {}  # S3 key -> the file's bytes
        self.calls = Calls(LIVEKIT_SETTINGS, bus, store)
        self.calls.livekit, self.calls.clock, self.calls.folder = self.livekit, self.clock, folder
        self.calls.transcribe, self.calls.upload = self.transcribe, self.upload
        # Real seconds for the timers, so short ones. The call's own clock is the fake one.
        self.calls.limits = Limits(gone=0.15, empty=0.05, max_age=30)
        bus.subscribe_all(self._seen)

    async def _seen(self, event: Event) -> None:
        self.events.append(event)

    async def transcribe(self, pcm: bytes, prompt: str) -> str:
        self.transcribed.append(pcm)
        return f"line {len(self.transcribed)}"

    async def upload(self, path: str, key: str, content_type: str) -> str:
        self.uploads[key] = Path(path).read_bytes()
        return key

    def named(self, name: str) -> list[Event]:
        return [e for e in self.events if e.name == name]

    async def deal(self, deal_id: str = "d1", hirer: Person = SUNITA, worker: Person = RAMESH):
        self.bus.publish(DealRequested(deal_id=deal_id, requested_by=hirer, other=worker, text="Ramesh painter se deal"))
        await self.bus.drain()
        return await self.store.deal(deal_id)

    async def join(self, deal_id: str = "d1", role: Role = Role.HIRER, after: int | None = None) -> str | None:
        """The person taps the join button and their browser connects."""
        ticket = await self.calls.join(await self.store.deal(deal_id), role, after)
        if ticket:
            self.room(deal_id).joined(role.value)
        return ticket and ticket[0]

    def room(self, deal_id: str = "d1") -> FakeRoom:
        """The deal's room that is open now."""
        [room] = [name for name in self.livekit.open if deal_of(name) == deal_id]
        return self.livekit.open[room]

    def talk(
        self, deal_id: str = "d1", hirer: bytes = b"", worker: bytes = b"", seconds: float | None = None,
        no_frames_from: str | None = None,
    ) -> None:
        """Both tracks deliver audio side by side while the clock runs. A person who is
        given no audio sends silence, as a quiet or muted microphone does. no_frames_from
        names a person whose track delivers nothing at all for this stretch."""
        room = self.room(deal_id)
        tracks = {"hirer": frames(hirer), "worker": frames(worker)}
        count = int(seconds / FRAME_SECONDS) if seconds else max(map(len, tracks.values()))
        for i in range(count):
            self.clock.now += FRAME_SECONDS
            for identity, track in tracks.items():
                if Role(identity) in room.present and identity != no_frames_from:
                    room.audio(identity, track[i] if i < len(track) else SILENT_FRAME)

    async def ended(self, deal_id: str = "d1", timeout: float = 3.0) -> CallEnded:
        for _ in range(int(timeout / 0.01)):
            await self.bus.drain()
            found = [e for e in self.named("call.ended") if e.deal_id == deal_id]
            if found:
                return found[0]
            await asyncio.sleep(0.01)
        raise TimeoutError("no call.ended")

    async def settle(self) -> None:
        """Let finished transcriptions publish their lines."""
        for _ in range(5):
            await asyncio.sleep(0)
        await self.bus.drain()


@pytest.fixture
async def world(bus, settings, tmp_path):
    store = Store(settings.database_path)
    await store.open()
    bus.subscribe_all(store.record_event)
    world = World(bus, store, tmp_path / "recordings")
    yield world
    # A call still open, or still ending, would write to the store after it is closed.
    await world.calls.close_all()
    await bus.drain()
    await store.close()
