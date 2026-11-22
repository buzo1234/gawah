"""Two checks on the words of a line that Sage2's answers do not make on their own: whether a
line that names Gawah asks it something, and whether someone is taking leave."""

import re
import unicodedata

_SPLIT = re.compile(r"[\s,.!?;:()\"'“”‘’\-–—/|।॥…]+")
_SENTENCE = re.compile(r"(?<=[.!?।॥])\s+")


def _norm(text: str) -> str:
    return unicodedata.normalize("NFC", unicodedata.normalize("NFD", text.lower()).replace("़", "").replace("ँ", "ं"))


def _words(text: str) -> list[str]:
    return [w for w in _SPLIT.split(_norm(text)) if w]


def _set(*words: str) -> set[str]:
    return {_norm(w) for w in words}


GAWAH = _set("gawah", "gawaah", "gavah", "gawa", "गवाह", "गवा")
_ASKING = _set(
    "kya", "kitna", "kitni", "kitne", "kab", "kaun", "kaunsa", "kahan", "kaise", "kyun", "kyon", "batao", "bataiye",
    "bata", "bataao", "bolo", "boliye", "sunao", "sunaiye", "yaad", "dilao", "padho", "confirm", "what", "when", "how",
    "which", "who", "tell", "repeat", "remind", "क्या", "कितना", "कितनी", "कितने", "कब", "कौन", "कहां", "कैसे", "क्यों",
    "बताओ", "बताइए", "बता", "बोलो", "बोलिए", "सुनाओ", "याद", "दिलाओ",
)


def _gawah(word: str) -> bool:
    """A word that is Gawah's name, with "ji" run on ("गवाजी") or a nasal mark the transcript added ("गवां")."""
    bare = word.replace("ं", "")
    return any(w in GAWAH for w in (word, bare, bare.removesuffix("जी"), bare.removesuffix("ji")))


def names_gawah(text: str) -> bool:
    return any(_gawah(w) for w in _words(text))


def asks_gawah(text: str) -> bool:
    """The line asks Gawah something: a question or a request from where it names Gawah on
    ("Gawah ji, advance kitna tay hua?"), or anywhere in a line that does not name it. Naming
    Gawah in passing ("Gawah sun raha hai") asks nothing."""
    sentences = [s for s in _SENTENCE.split(text) if s.strip()]
    named = next((i for i, s in enumerate(sentences) if names_gawah(s)), None)
    asked = sentences if named is None else sentences[named:]
    return any("?" in s or _ASKING & set(_words(s)) for s in asked)


_LEAVING = _set(
    "bye", "alvida", "hafiz", "milte", "milenge", "milta", "milti", "rakhta", "rakhti", "rakhte", "chalta", "chalti",
    "nikalta", "nikalti", "nikalna", "shukriya", "dhanyavad", "dhanyawad", "thanks", "thank", "namaste", "namaskar",
    "pranam", "goodbye", "aaunga", "aaungi", "आऊंगा", "आऊंगी", "बाय", "अलविदा", "हाफिज", "मिलते", "मिलेंगे", "मिलता", "रखता", "रखती", "चलता", "चलती", "निकलना",
    "शुक्रिया", "धन्यवाद", "नमस्ते", "नमस्कार", "प्रणाम",
)
_LEAVING_PAIRS = {
    ("baad", "mein"), ("baad", "me"), ("बाद", "में"), ("jaana", "hai"), ("jana", "hai"), ("जाना", "है"),
    ("phir", "baat"), ("fir", "baat"), ("फिर", "बात"), ("call", "karta"), ("call", "karti"), ("phone", "rakh"),
    # fixing when to meet next: "to Wednesday aa jao", "kal aa jaunga"
    ("aa", "jao"), ("aa", "jaana"), ("aa", "jana"), ("aa", "jaiye"), ("aa", "jaunga"), ("aa", "jaungi"), ("aa", "jayenge"),
    ("आ", "जाओ"), ("आ", "जाना"), ("आ", "जाइए"), ("आ", "जाऊंगा"), ("आ", "जाऊंगी"), ("आ", "जाएंगे"),
}


def takes_leave(text: str) -> bool:
    """Someone says goodbye, thanks to close, says they must go or will talk later, or fixes
    when they meet next."""
    words = _words(text)
    return bool(_LEAVING & set(words)) or any(pair in _LEAVING_PAIRS for pair in zip(words, words[1:]))
