"""A Document as plain text: what contract.ready carries, and what the dashboard shows."""

from app.contract.document import Document, both
from app.contract.wording import (
    BEFORE, BOTH_CONFIRMED, CHAIN, CHAIN_MEANS, CHANGED, CHANGES, CHANGES_LEAD, CONFIRMED, FINGERPRINT,
    IF_YOU_DISAGREE, IS, IS_NOT, NOW, TITLE,
)


def text(doc: Document) -> str:
    at = lambda t: f"  [कॉल / call {t}]" if t else ""  # noqa: E731
    lines = [TITLE.hi, TITLE.en.upper(), doc.subtitle.hi, doc.subtitle.en, "",
             f"संदर्भ संख्या / Reference no.: {doc.reference}",
             f"संस्करण / Version: {doc.version_line.hi} / {doc.version_line.en}",
             f"तारीख / Date: {doc.date.hi} / {doc.date.en}"]
    if doc.place:
        lines.append(f"काम की जगह / Place of work: {both(doc.place)}")
    lines += ["", "पक्ष / PARTIES", *(p.line() for p in doc.parties), f"{doc.lead.hi} / {doc.lead.en}"]
    for n, clause in enumerate(doc.clauses, 1):
        mark = f" ({CHANGED.hi} / {CHANGED.en})" if clause.changed else ""
        lines += ["", f"{n}. {clause.title.hi} / {clause.title.en}{mark}{at(clause.said_at)}"]
        if clause.body:
            lines += [clause.body.hi, clause.body.en]
        for pay in clause.payments:
            lines += [f"- {pay.label.hi} / {pay.label.en}: {both(pay.amount, ' / ')}{at(pay.said_at)}",
                      f"  {pay.when.hi}", f"  {pay.when.en}"]
        for note in clause.notes:
            lines += [f"- {note.text.hi}{at(note.said_at)}", f"  {note.text.en}"]
            if note.said:
                lines.append(f"  कहा / Said: “{note.said}”")
    if doc.changes:
        lines += ["", f"{CHANGES.hi} / {CHANGES.en.upper()}", CHANGES_LEAD.hi, CHANGES_LEAD.en]
        for c in doc.changes:
            lines += [f"{c.n}. {c.term.hi} / {c.term.en}{at(c.said_at)}",
                      f"  {BEFORE.hi} / {BEFORE.en}: {c.before.hi} / {c.before.en}",
                      f"  {NOW.hi} / {NOW.en}: {c.now.hi} / {c.now.en}",
                      f"  {BOTH_CONFIRMED.hi} / {BOTH_CONFIRMED.en}: {c.when.hi} / {c.when.en}"]
            if c.said:
                lines.append(f"  कहा / Said: “{c.said}”")
    lines += ["", "स्वीकृति / ACCEPTANCE"]
    for a in doc.acceptances:
        lines += [a.party.line(), f"{CONFIRMED.hi} / {CONFIRMED.en}", f"{a.when.hi} / {a.when.en}"]
        if a.said:
            lines.append(f"कहा / Said: “{a.said}”")
    lines += ["", "गवाह / WITNESS", doc.witness.hi, doc.witness.en]
    for call in doc.calls:
        lines += [call.hi, call.en]
    if doc.fingerprints:
        lines += [FINGERPRINT.hi, FINGERPRINT.en, *(f"{who.hi} / {who.en}: {digest}" for who, digest in doc.fingerprints)]
    if doc.chain:
        fingerprint, links = doc.chain
        lines += [f"{CHAIN.hi} / {CHAIN.en}: {links} कड़ियाँ / links, आख़िरी पहचान / head fingerprint {fingerprint}",
                  CHAIN_MEANS.hi, CHAIN_MEANS.en]
    lines += ["", "यह दस्तावेज़ क्या है / WHAT THIS DOCUMENT IS", IS.hi, IS.en, IS_NOT.hi, IS_NOT.en,
              IF_YOU_DISAGREE.hi, IF_YOU_DISAGREE.en]
    return "\n".join(lines)
