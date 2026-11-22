"""A term disputed on a call-back. The agreement is held until every one is settled: the clerk
writes it only once both have confirmed every term, so nothing here writes it; this makes
sure both know why it is held and how to settle it.

- When the call-back of the person who said no is over, both get one message, the same text:
  who said no to which terms, what else stands, that the agreement is held, and what the
  record holds for each term (who said it, who agreed, on which call, the clip), quoted as for
  a payment claim (dispute_words.quote_term). Several terms from one call-back, one message.
- The person who said no gets two choices per term. [Recording sahi hai] lifts it: a
  terms.confirmed for them, as a yes on the call-back would be. [Kuch aur tay hua tha] asks for
  their version; their next text or voice note is it (memory keeps it as a said fact beside the
  term, never in its place), and both see both versions with a call link.
- Settled by that person's yes (the button, or a later call-back), or by a change both confirmed.
- One reminder to both after tuning.DISPUTE_REMINDER_SECONDS if still open, with the choices
  again; never repeated (kept beside the Sentinel's reminders, so a restart keeps it).
- Every open dispute and the wait for a version are rebuilt from the event log on start.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING

from app.contracts import (
    CallEnded, CallKind, ChangeStatus, Deal, DisputeStep, Event, Fact, FactChanged, FactStatus, ItemKey, Person, Role,
    TermDispute, TermsConfirmed, TermsDisputed, call_path, new_id,
)
from app.records import dispute_words, term_words, tuning, words
from app.records.reminders import Reminders

if TYPE_CHECKING:
    from app.records.sentinel import Sentinel

MONEY = (ItemKey.AMOUNT, ItemKey.ADVANCE, ItemKey.BALANCE)
OFFERED = (DisputeStep.OPENED, DisputeStep.REMINDED, DisputeStep.VERSION)


@dataclass
class TermOpen:
    id: str  # the event id of the terms.disputed that opened it
    deal_id: str
    item: ItemKey
    person: Role
    value: str | None  # as read to them on the call-back
    step: DisputeStep | None = None  # None: not told yet
    over: bool = False  # the call-back it was said on is over
    fact_id: str | None = None
    version: str | None = None
    settling: str | None = None  # how it settles, while our own terms.confirmed is on its way


class TermDisputes:
    def __init__(self, sentinel: "Sentinel", reminders: Callable[["TermDisputes"], Reminders]) -> None:
        self.s = sentinel
        self.open: dict[str, TermOpen] = {}
        self.finished: dict[tuple[str, Role], bool] = {}  # their last call-back reached its end
        self.all_yes: set[tuple[str, Role]] = set()  # said yes to every term on a call-back
        self.reminders = reminders(self)

    def subscribe(self) -> None:
        bus = self.s.bus
        bus.subscribe(TermsDisputed, self.on_event)
        bus.subscribe(CallEnded, self.on_event)
        bus.subscribe(TermsConfirmed, self.on_event)
        bus.subscribe(FactChanged, self.on_event)

    async def load(self) -> None:
        """After a restart: the disputes as the event log left them, then the reminder timers."""
        for event in await self.s.store.events():
            self.apply(event)
        self.reminders.load()
        for d in [d for d in self.open.values() if d.step is None and d.over]:
            await self.tell(d.deal_id, d.person)

    # ---------- the fold: the same for a live event and a rebuild ----------

    def apply(self, event: Event) -> list[TermOpen]:
        """Take one event. Returns the disputes it settled."""
        match event:
            case TermsDisputed(item=item) if item is not None:
                if not self._mine(event.deal_id, event.person, item):
                    self.open[event.event_id] = TermOpen(event.event_id, event.deal_id, item, event.person, event.value)
            case CallEnded(kind=CallKind.CALLBACK, people=[person, *_]):
                self.finished[(event.deal_id, person.role)] = event.reason == "done"
                for d in self.open.values():
                    if d.deal_id == event.deal_id and d.person is person.role:
                        d.over = True
            case TermDispute():
                d = self.open.get(event.dispute_id)
                if d and event.step is DisputeStep.SETTLED:
                    del self.open[d.id]
                elif d:
                    d.step, d.fact_id, d.over = event.step, event.fact_id or d.fact_id, True
                    d.version = event.version or d.version
            case TermsConfirmed():
                if event.item is None:
                    self.all_yes.add((event.deal_id, event.person))
                return self._close(lambda d: d.deal_id == event.deal_id and d.person is event.person
                                   and event.item in (None, d.item))
            case FactChanged(status=ChangeStatus.CONFIRMED_BOTH, item=item) if item is not None:
                return self._close(lambda d: d.deal_id == event.deal_id and d.item is item)
        return []

    def _close(self, settles: Callable[[TermOpen], bool]) -> list[TermOpen]:
        closed = [d for d in self.open.values() if settles(d)]
        for d in closed:
            del self.open[d.id]
        return closed

    def _mine(self, deal_id: str, role: Role, item: ItemKey | None = None) -> list[TermOpen]:
        return [d for d in self.open.values() if d.deal_id == deal_id and d.person is role and item in (None, d.item)]

    # ---------- live ----------

    async def on_event(self, event: Event) -> None:
        for d in self.apply(event):
            how = d.settling or ("changed" if isinstance(event, FactChanged) else "confirmed")
            await self._settled(d, how, event.new_value if isinstance(event, FactChanged) else None)
            whole = isinstance(event, TermsConfirmed) and event.item is None
            if not whole and not self._mine(d.deal_id, d.person) and self.finished.get((d.deal_id, d.person)):
                # Their last no is settled: their call-back's yes to everything else, as it would have been.
                self.s.bus.publish(TermsConfirmed(deal_id=d.deal_id, person=d.person, said=event.said))
        if isinstance(event, CallEnded) and event.kind is CallKind.CALLBACK and event.people:
            await self.tell(event.deal_id, event.people[0].role)

    async def tell(self, deal_id: str, role: Role) -> None:
        """The call-back of the person who said no is over: both hear what the record holds."""
        untold = [d for d in self._mine(deal_id, role) if d.step is None]
        if not untold:
            return
        settle = getattr(self.s.memory, "settle", None)  # memory marks the term disputed first
        if settle:
            await settle()
        people = await self._people(deal_id)
        person = people.get(role) or Person(role=role)
        named, record, first_clip = [], [], None
        for d in untold:
            fact = await self.on_record(deal_id, d.item)
            d.fact_id = fact.id if fact else None
            named.append((d.item, _shown(fact, d.value)))
            if fact:
                line, clip = await self._quote(fact, people)
                record.append(line)
                first_clip = first_clip or clip
        rest = term_words.rest_confirmed(person, people.get(role.other) or Person(role=role.other),
                                         self._everything(deal_id, role) and self._everything(deal_id, role.other),
                                         self._everything(deal_id, role))
        text = term_words.disputed(person, named, rest, record)
        for p in people.values():
            self.s.outbox.send(deal_id, p.phone, p.role, text, link=first_clip, link_label=words.CLIP_BUTTON)
        for d, (_, shown) in zip(untold, named):
            self._offer(d, person, shown, term_words.choose)
            self._publish(d, DisputeStep.OPENED)
            when = self.s.wall() + timedelta(seconds=tuning.DISPUTE_REMINDER_SECONDS)
            self.reminders.at(deal_id, d.item, when, d.id)
        self.s._note(deal_id, f"the {role.value} said no to {', '.join(d.item.value for d in untold)} on the call-back: "
                     "told both what the record holds, agreement held", facts=[])

    def _offer(self, d: TermOpen, person: Person, shown: str | None, say) -> None:
        if not person.phone:
            return
        text = say(d.item, shown, not self.s.outbox.rich)
        buttons = ((f"term-ok:{d.id}", term_words.RECORDING_BUTTON), (f"term-other:{d.id}", term_words.OTHER_BUTTON))
        self.s.outbox.send(d.deal_id, person.phone, person.role, text, buttons=buttons)

    # ---------- their answer ----------

    async def reply(self, deal: Deal, sender: Person, text: str, button: str | None) -> bool:
        """A message from someone with a term in dispute. True if it was an answer here: a
        choice, or their version once asked for it."""
        mine = self._mine(deal.id, sender.role)
        choice, chosen = _tapped(button)
        if button and choice is not None:
            d = self.open.get(chosen)
            if d is None or d.deal_id != deal.id:
                self.s.outbox.send(deal.id, sender.phone, sender.role, words.ALREADY_ANSWERED)
                return True
        else:
            choice = term_words.CHOICES.get(" ".join(text.split()).casefold().rstrip(".!"))
            asked = [d for d in mine if d.step is DisputeStep.ASKED]
            if asked and text.strip() and (choice is None or text.strip() in ("1", "2")):
                await self.version(deal, sender, text.strip())
                return True
            offered = [d for d in mine if d.step in OFFERED]
            if choice is None or not offered:
                return False
            d = offered[0]
        if choice:
            self._withdraw(d, sender, text)
        else:
            self.s.outbox.send(deal.id, sender.phone, sender.role, term_words.ask_version(d.item))
            self._publish(d, DisputeStep.ASKED)
            self.s._note(deal.id, f"the {sender.role.value} says something else was agreed for the {d.item.value}: "
                         "asked for their version")
        return True

    def waiting(self, deal_id: str, role: Role) -> bool:
        """Their version is asked for: their next voice note is it."""
        return any(d.step is DisputeStep.ASKED for d in self._mine(deal_id, role))

    def _withdraw(self, d: TermOpen, sender: Person, said: str) -> None:
        """The recording is right: the same as a yes to this term on the call-back."""
        d.settling = "recording"
        self.s.bus.publish(TermsConfirmed(
            deal_id=d.deal_id, person=d.person, item=d.item, value=d.value, said=said or term_words.RECORDING_BUTTON,
        ))

    async def version(self, deal: Deal, sender: Person, text: str, voice: dict | None = None) -> None:
        """What they say was agreed: kept beside the record, and both see both."""
        d = next(d for d in self._mine(deal.id, sender.role) if d.step is DisputeStep.ASKED)
        d.version = text
        self._publish(d, DisputeStep.VERSION, version=text, version_fact_id=new_id(),
                      media_key=(voice or {}).get("media_key"), seconds=(voice or {}).get("seconds"))
        people = await self._people(deal.id)
        fact = await self.on_record(deal.id, d.item)
        record, clip = await self._quote(fact, people) if fact else (None, None)
        theirs = term_words.version_line(people.get(sender.role) or sender, text)
        for p in people.values():
            url = self.s.link(call_path(deal.id, p.role))
            self.s.outbox.send(deal.id, p.phone, p.role, term_words.both_versions(d.item, record, theirs, url),
                               link=url, link_label=CALL_BUTTON)
        self.s._note(deal.id, f"the {sender.role.value}'s version of the {d.item.value} kept beside the record: "
                     "both told both, with a call link", fact)

    # ---------- settled, reminded ----------

    async def _settled(self, d: TermOpen, how: str, new: str | None = None) -> None:
        self._publish(d, DisputeStep.SETTLED, how=how)
        people = await self._people(d.deal_id)
        person = people.get(d.person) or Person(role=d.person)
        fact = await self.on_record(d.deal_id, d.item)
        shown = _shown(fact, d.value)
        done = term_words.ALL_SETTLED if self._all_settled(d.deal_id) else ""  # its yes to the rest comes next
        for p in people.values():
            if how == "changed":
                text = term_words.changed(d.item, _figure(new))
            elif how == "recording":
                text = (term_words.withdrawn_for_them(d.item, shown) if p.role is d.person
                        else term_words.withdrawn_for_other(person, d.item, shown))
            else:
                text = term_words.confirmed(person, d.item, shown)
            self.s.outbox.send(d.deal_id, p.phone, p.role, text + done)
        self.s._note(d.deal_id, f"the dispute on the {d.item.value} is settled ({how})"
                     + ("; nothing else open, the agreement can be written" if done else ""), fact)

    async def remind(self, deal_id: str, item: ItemKey, dispute_id: str) -> bool:
        d = self.open.get(dispute_id)
        if d is None or d.step is None:
            return False
        people = await self._people(deal_id)
        person = people.get(d.person) or Person(role=d.person)
        shown = _shown(await self.on_record(deal_id, item), d.value)
        for p in people.values():
            self.s.outbox.send(deal_id, p.phone, p.role, term_words.remind(person, item, shown))
        self._offer(d, person, shown, term_words.choose)
        self._publish(d, DisputeStep.REMINDED)
        self.s._note(deal_id, f"the {item.value} is still in dispute: reminded both, once")
        return True

    def still_open(self, deal_id: str) -> str:
        """Said under an owed message or a reminder: the terms in dispute."""
        items = sorted({d.item for d in self.open.values() if d.deal_id == deal_id}, key=list(ItemKey).index)
        return term_words.still_open(items)

    # ---------- helpers ----------

    def _publish(self, d: TermOpen, step: DisputeStep, **more) -> None:
        event = TermDispute(deal_id=d.deal_id, dispute_id=d.id, item=d.item, person=d.person, step=step,
                            fact_id=d.fact_id, **more)
        if step is not DisputeStep.SETTLED:
            self.apply(event)
        self.s.bus.publish(event)

    def _everything(self, deal_id: str, role: Role) -> bool:
        """Every term other than those in dispute is confirmed by them: a yes to all on a
        call-back, or a call-back that went to its end."""
        return (deal_id, role) in self.all_yes or self.finished.get((deal_id, role), False)

    def _all_settled(self, deal_id: str) -> bool:
        return not any(d.deal_id == deal_id for d in self.open.values()) and all(
            self._everything(deal_id, r) for r in Role)

    async def on_record(self, deal_id: str, item: ItemKey) -> Fact | None:
        """The term on record: the one standing, or failing that the last one in dispute."""
        view = await self.s.memory.get_term(deal_id, item)
        if view.current is not None:
            return view.current
        latest = {f.id: f for f in view.history}
        disputed = [f for f in latest.values() if f.status is FactStatus.DISPUTED and f.kind.value == "term"]
        return disputed[-1] if disputed else None

    async def _quote(self, fact: Fact, people: dict[Role, Person]) -> tuple[str, str | None]:
        clip = await self.s._clip(fact)
        name = lambda role: words.who(people.get(role) or Person(role=role)) if role else None  # noqa: E731
        yes = next((r for r in [*fact.agreed_by, *fact.confirmed_by] if r != fact.said_by), None)
        when = f"call {fact.call_no} mein" + (f" ({_clock(fact.start)})" if fact.start is not None else "") \
            if fact.call_no is not None and fact.source.value == "call" else self.s.when(fact)
        line = dispute_words.quote_term(fact.item, _shown(fact, None), when, name(fact.said_by), name(yes), fact.quote, clip)
        return line, clip

    async def _people(self, deal_id: str) -> dict[Role, Person]:
        return {p.role: p for p in await self.s._people(deal_id)}


CALL_BUTTON = "Call kholiye"  # as app/whatsapp/words.py: records does not import the whatsapp stream


def _tapped(button: str | None) -> tuple[bool | None, str | None]:
    said, _, dispute_id = (button or "").partition(":")
    return {"term-ok": True, "term-other": False}.get(said), dispute_id or None


def _shown(fact: Fact | None, read: str | None) -> str | None:
    """The term's figure as on record (₹22,000), or failing that its words."""
    if fact is not None and fact.value_rupees is not None and fact.item in MONEY:
        return words.rupees(fact.value_rupees)
    return (fact.value if fact is not None and fact.value else read) or None


def _figure(new: str | None) -> str:
    found = re.fullmatch(r"([\d,]+) rupees", (new or "").strip())
    return f"₹{found.group(1)}" if found else new or ""


def _clock(seconds: float) -> str:
    return f"{int(seconds // 60)}:{int(seconds % 60):02d}"
