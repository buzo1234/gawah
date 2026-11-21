"""Values pinned down in code: rupees as whole numbers, dates when the words fix a day,
and the cheap check that a line is only a greeting or a yes."""

import re
from datetime import date, timedelta

_DEV_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")

_WORDS = {
    "ek": 1, "do": 2, "teen": 3, "tin": 3, "char": 4, "chaar": 4, "paanch": 5, "panch": 5, "paach": 5,
    "chhe": 6, "chhah": 6, "che": 6, "chah": 6, "chheh": 6, "saat": 7, "sat": 7, "aath": 8, "ath": 8,
    "nau": 9, "das": 10, "gyarah": 11, "gyara": 11, "barah": 12, "bara": 12, "baarah": 12, "terah": 13,
    "tera": 13, "chaudah": 14, "chauda": 14, "pandrah": 15, "pandra": 15, "solah": 16, "sola": 16,
    "satrah": 17, "satra": 17, "atharah": 18, "athara": 18, "unnees": 19, "unnis": 19, "bees": 20,
    "bis": 20, "ikkees": 21, "ikkis": 21, "baees": 22, "bais": 22, "baais": 22, "baaees": 22, "teis": 23,
    "teish": 23, "tees": 30, "chaubees": 24, "chaubis": 24, "pachchees": 25, "pachees": 25, "pachis": 25,
    "pacchis": 25, "chhabbees": 26, "chhabbis": 26, "sattaees": 27, "sattais": 27, "atthaees": 28,
    "atthais": 28, "untees": 29, "untis": 29, "tis": 30, "chalees": 40, "chalis": 40, "pachaas": 50,
    "pachas": 50, "saath": 60, "sattar": 70, "assi": 80, "nabbe": 90,
    "एक": 1, "दो": 2, "तीन": 3, "चार": 4, "पांच": 5, "पाँच": 5, "छह": 6, "छः": 6, "छे": 6, "सात": 7,
    "आठ": 8, "नौ": 9, "दस": 10, "ग्यारह": 11, "बारह": 12, "तेरह": 13, "चौदह": 14, "पंद्रह": 15,
    "पन्द्रह": 15, "सोलह": 16, "सत्रह": 17, "अठारह": 18, "उन्नीस": 19, "बीस": 20, "इक्कीस": 21,
    "बाईस": 22, "बाइस": 22, "तेईस": 23, "चौबीस": 24, "पच्चीस": 25, "छब्बीस": 26, "सत्ताईस": 27,
    "अट्ठाईस": 28, "उनतीस": 29, "तीस": 30, "चालीस": 40, "पचास": 50, "साठ": 60, "सत्तर": 70,
    "अस्सी": 80, "नब्बे": 90,
}
_FRACTIONS = {"dedh": 1.5, "derh": 1.5, "डेढ": 1.5, "dhai": 2.5, "dhaai": 2.5, "ढाई": 2.5}
_PLUS_HALF = {"saade", "sadhe", "saadhe", "साढे"}
_MULT = {
    "k": 1000, "hazaar": 1000, "hazar": 1000, "hajar": 1000, "hazaar.": 1000, "thousand": 1000,
    "हजार": 1000, "lakh": 100000, "lac": 100000, "lakhs": 100000, "लाख": 100000,
    "sau": 100, "सौ": 100, "hundred": 100,
}
_CURRENCY = {"rupaye", "rupaiye", "rupay", "rupees", "rupee", "rs", "inr", "₹", "रुपये", "रुपए", "रुपया"}


def _tokens(text: str) -> list[str]:
    t = text.lower().replace("़", "").translate(_DEV_DIGITS)  # drop the nukta: हज़ार == हजार
    t = re.sub(r"(?<=\d),(?=\d)", "", t)
    t = re.sub(r"₹", " ₹ ", t)
    t = re.sub(r"(\d)(k|rs)\b", r"\1 \2", t)
    t = re.sub(r"(?<!\d)\.|\.(?!\d)", " ", t)
    return [w for w in re.split(r"[\s,!?;:()\"'“”‘’\-–—/|]+", t) if w]


def _number(toks: list[str], i: int) -> tuple[float | None, int, bool]:
    """A number at toks[i]: (value, index after it, spoken as a word)."""
    if i >= len(toks):
        return None, i, False
    half = 0.0
    if toks[i] in _PLUS_HALF and i + 1 < len(toks):
        half, i = 0.5, i + 1
    tok = toks[i]
    if re.fullmatch(r"\d+(\.\d+)?", tok):
        return float(tok) + half, i + 1, False
    if tok in _WORDS:
        return _WORDS[tok] + half, i + 1, True
    if tok in _FRACTIONS:
        return _FRACTIONS[tok], i + 1, True
    return None, i, False


def parse_rupees(text: str | None) -> list[int]:
    """Every amount the words state outright: with a unit (hazaar, lakh, k, rupaye, ₹) or as a
    figure of 1,000 or more. A bare "14" is left out: only the context says it means 14,000."""
    if not text:
        return []
    toks, out, i = _tokens(text), [], 0
    while i < len(toks):
        value, j, spoken = _number(toks, i)
        if value is None:
            i += 1
            continue
        prefixed = i > 0 and toks[i - 1] in _CURRENCY
        total, stated = 0.0, False
        while True:
            unit = toks[j] if j < len(toks) else None
            if unit in _MULT:
                total += value * _MULT[unit]
                stated, j = True, j + 1
                nxt, k, _ = _number(toks, j)
                if nxt is not None and k < len(toks) and toks[k] in _MULT and _MULT[toks[k]] < _MULT[unit]:
                    value, j = nxt, k
                    continue
                if nxt is not None and _MULT[unit] >= 1000 and nxt < 1000 and not (k < len(toks) and toks[k] in _MULT):
                    total, j = total + nxt, k
                if j < len(toks) and toks[j] in _CURRENCY:
                    j += 1
                break
            total += value
            if unit in _CURRENCY:
                stated, j = True, j + 1
            elif prefixed or (not spoken and value >= 1000):
                stated = True
            break
        if stated and total > 0:
            out.append(int(round(total)))
        i = max(j, i + 1)
    return out


def _bare_numbers(text: str) -> set[float]:
    return {float(t) for t in _tokens(text) if re.fullmatch(r"\d+(\.\d+)?", t)}


def normalise_rupees(model: int | None, value: str | None, quote: str) -> int | None:
    """Whole rupees for a claim. The words win where they are explicit; the model's figure is
    taken where the words leave the scale to the context ("14 kar dete hain" is 14,000)."""
    said = parse_rupees(quote)
    if model is not None:
        if model in said or (model % 1000 == 0 and model // 1000 in _bare_numbers(quote)):
            return model
        if len(set(said)) == 1:
            return said[0]
        return model
    if len(set(said)) == 1:
        return said[0]
    from_value = parse_rupees(value)
    return from_value[0] if len(set(from_value)) == 1 else None


def format_rupees(rupees: int) -> str:
    return f"{rupees:,} rupees"


# ---------- dates ----------

_WEEKDAYS = {
    "monday": 0, "somvar": 0, "somwar": 0, "सोमवार": 0, "tuesday": 1, "mangalvar": 1, "mangalwar": 1,
    "मंगलवार": 1, "wednesday": 2, "budhvar": 2, "budhwar": 2, "बुधवार": 2, "thursday": 3, "guruvar": 3,
    "guruwar": 3, "brihaspativar": 3, "गुरुवार": 3, "friday": 4, "shukravar": 4, "shukrawar": 4,
    "शुक्रवार": 4, "saturday": 5, "shanivar": 5, "shaniwar": 5, "शनिवार": 5, "sunday": 6, "ravivar": 6,
    "raviwar": 6, "itvaar": 6, "itwar": 6, "रविवार": 6,
}
_RELATIVE = {"aaj": 0, "आज": 0, "kal": 1, "कल": 1, "parson": 2, "parso": 2, "परसों": 2, "परसो": 2}
_MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3, "apr": 4, "april": 4, "may": 5,
    "jun": 6, "june": 6, "jul": 7, "july": 7, "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10, "nov": 11, "november": 11, "navambar": 11, "dec": 12, "december": 12,
    "disambar": 12,
}


def date_candidates(text: str, today: date) -> set[date]:
    toks, found = _tokens(text), set()
    for i, tok in enumerate(toks):
        if tok in _WEEKDAYS:
            ahead = (_WEEKDAYS[tok] - today.weekday()) % 7 or 7
            found.add(today + timedelta(days=ahead))
        elif tok in _RELATIVE:
            found.add(today + timedelta(days=_RELATIVE[tok]))
        elif tok in _MONTHS and i > 0 and re.fullmatch(r"\d{1,2}", toks[i - 1]):
            try:
                day = date(today.year, _MONTHS[tok], int(toks[i - 1]))
            except ValueError:
                continue
            found.add(day if day >= today - timedelta(days=60) else day.replace(year=today.year + 1))
    return found


def pin_date(quote: str, today: date, model: date | None) -> date | None:
    """The day the words fix, if they fix one. Two different days in the words and no
    agreement from the model means it is not pinned down."""
    found = date_candidates(quote, today)
    if model is not None and model in found:
        return model
    if len(found) == 1:
        return next(iter(found))
    return model if not found else None


# ---------- lines with nothing to extract ----------

_YES = {
    "haan", "han", "haa", "ha", "haanji", "hanji", "theek", "thik", "theekh", "ok", "okay", "done", "pakka",
    "chalo", "achha", "accha", "acha", "achcha", "sahi", "bilkul", "right", "yes", "sure", "हाँ", "हां",
    "ठीक", "ओके", "पक्का", "चलो", "अच्छा", "बिलकुल", "बिल्कुल", "सही", "डन",
}
_FILLER = {
    "ji", "jee", "hai", "he", "h", "hmm", "hm", "madam", "sir", "bhaiya", "bhai", "didi", "aunty", "uncle",
    "hello", "hi", "helo", "hallo", "namaste", "namaskar", "pranam", "bye", "dhanyavad", "dhanyawad",
    "shukriya", "thanks", "thank", "you", "phir", "fir", "to", "toh", "जी", "है", "हम्म", "नमस्ते",
    "नमस्कार", "हेलो", "धन्यवाद", "शुक्रिया", "फिर", "तो",
}


def filler_kind(text: str, names: set[str] = frozenset()) -> str | None:
    """"yes" for a line that is only a yes ("theek hai", "haan ji", "done"), "greeting" for a
    line with nothing to extract at all ("namaste", "hello"), None for anything else."""
    toks = [t for t in _tokens(text) if t not in names]
    if not toks or not all(t in _YES or t in _FILLER for t in toks):
        return None if toks else "greeting"
    return "yes" if any(t in _YES for t in toks) else "greeting"
