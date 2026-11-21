"""The contract as a document: every line in Hindi and in English.

The model writes only the six terms and the names. Everything else here (date, phone
numbers, call times, the closing statement, the deal id) is filled in by code from the
store, so it cannot be invented. One Document gives both the plain text and the page
that is printed to PDF.
"""

from dataclasses import dataclass
from datetime import datetime
from html import escape
from typing import NamedTuple
from zoneinfo import ZoneInfo

from app.contracts import ChecklistItem, ItemKey, ItemState, Person, Role, TranscriptLine

IST = ZoneInfo("Asia/Kolkata")


class Bi(NamedTuple):
    hi: str
    en: str


TITLE = Bi("सौदे का लिखित रिकॉर्ड", "Written record of a deal")
ROLES = {Role.HIRER: Bi("काम देने वाले", "Hirer"), Role.WORKER: Bi("काम करने वाले", "Worker")}
TERMS = {
    ItemKey.WORK: Bi("काम", "The work"),
    ItemKey.AMOUNT: Bi("कुल पैसा", "The amount"),
    ItemKey.ADVANCE: Bi("एडवांस", "The advance"),
    ItemKey.BALANCE: Bi("बाकी पैसा", "The balance"),
    ItemKey.DATES: Bi("काम की तारीखें", "The dates"),
    ItemKey.LATE_OR_UNFINISHED: Bi("देर हुई या काम अधूरा रहा तो", "If the work is late or left unfinished"),
}
NOT_AGREED = Bi("यह बात कॉल पर तय नहीं हुई।", "This was not agreed on the call.")
_MONTHS_HI = ("जनवरी", "फ़रवरी", "मार्च", "अप्रैल", "मई", "जून", "जुलाई", "अगस्त", "सितंबर", "अक्टूबर", "नवंबर", "दिसंबर")


@dataclass
class Party:
    role: Bi
    name: Bi
    phone: str


@dataclass
class Term:
    title: Bi
    body: Bi
    said_at: Bi | None = None


@dataclass
class Document:
    deal_id: str
    date: Bi
    parties: list[Party]
    terms: list[Term]
    statement: Bi

    def text(self) -> str:
        lines = [TITLE.hi, TITLE.en, "", f"तारीख / Date: {self.date.hi} / {self.date.en}",
                 f"सौदा नंबर / Deal ID: {self.deal_id}", "", "लोग / People"]
        lines += [f"{p.role.hi} / {p.role.en}: {_both(p.name)}, {p.phone}" for p in self.parties]
        lines += ["", "तय हुई बातें / What was agreed"]
        for n, term in enumerate(self.terms, 1):
            lines += ["", f"{n}. {term.title.hi} / {term.title.en}", term.body.hi, term.body.en]
            if term.said_at:
                lines.append(f"({term.said_at.hi} / {term.said_at.en})")
        lines += ["", "यह रिकॉर्ड क्या है / What this record is", self.statement.hi, self.statement.en]
        return "\n".join(lines)

    def html(self) -> str:
        e = escape
        people = "".join(
            f"<tr><th>{e(p.role.hi)} <span>/ {e(p.role.en)}</span></th>"
            f"<td>{e(_both(p.name))}, {e(p.phone)}</td></tr>" for p in self.parties
        )
        terms = "".join(
            f"<section><h2>{n}. {e(t.title.hi)} <span>/ {e(t.title.en)}</span></h2>"
            f"<p>{e(t.body.hi)}</p><p>{e(t.body.en)}</p>"
            + (f"<p class=when>{e(t.said_at.hi)} / {e(t.said_at.en)}</p>" if t.said_at else "")
            + "</section>"
            for n, t in enumerate(self.terms, 1)
        )
        return _PAGE.format(
            title_hi=e(TITLE.hi), title_en=e(TITLE.en), date=e(f"{self.date.hi} / {self.date.en}"),
            deal_id=e(self.deal_id), people=people, terms=terms,
            statement_hi=e(self.statement.hi), statement_en=e(self.statement.en),
        )


def build(
    deal_id: str,
    people: dict[Role, Person],
    names: dict[Role, Bi | None],
    items: list[ChecklistItem],
    bodies: dict[str, dict[str, str]],
    transcript: list[TranscriptLine],
    confirmed_at: dict[Role, datetime],
    call_ended_at: datetime | None,
    now: datetime,
) -> Document:
    """names holds the names said on the call (None if never said); bodies is the
    model's text, {item key: {"hi": ..., "en": ...}}."""
    lines = {line.line_no or n: line for n, line in enumerate(transcript, 1)}
    called = {role: names.get(role) or ROLES[role] for role in Role}
    terms = []
    for item in sorted(items, key=lambda i: list(ItemKey).index(i.key)):
        if item.state is not ItemState.AGREED or not item.value:
            terms.append(Term(TERMS[item.key], NOT_AGREED))
            continue
        body = bodies[item.key.value]
        line = lines.get(item.line_no)
        terms.append(Term(TERMS[item.key], Bi(body["hi"].strip(), body["en"].strip()), line and _said_at(line.start)))
    on_call = _day(call_ended_at) if call_ended_at else None
    confirms = {role: _moment(confirmed_at[role]) for role in Role}
    statement = Bi(
        f"यह {on_call.hi + ' को ' if on_call else ''}रिकॉर्ड की गई कॉल पर बोलकर तय हुए सौदे का लिखित रिकॉर्ड है। "
        f"दोनों लोगों ने ये बातें अलग-अलग सुनकर सही बताईं: {called[Role.HIRER].hi} ने "
        f"{confirms[Role.HIRER].hi} और {called[Role.WORKER].hi} ने {confirms[Role.WORKER].hi}।",
        f"This is a written record of a spoken agreement made on a recorded call"
        f"{' on ' + on_call.en if on_call else ''}. Both people confirmed these terms separately: "
        f"{called[Role.HIRER].en} on {confirms[Role.HIRER].en}, and {called[Role.WORKER].en} on "
        f"{confirms[Role.WORKER].en}.",
    )
    parties = [
        Party(ROLES[role], called[role], (people.get(role) and people[role].phone) or "-") for role in Role
    ]
    return Document(deal_id, _day(now), parties, terms, statement)


def _both(name: Bi) -> str:
    return name.hi if name.hi == name.en else f"{name.hi} ({name.en})"


def _said_at(seconds: float) -> Bi:
    minutes, secs = divmod(int(seconds), 60)
    return Bi(f"कॉल में {minutes} मिनट {secs} सेकंड पर कहा गया", f"Said {minutes} min {secs} sec into the call")


def _day(when: datetime) -> Bi:
    d = when.astimezone(IST)
    return Bi(f"{d.day} {_MONTHS_HI[d.month - 1]} {d.year}", f"{d.day} {d:%B %Y}")


def _moment(when: datetime) -> Bi:
    d = when.astimezone(IST)
    part = "रात" if d.hour < 4 or d.hour >= 20 else "सुबह" if d.hour < 12 else "दोपहर" if d.hour < 16 else "शाम"
    clock = f"{d.hour % 12 or 12}:{d.minute:02d}"
    day = _day(when)
    return Bi(f"{day.hi} को {part} {clock} बजे", f"{day.en} at {clock} {'am' if d.hour < 12 else 'pm'}")


_PAGE = """<!doctype html>
<html lang="hi"><head><meta charset="utf-8"><title>{title_en}</title><style>
@page {{ size: A4; margin: 13mm 16mm; }}
body {{ font-family: "Kohinoor Devanagari", "Noto Sans Devanagari", "Devanagari Sangam MN", "Nirmala UI",
  "Helvetica Neue", Arial, sans-serif; font-size: 10.5pt; line-height: 1.4; color: #111; margin: 0; }}
h1 {{ font-size: 16pt; line-height: 1.3; margin: 0 0 2mm; }}
h1 span, h2 span, th span {{ font-weight: normal; }}
h2 {{ font-size: 11pt; margin: 0 0 0.5mm; }}
h3 {{ font-size: 11pt; margin: 4mm 0 1.5mm; padding-bottom: 0.8mm; border-bottom: 0.3mm solid #999; }}
p {{ margin: 0; }}
table {{ border-collapse: collapse; }}
th {{ text-align: left; padding: 0 6mm 0.5mm 0; }}
td {{ padding: 0 0 0.5mm; }}
section {{ margin: 0 0 2.4mm; break-inside: avoid; }}
.when, .meta {{ color: #555; font-size: 9.5pt; }}
.statement {{ break-inside: avoid; }}
</style></head><body>
<h1>{title_hi}<br><span>{title_en}</span></h1>
<p class="meta">तारीख / Date: {date}<br>सौदा नंबर / Deal ID: {deal_id}</p>
<h3>लोग / People</h3>
<table>{people}</table>
<h3>तय हुई बातें / What was agreed</h3>
{terms}
<div class="statement"><h3>यह रिकॉर्ड क्या है / What this record is</h3>
<p>{statement_hi}</p><p>{statement_en}</p></div>
</body></html>
"""
