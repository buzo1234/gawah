"""Saying a figure back: whether it accepts the figure or only repeats it with a complaint,
a hedge, a question or a deferral, and the scale a bare figure said back takes."""

import re

from app.contracts import TranscriptLine
from app.memory.book import DealBook
from app.memory.claims import Claim
from app.memory.normalise import STRONG_YES, bare_numbers, normed, parse_rupees, tokens

# A complaint, a doubt, a hedge or a deferral about a figure: "thoda zyada hai", "dekhte hain",
# "vo baad mein". Saying the other person's figure back with one of these accepts nothing.
_DOUBT = normed({
    "zyada", "jyada", "jada", "zada", "jaada", "zyaada", "ज्यादा", "जादा", "ज्याडा", "mehenga", "mehnga", "mahenga",
    "mehanga", "महंगा", "महँगा", "shayad", "शायद", "lekin", "magar", "लेकिन", "मगर", "but", "dekhte", "dekhenge",
    "देखते", "देखेंगे", "sochte", "sochenge", "sochna", "sochungi", "sochunga", "सोचते", "सोचेंगे", "सोचना", "mushkil",
    "मुश्किल", "pata", "पता", "kam", "कम", "too", "much", "expensive", "maybe", "later",
})
# "Baarah mein to ...": what that figure would get, said before a counter.
_DOUBT_PAIRS = {("mein", "to"), ("me", "to"), ("में", "तो"), ("baad", "mein"), ("baad", "me"), ("बाद", "में"), ("abhi", "nahi"), ("अभी", "नहीं"), ("nahi", "chalega"), ("नहीं", "चलेगा")}
_QUESTION = normed({"kya", "kitna", "kitni", "kitne", "kaise", "kab", "क्या", "कितना", "कितनी", "कितने", "कैसे", "कब"})
_PLAIN_YES = normed({"haan", "han", "haa", "haanji", "hanji", "ji", "jee", "yes", "chalo", "chaliye", "हाँ", "हां", "जी", "चलो", "चलिए"})
# A commitment to pay or to do it: "de dungi", "kar denge", "chalega".
_COMMIT = normed({
    "dunga", "dungi", "doonga", "doongi", "doon", "dun", "denge", "karunga", "karungi", "karenge", "chalega", "chalegi",
    "manzoor", "maanjoor", "दूंगा", "दूंगी", "देंगे", "करूंगा", "करूंगी", "करेंगे", "चलेगा", "मंजूर", "दूं", "agreed",
})


def doubts(text: str | None) -> bool:
    """A complaint, a doubt, a hedge, a question or a deferral."""
    if not text:
        return False
    if "?" in text or "..." in text or "…" in text:
        return True
    toks = tokens(text)
    return any(t in _DOUBT or t in _QUESTION for t in toks) or any(pair in _DOUBT_PAIRS for pair in zip(toks, toks[1:]))


_CLAUSE = re.compile(r"(?:[^,.।॥!?;…]|(?<=\d)[,.](?=\d))+[,.।॥!?;…]*")


def _has_figure(clause: str, rupees: int) -> bool:
    return rupees in parse_rupees(clause) or any(round(b * k) == rupees for b in bare_numbers(clause) for k in (1, 1000, 100000))


def doubts_figure(text: str | None, rupees: int | None) -> bool:
    """The clause that says the figure complains, doubts, hedges, asks or defers, with no firm
    yes in it: "9,300 thoda zyada hai", not "theek hai, 9,000, lekin material aapka"."""
    if not text:
        return False
    clauses = [m.group() for m in _CLAUSE.finditer(text)] or [text]
    said = [i for i, c in enumerate(clauses) if rupees and _has_figure(c, rupees)]
    if not said:
        return False  # the figure is not said back here

    def firm(i: int, head: int = 99) -> bool:
        return i < len(clauses) and any(t in STRONG_YES for t in tokens(clauses[i])[:head])

    # "8 hazaar... theek hai": a firm yes in the clause, or opening the next one, outweighs the doubt.
    return any(doubts(clauses[i]) and not firm(i) and not firm(i + 1, 3) for i in said)


def says_figure(text: str | None, rupees: int | None) -> bool:
    """The words say this figure, at any scale ("pandrah" for 15,000)."""
    return bool(text and rupees) and _has_figure(text, rupees)


def commits(text: str | None, rupees: int | None = None) -> bool:
    """A clear yes ("haan", "theek", "pakka") or a commitment to pay or do it ("de dungi"), and
    no doubt about the figure."""
    if not text or doubts_figure(text, rupees) or (not says_figure(text, rupees) and doubts(text)):
        return False
    return any(t in STRONG_YES or t in _PLAIN_YES or t in _COMMIT for t in tokens(text))


def recent_rupees(deal: DealBook, line: TranscriptLine, speaker=None) -> set[int]:
    """Every amount stated outright in the last few lines, by `speaker` if given."""
    found: set[int] = set()
    for n in range(line.line_no - 1, max(0, line.line_no - 5), -1):
        said = deal.lines.get((line.call_no, n))
        if said is not None and speaker in (None, said.speaker):
            found |= set(parse_rupees(said.text))
    return found


def echoes(deal: DealBook, line: TranscriptLine, rupees: int | None) -> bool:
    """The figure is one the other person said in the last few lines."""
    return bool(rupees) and rupees in recent_rupees(deal, line, line.speaker.other)


def scale(deal: DealBook, line: TranscriptLine, claim: Claim) -> None:
    """"Dhai. Theek hai." after "dhai lakh": a bare figure said back takes the scale it was
    just said with, whatever the model made of it."""
    if claim.rupees is None or claim.rupees in parse_rupees(claim.quote):
        return
    recent = recent_rupees(deal, line)
    if claim.rupees in recent:
        return
    for bare in sorted(bare_numbers(claim.quote)):
        scaled = next((round(bare * k) for k in (1000, 100000) if round(bare * k) in recent), None)
        if scaled:
            if claim.value:
                claim.value = claim.value.replace(f"{claim.rupees:,}", f"{scaled:,}")
            claim.rupees = scaled
            return
