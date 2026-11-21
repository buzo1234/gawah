"""One deal call from the first tap to call.ended, and the set of calls in progress.

A session owns one LiveKit room, Gawah's listener in it, the two recordings and the ears.
Time zero is the moment both people are in the room; call.started is sent then.
"""

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from app.bus import Bus
from app.call.livekit import LiveKit, room_name
from app.call.recording import Recording
from app.config import ROOT, Settings
from app.contracts import CallEnded, CallStarted, Deal, DealStatus, Role
from app.ears.lines import Ears
from app.ears.transcribe import Transcriber, prompt_for
from app.log import deal_log
from app.store import S3, Store

Transcribe = Callable[[bytes, str], Awaitable[str]]  # audio, prompt -> text
Upload = Callable[[str, str, str], Awaitable[str]]  # path, key, content type -> key


@dataclass
class Limits:
    # LiveKit reports a silent drop 22 s late (spike 1), so by the time we hear of it the
    # person has been gone that long. 20 s more is time to tap the link again; a longer
    # wait holds up the contract and spends free minutes on a call that is over.
    gone: float = 20.0
    # Nobody in the room. Not zero: a reload shows up as a leave and a join a moment apart.
    empty: float = 3.0
    # Our own cap on a room, counted from when it opens. LiveKit has no such setting.
    max_age: float = 600.0


class CallSession:
    def __init__(
        self, deal: Deal, prompt: str, *, bus: Bus, livekit: LiveKit, transcribe: Transcribe,
        upload: Upload, limits: Limits, clock: Callable[[], float], folder: Path,
        on_closed: Callable[["CallSession"], None],
    ) -> None:
        self.deal, self.room = deal, room_name(deal.id)
        self.log = deal_log("gawah.call", deal.id)
        self._prompt, self._bus, self._livekit = prompt, bus, livekit
        self._transcribe, self._upload, self._limits = transcribe, upload, limits
        self._clock, self._folder, self._on_closed = clock, folder, on_closed
        self.present: set[Role] = set()
        self.started_at: float | None = None  # time zero, on our clock
        self.ears: Ears | None = None
        self._recordings: dict[Role, Recording] = {}
        self._listener = None
        self._timers: dict[str, asyncio.Task] = {}
        self._closing = False

    async def open(self) -> None:
        await self._livekit.create_room(self.room)
        try:
            self._listener = await self._livekit.listen(self.room, self)
        except BaseException:
            await self._livekit.delete_room(self.room)
            raise
        self._timer("age", self._limits.max_age, "time_limit")
        self.log.info("room %s open, listener in", self.room)

    # ---- what the listener reports ----

    def joined(self, identity: str) -> None:
        role = _role(identity)
        if role is None or self._closing:
            return
        self.present.add(role)
        self.log.info("%s joined", identity)
        if self.started_at is None and len(self.present) == len(Role):
            self._start()
        self._watch_absence()

    def left(self, identity: str) -> None:
        role = _role(identity)
        if role is None or self._closing:
            return
        self.present.discard(role)
        self.log.info("%s left", identity)
        self._watch_absence()

    def audio(self, identity: str, pcm: bytes) -> None:
        role = _role(identity)
        if role is None or self.started_at is None or self._closing:
            return
        at = self._recordings[role].write(pcm, self._clock() - self.started_at)
        self.ears.hear(role, pcm, at)

    # ---- start and end ----

    def _start(self) -> None:
        self.started_at = started = self._clock()
        folder = self._folder / self.deal.id
        self._recordings = {role: Recording(folder / f"{role.value}.wav") for role in Role}
        self.ears = Ears(
            self.deal.id, self._bus, lambda pcm: self._transcribe(pcm, self._prompt),
            clock=lambda: self._clock() - started,
        )
        self._bus.publish(CallStarted(deal_id=self.deal.id, people=self.deal.people, room=self.room))
        self.log.info("call started")

    def _watch_absence(self) -> None:
        if not self.present:
            self._timer("absence", self._limits.empty, "both_left")
        elif self.started_at is not None and len(self.present) < len(Role):
            self._timer("absence", self._limits.gone, "one_left")
        elif task := self._timers.pop("absence", None):
            task.cancel()

    def _timer(self, name: str, wait: float, reason: str) -> None:
        async def run() -> None:
            await asyncio.sleep(wait)
            await self.close(reason)

        if old := self._timers.pop(name, None):
            old.cancel()
        self._timers[name] = asyncio.create_task(run())

    async def close(self, reason: str) -> None:
        """End the call: leave and delete the room first, then send what is owed."""
        if self._closing:
            return
        self._closing = True
        self._on_closed(self)
        for task in self._timers.values():
            if task is not asyncio.current_task():
                task.cancel()
        started = self.started_at is not None
        duration = self._clock() - self.started_at if started else 0.0
        try:
            if self._listener:
                await self._listener.disconnect()
        except Exception:
            self.log.exception("listener did not disconnect cleanly")
        try:
            await self._livekit.delete_room(self.room)
            self.log.info("room %s deleted (%s)", self.room, reason)
        except Exception:
            self.log.exception("ROOM NOT DELETED: %s is still open on LiveKit", self.room)
        if started:
            await self.ears.finish()
            keys = await self._save_recordings(duration)
            self._bus.publish(CallEnded(
                deal_id=self.deal.id, people=self.deal.people, room=self.room,
                duration=round(duration, 1), recording_keys=keys, reason=reason,
            ))
            self.log.info("call ended after %.0fs (%s), recordings: %s", duration, reason, sorted(keys))

    async def _save_recordings(self, duration: float) -> dict[str, str]:
        async def save(role: Role, recording: Recording) -> tuple[str, str] | None:
            try:
                recording.close(duration)
                key = f"recordings/{self.deal.id}/{role.value}.wav"
                return role.value, await self._upload(str(recording.path), key, "audio/wav")
            except Exception:
                self.log.exception("recording of %s not uploaded; it is still at %s", role.value, recording.path)
                return None

        saved = await asyncio.gather(*(save(role, rec) for role, rec in self._recordings.items()))
        return dict(s for s in saved if s)


def _role(identity: str) -> Role | None:
    return Role(identity) if identity in Role else None


class Calls:
    """Every call in progress, by deal. Tests replace livekit, transcribe and upload."""

    def __init__(self, settings: Settings, bus: Bus, store: Store) -> None:
        self.bus, self.store = bus, store
        self.livekit = LiveKit(settings)
        self.transcriber = Transcriber(settings)
        self.transcribe: Transcribe = self.transcriber.transcribe
        self.upload: Upload = S3(settings).upload
        self.limits = Limits()
        self.clock: Callable[[], float] = time.monotonic
        self.folder = ROOT / "recordings"
        self.sessions: dict[str, CallSession] = {}
        self._over: set[str] = set()
        self._lock = asyncio.Lock()

    def is_over(self, deal: Deal) -> bool:
        """A deal has one call. Its link stops working once that call has ended."""
        return deal.id in self._over or deal.status in (DealStatus.CALL_ENDED, DealStatus.CONTRACT_READY)

    async def join(self, deal: Deal, role: Role) -> str | None:
        """A join token for this person, opening the room first if it is not open yet.
        None when the call is already over."""
        async with self._lock:
            if self.is_over(deal):
                return None
            session = self.sessions.get(deal.id)
            if session is None:
                asked = await self.store.events(deal.id, "deal.requested")
                prompt = prompt_for(deal, asked[-1].text if asked else None)
                session = CallSession(
                    deal, prompt, bus=self.bus, livekit=self.livekit, transcribe=self.transcribe,
                    upload=self.upload, limits=self.limits, clock=self.clock, folder=self.folder,
                    on_closed=self._closed,
                )
                await session.open()
                self.sessions[deal.id] = session
        person = deal.person(role)
        return self.livekit.token(session.room, role.value, name=person.name if person else None)

    def _closed(self, session: CallSession) -> None:
        if self.sessions.get(session.deal.id) is session:
            del self.sessions[session.deal.id]
        if session.started_at is not None:
            self._over.add(session.deal.id)

    async def close_all(self) -> None:
        """Server shutdown: never leave a room open or the listener sitting in one."""
        await asyncio.gather(*(s.close("shutdown") for s in list(self.sessions.values())))
        await self.transcriber.close()
        await self.livekit.close()
