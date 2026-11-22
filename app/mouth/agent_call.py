"""Gawah the agent on one deal call (JUDGE_MODE=live), on the plain voice's floor control.

- Every transcript line goes into the agent's conversation, labelled with who said it, and
  every fact and contradiction from memory as a short note.
- A judge.speak hands the agent a situation (moments.py); the agent picks the words and
  any tools (tools.py).
- A line that names Gawah is a moment of its own: "Haan ji, ek second" at the next pause,
  then the answer. The brain's own addressed judge.speak for that line joins the same turn.
- A contradiction is answered with the record (its value, who said it and who agreed, which
  call) and an offer to play the recording. A yes to that offer (or asking for it) in the
  next CLIP_OFFER_LINES lines plays it, after a short lead-in; a no or anything else does not.
- After a contradiction is put to them, or a change is proposed, the next lines are each
  checked for an answer (a change wanted, or a yes or no to one), usually silently.
"""

import asyncio
import time
from collections.abc import Callable
from datetime import UTC, datetime

from app.contracts import (
    AgentNote, Audience, ChangeStatus, CrewAgent, Fact, FactChanged, FactConflict, FactRecorded, JudgeSpeak,
    MemoryQueries, Role, SpeakReason, TranscriptLine, new_id,
)
from app.mouth import agent, moments, tuning
from app.mouth.agent import Agent, Turn
from app.mouth.deal_call import ADDRESSED, DealCall, _Job
from app.mouth.tools import Tools


# Moments about one agreed term, released while a change to that term waits for both to say yes.
_ABOUT_A_TERM = (SpeakReason.CONTRADICTS_RECORD, SpeakReason.CHANGE_PROPOSED, SpeakReason.WRAPPING_UP)
# The brain's answers to a line: they join a turn already under way for that line.
_ANSWERS = (SpeakReason.ADDRESSED_DIRECTLY, SpeakReason.UNANSWERED_QUESTION, SpeakReason.READ_BACK)
# Moments that only make sense right after the line they follow: dropped once someone has spoken since.
_OF_THE_MOMENT = (SpeakReason.OPEN_TERMS.value, SpeakReason.UNANSWERED_QUESTION.value)
# A brain answer whose question asks for a recording (app/brain/judge.py ROUTE["recording"]).
_WANTS_RECORDING = "hear a recording"
# Waiting for their pause, these give way to a recording someone asked for.
_GIVES_WAY = ("follow_up", SpeakReason.CHANGE_PROPOSED.value, *_OF_THE_MOMENT)

class AgentCall(DealCall):
    def __init__(self, *args, memory: Callable[[], MemoryQueries | None] = lambda: None) -> None:
        self._memory = memory
        self.facts: dict[str, Fact] = {}
        self.lines: list[TranscriptLine] = []
        self._addressed: dict[int, _Job] = {}  # by the line that spoke to Gawah
        self._follow_left = 0  # lines still to check for an answer
        self._follow_about = ""  # the contradiction put to them, while no change is open
        self._follow_queued = False
        self._follow_job: _Job | None = None
        self._clip_offer: tuple[str, int] | None = None  # the fact whose recording was offered, and lines left to say yes
        self._offered: tuple[str, int] | None = None  # the recording last offered, and the line it was offered after
        self._clips: dict[str, asyncio.Task] = {}  # fact id -> its clip, fetched when it was offered
        self._lead_in: bytes | None = None
        super().__init__(*args)

    def _connect(self, make_link: Callable):
        self.tools = Tools(self.deal_id, self._memory, self.facts, self.names, self.lines, self.log)
        self.agent = Agent(self.tools, self.names, self.log)
        self.agent.link = make_link(agent.config(self.names), self.agent.on_event, self.log)
        return self.agent.link

    # ---- what happens on the call ----

    def on_speak(self, event: JudgeSpeak) -> None:
        if event.item and event.reason in _ABOUT_A_TERM and any(
            c.event.item == event.item for c in self.tools.open_changes()
        ):
            # A change to this term is waiting for both to say yes. The brain sees the new figure as a
            # contradiction until then; replaying the old one would take the turn that records the yes.
            return self._drop(_Job(event.instruction, False, event, event.reason.value, event.to), "a change to it is open")
        if self._follow_job and self._follow_job.spoke is None and not self._follow_job.playing:
            self._follow_job.superseded = True  # the brain's moment comes first; it reads the same lines
        addressed = event.reason in _ANSWERS
        linked = self._addressed.get(event.after_line) if addressed else None
        offered = self._recent_offer()
        if not linked and addressed and offered and _WANTS_RECORDING in event.instruction:
            # The brain read the line as asking for the recording that was offered: play it now.
            linked = self._clip_job(offered, event.after_line, event.to, Role(event.to.value) if event.to in (Audience.HIRER, Audience.WORKER) else None)
        if linked:
            # The line named Gawah and its turn is already under way: this judge.speak is that turn.
            if linked.spoke is None:
                linked.speak = event
            else:
                self.bus.publish(linked.spoke.model_copy(update={
                    "speak_id": event.event_id, "event_id": new_id(), "ts": datetime.now(UTC),
                }))
            return
        line = next((line for line in self.lines if line.line_no == event.after_line), None)
        situation = moments.moment(event, self.names, self.facts, line.text if line else None, self.checklist)
        ack = event.reason is SpeakReason.ADDRESSED_DIRECTLY
        job = _Job(situation, event.reason is SpeakReason.WRAPPING_UP, event, event.reason.value, event.to, ack=ack, line=line)
        if addressed and event.after_line is not None:
            self._addressed[event.after_line] = job
        self._jobs.put_nowait(job)

    async def on_line(self, event: TranscriptLine) -> None:
        if event.call_no != self.call_no:
            return
        self._stop_if_told(event)
        if event.line_no is None:
            event = event.model_copy(update={"line_no": len(self.lines) + 1})
        self.lines.append(event)
        await self.agent.hear(moments.line(event, self.names))
        offer = self._clip_offer
        if offer:
            left = offer[1] - 1
            self._clip_offer = None if left <= 0 or moments.declines_clip(event.text) else (offer[0], left)
        offered = self._recent_offer()
        if offer and moments.wants_clip(event.text) or offered and moments.asks_for_clip(event.text):
            # A yes to the offer, or asking for that recording (by name or not): it is played first, at the next pause.
            self._clip_offer = None
            self._clip_job(offer[0] if offer else offered, event.line_no, Audience(event.speaker.value), event.speaker)
        elif moments.addresses_gawah(event.text):
            job = _Job(moments.addressed_moment(event, self.names, self.checklist), False, None, ADDRESSED,
                       Audience(event.speaker.value), ack=True, line=event)
            self._addressed[event.line_no] = job
            self._note(f"heard its name: {self.names.of(event.speaker)} asked something", line_nos=[event.line_no])
            self._jobs.put_nowait(job)
        elif self._waiting_for() and not self._follow_queued:
            self._follow_left -= 1
            self._follow_queued = True  # one queued is enough: it reads every line up to when it starts
            self._follow_job = _Job("", False, None, "follow_up", Audience.BOTH)
            self._jobs.put_nowait(self._follow_job)

    async def on_fact(self, event: FactRecorded | FactConflict) -> None:
        if isinstance(event, FactRecorded):
            self.facts[event.fact.id] = event.fact
            await self.agent.note(tuning.FACT_NOTE.format(fact=moments.fact(event.fact, self.names)))
        else:
            await self.agent.note(moments.conflict(event))

    def _recent_offer(self) -> str | None:
        """The recording last offered, while it can still be asked for."""
        if self._offered is None:
            return None
        last = self.lines[-1].line_no if self.lines else 0
        return self._offered[0] if (last or 0) - self._offered[1] <= tuning.CLIP_ASKED_LINES else None

    def _clip_job(self, fact_id: str, line_no: int | None, to: Audience | None, who: Role | None) -> _Job:
        """The recording they asked for: the made lead-in, then the clip, at the next pause, ahead of
        anything else still waiting for one."""
        name = self.names.of(who)
        self._note(f"{name} asked to hear the recording", fact_ids=[fact_id], line_nos=[line_no] if line_no else [])
        job = _Job(moments.clip_moment(name, fact_id), False, None, "clip", to or Audience.BOTH, fact_id=fact_id)
        if line_no is not None:
            self._addressed[line_no] = job
        self._fetch_clip(fact_id)
        current = self._current
        if current and not current.playing and current.kind in _GIVES_WAY:
            current.superseded = True  # the brain asks it again at the next pause
        waiting = []
        while not self._jobs.empty():
            waiting.append(self._jobs.get_nowait())
        for queued in [job, *waiting]:
            self._jobs.put_nowait(queued)
        return job

    def _fetch_clip(self, fact_id: str) -> None:
        if fact_id not in self._clips:
            self._clips[fact_id] = asyncio.create_task(self.tools.run("play_clip", {"fact_id": fact_id}))

    def _stale(self, job: _Job) -> bool:
        last = self.lines[-1].line_no if self.lines else None
        return job.kind in _OF_THE_MOMENT and bool(job.speak) and last is not None and last > (job.speak.after_line or 0)

    def _waiting_for(self, queued: bool = False) -> str | None:
        """What Gawah is waiting to hear an answer about, if anything. queued: for a check already
        queued for a line inside the window, whose count it has used."""
        if self._follow_left <= 0 and not queued:
            return None
        changes = self.tools.open_changes()
        if changes:
            change = changes[-1]
            c = change.event
            waiting = " and ".join(self.names.of(r) for r in Role if r not in c.confirmed_by)
            item = tuning.LABEL[c.item] if c.item else "the term"
            return tuning.FOLLOW_UP_CHANGE.format(change=c.change_id, item=item, old=change.old, new=c.new_value, waiting=waiting)
        return self._follow_about or None

    # ---- the floor's hooks ----

    async def _before_opening(self) -> None:
        """Make the acknowledgement once, so it costs no model time when Gawah is spoken to."""
        try:
            turn = await self.agent.say_once(tuning.ACK_MAKE)
            while not turn.complete and not turn.stalled():
                await asyncio.sleep(tuning.TICK_S)
        except Exception:
            self.log.exception("no acknowledgement")
            return
        if turn.audio and not turn.failed:
            self._ack = bytes(turn.audio) + bytes(tuning.RATE * tuning.ACK_GAP_MS // 1000 * 2)
        try:
            lead = await self.agent.say_once(tuning.LEAD_IN_MAKE)
            while not lead.complete and not lead.stalled():
                await asyncio.sleep(tuning.TICK_S)
        except Exception:
            self.log.exception("no lead-in for a recording")
            return
        if lead.audio and not lead.failed:
            self._lead_in = bytes(lead.audio)

    def _opening(self) -> str:
        return moments.opening(self.names)

    def _wait_s(self, job: _Job) -> float:
        return tuning.WAIT_S.get(job.kind, tuning.PAUSE_WAIT_S)

    async def _say(self, job: _Job) -> None:
        if job.kind == "follow_up":
            # It reads every line up to now, so its wait for a pause starts now, not when it was queued.
            self._follow_queued = False
            job.arrived = time.monotonic()
        await super()._say(job)

    async def _prepare(self, job: _Job) -> Turn | None:
        if job.kind == "follow_up":
            about = self._waiting_for(queued=True)
            if about is None:
                return None
            job.instruction = moments.follow_up(about, self.names)
        if job.kind == SpeakReason.CONTRADICTS_RECORD.value:
            # The record and the offer of its recording; the recording plays only on a yes (on_line).
            return await self.agent.turn(job.instruction, use_tools=False)
        if job.kind == "clip":
            return await self._clip_turn(job)
        if job.kind in (SpeakReason.OPEN_TERMS.value, SpeakReason.READ_BACK.value):
            return await self.agent.turn(job.instruction, use_tools=False)  # the terms are in the Judge's note
        if job.kind in ("follow_up", SpeakReason.CHANGE_PROPOSED.value):
            # A change: propose it (or record a yes already said), then ask both. It needs the tools.
            return await self.agent.turn(job.instruction, first_choice="required", speak_after={"propose_change", "confirm_change"})
        if job.kind in (ADDRESSED, SpeakReason.UNANSWERED_QUESTION.value):
            if job.line is not None:  # the checklist as it is now, and the Judge's note if it has come
                job.instruction = (
                    moments.moment(job.speak, self.names, self.facts, job.line.text, self.checklist) if job.speak
                    else moments.addressed_moment(job.line, self.names, self.checklist)
                )
            return await self.agent.turn(job.instruction, first_choice="required", answers=True)  # look it up first, then speak
        # The opening, and a question the brain wants asked: nothing to look up, only the words to choose.
        return await self.agent.turn(job.instruction, use_tools=False)

    async def _clip_turn(self, job: _Job) -> Turn:
        """The lead-in made at the start of the call and the clip fetched when it was offered: no model
        round trip, so the recording starts at the first pause. Without them, the model says a lead-in."""
        self._fetch_clip(job.fact_id)
        result = await self._clips.pop(job.fact_id)
        if not result.clip or self._lead_in is None:
            return await self.agent.turn(job.instruction, use_tools=False, then=[("clip", job.fact_id)])
        turn = Turn(job.instruction, use_tools=False)
        turn.audio.extend(self._lead_in + result.clip)
        turn.first_audio_at = turn.last_audio_at = time.monotonic()
        turn.text, turn.clip_fact_id, turn.effects, turn.complete = f"{tuning.LEAD_IN} [clip]", job.fact_id, list(result.effects), True
        await self.agent.note(result.output)
        return turn

    async def _cancel(self, utterance: Turn, heard_ms: float | None = None) -> None:
        await self.agent.cancel(utterance, heard_ms)

    def _drop(self, job: _Job, why: str, utterance: Turn | None = None) -> None:
        if utterance is not None:
            # A silent turn is carried out (a yes recorded quietly); a dropped one only keeps its notes.
            for event in utterance.effects:
                if why == "stayed silent" or isinstance(event, AgentNote):
                    self._carry_out(event)
        super()._drop(job, why, utterance)

    def _carry_out(self, event) -> None:
        if isinstance(event, FactChanged):
            self.tools.changed(event)
            if event.status in (ChangeStatus.CONFIRMED_BOTH, ChangeStatus.WITHDRAWN):
                self._follow_left, self._follow_about = 0, ""
            else:
                self._follow_left = tuning.FOLLOW_UP_LINES
        self.bus.publish(event)

    def _starting(self, job: _Job, utterance: Turn) -> None:
        for event in utterance.effects:
            self._carry_out(event)
        if job.kind != "clip":
            self._clip_offer = None  # Gawah has moved on: a "haan" now answers what it says next
        if job.kind == SpeakReason.CONTRADICTS_RECORD.value and not self.tools.open_changes():
            self._follow_left = tuning.FOLLOW_UP_LINES
            self._follow_about = tuning.FOLLOW_UP_CONTRADICTION.format(facts=", ".join(job.speak.fact_ids))
            if job.speak.fact_ids:
                self._clip_offer = (job.speak.fact_ids[0], tuning.CLIP_OFFER_LINES)
                last = self.lines[-1].line_no if self.lines else 0
                self._offered = (job.speak.fact_ids[0], max(job.speak.after_line or 0, last or 0))
                self._fetch_clip(job.speak.fact_ids[0])
        if job.kind == "clip" and self._follow_about:
            self._follow_left = tuning.FOLLOW_UP_LINES  # heard the record: do they still want the new value?

    async def _play_ack(self) -> float:
        started = await super()._play_ack()
        self._note(f"said '{tuning.ACK}'")
        return started

    def _said(self, job: _Job) -> None:
        # Only a turn the brain asked for goes out as judge.spoke: the brain takes a judge.spoke it
        # did not ask for as the answer to its last judge.speak. Gawah's own turns show as notes.
        if job.speak or job.kind == "opening":
            super()._said(job)
        clip = job.spoke.clip_fact_id
        self._note(f"said: {job.spoke.text[:160]}", fact_ids=[clip] if clip else [])

    def _note(self, text: str, fact_ids: list[str] | None = None, line_nos: list[int] | None = None) -> None:
        self.bus.publish(AgentNote(deal_id=self.deal_id, agent=CrewAgent.GAWAH, text=text, fact_ids=fact_ids or [],
                                   line_nos=line_nos or []))
