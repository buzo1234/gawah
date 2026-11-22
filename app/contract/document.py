"""The work agreement as a document: every line in Hindi and in English.

The model writes only the terms (and both sides of each change, and the other things both
agreed), and finds the names and the place said on the calls. Everything else here
(reference number, version, date, phone numbers, call times, the payment amounts, who
confirmed and when, the witness lines, the chain) is filled in by code from the store, the
events and memory's facts, so it cannot be invented. Nothing is added that was not said on
a call: no governing-law, penalty, warranty or other standard clause.

page.py turns a Document into the page that is printed to PDF.
"""

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.contract import check
from app.contract.terms import AlsoAgreed, Bi, Change, Said, Term
from app.contract.trigger import Call
from app.contract.wording import (
    ALL_AGREED, ALSO_AGREED, AS_STATED, CLAUSES, LEAD, NOT_AGREED, OPEN_CLAUSE, OPEN_POINTS, PARTIES,
    PAYMENT_CLAUSE, PAYMENTS, ROLES, SUBTITLE, THE_REST, VOICES, WITNESS,
)
from app.contracts import Fact, FactKind, FactSource, FactStatus, ItemKey, Person, Role

__all__ = ["Bi", "Document", "build", "both"]

IST = ZoneInfo("Asia/Kolkata")
_MONTHS_HI = ("जनवरी", "फ़रवरी", "मार्च", "अप्रैल", "मई", "जून", "जुलाई", "अगस्त", "सितंबर", "अक्टूबर", "नवंबर", "दिसंबर")
# A figure the value itself marks as money: "3,000 rupees", "₹3,000", "Rs 3000".
_MONEY = re.compile(
    r"(?:₹|rs\.?|inr)\s*(\d[\d,]*)|(\d[\d,]*(?:\s*(?:hazaar|hazar|thousand|k|lakhs?|lac))?)\s*(?:rupees?|rupaye|rupay|rs\b|/-)",
    re.IGNORECASE,
)
# Said of one call; with more than one call, the same words for all of them.
_PLURAL = (
    (r"\bon the call\b", "on the calls"), (r"\bon a recorded call\b", "on recorded calls"),
    (r"\band recorded it\b", "and recorded them"), ("इस कॉल पर", "इन कॉल पर"), ("कॉल रिकॉर्ड की।", "कॉल रिकॉर्ड कीं।"),
)


@dataclass
class Party:
    title: Bi  # first party / second party
    role: Bi
    name: Bi | None  # None when the name was never said on the call
    phone: str

    def line(self) -> str:
        name = f"{both(self.name)}, " if self.name else ""
        return f"{self.title.hi} ({self.role.hi}) / {self.title.en} ({self.role.en}): {name}फ़ोन / phone {self.phone}"


@dataclass
class Payment:
    label: Bi
    amount: Bi
    when: Bi
    said_at: str | None


@dataclass
class Note:
    """Something else both agreed, with the words it was said in."""

    text: Bi
    said: str | None
    said_at: str | None


@dataclass
class Clause:
    title: Bi
    body: Bi | None = None
    said_at: str | None = None  # "call no, minutes:seconds into that call"
    payments: list[Payment] = field(default_factory=list)
    notes: list[Note] = field(default_factory=list)
    changed: bool = False


@dataclass
class ChangeRow:
    n: int
    term: Bi
    before: Bi
    now: Bi
    said_at: str | None
    when: Bi
    said: str | None


@dataclass
class Acceptance:
    party: Party
    when: Bi
    said: str | None


@dataclass
class Document:
    reference: str
    version: int
    date: Bi
    made: Bi  # when this document was made, for the footer
    place: Bi | None
    subtitle: Bi
    lead: Bi
    parties: list[Party]
    clauses: list[Clause]
    changes: list[ChangeRow]
    acceptances: list[Acceptance]
    witness: Bi
    calls: list[Bi]
    fingerprints: list[tuple[Bi, str]]
    chain: tuple[str, int] | None  # head fingerprint and number of links, when the chain held

    @property
    def version_line(self) -> Bi:
        if self.version == 1:
            return Bi(f"संस्करण {self.version}", f"Version {self.version}")
        return Bi(f"संस्करण {self.version} (संस्करण {self.version - 1} की जगह)",
                  f"Version {self.version} (replaces version {self.version - 1})")

    def text(self) -> str:
        from app.contract.plain import text  # plain.py reads this module's types

        return text(self)


def build(
    *,
    deal_id: str,
    people: dict[Role, Person],
    names: dict[Role, Bi | None],
    place: Bi | None,
    terms: list[Term],
    bodies: dict[str, dict[str, str]],
    confirmed_at: dict[Role, datetime],
    confirmed_said: dict[Role, str | None],
    calls: dict[int, Call],
    fingerprints: dict[tuple[int, Role], str],
    now: datetime,
    version: int = 1,
    changes: list[Change] = (),
    change_texts: dict[str, tuple[Bi, Bi]] | None = None,
    also: list[AlsoAgreed] = (),
    also_texts: dict[str, Bi] | None = None,
    chain: tuple[str, int] | None = None,
    facts: dict[str, Fact] | None = None,
) -> Document:
    """names and place are what was said on the calls (None if never said); bodies is the
    model's text, {item key: {"hi": ..., "en": ...}}, and change_texts and also_texts its
    text for each change (before, now) and each other thing agreed; fingerprints is the
    SHA-256 of each person's recording of each call, for those that could be read; facts is
    each fact as it stands, for the payment and work claims still in dispute."""
    agreed = {t.item.key: t for t in terms if t.item.value}
    many = len(calls) > 1
    say = (lambda text: _plural(text)) if many else (lambda text: text)  # noqa: E731

    def body(key: ItemKey) -> Bi:
        return Bi(bodies[key.value]["hi"].strip(), bodies[key.value]["en"].strip())

    def said_at(key: ItemKey) -> str | None:
        return agreed[key].at.label() if agreed[key].at else None

    said = {key: found for key in ItemKey if key not in agreed and (found := said_not_agreed(facts or {}, key, names))}

    def clause(key: ItemKey) -> Clause:
        if key in said:
            return Clause(CLAUSES[key], said[key].text, said[key].said_at)
        if key not in agreed:
            return Clause(CLAUSES[key], say(NOT_AGREED))
        return Clause(CLAUSES[key], body(key), said_at(key), changed=agreed[key].changed)

    payments = [
        Payment(PAYMENTS[key], _amount(agreed[key].item.value, THE_REST if key is ItemKey.BALANCE else AS_STATED), body(key), said_at(key))
        for key in (ItemKey.ADVANCE, ItemKey.BALANCE) if key in agreed
    ]
    still_open = [OPEN_POINTS[key] for key in ItemKey if key not in agreed]
    notes = [Note((also_texts or {})[a.key], a.quote, a.at.label() if a.at else None) for a in also]
    clauses = [
        clause(ItemKey.WORK),
        clause(ItemKey.AMOUNT),
        Clause(PAYMENT_CLAUSE, None if payments else say(NOT_AGREED), payments=payments,
               notes=[said[k] for k in (ItemKey.ADVANCE, ItemKey.BALANCE) if k in said] + disputed(facts or {}, names),
               changed=any(agreed[k].changed for k in (ItemKey.ADVANCE, ItemKey.BALANCE) if k in agreed)),
        clause(ItemKey.DATES),
        clause(ItemKey.LATE_OR_UNFINISHED),
        *([Clause(ALSO_AGREED, notes=notes)] if notes else []),
        Clause(OPEN_CLAUSE, say(Bi(
            "कॉल पर ये बातें तय नहीं हुईं: " + "; ".join(p.hi for p in still_open) + "।",
            "These were not agreed on the call: " + "; ".join(p.en for p in still_open) + ".",
        )) if still_open else say(ALL_AGREED)),
    ]
    parties = {
        role: Party(PARTIES[role], ROLES[role], names.get(role), (people.get(role) and people[role].phone) or "-")
        for role in Role
    }
    rows = [
        ChangeRow(n, CLAUSES.get(c.item) or PAYMENTS[c.item], *(change_texts or {})[c.key],
                  c.at.label() if c.at else None, _moment(c.when), c.said)
        for n, c in enumerate(changes, 1)
    ]
    return Document(
        reference="GW-" + re.sub(r"[^A-Za-z0-9-]", "-", deal_id).upper(),
        version=version,
        date=_day(now),
        made=_moment(now),
        place=place,
        subtitle=say(SUBTITLE),
        lead=say(LEAD),
        parties=list(parties.values()),
        clauses=clauses,
        changes=rows,
        acceptances=[Acceptance(parties[role], _moment(confirmed_at[role]), confirmed_said.get(role)) for role in Role],
        witness=say(WITNESS),
        calls=[line for n in sorted(calls) if (line := _call(n, calls[n]))],
        fingerprints=[
            (Bi(f"कॉल {n} · {VOICES[role].hi}", f"Call {n} · {VOICES[role].en}"), fingerprints[(n, role)])
            for n in sorted(calls) for role in Role if (n, role) in fingerprints
        ],
        chain=chain,
    )


def said_not_agreed(facts: dict[str, Fact], key: ItemKey, names: dict[Role, Bi | None]) -> Note | None:
    """A term said on a call that was never agreed: never left out, written as not agreed, with
    the last thing said for it and who said it, in their own words. Who said it, never who is right."""
    said = sorted(
        (f for f in facts.values() if f.item is key and f.kind is FactKind.TERM and f.source is FactSource.CALL
         and f.status in (FactStatus.SAID, FactStatus.AGREED) and f.said_by is not None and (f.quote or f.value)),
        key=lambda f: (f.call_no or 0, f.line_no or 0),
    )
    if not said:
        return None
    fact, label = said[-1], CLAUSES.get(key) or PAYMENTS[key]
    who = names.get(fact.said_by) or ROLES[fact.said_by]
    words = " ".join((fact.quote or fact.value).split())
    value = f" ({fact.value})" if fact.value and fact.quote else ""
    return Note(Bi(
        f"{label.hi}: तय नहीं हुआ। कॉल पर {who.hi} ने कहा: “{words}”",
        f"{label.en}: not agreed. On the call, {who.en} said: “{words}”{value}.",
    ), None, Said(fact.call_no, fact.start).label() if fact.call_no else None)


def disputed(facts: dict[str, Fact], names: dict[Role, Bi | None]) -> list[Note]:
    """A payment or the work, reported by one person on WhatsApp and denied by the other, and
    not confirmed since: listed as disputed, not counted. Who said what, never who is right."""
    notes = []
    for fact in facts.values():
        if fact.status is not FactStatus.DISPUTED or not fact.record_id or fact.said_by is None:
            continue
        who, other = (names.get(r) or ROLES[r] for r in (fact.said_by, fact.said_by.other))
        on = _day(fact.valid_from) if fact.valid_from else Bi("", "")
        if fact.kind is FactKind.PAYMENT and fact.value_rupees:
            figure = _amount(f"{fact.value_rupees} rupees", AS_STATED)
            hi, en = f"{figure.hi} का भुगतान बताया", f"reported a payment of {figure.en}"
            end = Bi("यह हिसाब में नहीं जुड़ा।", "It is not counted.")
        elif fact.kind is FactKind.WORK:
            hi, en = "काम पूरा होना बताया", "reported the work done"
            end = Bi("रिकॉर्ड में काम पूरा नहीं माना गया।", "It is not on record as done.")
        else:
            continue
        notes.append(Note(Bi(
            f"विवादित: {who.hi} ने {hi}" + (f" ({on.hi})" if on.hi else "") + f"; {other.hi} ने मना किया। {end.hi}",
            f"Disputed: {who.en} {en}" + (f" ({on.en})" if on.en else "") + f"; {other.en} said no. {end.en}",
        ), fact.quote, None))
    return notes


def both(text: Bi, joiner: str | None = None) -> str:
    if text.hi == text.en:
        return text.hi
    return f"{text.hi}{joiner}{text.en}" if joiner else f"{text.hi} ({text.en})"


def _amount(value: str, otherwise: Bi) -> Bi:
    """The payment's amount, only when the checklist value states exactly one."""
    found = list(_MONEY.finditer(value))
    if not found:
        return otherwise
    figures = check.numbers(found[0].group(1) or found[0].group(2))
    if len(found) > 1 or len(figures) != 1:
        return AS_STATED
    digits = str(int(figures.pop()))
    head, groups = digits[:-3], [digits[-3:]]
    while head:  # Indian grouping: 1,50,000
        head, groups = head[:-2], [head[-2:], *groups]
    return Bi("₹" + ",".join(groups), "₹" + ",".join(groups))


def _plural(text: Bi) -> Bi:
    for one, many in _PLURAL:
        text = Bi(re.sub(one, many, text.hi), re.sub(one, many, text.en))
    return text


def _call(n: int, call: Call) -> Bi | None:
    ended = call.ended
    duration = ended.duration if ended else None
    began = call.started or (ended.ts - timedelta(seconds=duration) if ended and duration else None)
    if began is None:
        if not ended:
            return None
        day = _day(ended.ts)
        return Bi(f"कॉल {n}: {day.hi} को हुई।", f"Call {n} was on {day.en}.")
    start = _moment(began)
    if not duration:
        return Bi(f"कॉल {n}: {start.hi} शुरू हुई।", f"Call {n} started on {start.en}.")
    minutes, seconds = divmod(int(duration), 60)
    return Bi(
        f"कॉल {n}: {start.hi} शुरू हुई और {minutes} मिनट {seconds} सेकंड चली।",
        f"Call {n} started on {start.en} and lasted {minutes} min {seconds} sec.",
    )


def _day(when: datetime) -> Bi:
    d = when.astimezone(IST)
    return Bi(f"{d.day} {_MONTHS_HI[d.month - 1]} {d.year}", f"{d.day} {d:%B %Y}")


def _moment(when: datetime) -> Bi:
    d = when.astimezone(IST)
    part = "रात" if d.hour < 4 or d.hour >= 20 else "सुबह" if d.hour < 12 else "दोपहर" if d.hour < 16 else "शाम"
    clock = f"{d.hour % 12 or 12}:{d.minute:02d}"
    day = _day(when)
    return Bi(f"{day.hi} को {part} {clock} बजे", f"{day.en} at {clock} {'am' if d.hour < 12 else 'pm'} IST")
