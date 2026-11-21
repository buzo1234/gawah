"""The deal's terms as the memory's facts have them. The checklist is built from here.

A fold of fact.recorded: the latest version of each fact, kept per deal across its calls.
An item is agreed when its current fact is, by the rule memory's get_term uses: the latest
confirmed term fact if any, else the latest agreed one. Offers, rejected counter-offers and
filler "theek hai"s never make an item agreed; only the Scribe's facts do.

One inference is added, for the work: once a price is agreed, the work described before it
is agreed too, since nobody agrees a price for a job they have not accepted. People describe
the work and say "ho jayega"; the Scribe rarely hears that as accepting it. The checklist
then names the line, and memory turns that work fact agreed (its checklist.updated path).
"""

from app.contracts import ChecklistItem, Fact, FactKind, FactStatus, ItemKey, ItemState, MemoryQueries

HOLDS = (FactStatus.CONFIRMED, FactStatus.AGREED)
LIVE = (FactStatus.CONFIRMED, FactStatus.AGREED, FactStatus.SAID)
# One figure: the current fact's value is the term. The others gather details over several
# lines ("Monday se shuru", later "Friday tak khatam"), so every agreed part is kept, the
# first ones first: what comes late is mostly a recap or the goodbye.
ONE_FIGURE = {ItemKey.AMOUNT, ItemKey.ADVANCE}
MAX_PARTS = 4


class Terms:
    def __init__(self) -> None:
        self.latest: dict[str, Fact] = {}  # fact id -> latest version; oldest fact first
        self._seen: dict[str, int] = {}  # fact id -> when its latest version came
        self._n = 0

    def add(self, fact: Fact) -> bool:
        """Take a version. False if it is the version already held (a seed and its event)."""
        held = self.latest.get(fact.id)
        if held is not None and fact.hash and held.hash == fact.hash:
            return False
        self._n += 1
        self.latest[fact.id], self._seen[fact.id] = fact, self._n
        return True

    async def seed(self, memory: MemoryQueries, deal_id: str) -> None:
        """Every term fact memory holds for the deal: after a restart, the brain has seen none."""
        for key in ItemKey:
            for version in (await memory.get_term(deal_id, key)).history:
                self.add(version)

    def _standing(self, key: ItemKey, statuses=HOLDS) -> list[Fact]:
        return [f for f in self.latest.values() if f.item == key and f.kind == FactKind.TERM and f.status in statuses]

    def _described_work(self) -> list[Fact]:
        """The work said before the price was agreed, if a price is agreed."""
        price = self.current(ItemKey.AMOUNT)
        if price is None:
            return []
        upto = (price.call_no or 0, price.line_no or 0)
        return [f for f in self._standing(ItemKey.WORK, LIVE) if (f.call_no or 0, f.line_no or 0) <= upto]

    def agreed(self, key: ItemKey) -> bool:
        return self.current(key) is not None or (key is ItemKey.WORK and bool(self._described_work()))

    def proposal(self, key: ItemKey, suspect: frozenset[tuple] = frozenset()) -> tuple[str, list[Fact]] | None:
        """What was stated for a term nobody has agreed, to be confirmed: its words and the facts.
        None when nothing was stated, or a money term had two figures (that is bargaining).
        suspect: (call_no, line_no) of lines that contradicted the record; nothing is taken from them."""
        if self.agreed(key):
            return None
        said = [
            f for f in self._standing(key, (FactStatus.SAID,))
            if f.value and (f.call_no, f.line_no) not in suspect
        ]
        if not said:
            return None
        if key in ONE_FIGURE:
            if len({f.value_rupees for f in said if f.value_rupees is not None}) > 1:
                return None
            said = said[-1:]
        words: list[str] = []
        for fact in said:
            if fact.value.lower() not in (w.lower() for w in words):
                words.append(fact.value)
        return "; ".join(words[:MAX_PARTS]), said

    def current(self, key: ItemKey) -> Fact | None:
        standing = self._standing(key)
        for status in HOLDS:
            matches = [f for f in standing if f.status == status]
            if matches:
                return max(matches, key=lambda f: self._seen[f.id])
        return None

    def _parts(self, key: ItemKey) -> list[Fact]:
        current = self.current(key)
        if key in ONE_FIGURE:
            return [current] if current else []
        if key is ItemKey.WORK:  # a description: every detail said about it, agreed or not
            return self._standing(key, LIVE) if self.agreed(key) else []
        return self._standing(key)

    def value(self, key: ItemKey) -> str | None:
        parts: list[str] = []
        for fact in self._parts(key):
            words = fact.value or fact.text
            if words.lower() not in (p.lower() for p in parts):
                parts.append(words)
        return "; ".join(parts[:MAX_PARTS]) or None

    def item(self, key: ItemKey, note: str | None = None) -> ChecklistItem:
        if not self.agreed(key):
            return ChecklistItem(key=key, note=note)
        source = self.current(key) or self._described_work()[-1]
        return ChecklistItem(
            key=key, state=ItemState.AGREED, value=self.value(key), source_text=source.quote,
            line_no=source.line_no, note=note,
        )

    def signature(self, key: ItemKey) -> tuple:
        """What a read-back would say about the item: changes when its term changes."""
        current = self.current(key)
        figure = (current.value_rupees, current.value_date) if current else ()
        return (self.agreed(key), figure, self.value(key))
