"""Dates pinned down in code: the days the words fix, and whether each day is when the work
starts or when it finishes. A meeting day ("Monday ko milte hain") is neither."""

import re
from dataclasses import dataclass
from datetime import date, timedelta

from app.memory.normalise import BREAK, normed, number_at, tokens

_WEEKDAYS = normed({
    "monday": 0, "somvar": 0, "somwar": 0, "सोमवार": 0, "tuesday": 1, "mangalvar": 1, "mangalwar": 1,
    "मंगलवार": 1, "wednesday": 2, "budhvar": 2, "budhwar": 2, "बुधवार": 2, "thursday": 3, "guruvar": 3,
    "guruwar": 3, "brihaspativar": 3, "गुरुवार": 3, "friday": 4, "shukravar": 4, "shukrawar": 4,
    "शुक्रवार": 4, "saturday": 5, "shanivar": 5, "shaniwar": 5, "शनिवार": 5, "sunday": 6, "ravivar": 6,
    "raviwar": 6, "itvaar": 6, "itwar": 6, "रविवार": 6, "मंडे": 0, "ट्यूजडे": 1, "वेडनेसडे": 2,
    "वेंसडे": 2, "थर्सडे": 3, "फ्राइडे": 4, "सैटरडे": 5, "संडे": 6,
})
_RELATIVE = normed({"aaj": 0, "आज": 0, "kal": 1, "कल": 1, "parson": 2, "parso": 2, "परसों": 2, "परसो": 2})
_MONTHS = normed({
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3, "apr": 4, "april": 4, "may": 5,
    "jun": 6, "june": 6, "jul": 7, "july": 7, "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10, "nov": 11, "november": 11, "navambar": 11, "नवंबर": 11, "नवम्बर": 11,
    "dec": 12, "december": 12, "disambar": 12, "दिसंबर": 12, "दिसम्बर": 12, "जनवरी": 1, "फरवरी": 2,
})
_DAY_OF_MONTH = normed({"tarikh", "tareekh", "tarik", "taarikh", "tareek", "तारीख", "तारिख", "तारीक", "date", "डेट"})

# What follows (or, in English, comes before) a day says whether it is a start or a finish.
_START = normed({"se", "से", "shuru", "शुरू", "शुरु", "start", "स्टार्ट", "chalu", "चालू", "from", "starting"})
_FINISH = normed({
    "tak", "तक", "khatam", "khatm", "खत्म", "खतम", "finish", "फिनिश", "complete", "कम्प्लीट", "poora", "pura",
    "पूरा", "by", "till", "until", "ready", "रेडी", "pehle", "पहले", "before",
})
_BEFORE_DAY = normed({"from": "start", "starting": "start", "start": "start", "by": "finish", "till": "finish",
                       "until": "finish", "finish": "finish", "before": "finish"})


@dataclass(frozen=True)
class Day:
    day: date
    weekday_only: bool = False  # "Friday" fixes the weekday; which Friday depends on the call's date

    def same(self, other: "Day") -> bool:
        if self.weekday_only or other.weekday_only:
            return self.day.weekday() == other.day.weekday()
        return self.day == other.day


def _mentions(toks: list[str], today: date) -> list[tuple[int, int, Day]]:
    """(first token, token after, day) for every day the words fix."""
    found, i = [], 0
    while i < len(toks):
        tok = toks[i]
        if tok in _WEEKDAYS:
            ahead = (_WEEKDAYS[tok] - today.weekday()) % 7 or 7
            found.append((i, i + 1, Day(today + timedelta(days=ahead), weekday_only=True)))
        elif tok in _RELATIVE:
            found.append((i, i + 1, Day(today + timedelta(days=_RELATIVE[tok]))))
        elif tok in _MONTHS and i + 1 < len(toks) and re.fullmatch(r"\d{1,2}", toks[i + 1]):
            day = _in_month(int(toks[i + 1]), _MONTHS[tok], today)
            if day:
                found.append((i, i + 2, Day(day)))
                i += 2
                continue
        else:
            value, j, _ = number_at(toks, i)
            if value is not None and value == int(value) and 1 <= value <= 31 and j < len(toks):
                day = None
                if toks[j] in _MONTHS:
                    day = _in_month(int(value), _MONTHS[toks[j]], today)
                elif toks[j] in _DAY_OF_MONTH:
                    day = _next_day_of_month(int(value), today)
                if day:
                    found.append((i, j + 1, Day(day)))
                    i = j + 1
                    continue
        i += 1
    return found


def _in_month(n: int, month: int, today: date) -> date | None:
    try:
        day = date(today.year, month, n)
    except ValueError:
        return None
    return day if day >= today - timedelta(days=60) else day.replace(year=today.year + 1)


def _next_day_of_month(n: int, today: date) -> date | None:
    """"bees tarikh": the 20th of this month, or of the next if that has passed."""
    year, month = today.year, today.month
    for _ in range(3):
        try:
            day = date(year, month, n)
        except ValueError:
            day = None
        if day and day >= today:
            return day
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return None


def date_candidates(text: str, today: date) -> set[date]:
    return {m[2].day for m in _mentions(tokens(text), today)}


def pin_date(quote: str, today: date, model: date | None) -> date | None:
    """The day the words fix, if they fix one. Two different days in the words and no
    agreement from the model means it is not pinned down."""
    found = date_candidates(quote, today)
    if model is not None and model in found:
        return model
    if len(found) == 1:
        return next(iter(found))
    return model if not found else None


def date_parts(text: str | None, today: date) -> dict[str, Day]:
    """The start and the finish the words fix: "Monday se shuru, Friday tak" is both;
    "15 tarikh se pehle" is a finish; "Monday ko milte hain" is neither."""
    if not text:
        return {}
    toks = tokens(text, breaks=True)
    mentions = _mentions(toks, today)
    parts: dict[str, Day | None] = {}
    for n, (first, after, day) in enumerate(mentions):
        stop = mentions[n + 1][0] if n + 1 < len(mentions) else len(toks)
        window = []
        for tok in toks[after:min(after + 4, stop)]:
            if tok == BREAK:
                break
            window.append(tok)
        before = toks[first - 1] if first > 0 else None
        part = None
        if any(t in ("pehle", "पहले", "before") for t in window):
            part = "finish"
        else:
            part = next(("start" if t in _START else "finish" for t in window if t in _START or t in _FINISH), None)
        part = part or _BEFORE_DAY.get(before or "")
        if part:
            # Two different days for one part ("Friday tak ... 15 tarikh se pehle") pin neither.
            parts[part] = day if part not in parts or (parts[part] and parts[part].same(day)) else None
    return {part: day for part, day in parts.items() if day}


_MEET = normed({
    "milte", "milenge", "milna", "milo", "milta", "milti", "मिलते", "मिलेंगे", "मिलना", "मिलो", "मिलता", "मिलती",
    "phone", "फोन", "call", "कॉल", "bye", "बाय",
})


def meets(text: str) -> bool:
    """The words talk about meeting or speaking again ("Monday ko milte hain", "kal phone karna")."""
    return any(t in _MEET for t in tokens(text))
