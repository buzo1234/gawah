"""The work agreement as a document: every line in Hindi and in English.

The model writes only the terms, and finds the names and the place said on the call.
Everything else here (reference number, date, phone numbers, call times, the payment
amounts, who confirmed and when, the witness lines) is filled in by code from the store
and the events, so it cannot be invented. Nothing is added that was not said on the
call: no governing-law, penalty, warranty or other standard clause.

page.py turns a Document into the page that is printed to PDF.
"""

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import NamedTuple
from zoneinfo import ZoneInfo

from app.contract import check
from app.contracts import CallEnded, ChecklistItem, ItemKey, ItemState, Person, Role, TranscriptLine

IST = ZoneInfo("Asia/Kolkata")


class Bi(NamedTuple):
    hi: str
    en: str


TITLE = Bi("काम का अनुबंध", "Work Agreement")
SUBTITLE = Bi(
    "रिकॉर्ड की गई फ़ोन कॉल पर बोलकर हुए समझौते का लिखित रिकॉर्ड",
    "Written record of an agreement made by voice on a recorded call",
)
PARTIES = {Role.HIRER: Bi("पहला पक्ष", "First party"), Role.WORKER: Bi("दूसरा पक्ष", "Second party")}
ROLES = {Role.HIRER: Bi("काम देने वाले", "the hirer"), Role.WORKER: Bi("काम करने वाले", "the worker")}
LEAD = Bi("दोनों पक्षों ने कॉल पर ये बातें तय कीं।", "The two parties agreed the following on the call.")
CLAUSES = {
    ItemKey.WORK: Bi("काम", "The work"),
    ItemKey.AMOUNT: Bi("कीमत और उसमें क्या शामिल है", "The price and what it covers"),
    ItemKey.DATES: Bi("काम की तारीखें", "The dates"),
    ItemKey.LATE_OR_UNFINISHED: Bi("देर हुई या काम अधूरा रहा तो", "If the work is late or left unfinished"),
}
PAYMENT_CLAUSE = Bi("भुगतान कब और कैसे", "Payment schedule")
PAYMENTS = {ItemKey.ADVANCE: Bi("एडवांस", "Advance"), ItemKey.BALANCE: Bi("बाकी पैसा", "Balance")}
THE_REST = Bi("बाकी रकम", "The rest")
AS_STATED = Bi("जैसा आगे लिखा है", "As stated")
OPEN_CLAUSE = Bi("जो बातें तय नहीं हुईं", "What was not agreed")
NOT_AGREED = Bi("यह बात कॉल पर तय नहीं हुई।", "This was not agreed on the call.")
OPEN_POINTS = {
    ItemKey.WORK: Bi("काम क्या है", "what the work is"),
    ItemKey.AMOUNT: Bi("कीमत और उसमें क्या शामिल है", "the price and what it covers"),
    ItemKey.ADVANCE: Bi("एडवांस कितना और कब", "the advance, how much and when"),
    ItemKey.BALANCE: Bi("बाकी पैसा कब और किस बात पर मिलेगा", "when the balance is paid and against what"),
    ItemKey.DATES: Bi("काम कब शुरू और कब पूरा होगा", "the start and finish dates"),
    ItemKey.LATE_OR_UNFINISHED: Bi("देर होने या काम अधूरा रहने पर क्या होगा", "what happens if the work is late or left unfinished"),
}
ALL_AGREED = Bi(
    "गवाह छह बातें पूछता है: काम, कीमत, एडवांस, बाकी पैसा, तारीखें, और देर होने या काम अधूरा रहने पर क्या होगा। "
    "ये सभी छह बातें कॉल पर तय हुईं।",
    "Gawah checks six points: the work, the price, the advance, the balance, the dates, and what happens "
    "if the work is late or left unfinished. All six were agreed on the call.",
)
CONFIRMED = Bi("गवाह के साथ अलग कॉल पर बोलकर पुष्टि की", "Confirmed by voice on a separate call with Gawah")
WITNESS = Bi(
    "गवाह (Gawah) एक AI गवाह है। वह इस कॉल पर मौजूद था, और दोनों लोगों के रिकॉर्डिंग के लिए हाँ कहने के बाद उसने कॉल रिकॉर्ड की।",
    "Gawah is an AI witness. It was on the call, and recorded it after both people agreed to the recording.",
)
FINGERPRINT = Bi(
    "रिकॉर्डिंग की पहचान (SHA-256)। रिकॉर्डिंग ज़रा भी बदले तो ये अक्षर बदल जाते हैं।",
    "Recording fingerprint (SHA-256). If a recording is changed at all, these characters change.",
)
VOICES = {Role.HIRER: Bi("पहले पक्ष की आवाज़", "First party's audio"), Role.WORKER: Bi("दूसरे पक्ष की आवाज़", "Second party's audio")}
IS = Bi(
    "यह दस्तावेज़ बोलकर हुए समझौते का लिखित रिकॉर्ड है, जिसकी दोनों लोगों ने अलग-अलग पुष्टि की है।",
    "This document is a written record of a spoken agreement, confirmed separately by both people.",
)
IS_NOT = Bi(
    "इसे किसी वकील ने तैयार नहीं किया है और यह स्टाम्प पेपर पर नहीं है।",
    "It was not drafted by a lawyer and is not on stamp paper.",
)
IF_YOU_DISAGREE = Bi(
    "अगर बाद में किसी बात पर असहमति हो, तो दोनों में से कोई भी गवाह से उस बात की रिकॉर्डिंग माँग सकता है।",
    "If either person disagrees later, they can ask Gawah for the recording of any term.",
)
_MONTHS_HI = ("जनवरी", "फ़रवरी", "मार्च", "अप्रैल", "मई", "जून", "जुलाई", "अगस्त", "सितंबर", "अक्टूबर", "नवंबर", "दिसंबर")
# A figure the value itself marks as money: "3,000 rupees", "₹3,000", "Rs 3000".
_MONEY = re.compile(
    r"(?:₹|rs\.?|inr)\s*(\d[\d,]*)|(\d[\d,]*(?:\s*(?:hazaar|hazar|thousand|k|lakhs?|lac))?)\s*(?:rupees?|rupaye|rupay|rs\b|/-)",
    re.IGNORECASE,
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
class Clause:
    title: Bi
    body: Bi | None = None
    said_at: str | None = None  # minutes:seconds into the call
    payments: list[Payment] = field(default_factory=list)


@dataclass
class Acceptance:
    party: Party
    when: Bi
    said: str | None


@dataclass
class Document:
    reference: str
    date: Bi
    made: Bi  # when this document was made, for the footer
    place: Bi | None
    parties: list[Party]
    clauses: list[Clause]
    acceptances: list[Acceptance]
    call: Bi | None
    fingerprints: list[tuple[Bi, str]]

    def text(self) -> str:
        at = lambda t: f"  [कॉल / call {t}]" if t else ""  # noqa: E731
        lines = [TITLE.hi, TITLE.en.upper(), SUBTITLE.hi, SUBTITLE.en, "",
                 f"संदर्भ संख्या / Reference no.: {self.reference}", f"तारीख / Date: {self.date.hi} / {self.date.en}"]
        if self.place:
            lines.append(f"काम की जगह / Place of work: {both(self.place)}")
        lines += ["", "पक्ष / PARTIES", *(p.line() for p in self.parties), f"{LEAD.hi} / {LEAD.en}"]
        for n, clause in enumerate(self.clauses, 1):
            lines += ["", f"{n}. {clause.title.hi} / {clause.title.en}{at(clause.said_at)}"]
            if clause.body:
                lines += [clause.body.hi, clause.body.en]
            for pay in clause.payments:
                lines += [f"- {pay.label.hi} / {pay.label.en}: {both(pay.amount, ' / ')}{at(pay.said_at)}",
                          f"  {pay.when.hi}", f"  {pay.when.en}"]
        lines += ["", "स्वीकृति / ACCEPTANCE"]
        for a in self.acceptances:
            lines += [a.party.line(), f"{CONFIRMED.hi} / {CONFIRMED.en}", f"{a.when.hi} / {a.when.en}"]
            if a.said:
                lines.append(f"कहा / Said: “{a.said}”")
        lines += ["", "गवाह / WITNESS", WITNESS.hi, WITNESS.en]
        if self.call:
            lines += [self.call.hi, self.call.en]
        if self.fingerprints:
            lines += [FINGERPRINT.hi, FINGERPRINT.en, *(f"{who.hi} / {who.en}: {digest}" for who, digest in self.fingerprints)]
        lines += ["", "यह दस्तावेज़ क्या है / WHAT THIS DOCUMENT IS", IS.hi, IS.en, IS_NOT.hi, IS_NOT.en,
                  IF_YOU_DISAGREE.hi, IF_YOU_DISAGREE.en]
        return "\n".join(lines)


def build(
    *,
    deal_id: str,
    people: dict[Role, Person],
    names: dict[Role, Bi | None],
    place: Bi | None,
    items: list[ChecklistItem],
    bodies: dict[str, dict[str, str]],
    transcript: list[TranscriptLine],
    confirmed_at: dict[Role, datetime],
    confirmed_said: dict[Role, str | None],
    call: CallEnded | None,
    fingerprints: dict[Role, str],
    now: datetime,
) -> Document:
    """names and place are what was said on the call (None if never said); bodies is the
    model's text, {item key: {"hi": ..., "en": ...}}; fingerprints is the SHA-256 of each
    person's recording, for those that could be read."""
    lines = {line.line_no or n: line for n, line in enumerate(transcript, 1)}
    agreed = {i.key: i for i in items if i.state is ItemState.AGREED and i.value}

    def body(key: ItemKey) -> Bi:
        return Bi(bodies[key.value]["hi"].strip(), bodies[key.value]["en"].strip())

    def said_at(key: ItemKey) -> str | None:
        line = lines.get(agreed[key].line_no)
        return f"{int(line.start) // 60}:{int(line.start) % 60:02d}" if line else None

    def clause(key: ItemKey) -> Clause:
        return Clause(CLAUSES[key], body(key), said_at(key)) if key in agreed else Clause(CLAUSES[key], NOT_AGREED)

    payments = [
        Payment(PAYMENTS[key], _amount(agreed[key].value, THE_REST if key is ItemKey.BALANCE else AS_STATED), body(key), said_at(key))
        for key in (ItemKey.ADVANCE, ItemKey.BALANCE) if key in agreed
    ]
    still_open = [OPEN_POINTS[key] for key in ItemKey if key not in agreed]
    clauses = [
        clause(ItemKey.WORK),
        clause(ItemKey.AMOUNT),
        Clause(PAYMENT_CLAUSE, None if payments else NOT_AGREED, payments=payments),
        clause(ItemKey.DATES),
        clause(ItemKey.LATE_OR_UNFINISHED),
        Clause(OPEN_CLAUSE, Bi(
            "कॉल पर ये बातें तय नहीं हुईं: " + "; ".join(p.hi for p in still_open) + "।",
            "These were not agreed on the call: " + "; ".join(p.en for p in still_open) + ".",
        ) if still_open else ALL_AGREED),
    ]
    parties = {
        role: Party(PARTIES[role], ROLES[role], names.get(role), (people.get(role) and people[role].phone) or "-")
        for role in Role
    }
    return Document(
        reference="GW-" + re.sub(r"[^A-Za-z0-9-]", "-", deal_id).upper(),
        date=_day(now),
        made=_moment(now),
        place=place,
        parties=list(parties.values()),
        clauses=clauses,
        acceptances=[Acceptance(parties[role], _moment(confirmed_at[role]), confirmed_said.get(role)) for role in Role],
        call=_call(call),
        fingerprints=[(VOICES[role], fingerprints[role]) for role in Role if role in fingerprints],
    )


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


def _call(call: CallEnded | None) -> Bi | None:
    if not call:
        return None
    if not call.duration:
        day = _day(call.ts)
        return Bi(f"कॉल {day.hi} को हुई।", f"The call was on {day.en}.")
    start, (minutes, seconds) = _moment(call.ts - timedelta(seconds=call.duration)), divmod(int(call.duration), 60)
    return Bi(
        f"कॉल {start.hi} शुरू हुई और {minutes} मिनट {seconds} सेकंड चली।",
        f"The call started on {start.en} and lasted {minutes} min {seconds} sec.",
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
