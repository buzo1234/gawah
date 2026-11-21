"""Values pinned down in code: rupees as whole numbers, and the cheap check that a line is
only a greeting or a yes. Dates are in dates.py; both read words through `tokens`."""

import re
import unicodedata

from app.memory.number_words import DEVANAGARI, ENGLISH, ROMAN, table

_MARK = "\x00"
BREAK = "|"  # a comma, a danda, a full stop, "aur": figures on either side stay apart

_DEV_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")


def norm(word: str) -> str:
    """One spelling for what transcription writes several ways: no nukta (हज़ार is हजार),
    chandrabindu as anusvara (पाँच is पांच)."""
    word = unicodedata.normalize("NFD", word.lower()).replace("़", "").replace("ँ", "ं")
    return unicodedata.normalize("NFC", word)


def normed(words) -> dict | set:
    return {norm(k): v for k, v in words.items()} if isinstance(words, dict) else {norm(w) for w in words}


_SPLIT = re.compile(r"[\s!?;:()\"'“”‘’\-–—/|,।॥]+")
_BREAKS = re.compile(r"(?<!\d),|,(?!\d)|[।॥!?;:]|(?<!\d)\.|\.(?!\d)|\n")
_JOINS = normed({"aur", "और", "and", "or", "ya", "या", "phir", "fir", "फिर"})


def tokens(text: str, breaks: bool = False) -> list[str]:
    """Words, lower case, Devanagari digits as digits, "22,000" as "22000", "15th" as "15".
    With `breaks`, a BREAK stands where a list or a sentence turns: punctuation and "aur"."""
    t = norm(text).translate(_DEV_DIGITS)
    t = re.sub(r"(?<=\d),(?=\d)", "", t)
    t = re.sub(r"\b(rs|no)\.", r"\1 ", t)
    t = re.sub(r"₹", " ₹ ", t)
    t = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", t)
    t = re.sub(r"(\d)(k|rs)\b", r"\1 \2", t)
    words = [w for w in _SPLIT.split(_BREAKS.sub(f" {_MARK} ", t)) if w]
    if not breaks:
        return [w for w in words if w != _MARK]
    out: list[str] = []
    for w in words:
        w = BREAK if w == _MARK or w in _JOINS else w
        if not (w == BREAK and (not out or out[-1] == BREAK)):
            out.append(w)
    return out


# ---------- rupees ----------

_WORDS = normed(table(ROMAN) | table(DEVANAGARI) | table(ENGLISH))
_TENS_EN = normed({w for w, v in table(ENGLISH).items() if v >= 20})
_UNITS_EN = normed({w for w, v in table(ENGLISH).items() if v < 10})
_ALONE = normed({  # a fraction said on its own: dedh sau, dhai hazaar, sava lakh, pauna hazaar
    "dedh": 1.5, "derh": 1.5, "dedd": 1.5, "डेढ": 1.5, "dhai": 2.5, "dhaai": 2.5, "adhai": 2.5,
    "arhai": 2.5, "ढाई": 2.5, "अढाई": 2.5, "sava": 1.25, "sawa": 1.25, "सवा": 1.25,
    "pauna": 0.75, "paune": 0.75, "पौना": 0.75, "पौने": 0.75,
})
_BEFORE = normed({  # said before a number: saade teen 3.5, sava do 2.25, paune do 1.75
    "saade": 0.5, "sadhe": 0.5, "saadhe": 0.5, "sade": 0.5, "साढे": 0.5,
    "sava": 0.25, "sawa": 0.25, "सवा": 0.25, "paune": -0.25, "pone": -0.25, "पौने": -0.25,
})
_MULT = normed({
    "k": 1000, "hazaar": 1000, "hazar": 1000, "hajar": 1000, "hajaar": 1000, "hazzar": 1000,
    "thousand": 1000, "हजार": 1000, "थाउजंड": 1000, "थाउसेंड": 1000, "थाउजेंड": 1000,
    "lakh": 100000, "lac": 100000, "lakhs": 100000, "laakh": 100000, "लाख": 100000,
    "crore": 10000000, "karod": 10000000, "करोड": 10000000,
    "sau": 100, "सौ": 100, "hundred": 100, "हंड्रेड": 100,
})
_CURRENCY = normed({
    "rupaye", "rupaiye", "rupay", "rupye", "rupiya", "rupaiya", "rupya", "rupees", "rupee", "rs", "inr", "₹",
    "रुपये", "रुपए", "रुपया", "रूपये", "रूपए", "रुपयों", "रूपया",
})
ITEM_WORDS = normed({
    "advance": "advance", "एडवांस": "advance", "pehle": "advance",
    "baaki": "balance", "baki": "balance", "बाकी": "balance", "balance": "balance", "remaining": "balance",
    "total": "amount", "price": "amount", "rate": "amount", "kharcha": "amount", "amount": "amount",
    "टोटल": "amount", "कुल": "amount",
    "shuru": "dates", "khatam": "dates", "date": "dates", "start": "dates", "finish": "dates",
    "late": "late_or_unfinished", "deri": "late_or_unfinished", "adhoora": "late_or_unfinished",
    "chhod": "late_or_unfinished", "unfinished": "late_or_unfinished",
})


def number_at(toks: list[str], i: int) -> tuple[float | None, int, bool]:
    """A number at toks[i]: (value, index after it, spoken as a word)."""
    if i >= len(toks):
        return None, i, False
    tok = toks[i]
    if tok in _BEFORE and i + 1 < len(toks):
        value, j, _ = number_at(toks, i + 1)
        if value is not None and value >= 1:
            return value + _BEFORE[tok], j, True
    if re.fullmatch(r"\d+(\.\d+)?", tok):
        return float(tok), i + 1, False
    if tok in _WORDS:
        value = _WORDS[tok]
        if tok in _TENS_EN and i + 1 < len(toks) and toks[i + 1] in _UNITS_EN:
            return value + _WORDS[toks[i + 1]], i + 2, True
        return value, i + 1, True
    if tok in _ALONE:
        return _ALONE[tok], i + 1, True
    return None, i, False


def figures(text: str | None) -> list[tuple[int | float, bool]]:
    """Every number group in the words, in order: (value, stated as an amount). Stated means
    with a unit (hazaar, lakh, sau, k, rupaye, ₹) or a figure of 1,000 or more."""
    if not text:
        return []
    toks, out, i = tokens(text, breaks=True), [], 0
    while i < len(toks):
        value, j, spoken = number_at(toks, i)
        if value is None:
            if toks[i] in _MULT and toks[i] != "k" and i + 1 < len(toks) and toks[i + 1] in _CURRENCY:
                out.append((_MULT[toks[i]], True))  # "sau rupaye"
                i += 2
                continue
            i += 1
            continue
        prefixed = i > 0 and toks[i - 1] in _CURRENCY
        total, stated = 0.0, False
        while True:
            unit = toks[j] if j < len(toks) else None
            if unit in _MULT:
                total += value * _MULT[unit]
                stated, j = True, j + 1
                nxt, k, _ = number_at(toks, j)
                if nxt is not None and k < len(toks) and toks[k] in _MULT and _MULT[toks[k]] < _MULT[unit]:
                    value, j = nxt, k  # ek lakh bees hazaar, 38 hazaar paanch sau
                    continue
                after = toks[k] if k < len(toks) else None
                if nxt is not None and 100 <= nxt < _MULT[unit] and after not in _MULT and after not in ITEM_WORDS:
                    total, j = total + nxt, k  # 13 hazaar 500; not "22 hazaar paanch" (a 5 is another figure)
                if j < len(toks) and toks[j] in _CURRENCY:
                    j += 1
                break
            total += value
            if unit in _CURRENCY:
                stated, j = True, j + 1
            elif prefixed or (not spoken and value >= 1000):
                stated = True
            break
        if total > 0 or stated:
            out.append((int(round(total)) if stated else total, stated))
        i = max(j, i + 1)
    return out


def parse_rupees(text: str | None) -> list[int]:
    """Every amount the words state outright. A bare "14" is left out: only the context says
    it means 14,000."""
    return [int(v) for v, stated in figures(text) if stated and v > 0]


def bare_numbers(text: str) -> set[float]:
    return {float(v) for v, stated in figures(text) if not stated}


def normalise_rupees(model: int | None, value: str | None, quote: str) -> int | None:
    """Whole rupees for a claim. The model says whether the claim has an amount; the words win
    where they state it outright, and the model's figure is taken where the words leave the
    scale to the context ("14 kar dete hain" is 14,000; "paanch advance" is 5,000)."""
    said = parse_rupees(quote)
    if model is not None:
        if model in said or (model > 0 and model / 1000 in bare_numbers(quote)):
            return model
        if len(set(said)) == 1:
            return said[0]
        return model
    return None  # the model saw no amount in this claim: a figure nearby belongs to another term


def one_amount(text: str | None) -> int | None:
    """The amount a short value states, if it states exactly one ("24,000 rupees, with the balcony")."""
    found = set(parse_rupees(text))
    return found.pop() if len(found) == 1 else None


_TOTAL = normed({"total", "kul", "कुल", "pura", "poora", "पूरा", "टोटल"})


def stated_total(text: str) -> int | None:
    """An amount the words call the total ("to total 14 hazaar", "kul 22 hazaar"), up to the
    next break: "total 22 hazaar, 5 advance" is 22,000."""
    toks = tokens(text, breaks=True)
    for i, tok in enumerate(toks):
        if tok in _TOTAL:
            span = toks[i + 1:i + 8]
            while span and span[0] == BREAK:
                span = span[1:]
            span = span[:span.index(BREAK)] if BREAK in span else span
            found = parse_rupees(" ".join(span))
            if found:
                return found[0]
    return None


def format_rupees(rupees: int) -> str:
    return f"{rupees:,} rupees"


# ---------- lines with nothing to extract ----------

STRONG_YES = normed({
    "theek", "thik", "theekh", "ok", "okay", "done", "pakka", "bilkul", "sahi", "manzoor", "final", "deal",
    "ठीक", "ओके", "पक्का", "बिलकुल", "बिल्कुल", "सही", "डन", "मंजूर", "फाइनल", "डील",
})
_YES = STRONG_YES | normed({
    "haan", "han", "haa", "ha", "haanji", "hanji", "chalo", "achha", "accha", "acha", "achcha", "right",
    "yes", "sure", "हाँ", "हां", "चलो", "अच्छा",
})
_FILLER = normed({
    "ji", "jee", "hai", "he", "h", "hmm", "hm", "madam", "sir", "bhaiya", "bhai", "didi", "aunty", "uncle",
    "hello", "hi", "helo", "hallo", "namaste", "namaskar", "pranam", "bye", "dhanyavad", "dhanyawad",
    "shukriya", "thanks", "thank", "you", "phir", "fir", "to", "toh", "जी", "है", "हम्म", "नमस्ते",
    "नमस्कार", "हेलो", "धन्यवाद", "शुक्रिया", "फिर", "तो", "मैडम", "सर", "भैया", "दीदी", "बाय",
})


def filler_kind(text: str, names: set[str] = frozenset()) -> str | None:
    """"yes" for a line that is only a yes ("theek hai", "haan ji", "ठीक है।"), "greeting" for
    a line with nothing to extract at all ("namaste", "hello"), None for anything else."""
    names = {norm(n) for n in names}
    toks = [t for t in tokens(text) if t not in names]
    if not toks or not all(t in _YES or t in _FILLER for t in toks):
        return None if toks else "greeting"
    return "yes" if any(t in _YES for t in toks) else "greeting"


def opens_with_yes(text: str, names: set[str] = frozenset()) -> bool:
    """A line whose first clause is a firm yes and that then goes on ("Chalo theek hai. To
    Wednesday aa jao"). "Haan" or "achha" alone can just mean "I hear you", so a firm word
    ("theek", "pakka", "done") is needed."""
    toks = tokens(text, breaks=True)
    if BREAK not in toks:
        return False
    cut = toks.index(BREAK)
    first, rest = toks[:cut], [t for t in toks[cut:] if t != BREAK]
    return bool(rest) and filler_kind(" ".join(first), names) == "yes" and any(t in STRONG_YES for t in first)


_ALL = normed({"sab", "sabhi", "saara", "sara", "everything", "सब", "सभी", "सारा"})
_SETTLED = normed({"tay", "tey", "final", "pakka", "fix", "settle", "settled", "done", "तय", "फाइनल", "पक्का", "फिक्स", "डन"})


def settles_all(text: str) -> bool:
    """"Sab tay ho gaya", "sab final", "सब पक्का": everything said so far is agreed."""
    toks = tokens(text)
    return any(t in _ALL for t in toks) and any(t in _SETTLED for t in toks)


# ---------- search words ----------

_STOP = normed({
    "kya", "hai", "tha", "thi", "the", "hua", "hui", "kitna", "kitni", "kab", "kaun", "kaise", "ke", "ki",
    "ka", "mein", "baare", "aur", "hoga", "hogi", "was", "what", "how", "when", "who", "about", "baat",
    "tay", "gawah", "maine", "aapne", "bola", "kaha", "tha", "na", "and", "for", "with", "that", "this",
    "said", "says", "rupees", "will", "are", "has", "ji", "madam",
})


def search_words(text: str) -> set[str]:
    return {t for t in tokens(text) if len(t) > 2 and t not in _STOP and not t.isdigit()}


def items_named(text: str) -> set[str]:
    return {ITEM_WORDS[t] for t in tokens(text) if t in ITEM_WORDS}


_AGREED = normed({"tay", "tey", "pakka", "final", "agreed", "decide", "decided", "fix", "तय", "पक्का", "confirm", "confirmed"})


def asks_agreed(text: str) -> bool:
    return any(t in _AGREED for t in tokens(text))
