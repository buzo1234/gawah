"""One deal call: follows the transcript and the memory's facts, keeps the checklist, asks
the Judge rules what to say. Everything here runs on the event loop, one event at a time.

The checklist comes from the facts (facts.py). Sage2 only says when to look: someone spoke
to Gawah, a topic was left, the balance was skipped, they are wrapping up. Contradictions
come from the memory as fact.conflict. Whether a newly agreed term can be heard two ways
is one small model call, off the line's path.
"""

import asyncio
from dataclasses import dataclass

from app.brain import sage, tuning
from app.brain.closing import Closing
from app.brain.facts import Terms
from app.brain.judge import Ambiguity, Conflict, Judge, Proposal, View
from app.brain.names import People
from app.brain.sage import Answers, Decisions, yes
from app.brain.values import TERMS, Kind, Values
from app.bus import Bus
from app.contracts import (
    CallKind,
    CallStarted,
    ChecklistUpdated,
    Fact,
    FactConflict,
    FactKind,
    FactStatus,
    ItemKey,
    ItemState,
    JudgeSpeak,
    JudgeSpoke,
    Person,
    Role,
    SpeakReason,
    TranscriptLine,
)
from app.log import deal_log


@dataclass
class _Line:
    no: int
    speaker: Role
    text: str
    end: float


def _text(value: object, limit: int = 300) -> str | None:
    """One clean line of model output, or None."""
    if not isinstance(value, (str, int, float)) or isinstance(value, bool):
        return None
    return " ".join(str(value).split())[:limit] or None


def _item(value: object) -> ItemKey | None:
    try:
        return ItemKey(value)
    except ValueError:
        return None


class Session:
    def __init__(
        self, started: CallStarted, bus: Bus, decisions: Decisions, values: Values, mode: str,
        terms: Terms, checked: set[str],
    ) -> None:
        self.deal_id = started.deal_id
        self.call_no = started.call_no
        self.log = deal_log("gawah.brain", self.deal_id)
        self.bus, self.decisions, self.values = bus, decisions, values
        self.room = started.room
        self.who = People(started.people)
        self.naming = False
        self.judge = Judge(mode)
        self.terms = terms
        self.checked = checked  # fact ids already checked for two meanings, on any call of the deal
        self.at_start = {key: terms.signature(key) for key in ItemKey}
        self.items = {key: terms.item(key) for key in ItemKey}
        self.current_ids = {key: (f.id if (f := terms.current(key)) else None) for key in ItemKey}
        self.conflict_against: dict[str, str | None] = {}  # conflict id -> the term's current fact then
        self.facts_heard = 0  # facts the memory sent from this call's lines
        self.lines: list[_Line] = []
        self.answers: Answers = {}
        self.conflicts: list[Conflict] = []
        self.ambiguities: list[Ambiguity] = []
        self.unclear: ItemKey | None = None
        self.unclear_looked_up = False
        self.speaks: dict[str, JudgeSpeak] = {}
        self.topics_of: dict[str, list[str]] = {}  # judge.speak id -> its topics
        self.wrapping_up = False
        self.closing = False  # the latest line, or the silence after it, says they are wrapping up
        self.ending = Closing()
        self.tasks: set[asyncio.Task] = set()
        self.ended = False

    # ---- events ----

    async def start(self) -> None:
        self.answers = await self.decisions.open(sage.preamble(self.who.all)) or {}
        agreed = [key.value for key, item in self.items.items() if item.state is ItemState.AGREED]
        if self.call_no > 1:
            self.log.info("call %s starts with %s agreed: %s", self.call_no, len(agreed), ", ".join(agreed) or "nothing")
        self._publish_checklist([])

    async def on_line(self, event: TranscriptLine) -> None:
        line = _Line(event.line_no or len(self.lines) + 1, event.speaker, event.text, event.end)
        self.lines.append(line)
        got = await self.decisions.append(line.no, sage.line_text(self.who.sage_names[line.speaker], line.text))
        if got is None:
            self.log.info("line %s: no answer from sage2", line.no)
            # Keep what we knew, but "did the last line speak to Gawah" is not about this line.
            got = {**self.answers, "addressed_gawah": None}
        else:
            self.log.info("line %s: sage2 yes to %s", line.no, ", ".join(q for q in got if yes(got, q)) or "nothing")
        self.answers = got

        self._closing_signal()
        await self._find_unclear_item()
        self._look_for_names()
        self._decide()
        self._wait_for_silence()
        # A reply that is already there (a recorded one) lands before the next line.
        await asyncio.sleep(0)

    def on_fact(self, fact: Fact) -> None:
        """A fact.recorded for this deal, already taken into self.terms."""
        if fact.call_no == self.call_no and fact.line_no is not None:
            self.facts_heard += 1
        if fact.kind is FactKind.CHANGE:
            self._said_change(fact)
        if fact.item is None or fact.kind is not FactKind.TERM:
            return
        key = fact.item
        current = self.terms.current(key)
        settled = current is not None and (current.status is FactStatus.CONFIRMED or current.replaces is not None)
        moved = [c for c in self.conflicts if c.item == key and settled and current.id != self.conflict_against[c.id]]
        if moved:
            # Both confirmed a value since (a change both confirmed, or a confirmation): the
            # record settles it. A plain "theek hai" to the different figure does not.
            self.conflicts = [c for c in self.conflicts if c not in moved]
            self.log.info("%s confirmed after the contradiction: no longer open", key.value)
        self._refresh(key)
        if key is ItemKey.AMOUNT:
            self._refresh(ItemKey.WORK)  # the work is agreed with the price
        if current and current.id != self.current_ids[key]:
            self._check_two_ways(current)
        self.current_ids[key] = current.id if current else None
        self._decide()

    def on_conflict(self, event: FactConflict) -> None:
        held = [self.terms.latest[i] for i in event.fact_ids if i in self.terms.latest]
        item = next((f.item for f in held if f.item), None)
        self._open(Conflict(
            id=event.event_id, item=item, fact_ids=list(event.fact_ids), explanation=event.explanation,
            said=event.said, speaker=event.speaker, line_no=event.line_no,
        ))

    def _said_change(self, fact: Fact) -> None:
        """A change to an agreed term's figure, said on this call and not yet confirmed by both.
        Added details ("do ladke aur lagaunga") are not worth stopping a call for."""
        current = self.terms.current(fact.item) if fact.item else None
        cid = f"change:{fact.id}"
        if current is None or fact.call_no != self.call_no or any(c.id == cid for c in self.conflicts):
            return
        rupees = fact.value_rupees is not None and fact.value_rupees != current.value_rupees
        if fact.item is ItemKey.AMOUNT and fact.value_rupees == 0:
            return  # a job's total is never nothing: "free mein" is an addition at no cost
        # The dates term holds a start and a finish, so one day is not compared with another
        # (memory does not either); a date change comes as a fact.conflict from its model.
        day = fact.item is not ItemKey.DATES and fact.value_date is not None and current.value_date is not None
        if not (rupees or (day and fact.value_date != current.value_date)):
            return
        if fact.status not in (FactStatus.SAID, FactStatus.AGREED) or cid in self.conflict_against:
            return
        was = current.value or current.text
        where = f" (call {current.call_no}, line {current.line_no})" if current.line_no else ""
        self._open(Conflict(
            id=cid, item=fact.item, fact_ids=[current.id, fact.id],
            explanation=f"agreed as {was}{where}; now said as {fact.value or fact.text}.",
            said=fact.quote, speaker=fact.said_by, line_no=fact.line_no, change=True,
        ))

    def _open(self, conflict: Conflict) -> None:
        self.conflicts.append(conflict)
        item = conflict.item
        current = self.terms.current(item) if item else None
        self.conflict_against[conflict.id] = current.id if current else None
        what = "change" if conflict.change else "contradiction"
        self.log.info("%s at line %s about %s: %s", what, conflict.line_no, item.value if item else "-", conflict.explanation)
        if item:
            self._refresh(item)
        self._decide()

    def on_spoke(self, event: JudgeSpoke) -> None:
        # Gawah also speaks on its own (answers, follow-ups): only our own judge.speaks count here.
        speak = self.speaks.get(event.speak_id or "")
        if speak is None:
            return
        now = self.lines[-1].end if self.lines else 0.0
        if not event.text and event.start is None:
            # The mouth dropped it unsaid: stop waiting, and do not count it as a question heard.
            self.judge.dropped(self.topics_of.get(speak.event_id, []), speak.reason, now)
            return
        self.judge.spoke(max(now, event.end or 0.0), speak.reason is not SpeakReason.ADDRESSED_DIRECTLY)

    def meet(self, people: list[Person]) -> None:
        """call.started again for this call: take any name we did not have."""
        self.who.meet(people)

    async def end(self) -> None:
        self.ended = True
        self.ending.stop()
        await self.decisions.close()
        if self.tasks:
            _, late = await asyncio.wait(self.tasks, timeout=tuning.END_WAIT_S)
            for task in late:
                task.cancel()
        self.log.info("call %s ended after %s lines; judge spoke %s times", self.call_no, len(self.lines), len(self.speaks))

    async def idle(self) -> None:
        """Wait for model replies still on their way. For tests."""
        while self.tasks:
            await asyncio.wait(self.tasks)

    # ---- the checklist ----

    def _refresh(self, key: ItemKey) -> None:
        note = next((
            f"{'change said' if c.change else 'contradicted'} at line {c.line_no}: {c.explanation}"
            for c in self.conflicts if c.item == key
        ), None)
        item = self.terms.item(key, note)
        if item != self.items[key]:
            if item.state is ItemState.AGREED and self.items[key].state is ItemState.PENDING and self.lines:
                self.ending.settled_on.add(self.lines[-1].no)  # a term settled is no goodbye (closing.py)
            self.items[key] = item
            self._publish_checklist([key])

    def _changed(self) -> set[ItemKey]:
        return {key for key in ItemKey if self.terms.signature(key) != self.at_start[key]}

    def _agreed(self) -> int:
        return sum(item.state is ItemState.AGREED for item in self.items.values())

    def _discussed(self) -> int:
        """Agreed, or stated and waiting only for the other's yes: the Scribe hears fewer
        yeses than were said. For the silence rule only (CLOSE_MIN_DISCUSSED)."""
        return sum(item.state is ItemState.AGREED or self.terms.proposal(key) is not None for key, item in self.items.items())

    def _publish_checklist(self, changed: list[ItemKey]) -> None:
        self.bus.publish(
            ChecklistUpdated(
                deal_id=self.deal_id, items=[item.model_copy() for item in self.items.values()], changed=changed
            )
        )

    # ---- two meanings ----

    def _check_two_ways(self, fact: Fact) -> None:
        if fact.id in self.checked or fact.item is None or not self.lines:
            return
        self.checked.add(fact.id)
        self._spawn(self._two_ways(fact, self._transcript(), fact.line_no or self.lines[-1].no))

    async def _two_ways(self, fact: Fact, transcript: str, at_line: int) -> None:
        assert fact.item is not None
        value = fact.value or fact.text
        asked = f'{transcript}\n\nAgreed term: {TERMS[fact.item]}.\nAgreed value: {value}\nWords: "{fact.quote or ""}"'
        try:
            got = await self.values.lookup("ambiguous", fact.item, asked, at_line) or {}
        except Exception as e:
            self.log.warning("two-meanings check failed for %s (%s: %s)", fact.item.value, type(e).__name__, str(e)[:200])
            return
        readings = [r for r in map(lambda v: _text(v, 120), got.get("readings") or []) if r][:2]
        if got.get("ambiguous") is not True or len(readings) != 2 or self.ended:
            return
        if self.terms.current(fact.item) is None or self.terms.current(fact.item).id != fact.id:
            return  # the term moved on while the model was reading
        self.log.info("%s can be heard two ways: %s / %s", fact.item.value, *readings)
        self.ambiguities.append(Ambiguity(fact.item, fact.id, value, readings))
        self._decide()

    # ---- the end of the call ----

    def _closing_signal(self) -> None:
        self.closing = self.ending.on_line(self.answers, self.lines[-1].no, self._agreed())
        if self.closing and not self.wrapping_up:
            self.log.info("wrapping up at line %s", self.lines[-1].no)
        self.wrapping_up = self.wrapping_up or self.closing

    def _wait_for_silence(self) -> None:
        """closing_soon on the latest line: if nobody says anything more, they are done.
        Not while Gawah is about to talk, which is no silence."""
        quiet = not self.closing and self.judge.waiting_since is None
        due = quiet and Closing.silence_would_close(self.answers, self._discussed())
        self.ending.wait(self._so_far() if due else None, self.silence_passed)

    def _so_far(self) -> tuple[int, int]:
        return len(self.lines), len(self.speaks)

    def silence_passed(self) -> None:
        """CLOSING_SILENCE_S has gone by with no new line. The timer calls this; a test replaying a call may too."""
        if self.ended or not self.ending.silence_passed(self._so_far()) or self.judge.waiting_since is not None:
            return
        self.log.info("wrapping up: silence after line %s", self.lines[-1].no)
        self.closing = self.wrapping_up = True
        self._decide(silence=tuning.CLOSING_SILENCE_S)
        self.closing = False

    # ---- names, and the term left unclear ----

    def _look_for_names(self) -> None:
        if self.who.unknown() and not self.naming and len(self.lines) <= tuning.NAME_LINES:
            self.naming = True
            self._spawn(self._fetch_names(self._transcript(), self.lines[-1].no))

    async def _fetch_names(self, transcript: str, at_line: int) -> None:
        learned = await self.who.ask(self.values, transcript, at_line, self.log)
        self.naming = False
        if learned and not self.ended:
            # call.started is the event the store, the dashboard and the mouth take people from.
            # Sent again for the same room it only fills in names (brain, mouth, dashboard).
            self.bus.publish(CallStarted(
                deal_id=self.deal_id, people=self.who.all, kind=CallKind.DEAL, room=self.room, call_no=self.call_no,
            ))

    def _spawn(self, work) -> None:
        task = asyncio.create_task(work)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def _find_unclear_item(self) -> None:
        """Sage2 says a term was asked about and left unclear, but not which one.
        It also says so about a term that was contradicted; that case has its own rule."""
        if not yes(self.answers, "topic_left_unclear"):
            self.unclear, self.unclear_looked_up = None, False
            return
        if self.conflicts or self.unclear_looked_up or self.judge.mode != "live":
            return
        self.unclear_looked_up = True
        key = _item((await self._lookup_now("unclear", None) or {}).get("item"))
        if key and self.items[key].state is ItemState.PENDING:
            self.unclear = key

    async def _lookup_now(self, kind: Kind, item: ItemKey | None) -> dict | None:
        """A lookup the Judge's next question waits for, but not for long."""
        try:
            async with asyncio.timeout(tuning.LOOKUP_WAIT_S):
                return await self.values.lookup(kind, item, self._transcript(), self.lines[-1].no)
        except Exception as e:
            self.log.warning("%s lookup gave nothing (%s: %s)", kind, type(e).__name__, str(e)[:200])
            return None

    def _transcript(self) -> str:
        head = sage.preamble(self.who.all)
        return head + "\n".join(f"{line.no}. {self.who.names[line.speaker]}: {line.text}" for line in self.lines)

    # ---- the Judge ----

    def _proposals(self) -> dict[ItemKey, Proposal]:
        suspect = frozenset((self.call_no, c.line_no) for c in self.conflicts)
        found = {}
        for key, item in self.items.items():
            stated = self.terms.proposal(key, suspect) if item.state is ItemState.PENDING else None
            if stated:
                words, facts = stated
                speakers = {f.said_by for f in facts}
                found[key] = Proposal(words, speakers.pop() if len(speakers) == 1 else None, facts[0].id)
        return found

    def _decide(self, silence: float = 0.0) -> None:
        if self.ended or not self.lines:
            return
        line = self.lines[-1]
        view = View(
            now=line.end + silence, closing=self.closing, speaker=line.speaker, text=line.text, answers=self.answers,
            items=self.items, unclear=self.unclear, names=self.who.names, conflicts=self.conflicts,
            proposals=self._proposals(),
            ambiguities=self.ambiguities, follow_up=self.call_no > 1, changed=self._changed(),
            memory_silent=self.facts_heard == 0 and len(self.lines) >= tuning.MEMORY_SILENT_LINES,
        )
        speak = self.judge.decide(view)
        if speak is None:
            return
        event = JudgeSpeak(
            deal_id=self.deal_id, instruction=speak.instruction, to=speak.to, reason=speak.reason,
            item=speak.item, after_line=line.no, fact_ids=speak.fact_ids, question=speak.question,
        )
        self.speaks[event.event_id] = event
        self.topics_of[event.event_id] = speak.topics
        self.log.info("judge.speak after line %s: %s %s", line.no, speak.reason.value, speak.item.value if speak.item else "-")
        self.bus.publish(event)
