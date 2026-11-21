"""What Gawah says on WhatsApp about records. Short, plain Hinglish in Roman script.
Gawah never gives an opinion, so none of these do."""

from datetime import date

from app.contracts import ItemKey, Person, Record, RecordKind, Role

_ROLE = {Role.HIRER: "Kaam dene wale", Role.WORKER: "Kaam karne wale"}
_KIND = {
    RecordKind.ADVANCE: "advance",
    RecordKind.PAYMENT: "payment",
    RecordKind.WORK_DONE: "kaam poora",
}

ANSWER_NOTED = "Shukriya, aapka jawab likh liya."
ALREADY_ANSWERED = "Is sawaal ka jawab pehle hi likh liya hai."
# Reply buttons under a yes-or-no question (at most 20 characters each).
YES_BUTTON, NO_BUTTON = "Haan, sahi hai", "Nahi"
CLIP_BUTTON = "Wo pal suniye"  # the link to the clip, as a button


def who(person: Person) -> str:
    return f"{person.name} ji" if person.name else _ROLE[person.role]


def describe(record: Record) -> str:
    """The extracted fields in a few words, e.g. '₹8,000 payment, transaction id T123, 21 Nov'."""
    parts = [" ".join(filter(None, [_rupees(record.amount), _KIND.get(record.kind, "record")]))]
    if record.transaction_id:
        parts.append(f"transaction id {record.transaction_id}")
    if record.date:
        parts.append(record.date)
    return ", ".join(parts)


def logged(record: Record) -> str:
    return f"Record mein likh liya: {describe(record)}."


def asking_other(other: Person, record: Record | None = None) -> str:
    if record is not None and record.extra.get("voice_note") is not None and record.text:
        return f"{heard(record.text)} {who(other)} se confirm kar raha hoon."
    return f"Likh liya. {who(other)} se confirm kar raha hoon."


def confirm_question(sender: Person, record: Record) -> str:
    if record.extra.get("voice_note") is not None and record.text:
        said = f'ne voice note mein kaha: "{_short(record.text)}"'
    else:
        said = f'ne likha hai: "{record.text}"' if record.text else f"ne ek photo bheji hai: {describe(record)}"
    return f"{who(sender)} {said}. Kya yeh sahi hai? Haan ya nahi likhiye."


# ---------- voice notes ----------

VOICE_EMPTY = "Voice note mein kuch sunai nahi diya. Dobara bhejiye, ya likh kar bhejiye."
VOICE_FAILED = "Abhi voice note sun nahi paaya. Thodi der mein dobara bhejiye, ya likh kar bhejiye."


def heard(text: str) -> str:
    return f'Aapka voice note suna: "{_short(text)}".'


def voice_kept(text: str) -> str:
    """A voice note that is not a payment or work record: what was heard, and that it is kept."""
    return f"{heard(text)} Deal ke record mein rakh liya."


def _short(text: str, limit: int = 160) -> str:
    return text if len(text) <= limit else text[: limit - 1].rsplit(" ", 1)[0] + "…"


def answer_for_sender(answerer: Person, record: Record, confirmed: bool) -> str:
    what = f'"{record.text}"' if record.text else describe(record)
    if confirmed:
        return f"{who(answerer)} ne haan kaha. {what} record mein confirm ho gaya."
    return f"{who(answerer)} ne nahi kaha. {what} record mein bina confirm ke likha hai."


def _rupees(amount: float | None) -> str | None:
    return None if amount is None else f"₹{amount:,.0f}"


# ---------- the Sentinel: what is owed, what was agreed, reminders ----------

_TERM = {ItemKey.ADVANCE: "advance", ItemKey.AMOUNT: "kul paisa", ItemKey.BALANCE: "baaki paisa"}
_ANY_TERM = _TERM | {
    ItemKey.WORK: "kaam", ItemKey.DATES: "kaam ki tareekh", ItemKey.LATE_OR_UNFINISHED: "der ya adhoore kaam ki shart",
}


def rupees(amount: int) -> str:
    return f"₹{amount:,}"


def day(when: date) -> str:
    return f"{when.day} {when:%b}"


def agreed(item: ItemKey, agreed_rupees: int, when: str | None, paid_before: int, clip: str | None) -> str:
    """What the deal says about a term a claim disagrees with. Facts only, no opinion."""
    line = f"Deal mein {_TERM[item]} {rupees(agreed_rupees)} tay hua tha" + (f" ({when})" if when else "") + "."
    if paid_before:
        line += f" {rupees(paid_before)} pehle se record mein hai."
    if clip:
        line += f" Wo pal yahan suniye: {clip}"
    return line


def paid(kind: RecordKind, amount: int, advance_owed: int | None, total_owed: int | None, when: str = "") -> str:
    """After a payment: what came in and what is still owed, e.g.
    'Advance ₹3,000 mil gaya. Baaki ₹10,000 kaam ke baad.'"""
    partial = kind is RecordKind.ADVANCE and advance_owed is not None and advance_owed > 0
    if partial:
        line = f"Advance mein {rupees(amount)} mila, advance ke {rupees(advance_owed)} abhi baaki."
    elif kind is RecordKind.ADVANCE:
        line = f"Advance {rupees(amount)} mil gaya."
    else:
        line = f"{rupees(amount)} mil gaya."
    return line + _still_owed(total_owed, "Kul baaki" if partial else "Baaki", when)


def work_done(total_owed: int | None) -> str:
    return "Kaam poora ho gaya, dono ne confirm kiya." + _still_owed(total_owed, "Deal ke hisaab se baaki", "")


def remind_after_work(owed: int) -> str:
    return f"Yaad dila raha hoon: kaam poora ho chuka hai, dono ne confirm kiya tha. Deal ke hisaab se {rupees(owed)} baaki hai."


def remind_date(item: ItemKey, owed: int, due: date) -> str:
    return f"Yaad dila raha hoon: deal mein {_TERM[item]} {day(due)} tak dena tay hua tha. Abhi {rupees(owed)} baaki hai."


def hirer_reminded(hirer: Person, owed: int) -> str:
    return f"Gawah ne {who(hirer)} ko {rupees(owed)} baaki ki yaad dila di hai."


def _still_owed(total: int | None, lead: str, when: str) -> str:
    if total is None:
        return ""
    if total > 0:
        return f" {lead} {rupees(total)}{when}."
    if total == 0:
        return " Ab kuch baaki nahi."
    return f" Deal se {rupees(-total)} zyada record mein hai."


# ---------- a voice note that contradicts the deal, or asks to change it ----------


def term_name(item: ItemKey | None) -> str:
    return _ANY_TERM.get(item, "yeh shart") if item else "yeh shart"


def contradicted(speaker: Person, said: str, item: ItemKey | None, value: str, when: str | None, clip: str | None) -> str:
    """A voice note says something else than what was agreed: both hear what was agreed,
    when, and the clip. Facts only, no opinion on who is right."""
    line = (f'{who(speaker)} ne voice note mein kaha: "{_short(said)}". '
            f"Deal mein {term_name(item)} {value} tay hua tha" + (f" ({when})" if when else "") + ".")
    if clip:
        line += f" Wo pal yahan suniye: {clip}"
    return line


def change_question(speaker: Person, said: str, item: ItemKey | None, old: str, new: str) -> str:
    return (f'{who(speaker)} ne voice note mein kaha: "{_short(said)}". Isse deal mein {term_name(item)} '
            f"{old} se badal kar {new} ho jayega. Kya aap maante hain? Haan ya nahi likhiye.")


def change_asked(other: Person) -> str:
    return f"Yeh badlav tabhi hoga jab {who(other)} bhi haan kahenge. Unse pooch raha hoon."


def change_answered(answerer: Person, item: ItemKey | None, new: str, confirmed: bool) -> str:
    if confirmed:
        return f"{who(answerer)} ne haan kaha. Deal mein {term_name(item)} ab {new} hai."
    return f"{who(answerer)} ne nahi kaha. Deal mein {term_name(item)} pehle jaisa hi hai."
