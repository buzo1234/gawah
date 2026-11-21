"""A stand-in for memory: answers MemoryQueries from a fixed list of facts, so a stream can
be built against the interface with no memory stream present. Put it on app.state.memory
(MEMORY_STATE) in a test, the way the memory stream will."""

import io
import re
import wave
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta

from app.contracts import (
    Fact, FactKind, FactSource, FactStatus, ItemKey, OwedRow, Role, TermView,
)

STATUS_ORDER = [FactStatus.CONFIRMED, FactStatus.AGREED, FactStatus.SAID, FactStatus.DISPUTED, FactStatus.SUPERSEDED]
MONEY_TERMS = [ItemKey.AMOUNT, ItemKey.ADVANCE, ItemKey.BALANCE]
NOT_COUNTED = {FactStatus.DISPUTED, FactStatus.SUPERSEDED}


class FakeMemory:
    """Facts are given oldest first, every version as its own entry, as fact.recorded sends
    them: the last entry for an id is that fact as it stands. Search is word overlap over
    the facts only (no transcript lines), ranked by status first, then by overlap."""

    def __init__(self, facts: Iterable[Fact], clips: dict[str, bytes] | None = None) -> None:
        self.facts = list(facts)
        self.clips = dict(clips or {})

    def _current(self, deal_id: str) -> list[Fact]:
        latest: dict[str, Fact] = {}
        for fact in self.facts:
            if fact.deal_id == deal_id:
                latest[fact.id] = fact  # dicts keep first-insertion order: oldest fact first
        return list(latest.values())

    async def get_term(self, deal_id: str, item: ItemKey) -> TermView:
        history = [f for f in self.facts if f.deal_id == deal_id and f.item == item and f.kind != FactKind.PAYMENT]
        standing = {f.id: f for f in history}.values()  # latest version of each
        for status in (FactStatus.CONFIRMED, FactStatus.AGREED):
            matches = [f for f in standing if f.status == status]
            if matches:
                return TermView(item=item, current=matches[-1], history=history)
        return TermView(item=item, current=None, history=history)

    async def owed(self, deal_id: str) -> list[OwedRow]:
        rows = []
        payments = [f for f in self._current(deal_id) if f.kind == FactKind.PAYMENT and f.status not in NOT_COUNTED]
        for item in MONEY_TERMS:
            term = await self.get_term(deal_id, item)
            term_ids = {f.id for f in term.history}  # a payment may point at an older version
            counted = [p for p in payments if p.counts_towards in term_ids]
            agreed = term.current.value_rupees if term.current else None
            paid = sum(p.value_rupees or 0 for p in counted)
            rows.append(OwedRow(
                item=item, agreed_rupees=agreed, paid_rupees=paid,
                owed_rupees=None if agreed is None else agreed - paid,
                payment_fact_ids=[p.id for p in counted],
            ))
        return rows

    async def search(self, deal_id: str, query: str, k: int = 5) -> list[Fact]:
        asked = _words(query)
        scored = []
        for fact in self._current(deal_id):
            overlap = len(asked & _words(fact.text, fact.value, fact.quote))
            if overlap:
                scored.append((STATUS_ORDER.index(fact.status), -overlap, fact))
        scored.sort(key=lambda s: s[:2])  # stable: ties keep the oldest first
        return [fact for *_, fact in scored[:k]]

    async def clip(self, fact_id: str) -> bytes | None:
        return self.clips.get(fact_id)


def _words(*texts: str | None) -> set[str]:
    return {w for t in texts if t for w in re.findall(r"\w+", t.lower())}


def silent_wav(seconds: float = 0.5) -> bytes:
    """A WAV in the shape MemoryQueries.clip returns: 24 kHz, mono, 16-bit."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(24000)
        wav.writeframes(b"\0\0" * int(24000 * seconds))
    return buffer.getvalue()


def two_amounts_facts(deal_id: str = "replay-two-amounts") -> list[Fact]:
    """Facts for fixtures/call_two_amounts.json, in the order memory would send them:
    the 15,000 offer, the 13,000 agreed amount that supersedes it, the advance term, the
    amount confirmed on the call-back, and a 3,000 advance paid in cash."""
    call_start = datetime(2026, 11, 21, 10, 0, tzinfo=UTC)
    tomorrow = date(2026, 11, 22)
    at = lambda seconds: call_start + timedelta(seconds=seconds)  # noqa: E731
    offer = Fact(
        id="f-offer", deal_id=deal_id, text="The worker asked 15,000 rupees for labour only.",
        item=ItemKey.AMOUNT, kind=FactKind.TERM, value="15,000 rupees, labour only", value_rupees=15000,
        said_by=Role.WORKER, status=FactStatus.SAID, source=FactSource.CALL,
        quote="To sirf labour ka madam... 15 hazaar lagega.", call_no=1, line_no=7, start=38.3, end=42.1,
        valid_from=at(38.3),
    )
    amount = Fact(
        id="f-amount", deal_id=deal_id, text="The price is 13,000 rupees for labour only; the hirer buys the material.",
        item=ItemKey.AMOUNT, kind=FactKind.TERM, value="13,000 rupees, labour only", value_rupees=13000,
        said_by=Role.HIRER, agreed_by=[Role.WORKER], status=FactStatus.AGREED, source=FactSource.CALL,
        quote="Theek hai, 13 hazaar. Sirf labour, material mera.", call_no=1, line_no=12, start=59.8, end=62.6,
        valid_from=at(59.8), replaces=offer.id,
    )
    advance = Fact(
        id="f-advance", deal_id=deal_id, text="The advance is 3,000 rupees in cash, paid tomorrow morning.",
        item=ItemKey.ADVANCE, kind=FactKind.TERM, value="3,000 rupees, cash, tomorrow morning", value_rupees=3000,
        value_date=tomorrow, said_by=Role.HIRER, agreed_by=[Role.WORKER],
        status=FactStatus.AGREED, source=FactSource.CALL,
        quote="Theek hai, 3 hazaar kal subah de dungi, cash mein.", call_no=1, line_no=16, start=70.1, end=73.5,
        valid_from=at(70.1),
    )
    paid = Fact(
        id="f-paid", deal_id=deal_id, text="The hirer paid the 3,000 rupee advance in cash.",
        item=ItemKey.ADVANCE, kind=FactKind.PAYMENT, value="3,000 rupees, cash", value_rupees=3000,
        value_date=tomorrow, said_by=Role.HIRER, confirmed_by=[Role.WORKER],
        status=FactStatus.CONFIRMED, source=FactSource.TEXT, quote="3 hazaar advance de diya, cash mein.",
        record_id="r-advance", valid_from=call_start + timedelta(days=1, hours=-1), counts_towards=advance.id,
    )
    return [
        offer,
        amount,
        offer.model_copy(update={"status": FactStatus.SUPERSEDED, "superseded_at": at(59.8)}),
        advance,
        amount.model_copy(update={
            "status": FactStatus.CONFIRMED, "confirmed_by": [Role.HIRER, Role.WORKER],
        }),
        paid,
    ]
