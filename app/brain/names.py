"""Who is on the call: the people call.started brought, and names heard on the call.

A deal started on WhatsApp knows only the worker's phone. Gawah's opening line asks each
person to say their name, so the model is asked for names over the first lines. A name
heard fills one the call did not have and never replaces one.
"""

import logging

from app.brain import sage
from app.brain.values import Values
from app.contracts import Person, Role


def first_name(value: object) -> str | None:
    """A first name from the model: one word of letters, or None."""
    if not isinstance(value, str):
        return None
    word = (value.split() or [""])[0].strip(".,!?'\"")
    return word[:1].upper() + word[1:] if word.isalpha() and 2 <= len(word) <= 30 else None


class People:
    def __init__(self, people: list[Person]) -> None:
        self.by_role = {role: next((p for p in people if p.role is role), Person(role=role)) for role in Role}
        # Sage2 is sent the names the call started with, all the way through: its transcript
        # cannot be relabelled. The Judge's instructions use a name as soon as it is heard.
        self.sage_names = {role: sage.speaker_name(people, role) for role in Role}
        self.names = dict(self.sage_names)

    @property
    def all(self) -> list[Person]:
        return list(self.by_role.values())

    def unknown(self) -> bool:
        return any(not person.name for person in self.by_role.values())

    def meet(self, people: list[Person]) -> list[Person]:
        """Take any name we did not have. Returns the people whose name was new."""
        learned = []
        for person in people:
            known = self.by_role[person.role]
            if person.name and not known.name:
                self.by_role[person.role] = known.model_copy(update={"name": person.name})
                self.names[person.role] = sage.speaker_name(people, person.role)
                learned.append(person)
        return learned

    def learn(self, reply: dict) -> list[Person]:
        """The model's reply to the names lookup: {"hirer": name or null, "worker": ...}."""
        heard = [Person(role=role, name=name) for role in Role if (name := first_name(reply.get(role.value)))]
        return self.meet(heard)

    async def ask(self, values: Values, transcript: str, at_line: int, log: logging.LoggerAdapter) -> list[Person]:
        """Ask the model for the names said so far. Returns the people whose name was new."""
        try:
            reply = await values.lookup("names", None, transcript, at_line) or {}
        except Exception as e:
            log.warning("names lookup failed (%s: %s)", type(e).__name__, str(e)[:200])
            return []
        learned = self.learn(reply)
        if learned:
            log.info("learned at line %s: %s", at_line, ", ".join(f"{p.role.value} {p.name}" for p in learned))
        return learned
