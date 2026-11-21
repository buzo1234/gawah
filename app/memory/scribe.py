"""The Scribe: each transcript line to facts.

Lines are read in parallel (the model call is the slow part) but applied in line order,
so an acceptance always finds the offer it accepts. A line that is only a yes is handled
in code; a greeting is skipped; everything else goes to the model once.
"""

import asyncio
import logging
import time

from app.contracts import CallKind, Fact, FactKind, FactStatus, ItemKey, TranscriptLine
from app.memory import changes, echo, extract
from app.memory.book import DealBook
from app.memory.claims import Claim, say_day, compare, comparable, parse_claim, parts_of, schedule
from app.memory.dates import date_candidates, date_parts
from app.memory.echo import commits, doubts_figure, says_figure
from app.memory.normalise import (
    bare_numbers, filler_kind, format_rupees, opens_with_yes, parse_rupees, settles_all, stated_total,
)

log = logging.getLogger("gawah.memory")

ORDER_WAIT_S = 12.0  # how long a line waits for the line before it to be applied
CLIP_SPAN_S = 20.0  # an acceptance this close to its offer is cut into the same clip


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
        self._spawn(self._process(deal, line, previous, mine, time.monotonic()))

    async def settle(self) -> None:
        """Wait until every line received so far has been applied."""
        while pending := [t for t in self._tasks if not t.done()]:
            await asyncio.wait(pending)

    async def _process(self, deal: DealBook, line: TranscriptLine, previous, mine, received: float) -> None:
        try:
            names = {n.lower() for n in deal.names.values()}
            kind = filler_kind(line.text, names)
            opening = kind is None and opens_with_yes(line.text, names)
            claims: list[Claim] = []
            if kind is None:
                claims = await self._claims(deal, line)
            if previous is not None:
                try:
                    await asyncio.wait_for(asyncio.shield(previous), ORDER_WAIT_S)
                except TimeoutError:
                    log.warning("deal=%s line %s applied before line %s finished", line.deal_id, line.line_no, line.line_no - 1)
            if kind == "yes" or opening:
                self._plain_yes(deal, line, received, claims)
            for claim in self._with_total(deal, line, claims):
                self._apply(deal, line, claim, received)
            if settles_all(line.text) and not line.text.rstrip().endswith("?"):
                self._settle_all(deal, line, received)
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
        claims = [c for c in (parse_claim(r, line, today) for r in raw or []) if c]
        for claim in claims:
            echo.scale(deal, line, claim)
        # A question settles nothing unless it names a figure or a day ("15 mein karoge?").
        return [c for c in claims if not c.quote.rstrip().endswith("?") or c.rupees is not None or c.date or c.parts]

    def _with_total(self, deal: DealBook, line: TranscriptLine, claims: list[Claim]) -> list[Claim]:
        """Once an amount is agreed, a total stated in the words is an amount claim, whatever the
        model filed it under, so a restated different total is always caught in code."""
        total = stated_total(line.text)
        if total is None or deal.current(ItemKey.AMOUNT) is None:
            return claims
        for claim in claims:
            if claim.item != ItemKey.AMOUNT and claim.rupees == total:
                claim.rupees = None  # the total is not the balance or the advance
            elif claim.item == ItemKey.AMOUNT and claim.rupees == total and claim.kind not in (FactKind.TERM, FactKind.CHANGE):
                claim.kind, claim.stance = FactKind.TERM, "recall"
        if any(c.item == ItemKey.AMOUNT and c.rupees == total for c in claims):
            return claims
        said = Claim(
            item=ItemKey.AMOUNT, kind=FactKind.TERM, stance="recall",
            text=f"{deal.name(line.speaker)} says the total is {format_rupees(total)}.", value=format_rupees(total),
            rupees=total, date=None, quote=line.text, accepts_line=None, contradicts=None,
        )
        return [said, *claims]

    # ---------- applying ----------

    def _base(self, deal: DealBook, line: TranscriptLine, claim: Claim) -> dict:
        return dict(
            deal_id=line.deal_id, text=claim.text, item=claim.item, kind=claim.kind, value=claim.value,
            value_rupees=claim.rupees, value_date=claim.date, said_by=line.speaker, quote=claim.quote,
            call_no=line.call_no, line_no=line.line_no, start=line.start, end=line.end,
            valid_from=deal.at(line.call_no, line.start),
        )

    def _compare(self, deal: DealBook, claim: Claim) -> tuple[str | None, Fact | None, str | None]:
        return compare(deal, claim.item, claim.rupees, claim.date, claim.parts, claim.figure == "part")

    def _apply(self, deal: DealBook, line: TranscriptLine, claim: Claim, received: float) -> None:
        if claim.kind == FactKind.PAYMENT and echo.promises_to_pay(claim.quote):
            # "पांच हज़ार एडवांस कल पे कर दूँगी" is the advance term, not money paid: counted as paid
            # it would be taken off what is owed before it is handed over.
            claim.kind = FactKind.TERM
            claim.item = claim.item if claim.item in (ItemKey.ADVANCE, ItemKey.BALANCE) else ItemKey.BALANCE
        # A recall with a question tag still says what was agreed ("32 tay hua tha na?").
        asked = claim.stance != "recall"
        if claim.item and echo.echoes(deal, line, claim.rupees) and doubts_figure(line.text, claim.rupees, asked):
            # "9,000 thoda zyada hai", "9,000 mein to...", "9,000 wala baad mein": their figure said back
            # with a complaint, a hedge, a question or a deferral accepts nothing and offers nothing,
            # and turns down a change they offered with it.
            self.m.note("scribe", f"line {line.line_no}: {claim.item.value} {format_rupees(claim.rupees)} said back, not accepted", line=line)
            changes.turn_down(self.m, deal, line, claim, received)
            return
        changes.shape(deal, line, claim)
        if claim.kind == FactKind.CHANGE and claim.stance == "recall":
            claim.kind = FactKind.TERM  # says what was agreed: a different figure contradicts it, it proposes nothing
        if claim.kind == FactKind.CHANGE and claim.item:
            if deal.current(claim.item) is None:
                claim.kind = FactKind.TERM  # nothing agreed yet to change: it is an offer
            elif self._compare(deal, claim)[0] == "same":
                return  # the value that already stands
        differs = claim.kind in (FactKind.TERM, FactKind.CHANGE) and claim.item and self._compare(deal, claim)[0] == "differs"
        if differs and claim.item == ItemKey.BALANCE and claim.stance != "recall" and changes.carry(self.m, deal, line, claim, received):
            return
        if claim.kind == FactKind.TERM and differs:
            if claim.stance == "offer" or (claim.stance != "recall" and changes.offered(deal, line, claim.item, claim.rupees)):
                claim.kind = FactKind.CHANGE  # a new figure proposed for an agreed term: a change, bargained like any offer
        if claim.kind == FactKind.CHANGE and claim.item and claim.item != ItemKey.DATES:
            self._change(deal, line, claim, received)
            return
        base = self._base(deal, line, claim)
        if claim.kind in (FactKind.PAYMENT, FactKind.WORK):
            target = self.m.target_for(deal, claim.kind, claim.item)
            fact = self.m.record(Fact(**base, counts_towards=target.id if target else None), received)
            self.m.note("scribe", f"line {line.line_no}: {claim.kind.value} noted, {fact.value or fact.text}", fact, line)
            return
        verdict, against, part = self._compare(deal, claim)
        if claim.kind != FactKind.TERM or claim.item is None:
            fact = self.m.record(Fact(**base), received)
            if claim.kind == FactKind.CHANGE and claim.item == ItemKey.DATES and verdict == "differs":
                self._conflict(deal, line, claim, against, part, received)  # the brain compares no dates itself
            self._model_conflict(deal, line, claim, fact, received)
            return
        if verdict == "differs" and claim.stance == "recall" and echo.asks_which(claim.quote):
            fact = self.m.record(Fact(**base), received)  # a question about the figure asserts nothing
            self.m.note("scribe", f"line {line.line_no}: asked about {claim.item.value}, {fact.value or ''}", fact, line)
            return
        if verdict == "differs":
            if claim.stance != "accept":
                fact = self.m.record(Fact(**base), received)
                self.m.note("scribe", f"line {line.line_no}: {claim.item.value} {fact.value or ''} said", fact, line)
            self._conflict(deal, line, claim, against, part, received)
            return
        if claim.stance in ("state", "offer") and claim.rupees and self._accepted(deal, line, claim) and (
            commits(line.text, claim.rupees)
        ):
            claim.stance = "accept"  # says back the figure the other person just offered, with a yes or a promise
        target = self._accepted(deal, line, claim) if claim.stance == "accept" else None
        if claim.stance == "accept" and not target and verdict != "same" and not self._heard(deal, line, claim):
            claim.stance = "offer"  # nothing the other person said: it is this speaker's own proposal
        if claim.stance == "accept":
            if target:
                self.upgrade(deal, target, line, received, claim)
            elif verdict == "same":
                if line.speaker != against.said_by and line.speaker not in against.agreed_by:
                    self.upgrade(deal, against, line, received, None)
            else:
                fact = self.m.record(Fact(
                    **base | {"said_by": line.speaker.other, "agreed_by": [line.speaker], "status": FactStatus.AGREED}
                ), received)
                self.m.note("scribe", f"line {line.line_no}: {claim.item.value} {fact.value or ''} agreed", fact, line)
            return
        if verdict == "same":
            return  # repeats what already stands
        fact = self.m.record(Fact(**base), received)
        verb = "offered" if claim.stance == "offer" else "said"
        self.m.note("scribe", f"line {line.line_no}: {claim.item.value} {fact.value or ''} {verb}", fact, line)
        self._model_conflict(deal, line, claim, fact, received)

    def _change(self, deal: DealBook, line: TranscriptLine, claim: Claim, received: float) -> None:
        offer = changes.offered(deal, line, claim.item, claim.rupees, claim.added)
        # A change to a figure is agreed only by saying the figure (or the extra) back with a yes
        # or a promise: a bare "haan theek hai" to a new total changes nothing.
        figure = claim.added or claim.rupees
        if figure is None:
            accepting = claim.stance == "accept"
        else:
            accepting = says_figure(line.text, figure) and (claim.stance == "accept" or commits(line.text, figure))
        # Only what the other person said can be accepted: their change, or their figure.
        heard = echo.echoes(deal, line, figure) if figure is not None else self._heard(deal, line, claim)
        if accepting and (offer is not None or heard):
            changes.agree(self.m, deal, line, offer, claim, received)
            return
        fact = self.m.record(Fact(**self._base(deal, line, claim) | {"kind": FactKind.CHANGE}), received)
        self.m.note("scribe", f"line {line.line_no}: change to {claim.item.value} said, {fact.value or fact.text}", fact, line)

    def _conflict(self, deal: DealBook, line: TranscriptLine, claim: Claim, against: Fact, part: str | None, received: float) -> None:
        if part is None:
            self.m.conflict(deal, line, against, claim.rupees, claim.date, claim.value, received)
            return
        said, agreed = say_day(claim.parts[part]), say_day(parts_of(deal, against)[part])
        both = " by both" if against.agreed_by or against.confirmed_by else ""
        where = f" (call {against.call_no}, line {against.line_no})" if against.line_no else ""
        self.m.conflict(
            deal, line, against, None, None, f"a {part} on {said}", received,
            explanation=f"Says a {part} on {said}; the {part} was {against.status.value} as {agreed}{both}{where}.",
        )

    def _model_conflict(self, deal: DealBook, line: TranscriptLine, claim: Claim, fact: Fact, received: float) -> None:
        """Code could not compare values and the model cited an agreed or confirmed fact: one
        short model call on just the two decides, off the line's path."""
        if claim.kind == FactKind.CHANGE:
            return  # a proposed change is not a contradiction; it goes through fact.changed
        if claim.item == ItemKey.DATES:
            return  # code compares a start with the start and a finish with the finish; a day that is neither is no claim
        cited = extract.resolve(claim.contradicts, deal.standing())
        if cited is None or cited.status not in (FactStatus.AGREED, FactStatus.CONFIRMED) or cited.id == fact.id:
            return
        if comparable(deal, cited, claim):
            return  # code already compared them
        check = extract.Check(cited, claim.text, claim.quote, line.speaker, deal.call(line.call_no).room)
        self._spawn(self._check(deal, line, claim, check, received))

    async def _check(self, deal: DealBook, line: TranscriptLine, claim: Claim, check: extract.Check, received: float) -> None:
        try:
            verdict = await self.m.extractor.check(check)
        except Exception as e:
            log.warning("deal=%s line %s: the contradiction check failed (%s)", line.deal_id, line.line_no, e)
            return
        if verdict and verdict.get("contradicts"):
            self.m.conflict(deal, line, check.fact, claim.rupees, claim.date, claim.value, received,
                            confidence=0.7, explanation=verdict.get("reason"))

    def _spawn(self, coro) -> None:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

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

    def _heard(self, deal: DealBook, line: TranscriptLine, claim: Claim) -> bool:
        """An acceptance accepts something: the figure or day must be in what the other person
        said in the last few lines. A value code cannot read must at least name a line where the
        other person said something about the term."""
        if not claim.rupees and claim.date is None and not claim.parts:
            cited = deal.lines.get((line.call_no, claim.accepts_line or 0))
            if cited is None or cited.speaker != line.speaker.other:
                return cited is None  # no line named: taken on the model's word
            return any(f.item == claim.item for f in deal.from_line(line.call_no, cited.line_no))
        today = deal.call_date(line.call_no)
        for n in range(line.line_no - 1, max(0, line.line_no - 5), -1):
            said = deal.lines.get((line.call_no, n))
            if said is None or said.speaker != line.speaker.other:
                continue
            if claim.rupees and (claim.rupees in parse_rupees(said.text) or claim.rupees / 1000 in bare_numbers(said.text)):
                return True
            theirs = date_parts(said.text, today)
            if any(p in theirs and day.same(theirs[p]) for p, day in claim.parts.items()):
                return True
            if claim.date is not None and claim.date in date_candidates(said.text, today):
                return True
        return False

    def _plain_yes(self, deal: DealBook, line: TranscriptLine, received: float, claims: list[Claim] = ()) -> None:
        """"Theek hai" agrees to the other person's last line only when that line put exactly
        one value on the table; otherwise it agrees to nothing. On a line that goes on after
        its yes, a counter-offer for the same term in the rest of the line takes it back."""
        before = deal.lines.get((line.call_no, line.line_no - 1))
        if before is None or before.speaker == line.speaker:
            return
        offers = [
            f for f in deal.from_line(line.call_no, before.line_no)
            if f.kind == FactKind.TERM and f.item and f.status == FactStatus.SAID and f.said_by == before.speaker
            and (f.value_rupees is not None or f.value_date is not None or f.value)
        ]  # not a change: a change is agreed only with its figure said back (_change)
        if len(offers) > 1 and all(self._said_back(deal, line, f) for f in offers):
            for offer in offers:  # "Theek hai, das das aur chhe" to an advance and a balance in parts
                self.upgrade(deal, offer, line, received, None)
            return
        if len(offers) != 1 or any(self._counters(c, offers[0]) for c in claims):
            return
        offer = offers[0]
        if compare(deal, offer.item, offer.value_rupees, offer.value_date, parts_of(deal, offer))[0] != "differs":
            self.upgrade(deal, offer, line, received, None)

    @staticmethod
    def _counters(claim: Claim, offer: Fact) -> bool:
        """After the yes, the same term again with another figure or day, or as an offer, takes
        the yes back; the same term said back in other words ("kaam dekh ke hi dena") does not."""
        if claim.item != offer.item:
            return False
        if claim.stance == "offer":
            return True
        return (claim.rupees is not None and claim.rupees != offer.value_rupees) or (
            claim.date is not None and claim.date != offer.value_date
        )

    @staticmethod
    def _said_back(deal: DealBook, line: TranscriptLine, offer: Fact) -> bool:
        figures = schedule(offer) or ([offer.value_rupees] if offer.value_rupees else [])
        return bool(figures) and all(says_figure(line.text, r) for r in figures) and not doubts_figure(line.text, figures[0])

    def _settle_all(self, deal: DealBook, line: TranscriptLine, received: float) -> None:
        """"Sab tay ho gaya" agrees to each term the other person stated on this call that
        nothing agreed yet covers: the last thing they said about it."""
        for item in ItemKey:
            if deal.current(item) is not None:
                continue
            said = [
                f for f in deal.standing()
                if f.item == item and f.kind == FactKind.TERM and f.status == FactStatus.SAID
                and f.said_by == line.speaker.other and f.call_no == line.call_no and (f.line_no or 0) < line.line_no
            ]
            if said:
                self.upgrade(deal, max(said, key=lambda f: f.line_no or 0), line, received, None)

    def upgrade(self, deal: DealBook, fact: Fact, line: TranscriptLine, received: float, claim: Claim | None) -> Fact:
        update: dict = {
            "status": FactStatus.AGREED if fact.status == FactStatus.SAID else fact.status,
            "agreed_by": [*fact.agreed_by, line.speaker] if line.speaker not in fact.agreed_by else fact.agreed_by,
        }
        if fact.call_no == line.call_no and fact.start is not None and line.end - fact.start <= CLIP_SPAN_S:
            update["end"] = max(fact.end or 0, line.end)
        narrower = fact.item == ItemKey.DATES and not set(parts_of(deal, fact)) <= set(claim.parts if claim else {})
        if claim and claim.value and claim.rupees in (None, fact.value_rupees) and not narrower:
            update["value"] = claim.value
        agreed = self.m.record(fact.model_copy(update=update), received)
        what = agreed.item.value if agreed.item else "term"
        self.m.note("scribe", f"line {line.line_no}: {what} {agreed.value or ''} agreed by both", agreed, line)
        return agreed
