"""The call-back's steps, in order, and what came of them. No audio here.

The voice model is given one step at a time and reports each answer through a tool; the
tool's reply is the next step. So the order is ours, and the outcome is a structured
call, not a guess from a transcript. Gawah only reads back and asks: a disputed term is
recorded and passed on, never argued.

A change said or agreed on the deal call that was never confirmed through Gawah (the call
ended first) is not read as the term: it is put to the person as a change, in place of that
term's step ("Record mein X tha; call par Y kaha gaya. Kya aap ise Y karna chahte hain?").
Each answer is a fact.changed step, shared by both people's call-backs (`answers`), so the
second yes makes it confirmed_both and memory makes the new term.
"""

from collections.abc import Callable
from dataclasses import dataclass

from app.contracts import (
    ChangeStatus,
    ChecklistItem,
    ChecklistUpdated,
    Event,
    FactChanged,
    FactRecorded,
    ItemKey,
    ItemState,
    Person,
    Record,
    RecordConfirmed,
    RecordConfirmRequested,
    Role,
    TermsConfirmed,
    TermsDisputed,
)
from app.mouth import tuning
from app.mouth.left_open import OpenChange, Said, open_changes, said_not_agreed
from app.store import Store

_SAID = {"type": "string", "description": "The person's own words, as they said them."}
TOOLS = [
    {
        "type": "function",
        "name": "record_answer",
        "description": "Report the person's yes or no to the question about a record.",
        "parameters": {
            "type": "object",
            "properties": {"confirmed": {"type": "boolean", "description": "true if they say it is right"}, "said": _SAID},
            "required": ["confirmed", "said"],
        },
    },
    {
        "type": "function",
        "name": "term_answer",
        "description": "Report whether the person says the term just read is what was agreed on the call.",
        "parameters": {
            "type": "object",
            "properties": {
                "item": {"type": "string", "enum": [key.value for key in ItemKey]},
                "agrees": {"type": "boolean"},
                "said": _SAID,
            },
            "required": ["item", "agrees", "said"],
        },
    },
    {
        "type": "function",
        "name": "change_answer",
        "description": "Report whether the person wants the term changed to the value said on the call.",
        "parameters": {
            "type": "object",
            "properties": {"agrees": {"type": "boolean", "description": "true if they want the change"}, "said": _SAID},
            "required": ["agrees", "said"],
        },
    },
]


@dataclass
class _Step:
    say: str  # what the model is told to do
    ask: RecordConfirmRequested | None = None
    item: ChecklistItem | None = None
    change: OpenChange | None = None
    said: tuple[ItemKey, Said] | None = None  # a term said on the call and never agreed there


def _record_said(ask: RecordConfirmRequested) -> str:
    record: Record | None = ask.record
    if record is None:
        return f'"{ask.question}"' if ask.question else "a record"
    detail = tuning.RECORD_WORDS[record.kind]
    if record.amount is not None:
        detail += f" of {record.amount:,.0f} rupees"
    if record.date:
        detail += f", dated {record.date}"
    return f'"{record.text}" ({detail})' if record.text else detail


class Script:
    def __init__(
        self, deal_id: str, role: Role, people: list[Person], asks: list[RecordConfirmRequested],
        items: list[ChecklistItem], publish: Callable[[Event], None],
        changes: dict[ItemKey, OpenChange] | None = None, answers: dict[str, FactChanged] | None = None,
        said: dict[ItemKey, Said] | None = None, confirmed: dict[ItemKey, str] | None = None,
    ) -> None:
        """confirmed: what this person already confirmed, by term, at the value read to them then."""
        self.deal_id, self.role, self.publish = deal_id, role, publish
        names = {p.role: p.name.split()[0] for p in people if p.name}
        self.name = names.get(role) or "the person"
        self.other = names.get(role.other) or "the other person"
        self.persona = tuning.CALLBACK_PERSONA.format(name=self.name, role=tuning.ROLE_WORDS[role], other=self.other)
        self.steps: list[_Step] = []
        for ask in asks:
            sender = names.get(ask.record.sender if ask.record else role.other) or "The other person"
            self.steps.append(_Step(tuning.STEP_RECORD.format(sender=sender, said=_record_said(ask), name=self.name), ask=ask))
        self.answers = answers if answers is not None else {}  # change id -> its latest step, from either call-back
        open_keys = set(changes or {})  # its record is not what is being confirmed: never read as the term
        changes = {k: c for k, c in (changes or {}).items() if role not in self._step_of(c).confirmed_by}
        agreed = [item for item in items if item.state is ItemState.AGREED and item.value and item.key not in open_keys]
        confirmed = confirmed or {}
        # Confirmed before at the value on record now: not read again, one line covers them all.
        self.unchanged = [item.key for item in agreed if _same(confirmed.get(item.key), item.value)]
        self.terms = [item for item in agreed if item.key not in self.unchanged]
        for key in ItemKey:
            item = next((i for i in self.terms if i.key is key), None)
            if key in changes:
                c = changes[key]
                self.steps.append(_Step(tuning.STEP_CHANGE.format(
                    label=tuning.LABEL[key], old=c.record.value or c.record.text, new=c.change.value or c.change.text,
                    other=self.other), change=c))
            elif item:
                say = tuning.STEP_TERM.format(label=tuning.LABEL[item.key], value=item.value, key=item.key.value)
                self.steps.append(_Step(say, item=item))
            elif key in (said or {}):
                self.steps.append(_Step(self._said_step(key, said[key], names), said=(key, said[key])))
        read = {item.key for item in agreed} | open_keys | set(said or {})
        # Nothing said about these on the call: only these may be called never discussed, and only
        # to a person hearing it for the first time.
        self.never_agreed = [key for key in ItemKey if key not in read] if (items or said) and not confirmed else []
        self.disputed: list[ItemKey] = []
        self.said_yes: list[ItemKey] = []  # said on the call, and this person says it was agreed
        self.said_no: list[ItemKey] = []  # said on the call, and this person says it was not agreed
        self.at = 0

    def _said_step(self, key: ItemKey, said: Said, names: dict[Role, str]) -> str:
        mine = said.said_by is self.role
        who = names.get(said.said_by) if said.said_by else None
        return tuning.STEP_SAID.format(
            who=f"{self.name} (the person you are talking to)" if mine else who or "one of them",
            who_hi="aap" if mine else f"{who} ji" if who else "ek ne", label=tuning.LABEL[key], value=said.value,
            quote=" ".join(said.quote.split())[:200].replace('"', "'"), key=key.value, name=self.name,
        )

    @property
    def done(self) -> bool:
        return self.at >= len(self.steps)

    def opening(self) -> str:
        what = tuning.CALLBACK_WHAT_RECORD if self.steps and self.steps[0].ask else tuning.CALLBACK_WHAT_TERMS
        return tuning.CALLBACK_OPENING.format(name=self.name, what=what.format(other=self.other), step=self._now())

    def call(self, name: str, args: dict) -> str:
        """Take one tool call from the model. Returns what it is told next."""
        step = None if self.done else self.steps[self.at]
        said = str(args.get("said") or "")[:300] or None
        if step and step.ask and name == "record_answer" and isinstance(args.get("confirmed"), bool):
            record = step.ask.record.model_copy(update={"confirmed": args["confirmed"]}) if step.ask.record else None
            self.publish(RecordConfirmed(
                deal_id=self.deal_id, record_id=step.ask.record_id, confirmed_by=self.role,
                confirmed=args["confirmed"], record=record,
            ))
            self.at += 1
            return tuning.NEXT.format(step=self._now())
        if step and step.change and name == "change_answer" and isinstance(args.get("agrees"), bool):
            self._answer_change(step.change, args["agrees"], said)
            return self._next(said)
        if step and step.said and name == "term_answer" and args.get("item") == step.said[0].value and isinstance(args.get("agrees"), bool):
            key, what = step.said
            if args["agrees"]:  # agreed and confirmed for this person; memory makes it agreed once both say yes
                self.said_yes.append(key)
                self.publish(TermsConfirmed(deal_id=self.deal_id, person=self.role, item=key, value=what.value, said=said))
            else:  # not agreed: nothing to dispute, it stays open
                self.said_no.append(key)
            return self._next(said)
        item = step.item if step else None
        if item and name == "term_answer" and args.get("item") == item.key.value and isinstance(args.get("agrees"), bool):
            if not args["agrees"]:
                self.at += 1
                self.disputed.append(item.key)
                self.publish(TermsDisputed(deal_id=self.deal_id, person=self.role, item=item.key, value=item.value, said=said))
                return tuning.TERM_DISPUTED.format(name=self.name, other=self.other, step=self._now())
            return self._next(said)
        return tuning.NOT_NOW.format(step=self._now())

    def _next(self, said: str | None) -> str:
        self.at += 1
        if self.done and not self.disputed and (self.terms or self.said_yes):
            self.publish(TermsConfirmed(deal_id=self.deal_id, person=self.role, said=said))
        return tuning.NEXT.format(step=self._now())

    def _step_of(self, change: OpenChange) -> FactChanged:
        """The change's latest step, from either person's call-back, or as it stands before anyone answered."""
        return self.answers.get(change.change_id) or FactChanged(
            deal_id=self.deal_id, change_id=change.change_id, fact_id=change.record.id,
            new_value=change.change.value or change.change.text, item=change.record.item, proposed_by=change.change.said_by,
        )

    def _answer_change(self, change: OpenChange, agrees: bool, said: str | None) -> None:
        prior = self._step_of(change)
        if prior.change_id not in self.answers:
            self.publish(prior)  # proposed: put to them here, since nobody could on the call
        common = dict(deal_id=self.deal_id, change_id=prior.change_id, fact_id=prior.fact_id, new_value=prior.new_value,
                      item=prior.item, proposed_by=prior.proposed_by, said=said)
        if agrees:
            confirmed = sorted({*prior.confirmed_by, self.role}, key=list(Role).index)
            status = ChangeStatus.CONFIRMED_BOTH if len(confirmed) == 2 else ChangeStatus.CONFIRMED_ONE
            event = FactChanged(status=status, confirmed_by=confirmed, **common)
        else:
            event = FactChanged(status=ChangeStatus.WITHDRAWN, confirmed_by=prior.confirmed_by, **common)
        self.answers[prior.change_id] = event
        self.publish(event)

    def _now(self) -> str:
        """The current step, or how to end the call once the steps are done."""
        if not self.done:
            return self.steps[self.at].say
        labels = ", ".join(tuning.LABEL[key] for key in self.never_agreed)
        never = tuning.NEVER_AGREED.format(name=self.name, labels=labels) if labels else ""
        if self.unchanged:
            never = tuning.UNCHANGED.format(name=self.name, labels=", ".join(tuning.LABEL[k] for k in self.unchanged)) + never
        if self.said_no:
            never += tuning.SAID_NOT_AGREED.format(name=self.name, labels=", ".join(tuning.LABEL[k] for k in self.said_no))
        if self.disputed:
            disputed = ", ".join(tuning.LABEL[key] for key in self.disputed)
            end = tuning.END_DISPUTED.format(never=never, name=self.name, other=self.other, labels=disputed)
        elif self.terms or self.said_yes:
            end = tuning.END_CONFIRMED.format(never=never, name=self.name, other=self.other)
        else:
            end = never + tuning.END_RECORD_ONLY.format(name=self.name)
        return tuning.END.format(name=self.name) + end


async def build(
    store: Store, deal_id: str, role: Role, publish: Callable[[Event], None], answers: dict[str, FactChanged] | None = None,
) -> Script | None:
    """The script for one person, from the event log. None if there is nothing to ask them.
    answers: the fact.changed steps given on call-backs in this process, shared between them."""
    deal = await store.deal(deal_id)
    if deal is None:
        return None
    answers = answers if answers is not None else {}
    facts: dict[str, Fact] = {}
    steps: dict[str, FactChanged] = {}
    asks: dict[str, RecordConfirmRequested] = {}
    checklist: ChecklistUpdated | None = None
    confirmed: dict[ItemKey, str] = {}  # what this person confirmed, by term, at the value read to them
    for event in await store.events(deal_id):
        match event:
            case RecordConfirmRequested() if event.confirm_by is role:
                asks[event.record_id] = event
            case RecordConfirmed():
                asks.pop(event.record_id, None)
            case ChecklistUpdated():
                checklist = event
            case TermsConfirmed(person=person, item=None) if person is role and checklist:
                confirmed |= {i.key: i.value for i in checklist.items if i.state is ItemState.AGREED and i.value}
            case TermsConfirmed(person=person, item=key) if person is role and key and event.value:
                confirmed[key] = event.value
            case TermsDisputed(person=person, item=key) if person is role:
                confirmed = {k: v for k, v in confirmed.items() if key not in (None, k)}
            case FactRecorded():
                facts.pop(event.fact.id, None)  # in the order they last changed
                facts[event.fact.id] = event.fact
            case FactChanged():
                steps[event.change_id] = event
                if role in event.confirmed_by and event.item and event.status in (ChangeStatus.CONFIRMED_ONE, ChangeStatus.CONFIRMED_BOTH):
                    confirmed[event.item] = event.new_value  # confirmed the change, on the call or a call-back
    for change_id, step in steps.items():
        answers.setdefault(change_id, step)
    # A change both confirmed after the call's last checklist: the checklist's value for it is the old one.
    since = checklist.ts if checklist else None
    moved = {c.item for c in answers.values() if c.deal_id == deal_id and c.status is ChangeStatus.CONFIRMED_BOTH
             and (since is None or c.ts > since)}
    items = [i for i in checklist.items if i.key not in moved] if checklist else []
    changes = open_changes(facts, {**steps, **{k: v for k, v in answers.items() if v.deal_id == deal_id}})
    pending = {key for key in ItemKey if key not in changes and key not in moved} - {
        i.key for i in items if i.state is ItemState.AGREED and i.value}
    said = said_not_agreed(facts, pending, role)
    plan = Script(deal_id, role, deal.people, list(asks.values()), items, publish, changes, answers, said, confirmed)
    return plan if plan.steps else None


def _same(confirmed: str | None, now: str) -> bool:
    return confirmed is not None and " ".join(confirmed.split()).casefold() == " ".join(now.split()).casefold()
