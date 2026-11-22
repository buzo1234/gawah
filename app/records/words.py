"""What Gawah says on WhatsApp about records. Short, plain Hinglish in Roman script.
Gawah never gives an opinion, so none of these do."""

import re
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


def change_question(
    speaker: Person, said: str, item: ItemKey | None, old: str | None, new: str | None,
    when: str | None = None, clip: str | None = None,
) -> str:
    """old and new are figures (₹13,000) for a money term; for any other term the voice note's
    own words say what is added, so none are given. when and clip: where the term was agreed."""
    what = f"{term_name(item)} {old} se badal kar {new} ho jayega" if old and new else f"{term_name(item)} mein yeh jud jayega"
    agreed = f" Pehle wali shart {when} tay hui thi." if when else ""
    if clip:
        agreed += f" Wo pal yahan suniye: {clip}"
    return (f'{who(speaker)} ne voice note mein kaha: "{_short(said)}". Isse deal mein {what}.{agreed} '
            "Kya aap maante hain? Haan ya nahi likhiye.")


def change_asked(other: Person) -> str:
    return f"Yeh badlav tabhi hoga jab {who(other)} bhi haan kahenge. Unse pooch raha hoon."


def change_answered(answerer: Person, item: ItemKey | None, new: str, confirmed: bool) -> str:
    if confirmed:
        figure = re.fullmatch(r"([\d,]+) rupees", new.strip())
        if figure:
            return f"{who(answerer)} ne haan kaha. Deal mein {term_name(item)} ab ₹{figure.group(1)} hai."
        return f"{who(answerer)} ne haan kaha. Deal ke {term_name(item)} mein yeh jud gaya."
    return f"{who(answerer)} ne nahi kaha. Deal mein {term_name(item)} pehle jaisa hi hai."


# ---------- a claim the other person said no to ----------
# What the record holds and who said what, when. Never who is right.

_PROMISE = re.compile(r"\b\w+(?:ung[aie]|unga|enge|egi|ega)\b", re.IGNORECASE)  # dungi, karunga, bhej denge


def is_promise(said: str | None) -> bool:
    return bool(said and _PROMISE.search(said))


def payment_kind(kind: RecordKind) -> str:
    return "advance" if kind is RecordKind.ADVANCE else "payment"


def ledger(paid: list[tuple[int, str]]) -> str:
    """Every payment that counts, with how it stands: [(rupees, 'advance, 22 Nov, dono ne confirm kiya')]."""
    if not paid:
        return "Record ke hisaab se ab tak koi payment nahi mila."
    total = rupees(sum(r for r, _ in paid))
    if len(paid) == 1:
        return f"Record ke hisaab se ab tak {total} mila hai ({paid[0][1]})."
    return f"Record ke hisaab se ab tak {total} mila hai: " + ", ".join(f"{rupees(r)} ({how})" for r, how in paid) + "."


def owed_now(advance: int | None, total: int | None) -> str:
    if total is None:
        return ""
    if advance is not None and advance > 0:
        return f" Advance ke {rupees(advance)} baaki, kul baaki {rupees(total)}."
    return " Ab kuch baaki nahi." if total == 0 else f" Baaki {rupees(total)}." if total > 0 else f" Deal se {rupees(-total)} zyada record mein hai."


def still_disputed(amounts: list[int], work: bool = False) -> str:
    """Said under every later owed message and reminder while a claim stays disputed."""
    line = ""
    if amounts:
        figures = " aur ".join(rupees(a) for a in amounts)
        line = f"{figures} ka payment disputed hai, isme shaamil nahi." if len(amounts) == 1 else \
            f"{figures} ke payment disputed hain, isme shaamil nahi."
    if work:
        line = f"{line} Kaam poora hone ki baat disputed hai.".strip()
    return f" {line}" if line else ""


def denied(answerer: Person, record: Record, paid: list[tuple[int, str]], owed: str, others: str) -> str:
    """To both, when the other person says no to a payment or a work claim."""
    if record.kind is RecordKind.WORK_DONE:
        return (f"{who(answerer)} ne mana kiya ki kaam poora ho gaya. Record mein kaam poora hona disputed hai, "
                f"pakka nahi.{owed}{others}")
    amount = rupees(round(record.amount)) if record.amount is not None else "Yeh payment"
    return f"{who(answerer)} ne mana kiya. Yeh {amount} hisaab mein nahi juda. {ledger(paid)}{owed}{others}"


def denied_again(answerer: Person, record: Record, proof: str, owed: str, others: str) -> str:
    """The second no, after the claimer sent proof. Nothing more is asked."""
    amount = rupees(round(record.amount)) if record.amount is not None else "Yeh"
    return (f"{who(answerer)} ne phir mana kiya. {amount} ka payment disputed hai, hisaab mein nahi. "
            f"{proof} record mein rakha hai.{owed}{others}")


def quoted(about: str, items: list[str]) -> str:
    lines = "\n".join(f"{n}. {item}" for n, item in enumerate(items, 1))
    return f"{about} ke baare mein record mein yeh hai:\n{lines}"


def quote_term(item: ItemKey | None, figure: str | None, when: str | None, said_by: str | None, agreed_by: str | None,
               said: str | None, clip: str | None) -> str:
    line = f"{_when(when)}: {term_name(item)}" + (f" {figure}" if figure else "") + " tay hua tha."
    if said_by and said:
        line += f' {said_by} ne kaha: "{_said(said)}"' + (f", {agreed_by} ne maana." if agreed_by else ".")
    return line + (f" Suniye: {clip}" if clip else "")


def quote_said(speaker: str, said: str, when: str | None, clip: str | None) -> str:
    verb = "vaada kiya tha" if is_promise(said) else "kaha tha"
    return f'{_when(when)}: {speaker} ne {verb}: "{_said(said)}".' + (f" Suniye: {clip}" if clip else "")


def _said(said: str) -> str:
    return _short(said, 120).rstrip(" .!।")


def _when(when: str | None) -> str:
    return (when[0].upper() + when[1:]) if when else "Pehle"


def proof_ask(record: Record, other: Person) -> str:
    amount = f"{rupees(round(record.amount))} ke payment" if record.amount is not None else "Payment"
    return f"{amount} ka screenshot ya UPI reference bhejiye. Milne par {who(other)} se ek baar phir poochunga."


def proof_question(sender: Person, record: Record, screenshot: bool) -> str:
    amount = rupees(round(record.amount)) if record.amount is not None else "is"
    what = (f"ka screenshot bheja (transaction id {record.transaction_id})" if screenshot
            else f"ka UPI reference bheja: {record.transaction_id}")
    return f"{who(sender)} ne {amount} ke payment {what}. Kya yeh payment aapko mila? Haan ya nahi likhiye."


def proof_caption(sender: Person) -> str:
    return f"{who(sender)} ka bheja hua screenshot."


def proof_link(sender: Person, link: str) -> str:
    return f"{who(sender)} ka bheja hua screenshot yahan dekhiye: {link}"


def proof_taken(other: Person) -> str:
    return f"Proof record mein rakh liya. {who(other)} se ek baar phir pooch raha hoon."


def proof_mismatch(record: Record, shown: int | None, has_id: bool) -> str:
    claim = rupees(round(record.amount)) if record.amount is not None else "disputed"
    why = f"is screenshot mein {rupees(shown)} hai" if shown is not None and round(shown) != round(record.amount or 0) \
        else "is screenshot mein transaction id nahi dikhi" if not has_id else "yeh screenshot payment ka nahi lagta"
    return f"{why[0].upper()}{why[1:]}, {claim} wale payment se mel nahi khata. Woh payment abhi bhi disputed hai, hisaab mein nahi."


PROOF_BUTTON = "Screenshot dekhiye"
