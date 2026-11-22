"""The words the agent is given: each transcript line, each fact as a short note, and each
moment to speak. Text only; nothing here talks to the model or to memory."""

import re

from app.contracts import (
    Audience, ChecklistUpdated, Fact, FactConflict, FactStatus, ItemState, JudgeSpeak, Person, Role, TranscriptLine,
)
from app.mouth import tuning

ROLE_SHORT = {Role.HIRER: "paying for the work", Role.WORKER: "doing the work"}
_SPLIT = re.compile(r"[\s,.!?।|:;\"'()\[\]-]+")


def addresses_gawah(text: str) -> bool:
    """A line that names Gawah. Whole words only: "gawahi" (testimony) must not wake it. A nasal
    mark the transcript added ("गवां जी") and a "ji" run on ("गवांजी") still name it."""
    for word in _SPLIT.split(text.lower()):
        bare = word.replace("ं", "").replace("ँ", "")
        if any(w in tuning.ADDRESS_WORDS for w in (word, bare, bare.removesuffix("ji"), bare.removesuffix("जी"))):
            return True
    return False


def _words(text: str) -> list[str]:
    return [w for w in _SPLIT.split(text.lower()) if w]


def asks_for_clip(text: str) -> bool:
    """Asks to hear the recording, whatever comes first: "nahi, pehle recording sunao" asks for it,
    "recording mat sunao" does not."""
    words = _words(text)
    return any(w in tuning.CLIP_ASK_WORDS for w in words) and not any(w in tuning.CLIP_REFUSE_WORDS for w in words)


def wants_clip(text: str) -> bool:
    """A yes to the offer to play the recording, or asking for it: "Haan, sunaiye", "haan ji", "haan suno",
    "recording chalaiye". A yes that goes on about the term ("haan ji, baees hi tha") is not one."""
    if asks_for_clip(text):
        return True
    words = _words(text)
    if any(w in tuning.CLIP_NO_WORDS for w in words):
        return False
    return bool(words) and len(words) <= 3 and all(w in tuning.CLIP_YES_WORDS for w in words)


def declines_clip(text: str) -> bool:
    return any(w in tuning.CLIP_NO_WORDS or w in tuning.CLIP_REFUSE_WORDS for w in _words(text)) and not asks_for_clip(text)


def clip_moment(name: str, fact_id: str) -> str:
    head = tuning.MOMENT.format(why=tuning.MOMENT_WHY["clip"], to=name)
    return head + tuning.MOMENT_CLIP.format(name=name, fact=fact_id)


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


def moment(
    speak: JudgeSpeak, names: Names, facts: dict[str, Fact], question: str | None, checklist: ChecklistUpdated | None = None,
) -> str:
    """A judge.speak turned into a situation: why, to whom, the facts, and what was asked."""
    reason = speak.reason.value
    head = tuning.MOMENT.format(why=tuning.MOMENT_WHY[reason], to=names.to(speak.to))
    known = [fact(facts[i], names) for i in speak.fact_ids if i in facts]
    on_record = " ".join(known) or f"(facts {', '.join(speak.fact_ids) or 'not given'}; look them up)"
    if reason in ("addressed_directly", "unanswered_question"):
        role = Role(speak.to.value) if speak.to in (Audience.HIRER, Audience.WORKER) else None
        asked = addressed(names.of(role), speak.after_line, question or speak.question or speak.instruction, checklist)
        return head + asked + tuning.JUDGE_NOTE.format(instruction=clean_long(speak.instruction))
    if reason in ("open_terms", "read_back"):
        return head + tuning.MOMENT_SAY.format(instruction=clean_long(speak.instruction), to=names.to(speak.to))
    if reason == "change_proposed":
        fact_id = speak.fact_ids[0] if speak.fact_ids else "(look it up with get_term)"
        return head + tuning.MOMENT_CHANGE.format(instruction=clean(speak.instruction), facts=on_record, fact=fact_id, to=names.to(speak.to))
    if reason == "dispute_open":
        return head + tuning.MOMENT_DISPUTE.format(instruction=clean_long(speak.instruction), facts=on_record)
    if reason == "contradicts_record":
        return head + tuning.MOMENT_CONTRADICTION.format(instruction=clean(speak.instruction), facts=on_record, to=names.to(speak.to))
    body = tuning.MOMENT_ASK.format(instruction=clean(speak.instruction), to=names.to(speak.to))
    return head + body + (f" On record: {on_record}" if known else "")


def clean_long(text: str | None) -> str:
    """A Judge's note: a read-back lists every term, so it is kept whole."""
    return " ".join(str(text or "").split())[:1200].replace('"', "'")


def status(checklist: ChecklistUpdated | None) -> str:
    """What the checklist holds now, agreed and still open, for an answer about the deal."""
    if checklist is None:
        return ""
    agreed = [f"{tuning.LABEL[i.key]}: {clean(i.value)}" for i in checklist.items if i.state is ItemState.AGREED and i.value]
    still = [tuning.LABEL[i.key] for i in checklist.items if i.state is not ItemState.AGREED]
    return tuning.STATUS.format(agreed="; ".join(agreed) or "nothing yet", open=", ".join(still) or "nothing")


def addressed(name: str, line_no: int | None, question: str, checklist: ChecklistUpdated | None = None) -> str:
    return tuning.MOMENT_ADDRESSED.format(name=name, no=line_no or "?", question=clean(question), status=status(checklist))


def addressed_moment(event: TranscriptLine, names: Names, checklist: ChecklistUpdated | None = None) -> str:
    name = names.of(event.speaker)
    head = tuning.MOMENT.format(why=tuning.MOMENT_WHY["addressed_directly"], to=name)
    return head + addressed(name, event.line_no, event.text, checklist)


def follow_up(about: str, names: Names, to: Audience = Audience.BOTH) -> str:
    head = tuning.MOMENT.format(why=tuning.MOMENT_WHY["follow_up"], to=names.to(to))
    return head + tuning.FOLLOW_UP.format(about=about)


def opening(names: Names) -> str:
    known = [p.name.split()[0] + " ji" for p in names.people if p.name]
    said = " aur ".join(known) if len(known) == 2 else tuning.OPENING_NAMES_UNKNOWN
    return tuning.OPENING_MOMENT.format(line=tuning.OPENING_LINE.format(names=said))
