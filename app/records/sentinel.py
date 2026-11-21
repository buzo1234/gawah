"""The Sentinel: Gawah's watch between calls, on WhatsApp.

- A payment is checked against the deal before it is logged: memory says what was agreed
  and what is owed. A claim larger than what is owed gets what was agreed, when, and the
  clip of that moment; Gawah never says who is right.
- Once a payment stands (a screenshot, or the other person's yes), both are told what is
  still owed.
- Work confirmed done with money still owed, or a money term's date passed with money
  still owed: one reminder to the hirer, and the worker is told. Once per deal and term.
- After a second deal call, who needs the call-back: only those who have not confirmed a
  term that call changed.
"""

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta, timezone

from app.bus import Bus
from app.contracts import (
    AgentNote,
    CrewAgent,
    Fact,
    FactKind,
    FactRecorded,
    FactSource,
    FactStatus,
    ItemKey,
    MemoryQueries,
    OwedRow,
    Record,
    RecordConfirmed,
    RecordKind,
    Role,
    clip_path,
)
from app.log import deal_log
from app.records import tuning, words
from app.records.reminders import Reminders
from app.store import Store

IST = timezone(timedelta(hours=5, minutes=30))
MONEY = (RecordKind.ADVANCE, RecordKind.PAYMENT)
DATED = (ItemKey.ADVANCE, ItemKey.BALANCE)
WORK, DATE = "work", "date"  # why a reminder is due
_AFTER_WORK = re.compile(r"after|complet|finish|kaam ke baad|khatam|poora|pura", re.IGNORECASE)


@dataclass
class Check:
    """What memory said about a record before it was logged."""

    rows: dict[ItemKey, OwedRow]
    against: Fact | None = None  # the agreed term the claim is larger than
    line: str | None = None  # what was agreed and when, with the clip
    clip: str | None = None  # the link to the clip, also inside the line


class Sentinel:
    def __init__(
        self, bus: Bus, outbox, store: Store, memory: MemoryQueries, link: Callable[[str], str],
        reminders: Callable[["Sentinel"], Reminders], wall: Callable[[], datetime],
    ) -> None:
        self.bus, self.outbox, self.store, self.memory, self.link, self.wall = bus, outbox, store, memory, link, wall
        self.reminders = reminders(self)
        self._fact_of: dict[str, str] = {}  # record id -> memory's fact id for it
        self._work_done: set[str] = set()  # deals whose work both have confirmed

    def subscribe(self) -> None:
        self.bus.subscribe(RecordConfirmed, self.on_record_confirmed)
        self.bus.subscribe(FactRecorded, self.on_fact)

    # ---------- a record comes in ----------

    async def check(self, deal_id: str, record: Record) -> Check | None:
        """Before the record is published, so memory's answers do not count it yet."""
        try:
            rows = await self._rows(deal_id)
            check = Check(rows)
            if record.kind not in MONEY or record.amount is None:
                return check
            amount, advance, total = round(record.amount), rows.get(ItemKey.ADVANCE), _total(rows)
            if record.kind is RecordKind.ADVANCE and _owed(advance) is not None and amount > advance.owed_rupees:
                row = advance
            elif _owed(total) is not None and amount > total.owed_rupees:
                row = total
            else:
                return check
            check.against = (await self.memory.get_term(deal_id, row.item)).current
            check.clip = await self._clip(check.against)
            check.line = words.agreed(row.item, row.agreed_rupees, _when(check.against), row.paid_rupees, check.clip)
            return check
        except Exception:
            deal_log("gawah.records", deal_id).exception("could not check a record against memory")
            return None

    async def disagrees(self, deal_id: str, record: Record, check: Check, asked: Role | None) -> None:
        """Tell both what was agreed. The record flow then asks the other person, as always."""
        for person in await self._people(deal_id):
            self.outbox.send(deal_id, person.phone, person.role, check.line, link=check.clip, link_label=words.CLIP_BUTTON)
        term = check.against.item.value if check.against and check.against.item else "deal"
        whom = f", {asked.value} asked to confirm" if asked else ""
        self._note(deal_id, f"claim of {words.rupees(round(record.amount))} is more than the {term} owed: "
                   f"told both what was agreed{whom}", check.against)

    async def logged(self, deal_id: str, record: Record, check: Check) -> None:
        """A record that stands on its own (a payment screenshot): both hear what is owed now."""
        if check.line:
            await self.disagrees(deal_id, record, check, None)
        if record.kind in MONEY and record.amount is not None:
            await self._say_paid(deal_id, record, _minus(check.rows, record))

    async def on_record_confirmed(self, event: RecordConfirmed) -> None:
        record = event.record
        if not event.confirmed or record is None:
            return
        if record.kind in MONEY and record.amount is not None:
            rows = await self._rows(event.deal_id)
            counted = any(self._fact_of.get(record.id) in r.payment_fact_ids for r in rows.values())
            await self._say_paid(event.deal_id, record, rows if counted else _minus(rows, record))
        elif record.kind is RecordKind.WORK_DONE:
            self._work_done.add(event.deal_id)
            owed = _owed(_total(await self._rows(event.deal_id)))
            for person in await self._people(event.deal_id):
                self.outbox.send(event.deal_id, person.phone, person.role, words.work_done(owed))
            if owed and owed > 0:
                when = self.wall() + timedelta(seconds=tuning.BALANCE_REMINDER_SECONDS)
                self.reminders.at(event.deal_id, ItemKey.BALANCE, when, WORK)
                self._note(event.deal_id, f"work confirmed done, {words.rupees(owed)} owed: "
                           f"reminder in {tuning.BALANCE_REMINDER_SECONDS:.0f}s")
            else:
                self._note(event.deal_id, "work confirmed done, nothing owed")

    async def on_fact(self, event: FactRecorded) -> None:
        fact = event.fact
        if fact.record_id:
            self._fact_of[fact.record_id] = fact.id
        if (fact.kind is FactKind.TERM and fact.item in DATED and fact.value_date
                and fact.status in (FactStatus.AGREED, FactStatus.CONFIRMED)):
            passed = datetime.combine(fact.value_date + timedelta(days=1), time(), IST)
            when = passed + timedelta(hours=tuning.DATE_REMINDER_HOURS_AFTER)
            if self.reminders.at(fact.deal_id, fact.item, when, DATE):
                self._note(fact.deal_id, f"watching the {fact.item.value} date, {words.day(fact.value_date)}", fact)

    async def _say_paid(self, deal_id: str, record: Record, after: dict[ItemKey, OwedRow]) -> None:
        total = _total(after)
        if total is None and ItemKey.ADVANCE not in after:
            return  # memory knows no figure for this deal: the record line is all there is to say
        balance = (await self.memory.get_term(deal_id, ItemKey.BALANCE)).current
        line = words.paid(record.kind, round(record.amount), _owed(after.get(ItemKey.ADVANCE)), _owed(total),
                          self._balance_when(deal_id, balance))
        for person in await self._people(deal_id):
            self.outbox.send(deal_id, person.phone, person.role, line)
        self._note(deal_id, f"{record.kind.value} of {words.rupees(round(record.amount))} stands: "
                   f"{words.rupees(_owed(total)) if _owed(total) is not None else 'nothing'} still owed")

    # ---------- reminders ----------

    async def remind(self, deal_id: str, item: ItemKey, why: str) -> bool:
        """A reminder is due. Sent only if money is still owed on the term."""
        rows = await self._rows(deal_id)
        owed = _owed(_total(rows) if why == WORK else rows.get(item))
        term = (await self.memory.get_term(deal_id, item)).current
        if not owed or owed <= 0 or (why == DATE and not (term and term.value_date)):
            self._note(deal_id, f"{item.value} reminder due, nothing owed: not sent")
            return False
        people = {p.role: p for p in await self._people(deal_id)}
        hirer, worker = people.get(Role.HIRER), people.get(Role.WORKER)
        if hirer is None:
            return False
        text = words.remind_after_work(owed) if why == WORK else words.remind_date(item, owed, term.value_date)
        self.outbox.send(deal_id, hirer.phone, hirer.role, text)
        if worker:
            self.outbox.send(deal_id, worker.phone, worker.role, words.hirer_reminded(hirer, owed))
        self._note(deal_id, f"reminded the hirer: {words.rupees(owed)} owed ({'work done' if why == WORK else 'date passed'})"
                   + (", told the worker" if worker else ""), term)
        return True

    # ---------- after a second call ----------

    async def callback_roles(self, deal_id: str, call_no: int) -> set[Role]:
        """Who needs the call-back after this call: those who have not confirmed a term it
        changed. Waits for memory to finish the call's last lines first."""
        settle = getattr(self.memory, "settle", None)  # not in MemoryQueries; the real memory has it
        if settle:
            await settle()
        roles, changed = set(), []
        for item in ItemKey:
            term = (await self.memory.get_term(deal_id, item)).current
            if term and term.call_no == call_no and term.source is FactSource.CALL:
                missing = set(Role) - set(term.confirmed_by)
                if missing:
                    roles |= missing
                    changed.append(item.value)
        if changed:
            self._note(deal_id, f"call {call_no} changed {', '.join(changed)}: call-back links sent")
        else:
            self._note(deal_id, f"call {call_no}: no term changed, no call-back links")
        return roles

    # ---------- helpers ----------

    async def _rows(self, deal_id: str) -> dict[ItemKey, OwedRow]:
        return {r.item: r for r in await self.memory.owed(deal_id)}

    async def _people(self, deal_id: str):
        deal = await self.store.deal(deal_id)
        return [p for p in (deal.people if deal else []) if p.phone]

    async def _clip(self, fact: Fact | None) -> str | None:
        """A link to the moment, only when memory really has its audio."""
        if fact is None or fact.call_no is None or fact.start is None:
            return None
        return self.link(clip_path(fact.id)) if await self.memory.clip(fact.id) else None

    def _balance_when(self, deal_id: str, balance: Fact | None) -> str:
        if balance is None:
            return ""
        if balance.value_date:
            return f", {words.day(balance.value_date)} tak"
        said = f"{balance.value or ''} {balance.quote or ''}"
        return " kaam ke baad" if deal_id not in self._work_done and _AFTER_WORK.search(said) else ""

    def _note(self, deal_id: str, text: str, fact: Fact | None = None) -> None:
        deal_log("gawah.records", deal_id).info("sentinel: %s", text)
        self.bus.publish(AgentNote(
            deal_id=deal_id, agent=CrewAgent.SENTINEL, text=text[:160], fact_ids=[fact.id] if fact else [],
        ))


def _total(rows: dict[ItemKey, OwedRow]) -> OwedRow | None:
    """The whole deal: the amount if one is agreed, else the balance."""
    for item in (ItemKey.AMOUNT, ItemKey.BALANCE):
        if _owed(rows.get(item)) is not None:
            return rows[item]
    return None


def _owed(row: OwedRow | None) -> int | None:
    return row.owed_rupees if row else None


def _minus(rows: dict[ItemKey, OwedRow], record: Record) -> dict[ItemKey, OwedRow]:
    """The rows once this record counts, as memory counts it: every payment towards the
    amount, an advance towards the advance, any other payment towards the balance."""
    paid = round(record.amount)
    towards = {ItemKey.AMOUNT, ItemKey.ADVANCE if record.kind is RecordKind.ADVANCE else ItemKey.BALANCE}
    return {
        item: row.model_copy(update={
            "paid_rupees": row.paid_rupees + paid,
            "owed_rupees": None if row.owed_rupees is None else row.owed_rupees - paid,
        }) if item in towards else row
        for item, row in rows.items()
    }


def _when(fact: Fact | None) -> str | None:
    if fact is None or fact.valid_from is None:
        return None
    on = words.day(fact.valid_from.astimezone(IST).date())
    return f"{on} ki call mein" if fact.source in (FactSource.CALL, FactSource.CALLBACK) else f"{on} ko"


def wall_clock() -> datetime:
    return datetime.now(UTC)

