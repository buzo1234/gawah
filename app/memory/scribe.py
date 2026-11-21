"""The Scribe: each transcript line to facts.

Lines are read in parallel (the model call is the slow part) but applied in line order,
so an acceptance always finds the offer it accepts. A line that is only a yes is handled
in code; a greeting is skipped; everything else goes to the model once.
"""

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import date

from app.contracts import CallKind, Fact, FactKind, FactStatus, ItemKey, TranscriptLine
from app.memory import extract
from app.memory.book import DealBook
from app.memory.normalise import filler_kind, normalise_rupees, pin_date

log = logging.getLogger("gawah.memory")

ORDER_WAIT_S = 12.0  # how long a line waits for the line before it to be applied
CLIP_SPAN_S = 20.0  # an acceptance this close to its offer is cut into the same clip


@dataclass
class Claim:
    item: ItemKey | None
    kind: FactKind
    stance: str
    text: str
    value: str | None
    rupees: int | None
    date: date | None
    quote: str
    accepts_line: int | None
    contradicts: str | None


def _squash(text: str) -> str:
    return "".join(ch for ch in text.lower() if ch.isalnum())


def parse_claim(raw: dict, line: TranscriptLine, today: date) -> Claim | None:
    """A claim the model gave, or None if it is not grounded in the line's words."""
    quote = (raw.get("quote") or "").strip()
    if not quote or _squash(quote) not in _squash(line.text):
        log.info("deal=%s line %s: dropped a claim whose quote is not in the line: %r", line.deal_id, line.line_no, quote)
        return None
    try:
        item = ItemKey(raw["item"]) if raw.get("item") else None
        kind = FactKind(raw.get("kind") or "other")
        model_date = date.fromisoformat(raw["date"]) if raw.get("date") else None
    except ValueError:
        return None
    rupees = normalise_rupees(raw.get("rupees"), raw.get("value"), quote)
    return Claim(
        item=item, kind=kind, stance=raw.get("stance") or "state", text=raw.get("text") or quote,
        value=raw.get("value"), rupees=rupees, date=pin_date(quote, today, model_date), quote=quote,
        accepts_line=raw.get("accepts_line"), contradicts=raw.get("contradicts"),
    )


def differs(current: Fact | None, rupees: int | None, day: date | None) -> bool:
    if current is None:
        return False
    if rupees is not None and current.value_rupees is not None:
        return rupees != current.value_rupees
    return day is not None and current.value_date is not None and day != current.value_date


def same(current: Fact | None, rupees: int | None, day: date | None) -> bool:
    if current is None:
        return False
    return (rupees is not None and rupees == current.value_rupees) or (day is not None and day == current.value_date)


class Scribe:
    def __init__(self, memory) -> None:
        self.m = memory
        self._tail: dict[tuple[str, int], asyncio.Future] = {}
        self._tasks: set[asyncio.Task] = set()

    async def on_line(self, line: TranscriptLine) -> None:
        if line.kind != CallKind.DEAL:
            return
        deal = self.m.book.deal(line.deal_id)
        if line.line_no is None:
            taken = [n for (c, n) in deal.lines if c == line.call_no]
            line = line.model_copy(update={"line_no": max(taken, default=0) + 1})
        deal.lines[(line.call_no, line.line_no)] = line
        self.m.vectors.want(self.m.line_text(line))
        key = (line.deal_id, line.call_no)
        previous, mine = self._tail.get(key), asyncio.get_running_loop().create_future()
        self._tail[key] = mine
        task = asyncio.create_task(self._process(deal, line, previous, mine, time.monotonic()))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def settle(self) -> None:
        """Wait until every line received so far has been applied."""
        while pending := [t for t in self._tasks if not t.done()]:
            await asyncio.wait(pending)

    async def _process(self, deal: DealBook, line: TranscriptLine, previous, mine, received: float) -> None:
        try:
            names = {n.lower() for n in deal.names.values()}
            kind = filler_kind(line.text, names)
            claims: list[Claim] = []
            if kind is None:
                claims = await self._claims(deal, line)
            if previous is not None:
                try:
                    await asyncio.wait_for(asyncio.shield(previous), ORDER_WAIT_S)
                except TimeoutError:
                    log.warning("deal=%s line %s applied before line %s finished", line.deal_id, line.line_no, line.line_no - 1)
            if kind == "yes":
                self._plain_yes(deal, line, received)
            for claim in claims:
                self._apply(deal, line, claim, received)
        except Exception:
            log.exception("deal=%s line %s: scribe failed", line.deal_id, line.line_no)
        finally:
            if not mine.done():
                mine.set_result(None)

    async def _claims(self, deal: DealBook, line: TranscriptLine) -> list[Claim]:
        before = sorted(
            (l for (c, n), l in deal.lines.items() if c == line.call_no and n < line.line_no),
            key=lambda l: l.line_no,
        )[-extract.CONTEXT_LINES:]
        today = deal.call_date(line.call_no)
        request = extract.Request(
            deal_id=line.deal_id, line=line, before=before, facts=deal.standing(), names=dict(deal.names),
            today=today, room=deal.call(line.call_no).room,
        )
        try:
            raw = await self.m.extractor.claims(request)
        except Exception as e:
            log.warning("deal=%s line %s: the model gave no claims (%s)", line.deal_id, line.line_no, e)
            return []
        return [c for c in (parse_claim(r, line, today) for r in raw or []) if c]

    # ---------- applying ----------

    def _base(self, deal: DealBook, line: TranscriptLine, claim: Claim) -> dict:
        return dict(
            deal_id=line.deal_id, text=claim.text, item=claim.item, kind=claim.kind, value=claim.value,
            value_rupees=claim.rupees, value_date=claim.date, said_by=line.speaker, quote=claim.quote,
            call_no=line.call_no, line_no=line.line_no, start=line.start, end=line.end,
            valid_from=deal.at(line.call_no, line.start),
        )

    def _apply(self, deal: DealBook, line: TranscriptLine, claim: Claim, received: float) -> None:
        base = self._base(deal, line, claim)
        if claim.kind in (FactKind.PAYMENT, FactKind.WORK):
            target = self.m.target_for(deal, claim.kind, claim.item)
            fact = self.m.record(Fact(**base, counts_towards=target.id if target else None), received)
            self.m.note("scribe", f"line {line.line_no}: {claim.kind.value} noted, {fact.value or fact.text}", fact, line)
            return
        if claim.kind != FactKind.TERM or claim.item is None:
            fact = self.m.record(Fact(**base), received)
            self._model_conflict(deal, line, claim, fact, received)
            return
        current = deal.current(claim.item)
        if differs(current, claim.rupees, claim.date):
            if claim.stance != "accept":
                fact = self.m.record(Fact(**base), received)
                self.m.note("scribe", f"line {line.line_no}: {claim.item.value} {fact.value or ''} said", fact, line)
            self.m.conflict(deal, line, current, claim.rupees, claim.date, claim.value, received)
            return
        if claim.stance == "accept":
            target = self._accepted(deal, line, claim)
            if target:
                self.upgrade(deal, target, line, received, claim)
            elif current and same(current, claim.rupees, claim.date):
                if line.speaker != current.said_by and line.speaker not in current.agreed_by:
                    self.upgrade(deal, current, line, received, None)
            else:
                fact = self.m.record(Fact(
                    **base | {"said_by": line.speaker.other, "agreed_by": [line.speaker], "status": FactStatus.AGREED}
                ), received)
                self.m.note("scribe", f"line {line.line_no}: {claim.item.value} {fact.value or ''} agreed", fact, line)
            return
        if same(current, claim.rupees, claim.date):
            return  # repeats what already stands
        fact = self.m.record(Fact(**base), received)
        verb = "offered" if claim.stance == "offer" else "said"
        self.m.note("scribe", f"line {line.line_no}: {claim.item.value} {fact.value or ''} {verb}", fact, line)
        self._model_conflict(deal, line, claim, fact, received)

    def _model_conflict(self, deal: DealBook, line: TranscriptLine, claim: Claim, fact: Fact, received: float) -> None:
        """Code could not compare values; the model cited an agreed or confirmed fact."""
        cited = deal.latest.get(claim.contradicts or "")
        if claim.kind == FactKind.CHANGE:
            return  # a proposed change is not a contradiction; it goes through fact.changed
        if cited and cited.status in (FactStatus.AGREED, FactStatus.CONFIRMED) and cited.id != fact.id:
            if (claim.rupees is None and claim.date is None) or (cited.value_rupees is None and cited.value_date is None):
                self.m.conflict(deal, line, cited, claim.rupees, claim.date, claim.value, received, confidence=0.6)

    def _accepted(self, deal: DealBook, line: TranscriptLine, claim: Claim) -> Fact | None:
        offers = [
            f for f in deal.standing()
            if f.item == claim.item and f.kind == FactKind.TERM and f.status == FactStatus.SAID
            and f.said_by == line.speaker.other and f.call_no == line.call_no and (f.line_no or 0) < line.line_no
            and (claim.rupees is None or f.value_rupees == claim.rupees)
        ]
        on_line = [f for f in offers if f.line_no == claim.accepts_line]
        recent = [f for f in offers if line.line_no - (f.line_no or 0) <= 4]
        pick = on_line or recent
        return max(pick, key=lambda f: f.line_no or 0) if pick else None

    def _plain_yes(self, deal: DealBook, line: TranscriptLine, received: float) -> None:
        """"Theek hai" agrees to the other person's last line only when that line put exactly
        one value on the table; otherwise it agrees to nothing."""
        before = deal.lines.get((line.call_no, line.line_no - 1))
        if before is None or before.speaker == line.speaker:
            return
        offers = [
            f for f in deal.from_line(line.call_no, before.line_no)
            if f.kind == FactKind.TERM and f.item and f.status == FactStatus.SAID and f.said_by == before.speaker
            and (f.value_rupees is not None or f.value_date is not None or f.value)
        ]
        if len(offers) == 1 and not differs(deal.current(offers[0].item), offers[0].value_rupees, offers[0].value_date):
            self.upgrade(deal, offers[0], line, received, None)

    def upgrade(self, deal: DealBook, fact: Fact, line: TranscriptLine, received: float, claim: Claim | None) -> Fact:
        update: dict = {
            "status": FactStatus.AGREED if fact.status == FactStatus.SAID else fact.status,
            "agreed_by": [*fact.agreed_by, line.speaker] if line.speaker not in fact.agreed_by else fact.agreed_by,
        }
        if fact.call_no == line.call_no and fact.start is not None and line.end - fact.start <= CLIP_SPAN_S:
            update["end"] = max(fact.end or 0, line.end)
        if claim and claim.value and claim.rupees in (None, fact.value_rupees):
            update["value"] = claim.value
        agreed = self.m.record(fact.model_copy(update=update), received)
        what = agreed.item.value if agreed.item else "term"
        self.m.note("scribe", f"line {line.line_no}: {what} {agreed.value or ''} agreed by both", agreed, line)
        return agreed
