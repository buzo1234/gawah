"""Gawah's voice on one deal call: the opening line, then one thing said per judge.speak,
started in a pause and stopped if someone talks over it.

This is the plain voice (JUDGE_MODE=wrapup): each judge.speak's instruction is said as it
is. agent_call.py builds Gawah the agent (JUDGE_MODE=live) on the same floor control.

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
from app.contracts import (
    Audience, CallStarted, ChecklistUpdated, FactConflict, FactRecorded, ItemState, JudgeSpeak, JudgeSpoke, Role,
    SpeakReason, TranscriptLine,
)
from app.log import deal_log
from app.mouth import moments, tuning, voice
from app.mouth.hearing import Hearing
from app.mouth.player import Player, phrase_start
from app.mouth.voice import Voice

ADDRESSED = SpeakReason.ADDRESSED_DIRECTLY.value


@dataclass
class _Job:
    instruction: str  # the brain's instruction; for the agent, the situation
    must_say: bool  # said even if no pause comes: the opening line, and anything at wrap-up
    speak: JudgeSpeak | None = None  # the judge.speak it answers; None for the opening line
    kind: str = "opening"  # "opening", a SpeakReason value, or "follow_up"
    to: Audience | None = None
    arrived: float = field(default_factory=time.monotonic)
    spoke: JudgeSpoke | None = None  # once said or dropped
    ack: bool = False  # the acknowledgement may come first (the agent, when spoken to)
    superseded: bool = False  # something more important came; drop it unless it is already being said
    playing: bool = False

    @property
    def what(self) -> str:
        if self.speak and self.speak.item and self.kind != ADDRESSED:
            return self.speak.item.value
        return self.kind


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
        self.deal_id, self.room_name, self.call_no = started.deal_id, started.room, started.call_no
        self.log = deal_log("gawah.mouth", self.deal_id)
        self.bus = bus
        self.seat = make_seat(self.log)
        self.names = moments.Names(started.people)
        self.link = self._connect(make_link)
        self.player = Player(self.seat)
        self.hearing = Hearing()
        self.checklist: ChecklistUpdated | None = None
        self.outcomes: list[dict] = []  # one per thing Gawah was asked to say: said or dropped, why, how long it took
        self.on_over: Callable[[DealCall, str], None] = lambda call, why: None
        # Call seconds count from call.started, the one moment every stream shares.
        self._zero = time.monotonic() - (datetime.now(UTC) - started.ts).total_seconds()
        self._jobs: asyncio.Queue[_Job] = asyncio.Queue()
        self._tasks: list[asyncio.Task] = []
        self._ended = False
        self._ack: bytes | None = None  # the acknowledgement's audio, if this call has one
        self._since: float | None = None  # call seconds when what Gawah is saying now began
        self._told_to_stop = False  # a line asked it to stop while it was speaking: no carrying on

    def _connect(self, make_link: Callable):
        self.voice = Voice(self.log)
        self.voice.link = make_link(voice.config(), self.voice.on_event, self.log)
        return self.voice.link

    @property
    def people(self) -> list:
        return self.names.people

    async def start(self) -> None:
        self.seat.on_frame = self._on_frame
        self.seat.on_left = self.seat.on_silent = self.hearing.forget
        self.seat.on_closed = lambda: self.on_over(self, "the room closed")
        try:
            await self.seat.join(self.room_name)
            await self.link.open()
        except BaseException:
            await self.end()
            raise
        self._tasks = [asyncio.create_task(c) for c in (self.player.run(), self._work(), self._open(), self._limit())]
        self.log.info("in room %s as %s (%s)", self.room_name, tuning.IDENTITY, type(self).__name__)

    def meet(self, people: list) -> None:
        """Names learned on the call fill the ones the call started without."""
        self.names.meet(people)

    def on_speak(self, event: JudgeSpeak) -> None:
        self._jobs.put_nowait(_Job(event.instruction, event.reason is SpeakReason.WRAPPING_UP, event, event.reason.value, event.to))

    async def on_line(self, event: TranscriptLine) -> None:
        """The plain voice does not follow the conversation; it only stops when told to."""
        if event.call_no == self.call_no:
            self._stop_if_told(event)

    def _stop_if_told(self, line: TranscriptLine) -> None:
        """A line that names Gawah or tells it to stop, said while it was speaking: stop, and stay stopped.
        Lines come a second or two after they are said, so this catches a "ruko" too short to cut Gawah off."""
        if self._since is None or line.end < self._since:
            return
        words = set(line.text.lower().replace(",", " ").replace(".", " ").replace("?", " ").replace("!", " ").split())
        if moments.addresses_gawah(line.text) or words & set(tuning.STOP_WORDS):
            self._told_to_stop = True
            if self.player.active:
                self.log.info("%s told Gawah to stop", line.speaker.value)
                self.player.stop()

    async def on_fact(self, event: FactRecorded | FactConflict) -> None:
        """Nor the facts."""

    async def end(self) -> None:
        if self._ended:
            return
        self._ended = True
        for task in self._tasks:
            task.cancel()
        self.player.stop()
        for close in (self.seat.leave, self.link.close):  # out of the room first: that is what costs minutes
            try:
                await close()
            except Exception:
                self.log.exception("did not close cleanly")
        self.log.info("left room %s", self.room_name)

    # ---- when to speak ----

    async def _open(self) -> None:
        """The opening line, once both people can hear it."""
        deadline = time.monotonic() + tuning.OPENING_WAIT_S
        await self._before_opening()
        while len(self.hearing.people) < 2 and time.monotonic() < deadline:
            await asyncio.sleep(0.1)
        self._jobs.put_nowait(_Job(self._opening(), must_say=True))

    async def _before_opening(self) -> None: ...

    def _opening(self) -> str:
        names = [f"{p.name.split()[0]} ji" for p in self.people if p.name]
        names = " aur ".join(names) if len(names) == 2 else tuning.OPENING_NAMES_UNKNOWN
        return tuning.OPENING.format(names=names)

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
        gawah_db = self.player.loudness() if self.player.active else None
        if self.hearing.hear(who, pcm, gawah_ms, gawah_db):
            self.log.info("%s talked over Gawah", who)
            self.player.stop()

    def _agreed(self, job: _Job) -> bool:
        # A contradiction is about a term already agreed: that is the point of saying it.
        asks_a_term = job.kind not in (ADDRESSED, SpeakReason.CONTRADICTS_RECORD.value, SpeakReason.CHANGE_PROPOSED.value)
        item = job.speak.item if job.speak and asks_a_term else None
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

    def _wait_s(self, job: _Job) -> float:
        return tuning.PAUSE_WAIT_S

    async def _prepare(self, job: _Job):
        """Ask for the words. Returns something shaped like voice.Utterance, or None for nothing to say."""
        return await self.voice.ask(job.instruction, self._who())

    async def _cancel(self, utterance, heard_ms: float | None = None) -> None:
        await self.voice.cancel(utterance)

    def _drop(self, job: _Job, why: str, utterance=None) -> None:
        self.log.info("not said (%s): %s", why, job.what)
        self.outcomes.append({"what": job.what, "said": False, "why": why})
        # No words and no start time: nothing went into the room. The brain stops waiting for it.
        job.spoke = JudgeSpoke(deal_id=self.deal_id, text="", to=job.to, reason=_reason(job), item=job.speak.item if job.speak else None)
        if job.speak:
            self.bus.publish(job.spoke.model_copy(update={"speak_id": job.speak.event_id}))

    async def _say(self, job: _Job) -> None:
        deadline = job.arrived + self._wait_s(job)

        def late() -> bool:
            return time.monotonic() > deadline

        if job.superseded:
            return self._drop(job, "superseded")
        if self._agreed(job):
            return self._drop(job, "agreed in the meantime")
        if late() and not job.must_say:
            return self._drop(job, "waited too long behind something else")
        utterance = await self._prepare(job)
        if utterance is None:
            return
        ack: float | None = None  # when the acknowledgement started
        while True:
            if job.superseded:
                why = "superseded"
            elif self._agreed(job):
                why = "agreed in the meantime"
            elif utterance.failed or utterance.stalled():
                why = utterance.failed or "the voice model gave nothing"
            elif utterance.complete and not utterance.audio:
                return self._drop(job, "stayed silent", utterance)
            elif utterance.ready() and (self.hearing.in_pause() or (late() and job.must_say)):
                break
            elif job.ack and self._ack and ack is None and self.hearing.in_pause():
                ack = await self._play_ack()
                deadline = time.monotonic() + tuning.ANSWER_WAIT_S
                continue
            elif late() and not job.must_say:
                why = "no pause came"
            else:
                await asyncio.sleep(tuning.TICK_S)
                continue
            await self._cancel(utterance)
            return self._drop(job, why, utterance)
        await self._play(job, utterance, ack)

    # ---- speaking ----

    def _voice_end(self) -> float | None:
        """When someone last sustained voice, on the monotonic clock."""
        since = self.hearing.since_voice_ms()
        return None if since is None else time.monotonic() - since / 1000

    async def _play_ack(self) -> float:
        voice_end = self._voice_end()
        self.hearing.gawah_starts()
        self.player.begin()
        self.player.feed(self._ack)
        self.player.finish()
        await self.player.done.wait()
        started = self.player.started_at or self.player.ended_at
        self.outcomes.append({"what": "ack", "said": True, "text": tuning.ACK, "interrupted": self.player.cut, "at": started,
                              "after_voice_ms": _ms(started - voice_end) if voice_end else None})
        return started

    def _starting(self, job: _Job, utterance) -> None:
        """Gawah is about to speak this."""

    async def _play(self, job: _Job, utterance, ack: float | None) -> None:
        job.playing = True
        self._starting(job, utterance)
        voice_end = self._voice_end()
        over = self.hearing.talking()
        self.hearing.gawah_starts()
        self.player.begin()
        self._since, self._told_to_stop = time.monotonic() - self._zero, False
        fed, resumed = 0, 0
        while True:
            while not self.player.done.is_set():
                if len(utterance.audio) > fed:
                    self.player.feed(bytes(utterance.audio[fed:]))
                    fed = len(utterance.audio)
                if utterance.complete or utterance.stalled():
                    self.player.finish()
                await asyncio.sleep(tuning.TICK_S)
            if not self.player.cut or resumed >= tuning.RESUME_MAX or not await self._false_stop(job):
                break
            resumed += 1
            at = phrase_start(self.player.audio(), self.player.heard_ms)
            self.log.info("carrying on after a short sound: cut %d ms in, again from %d ms", self.player.heard_ms, at)
            self.hearing.gawah_starts()
            self.player.resume(at)
        self._since = None
        player, cut = self.player, self.player.cut
        if cut:
            await self._cancel(utterance, player.heard_ms)
        text = heard_part(utterance.text, player.heard_ms, utterance.audio_ms) if cut else utterance.text.strip()
        started = player.started_at if player.started_at is not None else player.ended_at
        clip = getattr(utterance, "clip_fact_id", None)
        job.spoke = JudgeSpoke(
            deal_id=self.deal_id, text=f"{tuning.ACK} {text}" if ack else text, to=job.to, reason=_reason(job),
            item=job.speak.item if job.speak else None, start=round((ack or started) - self._zero, 2),
            end=round(player.ended_at - self._zero, 2), interrupted=cut, clip_fact_id=clip,
        )
        self.outcomes.append({
            "what": job.what, "said": True, "text": text, "interrupted": cut, "spoken_over": over, "at": started,
            "wait_ms": _ms(started - job.arrived),  # the moment arriving to the first sound handed to the room
            "model_ms": _ms(utterance.first_audio_at - utterance.asked_at) if utterance.first_audio_at else None,
            "after_voice_ms": _ms(started - voice_end) if voice_end else None,  # someone's last voice to Gawah's first sound
            "ack_ms": _ms(ack - job.arrived) if ack else None, "tools": getattr(utterance, "tools", []), "clip": clip,
            "speech_ms": round(utterance.audio_ms), "heard_ms": round(player.heard_ms), "dry_ms": round(player.dry_ms),
            "resumed": resumed,
        })
        self.log.info(
            "said (%s) after %s ms%s%s: %s", job.what, self.outcomes[-1]["wait_ms"],
            f", over {', '.join(over)}" if over else "", ", cut off" if cut else "", job.spoke.text,
        )
        self._said(job)

    async def _false_stop(self, job: _Job) -> bool:
        """Just cut off. True if the sound that did it was over quickly: then it was not someone talking."""
        cut_at = time.monotonic()
        while (time.monotonic() - cut_at) * 1000 < tuning.RESUME_WITHIN_MS:
            if self._told_to_stop or job.superseded or self._ended:
                return False
            if self.hearing.quiet_ms() >= tuning.RESUME_QUIET_MS:
                return True
            await asyncio.sleep(tuning.TICK_S)
        return False

    def _said(self, job: _Job) -> None:
        self.bus.publish(job.spoke.model_copy(update={"speak_id": job.speak.event_id if job.speak else None}))


def _reason(job: _Job) -> SpeakReason | None:
    try:
        return SpeakReason(job.kind)
    except ValueError:
        return None


def _ms(seconds: float) -> int:
    return round(seconds * 1000)
