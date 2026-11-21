"""One deal call from the first tap to call.ended, and the set of calls in progress.

A session owns one LiveKit room, Gawah's listener in it, the two recordings and the ears.
Time zero is the moment both people are in the room; call.started is sent then.

A deal can have more than one call. Each has its number (call_no, 1 for the first), its
own room "deal-<deal id>-<call no>", its own recordings under recordings/<deal id>/<call no>/,
and transcript lines numbered from 1 with times from its own start.
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
from app.contracts import AgentNote, CallEnded, CallKind, CallStarted, CrewAgent, Deal, Role
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
        self, deal: Deal, call_no: int, prompt: str, *, bus: Bus, livekit: LiveKit, transcribe: Transcribe,
        upload: Upload, limits: Limits, clock: Callable[[], float], folder: Path,
        on_closing: Callable[["CallSession"], None], on_closed: Callable[["CallSession"], None],
    ) -> None:
        self.deal, self.call_no, self.room = deal, call_no, room_name(deal.id, call_no)
        self.log = deal_log("gawah.call", deal.id)
        self._prompt, self._bus, self._livekit = prompt, bus, livekit
        self._transcribe, self._upload, self._limits = transcribe, upload, limits
        self._clock, self._folder = clock, folder
        self._on_closing, self._on_closed = on_closing, on_closed
        self.present: set[Role] = set()
        self._absence_state: object = None  # what the absence timer is running for
        self.started_at: float | None = None  # time zero, on our clock
        self.ears: Ears | None = None
        self._recordings: dict[Role, Recording] = {}
        self._listener = None
        self._timers: dict[str, asyncio.Task] = {}
        self._closing = False
        self._closed = asyncio.Event()

    async def open(self) -> None:
        await self._livekit.create_room(self.room)
        try:
            self._listener = await self._livekit.listen(self.room, self)
        except BaseException:
            await self._livekit.delete_room(self.room)
            raise
        self._timer("age", self._limits.max_age, "time_limit")
        self.log.info("room %s open, listener in", self.room)
        self._look()  # no event fires for people who were already in the room

    # ---- what the listener reports ----

    def joined(self, identity: str) -> None:
        if _role(identity) and not self._closing:
            self.log.info("%s joined", identity)
        self._look()

    def left(self, identity: str) -> None:
        role = _role(identity)
        if role and not self._closing:
            self.log.info("%s left", identity)
            if self.ears:
                self.ears.forget(role)  # nothing of theirs is carried over to a rejoin
        self._look()

    def muted(self, identity: str, muted: bool) -> None:
        # A phone mutes the track when its screen locks or the page goes to the background.
        # The person is still on the call: their audio is silence until it comes back.
        if _role(identity) and not self._closing:
            self.log.info("%s's microphone %s", identity, "was muted by their device" if muted else "is back")

    def audio(self, identity: str, pcm: bytes) -> None:
        role = _role(identity)
        if role is None or self.started_at is None or self._closing:
            return
        at = self._recordings[role].write(pcm, self._clock() - self.started_at)
        self.ears.hear(role, pcm, at)

    def _look(self) -> None:
        """Take who is present from the room itself, not from what we remember of past events."""
        if self._listener is None or self._closing:
            return
        self.present = {Role(i) for i in self._listener.people() if i in Role}
        if self.started_at is None and len(self.present) == len(Role):
            self._start()
        self._watch_absence()

    def lost(self) -> None:
        # The listener gave up reconnecting, or the room was deleted from outside. Nobody is
        # listening any more, so the call is over as far as Gawah is concerned.
        if not self._closing:
            self.log.warning("listener lost the room")
            self._timer("lost", 0, "listener_lost")

    # ---- start and end ----

    def _start(self) -> None:
        self.started_at = started = self._clock()
        folder = self._folder / self.deal.id / str(self.call_no)
        self._recordings = {role: Recording(folder / f"{role.value}.wav") for role in Role}
        self.ears = Ears(
            self.deal.id, self._bus, lambda pcm: self._transcribe(pcm, self._prompt),
            clock=lambda: self._clock() - started, call_no=self.call_no,
        )
        self._bus.publish(CallStarted(
            deal_id=self.deal.id, people=self.deal.people, room=self.room, call_no=self.call_no,
        ))
        self._note(f"call {self.call_no}: both on the line, recording and listening")
        self.log.info("call %d started in %s", self.call_no, self.room)

    def _absence(self) -> tuple[float, str] | None:
        """How long to wait before ending the call for who is missing now, and why."""
        if not self.present:
            return self._limits.empty, "both_left"
        if self.started_at is not None and len(self.present) < len(Role):
            return self._limits.gone, "one_left"
        return None

    def _watch_absence(self) -> None:
        due = self._absence()
        state = (due, frozenset(self.present))
        if state == self._absence_state:
            return  # an event about someone else must not restart the clock
        self._absence_state = state
        if old := self._timers.pop("absence", None):
            old.cancel()
        if due:
            self._timer("absence", *due)

    def _timer(self, name: str, wait: float, reason: str) -> None:
        async def run() -> None:
            await asyncio.sleep(wait)
            if name == "absence":
                # Look at the room once more before ending a call on something remembered.
                self.present = {Role(i) for i in self._listener.people() if i in Role}
                due = self._absence()
                if due is None or due[1] != reason:
                    self._absence_state = None
                    return self._watch_absence()
            await self.close(reason)

        if old := self._timers.pop(name, None):
            old.cancel()
        self._timers[name] = asyncio.create_task(run())

    async def close(self, reason: str) -> None:
        """End the call: leave and delete the room first, then send what is owed."""
        if self._closing:
            await self._closed.wait()
            return
        self._closing = True
        self._on_closing(self)
        try:
            await self._close(reason)
        finally:
            self._closed.set()
            self._on_closed(self)

    async def _close(self, reason: str) -> None:
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
                duration=round(duration, 1), recording_keys=keys, reason=reason, call_no=self.call_no,
            ))
            self._note(f"call {self.call_no} over: {len(keys)} recordings saved, {self.ears.lines} lines heard")
            self.log.info(
                "call %d ended after %.0fs (%s), recordings: %s", self.call_no, duration, reason, sorted(keys),
            )

    def _note(self, text: str) -> None:
        self._bus.publish(AgentNote(deal_id=self.deal.id, agent=CrewAgent.EARS, text=text))

    async def _save_recordings(self, duration: float) -> dict[str, str]:
        async def save(role: Role, recording: Recording) -> tuple[str, str] | None:
            try:
                recording.close(duration)
                key = f"recordings/{self.deal.id}/{self.call_no}/{role.value}.wav"
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
        self._closing: set[CallSession] = set()  # out of sessions, still saving and uploading
        # deal -> the last of its calls that is over. Ahead of the store while a call is
        # ending: its call.ended is only sent once the recordings are up.
        self._over: dict[str, int] = {}
        self._lock = asyncio.Lock()

    async def numbers(self, deal_id: str) -> tuple[int, int]:
        """The last deal call that started and the last that is over (0 for none)."""
        started = ended = self._over.get(deal_id, 0)
        for event in await self.store.events(deal_id, "call.started"):
            if event.kind is CallKind.DEAL:
                started = max(started, event.call_no)
        for event in await self.store.events(deal_id, "call.ended"):
            if event.kind is CallKind.DEAL:
                ended = max(ended, event.call_no)
        return max(started, ended), ended

    async def ended_calls(self, deal: Deal) -> int:
        """How many of this deal's calls are over, while none is open; 0 while one is."""
        if deal.id in self.sessions:
            return 0
        return (await self.numbers(deal.id))[1]

    async def join(self, deal: Deal, role: Role, after: int | None = None) -> tuple[str, int] | None:
        """A join token for this person and the call number, opening a room first if none is
        open. `after` is how many calls the person's page knows are over: if another one has
        ended since, they were coming back to a call that is over, and get None instead of a
        new call they did not ask for. A call already open is always joined."""
        async with self._lock:
            session = self.sessions.get(deal.id)
            if session is None:
                started, ended = await self.numbers(deal.id)
                if after is not None and ended > after:
                    return None
                asked = await self.store.events(deal.id, "deal.requested")
                prompt = prompt_for(deal, asked[-1].text if asked else None)
                session = CallSession(
                    deal, started + 1, prompt, bus=self.bus, livekit=self.livekit, transcribe=self.transcribe,
                    upload=self.upload, limits=self.limits, clock=self.clock, folder=self.folder,
                    on_closing=self._session_closing, on_closed=self._closing.discard,
                )
                await session.open()
                self.sessions[deal.id] = session
                if started:
                    self.bus.publish(AgentNote(
                        deal_id=deal.id, agent=CrewAgent.EARS,
                        text=f"call {session.call_no}: room open, waiting for both",
                    ))
        person = deal.person(role)
        return self.livekit.token(session.room, role.value, name=person.name if person else None), session.call_no

    def _session_closing(self, session: CallSession) -> None:
        if self.sessions.get(session.deal.id) is session:
            del self.sessions[session.deal.id]
        self._closing.add(session)
        if session.started_at is not None:
            self._over[session.deal.id] = max(self._over.get(session.deal.id, 0), session.call_no)
    async def close_all(self) -> int:
        """Server shutdown: never leave a room open or the listener sitting in one, and let
        a call that is already ending finish sending its recordings and call.ended.
        Returns how many calls it closed or waited for."""
        sessions = [*self.sessions.values(), *self._closing]
        await asyncio.gather(*(s.close("shutdown") for s in sessions))
        await self.transcriber.close()
        await self.livekit.close()
        return len(sessions)
