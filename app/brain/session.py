"""One deal call: follows the transcript, keeps the checklist, asks the Judge rules
what to say. Everything here runs on the event loop, one event at a time."""

import asyncio
from dataclasses import dataclass

from app.brain import sage, tuning
from app.brain.closing import Closing
from app.brain.judge import Judge, View
from app.brain.names import People
from app.brain.sage import Answers, Decisions, yes
from app.brain.values import Kind, Values
from app.bus import Bus
from app.contracts import (
    CallKind,
    CallStarted,
    ChecklistItem,
    ChecklistUpdated,
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

ITEM_QUESTION: dict[ItemKey, str] = {
    ItemKey.WORK: "work_agreed",
    ItemKey.AMOUNT: "amount_agreed",
    ItemKey.ADVANCE: "advance_agreed",
    ItemKey.BALANCE: "balance_when",
    ItemKey.DATES: "dates_agreed",
    ItemKey.LATE_OR_UNFINISHED: "late_terms",
}


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
    def __init__(self, started: CallStarted, bus: Bus, decisions: Decisions, values: Values, mode: str) -> None:
        self.deal_id = started.deal_id
        self.log = deal_log("gawah.brain", self.deal_id)
        self.bus, self.decisions, self.values = bus, decisions, values
        self.room = started.room
        self.who = People(started.people)
        self.naming = False
        self.judge = Judge(mode)
        self.items: dict[ItemKey, ChecklistItem] = {key: ChecklistItem(key=key) for key in ItemKey}
        self.lines: list[_Line] = []
        self.answers: Answers = {}
        self.conflicts: dict[ItemKey, list[str]] = {}
        self.conflict_seen = False
        self.unclear: ItemKey | None = None
        self.unclear_looked_up = False
        self.speaks: dict[str, JudgeSpeak] = {}
        self.asked_at_line: dict[ItemKey, int] = {}  # the line count when the Judge finished asking
        self.tries: dict[ItemKey, int] = {}
        self.tried_at_line: dict[ItemKey, int] = {}
        self.fetching: set[ItemKey] = set()
        self.refreshed: set[ItemKey] = set()
        self.wrapping_up = False
        self.closing = False  # the latest line, or the silence after it, says they are wrapping up
        self.ending = Closing()
        self.tasks: set[asyncio.Task] = set()
        self.ended = False

    # ---- events ----

    async def start(self) -> None:
        self.answers = await self.decisions.open(sage.preamble(self.who.all)) or {}
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

        self._latch_agreed_items()
        self._closing_signal()
        if yes(got, "conflicting_figures") and not self.conflict_seen:
            self.conflict_seen = True  # Sage2 keeps saying yes from here on, so one conflict a call
            await self._open_conflict()
        await self._find_unclear_item()
        self._fetch_missing_values()
        self._look_for_names()
        self._decide()
        self._wait_for_silence()
        # A value that is already there (a recorded one) lands before the next line.
        await asyncio.sleep(0)

    def on_spoke(self, event: JudgeSpoke) -> None:
        speak = self.speaks.get(event.speak_id or "") or (list(self.speaks.values()) or [None])[-1]
        if speak is None:
            return
        if not event.text and event.start is None:
            # The mouth dropped it unsaid: stop waiting, and do not count it as a question heard.
            self.judge.dropped(speak.item, speak.reason, self.lines[-1].end if self.lines else 0.0)
            return
        now = self.lines[-1].end if self.lines else 0.0
        self.judge.spoke(max(now, event.end or 0.0), speak.reason is not SpeakReason.ADDRESSED_DIRECTLY)
        if speak.item:
            self.asked_at_line[speak.item] = len(self.lines)

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
        self.log.info("call ended after %s lines; judge spoke %s times", len(self.lines), len(self.speaks))

    async def idle(self) -> None:
        """Wait for values still on their way. For tests."""
        while self.tasks:
            await asyncio.wait(self.tasks)

    # ---- the checklist ----

    def _latch_agreed_items(self) -> None:
        """Once Sage2 says an item is agreed it stays agreed: its answers wobble when a
        second figure is said. An item with two figures stays pending until that is settled."""
        changed = []
        for key, question in ITEM_QUESTION.items():
            item = self.items[key]
            if item.state is ItemState.PENDING and key not in self.conflicts and yes(self.answers, question):
                item.state, item.confidence, item.line_no = ItemState.AGREED, self.answers[question], self.lines[-1].no
                changed.append(key)
                self.ending.settled_on.add(self.lines[-1].no)
        if changed:
            self._publish_checklist(changed)

    # ---- the end of the call ----

    def _closing_signal(self) -> None:
        self.closing = self.ending.on_line(self.answers, self.lines[-1].no, self._agreed())
        if self.closing and not self.wrapping_up:
            self.log.info("wrapping up at line %s", self.lines[-1].no)
        self.wrapping_up = self.wrapping_up or self.closing

    def _agreed(self) -> int:
        return sum(item.state is ItemState.AGREED for item in self.items.values())

    def _wait_for_silence(self) -> None:
        """closing_soon on the latest line: if nobody says anything more, they are done.
        Not while Gawah is about to talk, which is no silence."""
        quiet = not self.closing and self.judge.waiting_since is None
        due = quiet and Closing.silence_would_close(self.answers, self._agreed())
        self.ending.wait(self._so_far() if due else None, self.silence_passed)

    def _so_far(self) -> tuple[int, int]:
        return len(self.lines), len(self.speaks)

    def silence_passed(self) -> None:
        """CLOSING_SILENCE_S has gone by with no new line. The timer calls this; a test replaying a call may too."""
        if self.ended or not self.ending.silence_passed(self._so_far()) or self.judge.waiting_since is not None:
            return
        self.log.info("wrapping up: silence after line %s", self.lines[-1].no)
        self.closing = self.wrapping_up = True
        self._fetch_missing_values()
        self._decide(silence=tuning.CLOSING_SILENCE_S)
        self.closing = False

    # ---- names ----

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
            self.bus.publish(CallStarted(deal_id=self.deal_id, people=self.who.all, kind=CallKind.DEAL, room=self.room))

    def _spawn(self, work) -> None:
        task = asyncio.create_task(work)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def _open_conflict(self) -> None:
        got = await self._lookup_now("conflict", None) or {}
        key = _item(got.get("item"))
        if key is None:
            # The model did not say which. Sage2 drops the item's own answer to no when
            # a second figure is said, so take the agreed money item it no longer says yes to.
            dropped = [
                k for k in (ItemKey.AMOUNT, ItemKey.ADVANCE)
                if self.items[k].state is ItemState.AGREED and not yes(self.answers, ITEM_QUESTION[k])
            ]
            if not dropped:
                # Nothing says which term: guessing would wipe a term both agreed. The
                # read-back and the call-back are there to catch a real second figure.
                self.log.info("two figures said at line %s, but nothing says for which term: left as is", self.lines[-1].no)
                return
            key = dropped[0]
        figures = [f for f in map(lambda v: _text(v, 40), got.get("figures") or []) if f][:2]
        self.conflicts[key] = figures if len(figures) == 2 else []
        self.tries[key] = 0
        item = self.items[key]
        item.state, item.value, item.source_text, item.confidence = ItemState.PENDING, None, None, None
        item.line_no = self.lines[-1].no
        item.note = f"two figures said: {figures[0]} and {figures[1]}" if len(figures) == 2 else "two different figures said"
        self.log.info("two figures said for %s at line %s", key.value, self.lines[-1].no)
        self._publish_checklist([key])

    async def _find_unclear_item(self) -> None:
        """Sage2 says a term was asked about and left unclear, but not which one.
        It also says so about a term with two figures; that case has its own rule."""
        if not yes(self.answers, "topic_left_unclear"):
            self.unclear, self.unclear_looked_up = None, False
            return
        if self.conflicts or self.unclear_looked_up or self.judge.mode != "live":
            return
        self.unclear_looked_up = True
        key = _item((await self._lookup_now("unclear", None) or {}).get("item"))
        if key and self.items[key].state is ItemState.PENDING:
            self.unclear = key

    def _fetch_missing_values(self) -> None:
        n = len(self.lines)
        for key, item in self.items.items():
            if key in self.fetching:
                continue
            spaced = n - self.tried_at_line.get(key, -99) >= tuning.VALUE_RETRY_LINES
            may_try = spaced and self.tries.get(key, 0) < tuning.VALUE_TRIES
            if key in self.conflicts:
                # Worth a look only after the Judge asked and both have had a turn.
                asked = self.asked_at_line.get(key)
                due = may_try and asked is not None and n - asked >= tuning.RESOLVE_AFTER_LINES
                due = due and yes(self.answers, ITEM_QUESTION[key])
            elif item.state is not ItemState.AGREED:
                due = False
            elif item.value is None:
                due = may_try
            else:
                # A value is taken when the item is first agreed, and details are often
                # added later. Take each once more at wrap-up, for the read-back and the contract.
                due = self.wrapping_up and key not in self.refreshed
                if due:
                    self.refreshed.add(key)
            if due:
                self.tries[key] = self.tries.get(key, 0) + 1
                self.tried_at_line[key] = n
                self.fetching.add(key)
                self._spawn(self._fetch_value(key, self._transcript(), self.lines[-1].no, settles_conflict=key in self.conflicts))

    async def _fetch_value(self, key: ItemKey, transcript: str, at_line: int, settles_conflict: bool) -> None:
        try:
            got = await self.values.lookup("value", key, transcript, at_line) or {}
        except Exception as e:
            self.log.warning("value lookup failed for %s (%s: %s)", key.value, type(e).__name__, str(e)[:200])
            got = {}
        finally:
            self.fetching.discard(key)
        value = _text(got.get("value"))
        if value is None or (key in self.conflicts) != settles_conflict:
            return  # not settled, or asked before the second figure was said
        item = self.items[key]
        if settles_conflict:
            del self.conflicts[key]
            item.state, item.note, item.confidence = ItemState.AGREED, None, self.answers.get(ITEM_QUESTION[key])
            self.tries[key] = 0
        line_no = got.get("line_no")
        line_no = line_no if isinstance(line_no, int) and 1 <= line_no <= at_line else at_line
        new = (value, _text(got.get("source_text")), line_no)
        if settles_conflict or new != (item.value, item.source_text, item.line_no):
            item.value, item.source_text, item.line_no = new
            self._publish_checklist([key])
        self._decide()  # the read-back waits for values

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

    def _publish_checklist(self, changed: list[ItemKey]) -> None:
        self.bus.publish(
            ChecklistUpdated(
                deal_id=self.deal_id, items=[item.model_copy() for item in self.items.values()], changed=changed
            )
        )

    # ---- the Judge ----

    def _decide(self, silence: float = 0.0) -> None:
        if self.ended or not self.lines:
            return
        line = self.lines[-1]
        view = View(
            now=line.end + silence, closing=self.closing, speaker=line.speaker, text=line.text, answers=self.answers, items=self.items,
            conflicts=self.conflicts, unclear=self.unclear, values_on_their_way=bool(self.fetching), names=self.who.names,
        )
        speak = self.judge.decide(view)
        if speak is None:
            return
        event = JudgeSpeak(
            deal_id=self.deal_id, instruction=speak.instruction, to=speak.to, reason=speak.reason,
            item=speak.item, after_line=line.no,
        )
        self.speaks[event.event_id] = event
        self.log.info("judge.speak after line %s: %s %s", line.no, speak.reason.value, speak.item.value if speak.item else "-")
        self.bus.publish(event)
