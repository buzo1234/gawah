"""Gawah's voice on one deal call: the opening line, then one thing said per judge.speak,
started in a pause and stopped if someone talks over it.

The words are asked of the model the moment judge.speak arrives, while the wait for a
pause goes on. They are usually in hand before the pause comes, so Gawah starts as soon
as the pause is long enough to be one. Words that end up dropped were paid for.
"""

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.bus import Bus
from app.contracts import CallStarted, ChecklistUpdated, ItemState, JudgeSpeak, JudgeSpoke, Role, SpeakReason
from app.log import deal_log
from app.mouth import tuning, voice
from app.mouth.hearing import Hearing
from app.mouth.player import Player
from app.mouth.voice import Utterance, Voice


@dataclass
class _Job:
    instruction: str
    must_say: bool  # said even if no pause comes: the opening line, and anything at wrap-up
    speak: JudgeSpeak | None = None  # None for the opening line
    arrived: float = field(default_factory=time.monotonic)

    @property
    def what(self) -> str:
        if self.speak is None:
            return "opening"
        return self.speak.item.value if self.speak.item else self.speak.reason.value


def heard_part(text: str, heard_ms: float, total_ms: float) -> str:
    """Roughly the words that were out before Gawah was cut off. The model gives the
    text of the whole reply and no timing, so this goes by the share of the audio heard."""
    words = text.split()
    if heard_ms < tuning.HEARD_MIN_MS or not total_ms:
        return ""
    keep = round(len(words) * min(1.0, heard_ms / total_ms))
    return " ".join(words[:keep]) + (" ..." if keep < len(words) else "")


class DealCall:
    def __init__(self, started: CallStarted, bus: Bus, make_seat: Callable, make_link: Callable) -> None:
        self.deal_id, self.room_name, self.people = started.deal_id, started.room, started.people
        self.log = deal_log("gawah.mouth", self.deal_id)
        self.bus = bus
        self.seat = make_seat(self.log)
        self.voice = Voice(self.log)
        self.voice.link = make_link(voice.config(), self.voice.on_event, self.log)
        self.player = Player(self.seat)
        self.hearing = Hearing()
        self.checklist: ChecklistUpdated | None = None
        self.outcomes: list[dict] = []  # one per thing Gawah was asked to say: said or dropped, and why
        self.on_over: Callable[[DealCall, str], None] = lambda call, why: None
        # Call seconds count from call.started, the one moment every stream shares.
        self._zero = time.monotonic() - (datetime.now(UTC) - started.ts).total_seconds()
        self._jobs: asyncio.Queue[_Job] = asyncio.Queue()
        self._tasks: list[asyncio.Task] = []
        self._ended = False

    async def start(self) -> None:
        self.seat.on_frame = self._on_frame
        self.seat.on_left = self.seat.on_silent = self.hearing.forget
        self.seat.on_closed = lambda: self.on_over(self, "the room closed")
        try:
            await self.seat.join(self.room_name)
            await self.voice.link.open()
        except BaseException:
            await self.end()
            raise
        self._tasks = [asyncio.create_task(c) for c in (self.player.run(), self._work(), self._open(), self._limit())]
        self.log.info("in room %s as %s", self.room_name, tuning.IDENTITY)

    def on_speak(self, event: JudgeSpeak) -> None:
        self._jobs.put_nowait(_Job(event.instruction, event.reason is SpeakReason.WRAPPING_UP, event))

    async def end(self) -> None:
        if self._ended:
            return
        self._ended = True
        for task in self._tasks:
            task.cancel()
        self.player.stop()
        for close in (self.seat.leave, self.voice.link.close):  # out of the room first: that is what costs minutes
            try:
                await close()
            except Exception:
                self.log.exception("did not close cleanly")
        self.log.info("left room %s", self.room_name)

    # ---- when to speak ----

    async def _open(self) -> None:
        """The opening line, once both people can hear it."""
        deadline = time.monotonic() + tuning.OPENING_WAIT_S
        while len(self.hearing.people) < 2 and time.monotonic() < deadline:
            await asyncio.sleep(0.1)
        names = [f"{p.name.split()[0]} ji" for p in self.people if p.name]
        names = " aur ".join(names) if len(names) == 2 else tuning.OPENING_NAMES_UNKNOWN
        self._jobs.put_nowait(_Job(tuning.OPENING.format(names=names), must_say=True))

    async def _limit(self) -> None:
        await asyncio.sleep(tuning.DEAL_CALL_MAX_S)
        self.on_over(self, "the call ran past its limit")

    async def _work(self) -> None:
        """One thing at a time, in the order asked."""
        while True:
            job = await self._jobs.get()
            try:
                await self._say(job)
            except Exception:
                self.log.exception("could not say: %s", job.what)

    def _on_frame(self, who: str, pcm: bytes) -> None:
        gawah_ms = self.player.heard_so_far() if self.player.active else None
        if self.hearing.hear(who, pcm, gawah_ms):
            self.log.info("%s talked over Gawah", who)
            self.player.stop()

    def _agreed(self, job: _Job) -> bool:
        item = job.speak.item if job.speak else None
        if item is None or self.checklist is None:
            return False
        return any(i.key is item and i.state is ItemState.AGREED for i in self.checklist.items)

    def _who(self) -> str:
        """Who the names in the instruction are. The brain writes 'Hirer' for a person with no name."""
        lines = []
        for role in Role:
            person = next((p for p in self.people if p.role is role), None)
            if person and person.name:
                lines.append(tuning.WHO_KNOWN.format(name=person.name.split()[0], role=tuning.ROLE_WORDS[role]))
            else:
                lines.append(tuning.WHO_UNKNOWN.format(
                    word=role.value.capitalize(), role=tuning.ROLE_WORDS[role], hindi=tuning.ROLE_HINDI[role]
                ))
        return " ".join(lines)

    def _drop(self, job: _Job, why: str) -> None:
        self.log.info("not said (%s): %s", why, job.what)
        self.outcomes.append({"what": job.what, "said": False, "why": why})
        if job.speak:
            # No words and no start time: nothing went into the room. The brain stops waiting for it.
            speak = job.speak
            self.bus.publish(JudgeSpoke(
                deal_id=self.deal_id, text="", speak_id=speak.event_id, to=speak.to, reason=speak.reason, item=speak.item,
            ))

    async def _say(self, job: _Job) -> None:
        def late() -> bool:
            return time.monotonic() - job.arrived > tuning.PAUSE_WAIT_S

        if self._agreed(job):
            return self._drop(job, "agreed in the meantime")
        if late() and not job.must_say:
            return self._drop(job, "waited too long behind something else")
        utterance = await self.voice.ask(job.instruction, self._who())
        while True:
            if self._agreed(job):
                why = "agreed in the meantime"
            elif utterance.failed or utterance.stalled():
                why = utterance.failed or "the voice model gave nothing"
            elif utterance.ready() and (self.hearing.in_pause() or (late() and job.must_say)):
                break
            elif late() and not job.must_say:
                why = "no pause came"
            else:
                await asyncio.sleep(tuning.TICK_S)
                continue
            await self.voice.cancel(utterance)
            return self._drop(job, why)
        await self._play(job, utterance)

    # ---- speaking ----

    async def _play(self, job: _Job, utterance: Utterance) -> None:
        over = self.hearing.talking()
        self.hearing.gawah_starts()
        self.player.begin()
        fed = 0
        while not self.player.done.is_set():
            if len(utterance.audio) > fed:
                self.player.feed(bytes(utterance.audio[fed:]))
                fed = len(utterance.audio)
            if utterance.complete or utterance.stalled():
                self.player.finish()
            await asyncio.sleep(tuning.TICK_S)
        player, cut = self.player, self.player.cut
        if cut:
            await self.voice.cancel(utterance)
        text = heard_part(utterance.text, player.heard_ms, utterance.audio_ms) if cut else utterance.text.strip()
        started = player.started_at if player.started_at is not None else player.ended_at
        speak = job.speak
        spoke = JudgeSpoke(
            deal_id=self.deal_id, text=text, speak_id=speak.event_id if speak else None,
            to=speak.to if speak else None, reason=speak.reason if speak else None, item=speak.item if speak else None,
            start=round(started - self._zero, 2), end=round(player.ended_at - self._zero, 2), interrupted=cut,
        )
        self.outcomes.append({
            "what": job.what, "said": True, "text": text, "interrupted": cut, "spoken_over": over,
            "wait_ms": round((started - job.arrived) * 1000),  # judge.speak arriving to the first sound handed to the room
            "model_ms": round((utterance.first_audio_at - utterance.asked_at) * 1000) if utterance.first_audio_at else None,
            "speech_ms": round(utterance.audio_ms), "heard_ms": round(player.heard_ms), "dry_ms": round(player.dry_ms),
        })
        self.log.info(
            "said (%s) after %s ms%s%s: %s", job.what, self.outcomes[-1]["wait_ms"],
            f", over {', '.join(over)}" if over else "", ", cut off" if cut else "", text,
        )
        self.bus.publish(spoke)
