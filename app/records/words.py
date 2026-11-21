"""What Gawah says on WhatsApp about records. Short, plain Hinglish in Roman script.
Gawah never gives an opinion, so none of these do."""

from app.contracts import Person, Record, RecordKind, Role

_ROLE = {Role.HIRER: "Kaam dene wale", Role.WORKER: "Kaam karne wale"}
_KIND = {
    RecordKind.ADVANCE: "advance",
    RecordKind.PAYMENT: "payment",
    RecordKind.WORK_DONE: "kaam poora",
}

ANSWER_NOTED = "Shukriya, aapka jawab likh liya."


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


def asking_other(other: Person) -> str:
    return f"Likh liya. {who(other)} se confirm kar raha hoon."


def confirm_question(sender: Person, record: Record) -> str:
    said = f'ne likha hai: "{record.text}"' if record.text else f"ne ek photo bheji hai: {describe(record)}"
    return f"{who(sender)} {said}. Kya yeh sahi hai? Haan ya nahi likhiye."


def answer_for_sender(answerer: Person, record: Record, confirmed: bool) -> str:
    what = f'"{record.text}"' if record.text else describe(record)
    if confirmed:
        return f"{who(answerer)} ne haan kaha. {what} record mein confirm ho gaya."
    return f"{who(answerer)} ne nahi kaha. {what} record mein bina confirm ke likha hai."


def _rupees(amount: float | None) -> str | None:
    return None if amount is None else f"₹{amount:,.0f}"
