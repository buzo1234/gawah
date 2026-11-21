"""Checks the model's text against the values it was given, in code.

Every figure and day in an agreed value must be in that term's Hindi and English text,
and no figure may appear that is not in an agreed value. The other texts (each side of a
change, each fact that was also agreed) are held to their own value alone. A failed check
is a rejected draft: the caller retries with the problems listed.
"""

import re
import unicodedata

from app.contracts import ChecklistItem, ItemState

# Read aloud by the speech model this comes to 20-30 seconds: it measured about half a
# second a word, figures included.
SUMMARY_WORDS = (44, 55)

_DEVANAGARI_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")
_NUKTA = "़"  # the dot in ज़; dropped before matching so हज़ार and हजार are one word

_NUMBER = re.compile(
    r"(\d[\d,]*(?:\.\d+)?)"
    r"(?:\s*(?:(hazaar|hazar|hajaar|hajar|thousand|k|हजार)|(lakhs|lakh|lac|लाख))(?![a-z]))?"
)
# An amount spelled out instead of written in digits: "do hazaar", "पाँच सौ".
_SPELLED = re.compile(r"hazaa?r|hajaa?r|thousand|hundred|lakh|हजार|लाख|सौ(?![ऀ-ॿ])")

_DAYS = {
    "monday": ("somvar", "somvaar", "somwar", "सोमवार", "मंडे"),
    "tuesday": ("mangalvar", "mangalvaar", "mangalwar", "मंगलवार", "ट्यूजडे"),
    "wednesday": ("budhvar", "budhvaar", "budhwar", "बुधवार", "वेडनेसडे", "वेडनसडे"),
    "thursday": ("guruvar", "guruvaar", "guruwar", "गुरुवार", "बृहस्पतिवार", "थर्सडे"),
    "friday": ("shukravar", "shukravaar", "shukrawar", "शुक्रवार", "फ्राइडे"),
    "saturday": ("shanivar", "shanivaar", "shaniwar", "शनिवार", "सैटरडे"),
    "sunday": ("ravivar", "ravivaar", "raviwar", "itvaar", "itwar", "रविवार", "इतवार", "संडे"),
}
_MONTHS = {
    "january": ("jan", "जनवरी"), "february": ("feb", "फरवरी"), "march": ("mar", "मार्च"),
    "april": ("apr", "अप्रैल"), "may": ("मई",), "june": ("jun", "जून"), "july": ("jul", "जुलाई"),
    "august": ("aug", "अगस्त"), "september": ("sep", "sept", "सितंबर", "सितम्बर"),
    "october": ("oct", "अक्टूबर"), "november": ("nov", "नवंबर", "नवम्बर"),
    "december": ("dec", "दिसंबर", "दिसम्बर"),
}


def _plain(text: str) -> str:
    text = unicodedata.normalize("NFD", text).replace(_NUKTA, "")
    return unicodedata.normalize("NFC", text).translate(_DEVANAGARI_DIGITS).lower()


def numbers(text: str) -> set[float]:
    """Every figure in the text: "24,000", "२४,०००", "24 hazaar" and "24k" are all 24000."""
    found = set()
    for digits, thousand, lakh in _NUMBER.findall(_plain(text)):
        found.add(float(digits.replace(",", "")) * (1000 if thousand else 100000 if lakh else 1))
    return found


def days(text: str) -> set[str]:
    """Weekdays named in the text, and months that stand next to a day number."""
    text = _plain(text)
    found = {day for day, forms in _DAYS.items() if any(f in text for f in (day, *forms))}
    for month, forms in _MONTHS.items():
        names = "|".join((month, *forms))
        if re.search(rf"\d\s*(?:st|nd|rd|th)?\s*(?:{names})(?![a-z])|(?<![a-z])(?:{names})\s*\d", text):
            found.add(month)
    return found


def _spelled(text: str) -> bool:
    return bool(_SPELLED.search(_NUMBER.sub(" ", _plain(text))))


def _has_devanagari(text: str) -> bool:
    return bool(re.search(r"[ऀ-ॿ]", text))


def _has_letters(text: str) -> bool:
    return any(c.isalpha() for c in text)


def _show(values: set[float]) -> str:
    return ", ".join(f"{v:g}" for v in sorted(values))


def problems(
    items: list[ChecklistItem], terms: dict[str, dict[str, str]], summary: str,
    extras: dict[str, str] | None = None, extra_texts: dict[str, dict[str, str]] | None = None,
) -> list[str]:
    """What is wrong with a draft. terms is {item key: {"hi": ..., "en": ...}}. extras is
    {key: value} for the other texts, and extra_texts the model's {key: {"hi": ..., "en": ...}}
    for them. Empty means it passes."""
    agreed = [i for i in items if i.state is ItemState.AGREED and i.value]
    extras, extra_texts = extras or {}, extra_texts or {}
    allowed = set().union(*(numbers(i.value) for i in agreed))
    everything = allowed.union(*(numbers(v) for v in extras.values()))
    values_spell_amounts = any(_spelled(v) for v in [*(i.value for i in agreed), *extras.values()])
    found = []

    def foreign(where: str, text: str, allowed: set[float]) -> None:
        if extra := numbers(text) - allowed:
            found.append(f"{where} has the figure {_show(extra)}, which is not in the agreed terms")
        if not values_spell_amounts and _spelled(text):
            found.append(f"{where} spells an amount in words; write figures in digits")

    def restates(key: str, value: str, texts: dict[str, str], allowed: set[float]) -> None:
        for lang in ("hi", "en"):
            text = texts.get(lang, "").strip()
            where = f"{key}.{lang}"
            if not text:
                found.append(f"{where} is empty")
                continue
            if _has_devanagari(text) != (lang == "hi") and _has_letters(text):  # "₹13,000" fits either
                found.append(f"{where} is in the wrong script")
            if missing := numbers(value) - numbers(text):
                found.append(f"{where} is missing the figure {_show(missing)}; write it in digits")
            if missing := days(value) - days(text):
                found.append(f"{where} is missing the day or month {', '.join(sorted(missing))}")
            foreign(where, text, allowed)

    for item in agreed:
        restates(item.key.value, item.value, terms.get(item.key.value, {}), allowed)
    for key, value in extras.items():
        restates(key, value, extra_texts.get(key, {}), numbers(value))

    if not _has_devanagari(summary):
        found.append("summary_hi must be in Hindi, in Devanagari script")
    foreign("summary_hi", summary, everything)
    low, high = SUMMARY_WORDS
    if not low <= len(summary.split()) <= high:
        found.append(f"summary_hi has {len(summary.split())} words; it must have {low} to {high}")
    return found
