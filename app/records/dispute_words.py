"""What Gawah says on WhatsApp about a payment or work claim the other person said no to:
what the record holds and who said what, when. Never who is right."""

import re

from app.contracts import ItemKey, Person, Record, RecordKind
from app.records.words import _short, rupees, term_name, who

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
