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
