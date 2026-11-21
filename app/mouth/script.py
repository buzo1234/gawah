"""The call-back's steps, in order, and what came of them. No audio here.

The voice model is given one step at a time and reports each answer through a tool; the
tool's reply is the next step. So the order is ours, and the outcome is a structured
call, not a guess from a transcript. Gawah only reads back and asks: a disputed term is
recorded and passed on, never argued.
"""

from collections.abc import Callable
from dataclasses import dataclass

from app.contracts import (
    ChecklistItem,
    ChecklistUpdated,
    Event,
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
        "name": "end_call",
        "description": "Hang up. Only when the steps are finished and you have said goodbye.",
        "parameters": {"type": "object", "properties": {}},
    },
]


@dataclass
class _Step:
    say: str  # what the model is told to do
    ask: RecordConfirmRequested | None = None
    item: ChecklistItem | None = None


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
    ) -> None:
        self.deal_id, self.role, self.publish = deal_id, role, publish
        names = {p.role: p.name.split()[0] for p in people if p.name}
        self.name = names.get(role) or "the person"
        self.other = names.get(role.other) or "the other person"
        self.persona = tuning.CALLBACK_PERSONA.format(name=self.name, role=tuning.ROLE_WORDS[role], other=self.other)
        self.steps: list[_Step] = []
        for ask in asks:
            sender = names.get(ask.record.sender if ask.record else role.other) or "The other person"
            self.steps.append(_Step(tuning.STEP_RECORD.format(sender=sender, said=_record_said(ask), name=self.name), ask=ask))
        self.terms = [item for item in items if item.state is ItemState.AGREED and item.value]
        for item in self.terms:
            say = tuning.STEP_TERM.format(label=tuning.LABEL[item.key], value=item.value, key=item.key.value)
            self.steps.append(_Step(say, item=item))
        read = {item.key for item in self.terms}
        self.never_agreed = [item.key for item in items if item.key not in read]
        self.disputed: list[ItemKey] = []
        self.at = 0
        self.hang_up = False  # the model has said goodbye and asked to end the call

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
        if name == "end_call":
            if step:
                return tuning.NOT_FINISHED.format(step=step.say)
            self.hang_up = True
            return "ok"
        if step and step.ask and name == "record_answer" and isinstance(args.get("confirmed"), bool):
            record = step.ask.record.model_copy(update={"confirmed": args["confirmed"]}) if step.ask.record else None
            self.publish(RecordConfirmed(
                deal_id=self.deal_id, record_id=step.ask.record_id, confirmed_by=self.role,
                confirmed=args["confirmed"], record=record,
            ))
            self.at += 1
            return tuning.NEXT.format(step=self._now())
        item = step.item if step else None
        if item and name == "term_answer" and args.get("item") == item.key.value and isinstance(args.get("agrees"), bool):
            self.at += 1
            if not args["agrees"]:
                self.disputed.append(item.key)
                self.publish(TermsDisputed(deal_id=self.deal_id, person=self.role, item=item.key, value=item.value, said=said))
                return tuning.TERM_DISPUTED.format(name=self.name, other=self.other, step=self._now())
            if self.done and not self.disputed:
                self.publish(TermsConfirmed(deal_id=self.deal_id, person=self.role, said=said))
            return tuning.NEXT.format(step=self._now())
        return tuning.NOT_NOW.format(step=self._now())

    def _now(self) -> str:
        """The current step, or how to end the call once the steps are done."""
        if not self.done:
            return self.steps[self.at].say
        labels = ", ".join(tuning.LABEL[key] for key in self.never_agreed)
        never = tuning.NEVER_AGREED.format(name=self.name, labels=labels) if labels else ""
        if self.disputed:
            disputed = ", ".join(tuning.LABEL[key] for key in self.disputed)
            return tuning.END_DISPUTED.format(never=never, name=self.name, other=self.other, labels=disputed)
        if self.terms:
            return tuning.END_CONFIRMED.format(never=never, name=self.name, other=self.other)
        return never + tuning.END_RECORD_ONLY.format(name=self.name)


async def build(store: Store, deal_id: str, role: Role, publish: Callable[[Event], None]) -> Script | None:
    """The script for one person, from the event log. None if there is nothing to ask them."""
    deal = await store.deal(deal_id)
    if deal is None:
        return None
    asks: dict[str, RecordConfirmRequested] = {}
    checklist: ChecklistUpdated | None = None
    settled = False  # this person has already confirmed every term of the latest checklist
    for event in await store.events(deal_id):
        match event:
            case RecordConfirmRequested() if event.confirm_by is role:
                asks[event.record_id] = event
            case RecordConfirmed():
                asks.pop(event.record_id, None)
            case ChecklistUpdated():
                checklist, settled = event, False
            case TermsConfirmed(person=person, item=None) if person is role:
                settled = True
            case TermsDisputed(person=person) if person is role:
                settled = False
    items = checklist.items if checklist and not settled else []
    if not asks and not items:
        return None
    return Script(deal_id, role, deal.people, list(asks.values()), items, publish)
