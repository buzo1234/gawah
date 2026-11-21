"""Gawah the agent on one deal call (JUDGE_MODE=live), on the plain voice's floor control.

- Every transcript line goes into the agent's conversation, labelled with who said it, and
  every fact and contradiction from memory as a short note.
- A judge.speak hands the agent a situation (moments.py); the agent picks the words and
  any tools (tools.py).
- A line that names Gawah is a moment of its own: "Haan ji, ek second" at the next pause,
  then the answer. The brain's own addressed judge.speak for that line joins the same turn.
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
        super().__init__(*args)

    def _connect(self, make_link: Callable):
        self.tools = Tools(self.deal_id, self._memory, self.facts, self.names, self.lines, self.log)
        self.agent = Agent(self.tools, self.names, self.log)
        self.agent.link = make_link(agent.config(self.names), self.agent.on_event, self.log)
        return self.agent.link

    # ---- what happens on the call ----

    def on_speak(self, event: JudgeSpeak) -> None:
        if event.item and event.reason in (SpeakReason.CONTRADICTS_RECORD, SpeakReason.WRAPPING_UP) and any(
            c.event.item == event.item for c in self.tools.open_changes()
        ):
            # A change to this term is waiting for both to say yes. The brain sees the new figure as a
            # contradiction until then; replaying the old one would take the turn that records the yes.
            return self._drop(_Job(event.instruction, False, event, event.reason.value, event.to), "a change to it is open")
        if self._follow_job and self._follow_job.spoke is None and not self._follow_job.playing:
            self._follow_job.superseded = True  # the brain's moment comes first; it reads the same lines
        addressed = event.reason is SpeakReason.ADDRESSED_DIRECTLY
        linked = self._addressed.get(event.after_line) if addressed else None
        if linked:
            # The line named Gawah and its turn is already under way: this judge.speak is that turn.
            if linked.spoke is None:
                linked.speak = event
            else:
                self.bus.publish(linked.spoke.model_copy(update={
                    "speak_id": event.event_id, "event_id": new_id(), "ts": datetime.now(UTC),
                }))
            return
        question = next((line.text for line in self.lines if line.line_no == event.after_line), None)
        situation = moments.moment(event, self.names, self.facts, question)
        job = _Job(situation, event.reason is SpeakReason.WRAPPING_UP, event, event.reason.value, event.to, ack=addressed)
        if addressed and event.after_line is not None:
            self._addressed[event.after_line] = job
        self._jobs.put_nowait(job)

    async def on_line(self, event: TranscriptLine) -> None:
        if event.call_no != self.call_no:
            return
        if event.line_no is None:
            event = event.model_copy(update={"line_no": len(self.lines) + 1})
        self.lines.append(event)
        await self.agent.hear(moments.line(event, self.names))
        if moments.addresses_gawah(event.text):
            job = _Job(moments.addressed_moment(event, self.names), False, None, ADDRESSED, Audience(event.speaker.value), ack=True)
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

    def _waiting_for(self) -> str | None:
        """What Gawah is waiting to hear an answer about, if anything."""
        if self._follow_left <= 0:
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
            about = self._waiting_for()
            if about is None:
                return None
            job.instruction = moments.follow_up(about, self.names)
        if job.kind == SpeakReason.CONTRADICTS_RECORD.value:
            # A fixed order, so the clip always comes between what was agreed and the question.
            facts = job.speak.fact_ids if job.speak else []
            then = [("clip", facts[0])] if facts else []
            return await self.agent.turn(job.instruction, use_tools=False, then=then + [("say", moments.contradiction_ask(job.speak, self.names))])
        if job.kind == "follow_up":
            return await self.agent.turn(job.instruction, first_choice="required", speak_after={"propose_change", "confirm_change"})
        if job.kind == ADDRESSED:
            return await self.agent.turn(job.instruction, first_choice="required")  # look it up first, then speak
        # The opening, and a question the brain wants asked: nothing to look up, only the words to choose.
        return await self.agent.turn(job.instruction, use_tools=False)

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
        if job.kind == SpeakReason.CONTRADICTS_RECORD.value and not self.tools.open_changes():
            self._follow_left = tuning.FOLLOW_UP_LINES
            self._follow_about = tuning.FOLLOW_UP_CONTRADICTION.format(facts=", ".join(job.speak.fact_ids))

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
