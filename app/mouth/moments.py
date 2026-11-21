"""The words the agent is given: each transcript line, each fact as a short note, and each
moment to speak. Text only; nothing here talks to the model or to memory."""

import re

from app.contracts import Audience, Fact, FactConflict, FactStatus, JudgeSpeak, Person, Role, TranscriptLine
from app.mouth import tuning

ROLE_SHORT = {Role.HIRER: "paying for the work", Role.WORKER: "doing the work"}
_SPLIT = re.compile(r"[\s,.!?।|:;\"'()\[\]-]+")


def addresses_gawah(text: str) -> bool:
    """A line that names Gawah. Whole words only: "gawahi" (testimony) must not wake it."""
    for word in _SPLIT.split(text.lower()):
        if word in tuning.ADDRESS_WORDS or word.removesuffix("ji").removesuffix("जी") in tuning.ADDRESS_WORDS:
            return True
    return False


def clean(text: str | None) -> str:
    return " ".join(str(text or "").split())[: tuning.NOTE_MAX].replace('"', "'")


class Names:
    """Who is who on this call, by role. A person with no name is called by their role."""

    def __init__(self, people: list[Person]) -> None:
        self.people = list(people)

    def meet(self, people: list[Person]) -> None:
        known = {p.role: p for p in self.people}
        for person in people:
            if person.name and not (known.get(person.role) and known[person.role].name):
                known[person.role] = person
        self.people = list(known.values())

    def of(self, role: Role | None) -> str:
        person = next((p for p in self.people if p.role is role), None)
        if person and person.name:
            return person.name.split()[0]
        return {Role.HIRER: "the hirer", Role.WORKER: "the worker"}.get(role, "someone")

    def to(self, audience: Audience | None) -> str:
        if audience in (None, Audience.BOTH):
            return f"{self.of(Role.HIRER)} and {self.of(Role.WORKER)}"
        return self.of(Role(audience.value))

    def who(self) -> str:
        return tuning.AGENT_WHO.format(people="; ".join(
            f"{self.of(role)} is the person {ROLE_SHORT[role]} ({role.value})" for role in Role
        ))


def line(event: TranscriptLine, names: Names) -> str:
    return tuning.LINE.format(name=names.of(event.speaker), role=event.speaker.value, no=event.line_no or "?", text=clean(event.text))


def fact(f: Fact, names: Names) -> str:
    """One fact in a line: id, status, words, value, who, when, and whether it has a clip."""
    parts = [f"[{f.id}] {f.status.value}: {clean(f.text)}"]
    if f.value:
        parts.append(f"Value: {clean(f.value)}.")
    if f.said_by:
        said = f"Said by {names.of(f.said_by)}"
        if f.agreed_by:
            said += f"; agreed by {', '.join(names.of(r) for r in f.agreed_by)}"
        if f.confirmed_by:
            said += f"; confirmed by {', '.join(names.of(r) for r in f.confirmed_by)}"
        parts.append(said + ".")
    when = []
    if f.call_no:
        when.append(f"call {f.call_no}")
    if f.start is not None:
        when.append(f"{int(f.start // 60)} min {int(f.start % 60)} s in")
    if f.valid_from:
        when.append(f"on {f.valid_from.day} {f.valid_from.strftime('%B')}")
    if when:
        parts.append("When: " + ", ".join(when) + ".")
    if f.quote:
        parts.append(f"Words: '{clean(f.quote)}'.")
    if f.replaces:
        parts.append(f"Replaces {f.replaces}.")
    if f.status is FactStatus.SUPERSEDED:
        parts.append("No longer holds.")
    parts.append("Clip: yes." if f.start is not None and f.end is not None else "Clip: no.")
    return " ".join(parts)


def conflict(event: FactConflict) -> str:
    said = f" (said: '{clean(event.said)}')" if event.said else ""
    return tuning.CONFLICT_NOTE.format(ids=", ".join(event.fact_ids), explanation=clean(event.explanation), said=said)


def moment(speak: JudgeSpeak, names: Names, facts: dict[str, Fact], question: str | None) -> str:
    """A judge.speak turned into a situation: why, to whom, the facts, and what was asked."""
    reason = speak.reason.value
    head = tuning.MOMENT.format(why=tuning.MOMENT_WHY[reason], to=names.to(speak.to))
    known = [fact(facts[i], names) for i in speak.fact_ids if i in facts]
    on_record = " ".join(known) or f"(facts {', '.join(speak.fact_ids) or 'not given'}; look them up)"
    if reason == "addressed_directly":
        role = Role(speak.to.value) if speak.to in (Audience.HIRER, Audience.WORKER) else None
        return head + addressed(names.of(role), speak.after_line, question or speak.question or speak.instruction)
    if reason == "contradicts_record":
        return head + tuning.MOMENT_CONTRADICTION.format(instruction=clean(speak.instruction), facts=on_record, to=names.to(speak.to))
    body = tuning.MOMENT_ASK.format(instruction=clean(speak.instruction), to=names.to(speak.to))
    return head + body + (f" On record: {on_record}" if known else "")


def contradiction_ask(speak: JudgeSpeak, names: Names) -> str:
    return tuning.MOMENT_CONTRADICTION_ASK.format(to=names.to(speak.to))


def addressed(name: str, line_no: int | None, question: str) -> str:
    return tuning.MOMENT_ADDRESSED.format(name=name, no=line_no or "?", question=clean(question))


def addressed_moment(event: TranscriptLine, names: Names) -> str:
    name = names.of(event.speaker)
    head = tuning.MOMENT.format(why=tuning.MOMENT_WHY["addressed_directly"], to=name)
    return head + addressed(name, event.line_no, event.text)


def follow_up(about: str, names: Names, to: Audience = Audience.BOTH) -> str:
    head = tuning.MOMENT.format(why=tuning.MOMENT_WHY["follow_up"], to=names.to(to))
    return head + tuning.FOLLOW_UP.format(about=about)


def opening(names: Names) -> str:
    known = [p.name.split()[0] + " ji" for p in names.people if p.name]
    said = " aur ".join(known) if len(known) == 2 else tuning.OPENING_NAMES_UNKNOWN
    return tuning.OPENING_MOMENT.format(line=tuning.OPENING_LINE.format(names=said))
