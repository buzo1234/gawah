"""Memory: the fact store and its answers (MemoryQueries), fed by the Scribe and by the
events that move a fact's status. Everything here is rebuilt from the event log."""

import asyncio
import logging
import statistics
import time
from pathlib import Path

import numpy as np

from app.bus import Bus
from app.contracts import (
    CallEnded, CallKind, CallStarted, ChecklistUpdated, CrewAgent, AgentNote, Event, Fact, FactChanged,
    FactConflict, FactKind, FactRecorded, FactSource, FactStatus, ItemKey, OwedRow, RecordConfirmed,
    RecordReceived, Role, TermsConfirmed, TermsDisputed, TermView, TranscriptLine,
)
from app.memory import clips
from app.memory.book import IST, Book, DealBook
from app.memory.chain import first_break
from app.memory.extract import Extractor
from app.memory.normalise import asks_agreed, format_rupees, items_named, search_words
from app.memory.scribe import Scribe
from app.memory.status import Status
from app.memory.vectors import Embedder, Vectors

log = logging.getLogger("gawah.memory")

RANK_BONUS = {
    FactStatus.CONFIRMED: 0.10, FactStatus.AGREED: 0.05, FactStatus.SAID: 0.0,
    FactStatus.DISPUTED: -0.05, FactStatus.SUPERSEDED: -0.10,
}
NOT_COUNTED = {FactStatus.DISPUTED, FactStatus.SUPERSEDED}
LINE_PREFIX = "line~"


class Memory:
    def __init__(
        self, bus: Bus, extractor: Extractor, embedder: Embedder, root: Path,
        cache_dir: Path | None = None, embed_model: str = "text-embedding-3-small",
    ) -> None:
        self.bus, self.extractor, self.root = bus, extractor, root
        self.book = Book()
        self.vectors = Vectors(embedder, cache_dir, embed_model)
        self.scribe = Scribe(self)
        self.status = Status(self)
        self.latency: dict[str, list[float]] = {"fact": [], "conflict": []}
        self.conflicts: list[FactConflict] = []
        self._raised: set[tuple] = set()

    def attach(self, bus: Bus) -> None:
        s = self.status
        for event_type, handler in [
            (CallStarted, self.on_call_started), (CallEnded, self.on_call_ended),
            (TranscriptLine, self.scribe.on_line), (ChecklistUpdated, s.on_checklist),
            (TermsConfirmed, s.on_confirmed), (TermsDisputed, s.on_disputed), (RecordReceived, s.on_record),
            (RecordConfirmed, s.on_record_confirmed), (FactChanged, s.on_changed),
        ]:
            bus.subscribe(event_type, handler)

    def rebuild(self, events: list[Event]) -> None:
        """Back to where the log left off: facts as they were sent, hashes and all."""
        for e in events:
            if isinstance(e, CallStarted | CallEnded):
                self._call(e)
            elif isinstance(e, TranscriptLine) and e.kind == CallKind.DEAL and e.line_no is not None:
                self.book.deal(e.deal_id).lines[(e.call_no, e.line_no)] = e
            elif isinstance(e, FactRecorded):
                self.book.load(e.fact)
            elif isinstance(e, FactConflict):
                self.conflicts.append(e)
        for deal in self.book.deals.values():
            broken = first_break(deal.versions)
            if broken is not None:
                log.warning("deal=%s the witness chain breaks at version %d", deal.deal_id, broken)

    async def settle(self) -> None:
        await self.scribe.settle()

    async def close(self) -> None:
        await self.vectors.close()

    async def on_call_started(self, event: CallStarted) -> None:
        self._call(event)

    async def on_call_ended(self, event: CallEnded) -> None:
        self._call(event)

    def _call(self, event: CallStarted | CallEnded) -> None:
        if event.kind != CallKind.DEAL:
            return
        deal = self.book.deal(event.deal_id)
        call = deal.call(event.call_no)
        if isinstance(event, CallStarted):
            call.started_at, call.room = event.ts, event.room
            deal.learn_people(event)
        else:
            call.recordings.update({Role(k): v for k, v in event.recording_keys.items() if k in Role._value2member_map_})

    # ---------- writing ----------

    def record(self, fact: Fact, received: float | None = None) -> Fact:
        linked = self.book.append(fact)
        self.bus.publish(FactRecorded(deal_id=fact.deal_id, fact=linked))
        self.vectors.want(self.fact_text(linked))
        if received is not None:
            self.latency["fact"].append(time.monotonic() - received)
        return linked

    def conflict(
        self, deal: DealBook, line: TranscriptLine, current: Fact, rupees: int | None, day, value: str | None,
        received: float, confidence: float = 0.95, explanation: str | None = None,
    ) -> None:
        key = (deal.deal_id, line.call_no, current.id, rupees, day, None if rupees or day else value)
        if key in self._raised:
            return
        self._raised.add(key)
        event = FactConflict(
            deal_id=deal.deal_id, fact_ids=[current.id], explanation=explanation or self.explain(deal, line, current, rupees, day, value),
            said=line.text, speaker=line.speaker, call_no=line.call_no, line_no=line.line_no, confidence=confidence,
        )
        self.conflicts.append(event)
        self.bus.publish(event)
        self.latency["conflict"].append(time.monotonic() - received)
        self.note("memory", f"conflict: {event.explanation}", current, line)

    def explain(self, deal: DealBook, line: TranscriptLine, current: Fact, rupees, day, value) -> str:
        item = current.item.value.replace("_", " ") if current.item else "term"
        claimed = format_rupees(rupees) if rupees is not None else day.strftime("%d %B") if day else value or "something else"
        stands = format_rupees(current.value_rupees) if current.value_rupees is not None else current.value or current.text
        both = " by both" if current.said_by and (current.agreed_by or current.confirmed_by) else ""
        when = f" on {(current.valid_from + IST).strftime('%-d %B')}" if current.valid_from else ""
        where = f" (call {current.call_no}, line {current.line_no})" if current.line_no else ""
        text = f"Says {claimed}; the {item} was {current.status.value} at {stands}{both}{when}{where}."
        offer = next((
            f for f in deal.standing()
            if f.item == current.item and f.status == FactStatus.SAID and rupees is not None
            and f.value_rupees == rupees and (f.call_no, f.line_no) != (line.call_no, line.line_no)
        ), None)
        if offer:
            text += f" {claimed} was {deal.name(offer.said_by)}'s offer" + (f" on call {offer.call_no}" if offer.call_no else "") + "."
        return text

    def note(self, agent: str, text: str, fact: Fact | None = None, line: TranscriptLine | None = None) -> None:
        deal_id = fact.deal_id if fact else line.deal_id
        self.bus.publish(AgentNote(
            deal_id=deal_id, agent=CrewAgent(agent), text=text[:160],
            fact_ids=[fact.id] if fact else [], line_nos=[line.line_no] if line and line.line_no else [],
        ))

    def target_for(self, deal: DealBook, kind: FactKind, item: ItemKey | None) -> Fact | None:
        """The term a payment or a piece of work counts towards."""
        if kind == FactKind.WORK:
            return deal.latest_term(ItemKey.WORK)
        if item == ItemKey.ADVANCE:
            return deal.latest_term(ItemKey.ADVANCE) or deal.latest_term(ItemKey.AMOUNT)
        return deal.latest_term(ItemKey.BALANCE) or deal.latest_term(ItemKey.AMOUNT)

    @staticmethod
    def fact_text(fact: Fact) -> str:
        return f"{fact.text} {fact.value or ''} | {fact.quote or ''}"

    @staticmethod
    def line_text(line: TranscriptLine) -> str:
        return f"{line.speaker.value}: {line.text}"

    def line_fact(self, deal: DealBook, line: TranscriptLine) -> Fact:
        return Fact(
            id=f"{LINE_PREFIX}{deal.deal_id}~{line.call_no}~{line.line_no}", deal_id=deal.deal_id,
            text=f"{deal.name(line.speaker)} said: {line.text}", said_by=line.speaker, status=FactStatus.SAID,
            source=FactSource.CALL, quote=line.text, call_no=line.call_no, line_no=line.line_no,
            start=line.start, end=line.end, valid_from=deal.at(line.call_no, line.start),
        )

    # ---------- MemoryQueries ----------

    async def get_term(self, deal_id: str, item: ItemKey) -> TermView:
        deal = self.book.deal(deal_id)
        return TermView(item=item, current=deal.current(item), history=deal.history(item))

    async def owed(self, deal_id: str) -> list[OwedRow]:
        """Amount: every payment counts. Advance: payments towards the advance. Balance: the
        agreed balance figure, or else the amount less the advance; payments towards the
        balance or the amount count."""
        deal = self.book.deal(deal_id)
        agreed = {k: (deal.current(k).value_rupees if deal.current(k) else None) for k in (ItemKey.AMOUNT, ItemKey.ADVANCE, ItemKey.BALANCE)}
        payments = [f for f in deal.standing() if f.kind == FactKind.PAYMENT and f.status not in NOT_COUNTED and f.value_rupees]

        def towards(p: Fact) -> ItemKey:
            target = deal.latest.get(p.counts_towards or "")
            return (target.item if target else None) or p.item or ItemKey.AMOUNT

        balance = agreed[ItemKey.BALANCE]
        if balance is None and agreed[ItemKey.AMOUNT] is not None and agreed[ItemKey.ADVANCE] is not None:
            balance = agreed[ItemKey.AMOUNT] - agreed[ItemKey.ADVANCE]
        rows = []
        for item, figure, counted in [
            (ItemKey.AMOUNT, agreed[ItemKey.AMOUNT], payments),
            (ItemKey.ADVANCE, agreed[ItemKey.ADVANCE], [p for p in payments if towards(p) == ItemKey.ADVANCE]),
            (ItemKey.BALANCE, balance, [p for p in payments if towards(p) in (ItemKey.BALANCE, ItemKey.AMOUNT)]),
        ]:
            paid = sum(p.value_rupees for p in counted)
            rows.append(OwedRow(
                item=item, agreed_rupees=figure, paid_rupees=paid,
                owed_rupees=None if figure is None else figure - paid, payment_fact_ids=[p.id for p in counted],
            ))
        return rows

    async def search(self, deal_id: str, query: str, k: int = 5) -> list[Fact]:
        deal = self.book.deal(deal_id)
        facts = deal.standing()
        covered = {(f.call_no, f.line_no) for f in facts if f.line_no}
        # A line no fact covers comes back as itself, unless it only asks something: a question
        # is not evidence, and it is often the very question being answered.
        lines = [
            self.line_fact(deal, l) for key, l in sorted(deal.lines.items())
            if key not in covered and not l.text.rstrip().endswith("?")
        ]
        found = facts + lines
        if not found or not query.strip():
            return []
        texts = [self.fact_text(f) for f in found]
        matrix = await self.vectors.matrix([*texts, query])
        sims = matrix[:-1] @ matrix[-1]
        # Hybrid: meaning, the words themselves (Hinglish embeds loosely), the term the question
        # names, and then confirmed above agreed above said.
        asked, named = search_words(query), items_named(query)
        words = np.array([len(asked & search_words(t)) / len(asked) if asked else 0.0 for t in texts])
        item = np.array([0.1 if f.item and f.item.value in named else 0.0 for f in found])
        scores = sims + 0.25 * words + item + np.array([RANK_BONUS[f.status] for f in found])
        order = [i for i in np.argsort(-scores, kind="stable") if sims[i] > 0 or words[i] > 0 or item[i] > 0]
        best = [found[i] for i in order]
        if asks_agreed(query):  # "advance kitna tay hua tha": the term as it stands comes first
            standing = [deal.current(ItemKey(n)) for n in sorted(named)]
            best = [f for f in standing if f] + [f for f in best if f not in standing]
        best = best[:k]
        if best:
            self.note("memory", f"searched \"{query[:60]}\": {len(best)} found", best[0])
        return best

    async def clip(self, fact_id: str) -> bytes | None:
        fact = self._clip_fact(fact_id)
        if fact is None or fact.call_no is None or fact.start is None or fact.end is None:
            return None
        call = self.book.deal(fact.deal_id).calls.get(fact.call_no)
        keys = call.recordings if call and call.recordings else {}
        paths = [self.root / key for key in keys.values()] or [
            self.root / "recordings" / fact.deal_id / str(fact.call_no) / f"{role.value}.wav" for role in Role
        ]  # the bridge's layout, for a call whose call.ended has not come yet
        return await asyncio.to_thread(clips.cut, paths, fact.start, fact.end)

    def _clip_fact(self, fact_id: str) -> Fact | None:
        if fact_id.startswith(LINE_PREFIX):
            try:
                deal_id, call_no, line_no = fact_id[len(LINE_PREFIX):].rsplit("~", 2)
                deal = self.book.deals[deal_id]
                return self.line_fact(deal, deal.lines[(int(call_no), int(line_no))])
            except (KeyError, ValueError):
                return None
        return self.book.fact(fact_id)

    def latency_summary(self) -> dict:
        """Seconds from a transcript line to its fact.recorded, and to its fact.conflict."""
        return {
            name: {"median": round(statistics.median(xs), 2), "worst": round(max(xs), 2), "count": len(xs)}
            for name, xs in self.latency.items() if xs
        }

    def chain_break(self, deal_id: str) -> int | None:
        return first_break(self.book.deal(deal_id).versions)
