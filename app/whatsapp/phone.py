"""Read a start-a-deal message: the other person's phone number, and whether the sender
says they are the one doing the work."""

import re

# A run of 10 to 13 digits, with single spaces or dashes allowed between them.
_RUN = re.compile(r"(?<![\d+])\+?\d(?:[\s-]?\d){9,12}(?![\s-]?\d)")

# Only a clear first-person statement makes the sender the worker.
_WORKER = re.compile(
    r"\bkaam\s+(kar[ou]+ng[ai]|kar\s+rah[ai]\s+h[ou]+n?|kart[ai]\s+h[ou]+n?)\b"
    r"|\b(mera|meri|mere|hamara|hamare)\s+(customer|client|grahak|malik|maalik|seth)\b"
    r"|\b(main|mai|mein)\s+(\w+\s+)?(painter|plumber|mistri|mistry|karigar|electrician|carpenter"
    r"|mazdoor|majdoor|worker|thekedar|contractor|darzi|tailor|driver)\s+h[ou]+n?\b"
    r"|\bi\s*(am|'m)\s+(the\s+)?(worker|painter|plumber|electrician|carpenter|contractor)\b"
    r"|\bi\s*(will|'ll)\s+do\s+the\s+(work|job)\b",
    re.IGNORECASE,
)


def normalise(raw: str) -> str | None:
    """A full Indian mobile number like +919876543210, or None if it is not one."""
    digits = re.sub(r"\D", "", raw)
    if raw.strip().startswith("+"):
        return f"+{digits}" if len(digits) == 12 and digits.startswith("91") else None
    if len(digits) == 12 and digits.startswith("91") and digits[2] in "6789":
        return f"+{digits}"
    if len(digits) == 11 and digits[0] == "0" and digits[1] in "6789":
        return f"+91{digits[1:]}"
    if len(digits) == 10 and digits[0] in "6789":
        return f"+91{digits}"
    return None


def find_numbers(text: str) -> list[str]:
    """Every different Indian mobile number in the text, normalised, in order."""
    found: list[str] = []
    for match in _RUN.finditer(text):
        number = normalise(match.group())
        if number and number not in found:
            found.append(number)
    return found


def says_worker(text: str) -> bool:
    return bool(_WORKER.search(text))


# Words around a number that are not a name: Hinglish and English filler, kin and courtesy words,
# and the trades a worker names.
_FILLER = set(
    "ka ki ke ko se hai hain ye yeh woh wo is the a an this my mera meri mere unka unki uska uski inka "
    "number no num nmbr mobile phone contact name naam call karo kar kariye kijiye deal aur and with "
    "for of hi hello namaste please pls plz ji bhai bhaiya didi uncle aunty sir madam sahab saab "
    "main mai mein hum aap aapka tum i me am is are karna karni karne karwana karwani karenge baat pakki "
    "chahiye bhejo bhej send add start shuru new nayi naya hoon hu ho tha thi "
    "painter plumber mistri mistry karigar electrician carpenter mazdoor majdoor worker thekedar "
    "contractor darzi tailor driver customer client grahak malik maalik seth".split()
)


def find_name(text: str) -> str | None:
    """The other person's name, when the message has, besides the number, one or two words
    side by side that can only be a name: 'Namesh +919000000105' or 'Namesh ka number 9000000105'.
    Anything less clear is no name."""
    rest = _WORKER.sub(" ", _RUN.sub(" ", text))
    kept = [(i, w) for i, w in enumerate(re.findall(r"[^\W\d_]+", rest)) if w.lower() not in _FILLER]
    if not 1 <= len(kept) <= 2 or kept[-1][0] - kept[0][0] != len(kept) - 1:
        return None
    return " ".join(w.title() for _, w in kept)
