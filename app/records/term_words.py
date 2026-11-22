"""What Gawah says on WhatsApp about a term disputed on a call-back: who said no, what the
record holds, and the other person's version beside it. Never who is right. The record itself
is quoted as for a payment claim (dispute_words.quote_term)."""

from app.contracts import ItemKey, Person
from app.records.dispute_words import quoted
from app.records.words import _short, term_name, who

# Reply buttons for the person who said no (at most 20 characters each).
RECORDING_BUTTON, OTHER_BUTTON = "Recording sahi hai", "Kuch aur tay hua tha"
# The same choices typed, where the provider has no buttons (Twilio): their number, or the words.
CHOICES = {"1": True, RECORDING_BUTTON.casefold(): True, "2": False, OTHER_BUTTON.casefold(): False}


def _terms(named: list[tuple[ItemKey, str | None]]) -> str:
    parts = [term_name(item) + (f" {shown}" if shown else "") for item, shown in named]
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " aur " + parts[-1]


def _upper(text: str) -> str:
    return text[0].upper() + text[1:]


def disputed(person: Person, named: list[tuple[ItemKey, str | None]], rest: str, record: list[str]) -> str:
    """To both, once the call-back of the person who said no is over. named: each term with its
    figure as on record; rest: what else stands (rest_confirmed); record: dispute_words.quote_term lines."""
    line = f'{who(person)} ne {_terms(named)} par "nahi" kaha. {rest}Agreement tab tak ruka hai jab tak yeh tay nahi hota.'
    if record:
        line += "\n" + quoted(_upper(" aur ".join(term_name(item) for item, _ in named)), record)
    return line


def rest_confirmed(person: Person, other: Person, both: bool, theirs: bool) -> str:
    """both: every other term is confirmed by both; theirs: by the person who said no."""
    if both:
        return "Baaki sab dono ne confirm kar diya hai. "
    return f"Baaki sab {who(person)} ne maan liya hai. " if theirs else ""


def choose(item: ItemKey, shown: str | None, numbered: bool) -> str:
    """To the person who said no, under the record: the two choices. numbered: no buttons, so
    the choices are typed (Twilio)."""
    line = (f"Aapne {term_name(item)}" + (f" {shown}" if shown else "") + ' par "nahi" kaha. Upar record mein woh pal '
            "suniye. Kya recording sahi hai, ya kuch aur tay hua tha?")
    if numbered:
        line += f"\n1 likhiye: {RECORDING_BUTTON}\n2 likhiye: {OTHER_BUTTON}"
    return line


def ask_version(item: ItemKey) -> str:
    return f"Aapke hisaab se {term_name(item)} mein kya tay hua tha? Likh kar ya voice note mein bhejiye."


def version_line(person: Person, version: str) -> str:
    return f'{who(person)} ke hisaab se: "{_short(version, 160).rstrip(" .!।")}".'


def both_versions(item: ItemKey, record: str | None, version: str, url: str) -> str:
    """To both, side by side, with their own call link. record: the record's line (quote_term)."""
    lines = [record, version] if record else [version]
    numbered = "\n".join(f"{n}. {line}" for n, line in enumerate(lines, 1))
    return (f"{_upper(term_name(item))} par do baatein hain:\n{numbered}\n"
            "Dono saath call par baat karke tay kar lijiye; call mein Gawah dono baatein saamne rakhega. "
            f"Call ke liye yeh link kholiye: {url}")


def withdrawn_for_other(person: Person, item: ItemKey, shown: str | None) -> str:
    what = term_name(item) + (f" {shown}" if shown else "")
    return f"{who(person)} ne maana ki recording sahi hai: {what} ab dono ki taraf se pakka hai."


def withdrawn_for_them(item: ItemKey, shown: str | None) -> str:
    return "Likh liya: " + term_name(item) + (f" {shown}" if shown else "") + " aapki taraf se bhi pakka hai."


def confirmed(person: Person, item: ItemKey, shown: str | None) -> str:
    what = term_name(item) + (f" {shown}" if shown else "")
    return f"{who(person)} ne {what} confirm kar diya. Is par ab koi vivaad nahi."


def changed(item: ItemKey, new: str) -> str:
    return f"{_upper(term_name(item))} ab {new} hai, dono ne confirm kiya. Is par ab koi vivaad nahi."


ALL_SETTLED = " Ab sab tay hai: agreement thodi der mein yahin aayega."


def remind(person: Person, item: ItemKey, shown: str | None) -> str:
    what = term_name(item) + (f" {shown}" if shown else "")
    return (f'Yaad dila raha hoon: {what} par baat abhi baaki hai ({who(person)} ne "nahi" kaha tha). '
            "Agreement tab tak ruka hai.")


def still_open(items: list[ItemKey]) -> str:
    """Under an owed message or a reminder while a term is in dispute: the figures are the ones on record."""
    if not items:
        return ""
    return f" {_upper(' aur '.join(term_name(i) for i in items))} par vivaad hai."
