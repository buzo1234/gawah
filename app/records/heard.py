"""The Sentinel's watch over voice notes: what memory found in one, answered on WhatsApp.

- A contradiction of an agreed term (fact.conflict with no call): both hear what was agreed,
  when, and the clip, as for a payment claim larger than what is owed.
- A change to an agreed term: the other person is asked yes or no (Intake.ask_change), and
  fact.changed carries each step. Nothing changes until they say yes."""

from typing import TYPE_CHECKING

from app.contracts import ChangeStatus, Fact, FactChanged, FactConflict, ItemKey
from app.records import words

if TYPE_CHECKING:
    from app.records.sentinel import Sentinel

MONEY_TERMS = (ItemKey.AMOUNT, ItemKey.ADVANCE, ItemKey.BALANCE)


async def on_conflict(s: "Sentinel", event: FactConflict) -> None:
    """A contradiction found outside a call: a voice note. Told to both, as a payment
    claim larger than what is owed is."""
    if event.call_no is not None or not event.fact_ids:
        return
    against = await _fact(s, event.deal_id, event.fact_ids[0])
    people = {p.role: p for p in await s._people(event.deal_id)}
    speaker = people.get(event.speaker) if event.speaker else None
    if against is None or speaker is None:
        return
    clip = await s._clip(against)
    value = words.rupees(against.value_rupees) if against.value_rupees is not None else against.value or against.text
    line = words.contradicted(speaker, event.said or "", against.item, value, s.when(against), clip)
    for person in people.values():
        s.outbox.send(event.deal_id, person.phone, person.role, line, link=clip, link_label=words.CLIP_BUTTON)
    term = against.item.value if against.item else "deal"
    s._note(event.deal_id, f"voice note from the {speaker.role.value} differs from the {term} agreed: "
            "told both what was agreed" + (", with the clip" if clip else ""), against)


async def put_change(s: "Sentinel", fact: Fact) -> None:
    """A change asked for in a voice note: nothing changes until the other person says yes."""
    current = (await s.memory.get_term(fact.deal_id, fact.item)).current
    people = {p.role: p for p in await s._people(fact.deal_id)}
    sender, other = people.get(fact.said_by), people.get(fact.said_by.other)
    if current is None or sender is None or s.ask_change is None:
        return
    if other is None:
        s._note(fact.deal_id, f"change to the {fact.item.value} asked by voice note: no one to ask", fact)
        return
    money = fact.value_rupees is not None and fact.item in MONEY_TERMS
    new = f"{fact.value_rupees:,} rupees" if money else fact.value or fact.text
    old = words.rupees(current.value_rupees) if money and current.value_rupees is not None else current.value or current.text
    change = FactChanged(
        deal_id=fact.deal_id, fact_id=current.id, new_value=new, item=fact.item, proposed_by=fact.said_by,
        confirmed_by=[fact.said_by], status=ChangeStatus.CONFIRMED_ONE, said=fact.quote,
    )
    shown = words.rupees(fact.value_rupees) if money else new
    s.ask_change(change, sender, other, words.change_question(sender, fact.quote or fact.text, fact.item, old, shown))
    s._note(fact.deal_id, f"change to the {fact.item.value} asked by voice note ({new}): "
            f"asked the {other.role.value} to confirm", fact)


async def _fact(s: "Sentinel", deal_id: str, fact_id: str) -> Fact | None:
    """A fact as it stands, by id: MemoryQueries finds facts by term, so look in each."""
    for item in ItemKey:
        found = [f for f in (await s.memory.get_term(deal_id, item)).history if f.id == fact_id]
        if found:
            return found[-1]
    return None
