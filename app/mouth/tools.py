"""Gawah's tools on the deal call. The agent acts only through these. Lookups go to memory
(the MemoryQueries interface on app.state.memory); a change is proposed and confirmed here
and goes out as fact.changed. Nothing a tool does blocks on memory: a slow or missing
answer says so, and the agent answers from the conversation it already has.

What a tool publishes is held on the turn and sent only if the turn is carried out (said
aloud, or finished silently), so a change is never proposed in words nobody heard.
"""

import asyncio
import io
import logging
import wave
from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np

from app.contracts import (
    AgentNote, ChangeStatus, CrewAgent, Event, Fact, FactChanged, ItemKey, MemoryQueries, Role, TranscriptLine,
)
from app.mouth import moments, tuning
from app.mouth.moments import Names

_ROLE = {"type": "string", "enum": [r.value for r in Role]}
_SAID = {"type": "string", "description": "The person's own words from the line, as they said them."}


def _tool(name: str, description: str, properties: dict | None = None, required: list[str] | None = None) -> dict:
    return {
        "type": "function", "name": name, "description": description,
        "parameters": {"type": "object", "properties": properties or {}, "required": required or []},
    }


TOOLS = [
    _tool("get_term", "The current agreed or confirmed value of one term of the deal, its history (offers, older "
          "versions) with who said each and when, and the fact ids.",
          {"item": {"type": "string", "enum": [k.value for k in ItemKey]}}, ["item"]),
    _tool("owed", "What has been paid towards the total, the advance and the balance, and what is still owed, worked out in code."),
    _tool("search_facts", "Search everything on record for this deal, across calls and messages: facts and lines "
          "about something that is not one of the six terms, such as the paint or who buys the material.",
          {"query": {"type": "string"}}, ["query"]),
    _tool("play_clip", "Play the original audio of a fact into the call, in the people's own voices. Say a short "
          "lead-in first, in the same reply.", {"fact_id": {"type": "string"}}, ["fact_id"]),
    _tool("propose_change", "Start a change to an agreed term that someone on the call has asked for. Nothing "
          "changes until both people say yes.",
          {"fact_id": {"type": "string", "description": "the fact being changed"},
           "new_value": {"type": "string", "description": "the new value, in the words used on the call"},
           "proposed_by": _ROLE, "said": _SAID}, ["fact_id", "new_value", "proposed_by", "said"]),
    _tool("confirm_change", "Record one person's spoken yes or no to a proposed change, from a line they said.",
          {"change_id": {"type": "string"}, "person": _ROLE, "agrees": {"type": "boolean"}, "said": _SAID},
          ["change_id", "person", "agrees", "said"]),
    _tool("stay_silent", "Nothing needs saying now.", {"reason": {"type": "string"}}, []),
]


@dataclass
class Result:
    output: str  # what the model is told
    clip: bytes | None = None  # speech to play into the room, 24 kHz 16-bit mono
    clip_fact_id: str | None = None
    silent: bool = False
    effects: list[Event] = field(default_factory=list)  # sent if the turn is carried out


@dataclass
class _Change:
    event: FactChanged
    old: str
    after_line: int  # a yes counts only from a line said after this one


class Tools:
    def __init__(
        self, deal_id: str, memory: Callable[[], MemoryQueries | None], facts: dict[str, Fact], names: Names,
        lines: list[TranscriptLine], log: logging.LoggerAdapter,
    ) -> None:
        self.deal_id, self.memory, self.facts, self.names, self.lines, self.log = deal_id, memory, facts, names, lines, log
        self.changes: dict[str, _Change] = {}

    def open_changes(self) -> list[_Change]:
        return [c for c in self.changes.values() if c.event.status in (ChangeStatus.PROPOSED, ChangeStatus.CONFIRMED_ONE)]

    def changed(self, event: FactChanged) -> None:
        """A step of a change, once it has been sent."""
        if event.change_id in self.changes:
            self.changes[event.change_id].event = event

    async def run(self, name: str, args: dict) -> Result:
        try:
            return await getattr(self, f"_{name}")(**{k: v for k, v in args.items() if isinstance(k, str)})
        except (AttributeError, TypeError, ValueError) as e:
            self.log.warning("bad tool call %s %s: %s", name, args, e)
            return Result(f"No such tool call: {name} with {sorted(args)}.")

    def _note(self, text: str, fact_ids: list[str] | None = None) -> AgentNote:
        return AgentNote(deal_id=self.deal_id, agent=CrewAgent.GAWAH, text=text, fact_ids=fact_ids or [])

    async def _ask(self, query, what: str):
        """One memory query, bounded. None when there is no memory or no answer in time."""
        memory = self.memory()
        if memory is None:
            return None
        try:
            return await asyncio.wait_for(query(memory), tuning.TOOL_TIMEOUT_S)
        except Exception as e:
            self.log.warning("memory did not answer %s: %s", what, type(e).__name__)
            return None

    async def _fact(self, fact_id: str) -> Fact | None:
        return self.facts.get(fact_id)

    # ---- lookups ----

    async def _get_term(self, item: str) -> Result:
        key = ItemKey(item)
        view = await self._ask(lambda m: m.get_term(self.deal_id, key), f"get_term {item}")
        label = tuning.LABEL[key]
        if view is None and not self.memory():
            return Result(tuning.NO_MEMORY, effects=[self._note(f"looked up {label}: no memory")])
        if view is None or (view.current is None and not view.history):
            return Result(tuning.NOT_ON_RECORD.format(what=label), effects=[self._note(f"looked up {label}: nothing on record")])
        for f in view.history:
            self.facts.setdefault(f.id, f)
        current = moments.fact(view.current, self.names) if view.current else "nothing agreed yet"
        older = [moments.fact(f, self.names) for f in _latest(view.history) if not view.current or f.id != view.current.id]
        text = f"{label}: now {current}" + (f" History, oldest first: {' '.join(older)}" if older else "")
        ids = [f.id for f in view.history]
        return Result(text, effects=[self._note(f"looked up {label}", ids)])

    async def _owed(self) -> Result:
        rows = await self._ask(lambda m: m.owed(self.deal_id), "owed")
        if not rows:
            return Result(tuning.NO_MEMORY if not self.memory() else tuning.NOT_ON_RECORD.format(what="payments"))
        lines = []
        for row in rows:
            if row.agreed_rupees is None:
                lines.append(f"{tuning.LABEL[row.item]}: no figure agreed; paid {row.paid_rupees:,} rupees.")
            else:
                lines.append(f"{tuning.LABEL[row.item]}: agreed {row.agreed_rupees:,}, paid {row.paid_rupees:,}, "
                             f"still owed {row.owed_rupees:,} rupees (payment facts: {', '.join(row.payment_fact_ids) or 'none'}).")
        return Result(" ".join(lines), effects=[self._note("worked out what is owed")])

    async def _search_facts(self, query: str) -> Result:
        found = await self._ask(lambda m: m.search(self.deal_id, str(query), k=tuning.SEARCH_K), "search")
        if not found:
            return Result(tuning.NO_MEMORY if not self.memory() else tuning.NOT_ON_RECORD.format(what=f"'{moments.clean(query)}'"),
                          effects=[self._note(f"searched '{moments.clean(query)[:40]}': nothing")])
        for f in found:
            self.facts.setdefault(f.id, f)
        return Result(" ".join(moments.fact(f, self.names) for f in found),
                      effects=[self._note(f"searched '{moments.clean(query)[:40]}': {len(found)} found", [f.id for f in found])])

    async def _play_clip(self, fact_id: str) -> Result:
        wav = await self._ask(lambda m: m.clip(str(fact_id)), f"clip {fact_id}")
        pcm = _pcm(wav) if wav else None
        if not pcm:
            return Result(tuning.NO_CLIP.format(fact=fact_id))
        seconds = len(pcm) / 2 / tuning.RATE
        pad = bytes(tuning.RATE * tuning.CLIP_PAD_MS // 1000 * 2)
        return Result(
            tuning.CLIP_PLAYING.format(fact=fact_id, seconds=seconds, then=tuning.CLIP_THEN), clip=pad + pcm + pad,
            clip_fact_id=str(fact_id), effects=[self._note("played the clip of what was said", [str(fact_id)])],
        )

    # ---- changes ----

    async def _propose_change(self, fact_id: str, new_value: str, proposed_by: str, said: str = "") -> Result:
        old = await self._fact(str(fact_id))
        if old is None:
            return Result(tuning.UNKNOWN_FACT.format(fact=fact_id))
        event = FactChanged(
            deal_id=self.deal_id, fact_id=old.id, new_value=moments.clean(new_value), item=old.item,
            proposed_by=Role(proposed_by), said=moments.clean(said) or None,
        )
        last = max((line.line_no or 0 for line in self.lines), default=0)
        self.changes[event.change_id] = _Change(event, old.value or old.text, after_line=last)
        label = tuning.LABEL.get(old.item, "the term") if old.item else "the term"
        return Result(
            tuning.PROPOSED.format(change=event.change_id, item=label, old=old.value or old.text, new=event.new_value,
                                   both=self.names.to(None)),
            effects=[event, self._note(f"proposed a change to {label}: {event.new_value}", [old.id])],
        )

    async def _confirm_change(self, change_id: str, person: str, agrees: bool, said: str = "") -> Result:
        change = self.changes.get(str(change_id))
        if change is None or change not in self.open_changes():
            return Result(tuning.NO_CHANGE.format(change=change_id))
        role = Role(person)
        name, other = self.names.of(role), self.names.of(role.other)
        heard = [line for line in self.lines if line.speaker is role and (line.line_no or 0) > change.after_line]
        if not heard:
            return Result(tuning.NOT_HEARD.format(name=name))  # the model may not confirm for someone who has not spoken
        prior = change.event
        label = tuning.LABEL.get(prior.item, "the term") if prior.item else "the term"
        common = dict(change_id=prior.change_id, fact_id=prior.fact_id, new_value=prior.new_value, item=prior.item,
                      proposed_by=prior.proposed_by, said=moments.clean(said) or moments.clean(heard[-1].text))
        if not agrees:
            event = FactChanged(deal_id=self.deal_id, status=ChangeStatus.WITHDRAWN, confirmed_by=prior.confirmed_by, **common)
            output = tuning.WITHDRAWN.format(name=name, change=prior.change_id, old=change.old)
            note = f"{name} said no: the change to {label} is withdrawn"
        else:
            confirmed = sorted({*prior.confirmed_by, role}, key=list(Role).index)
            both = len(confirmed) == 2
            status = ChangeStatus.CONFIRMED_BOTH if both else ChangeStatus.CONFIRMED_ONE
            event = FactChanged(deal_id=self.deal_id, status=status, confirmed_by=confirmed, **common)
            if both:
                output = tuning.CONFIRMED_BOTH.format(change=prior.change_id, item=label, new=prior.new_value)
                note = f"both agreed: {label} is now {prior.new_value}"
            else:
                output = tuning.CONFIRMED_ONE.format(name=name, answer="yes", change=prior.change_id, other=other)
                note = f"{name} said yes to the change to {label}"
        change.event = event  # the next answer builds on this one, even before it is sent
        return Result(output, effects=[event, self._note(note, [prior.fact_id])])

    async def _stay_silent(self, reason: str = "") -> Result:
        return Result(tuning.SILENT, silent=True)


def _latest(history: list[Fact]) -> list[Fact]:
    """Each fact as it stands now, oldest first."""
    latest: dict[str, Fact] = {}
    for f in history:
        latest[f.id] = f
    return list(latest.values())


def _pcm(wav: bytes) -> bytes | None:
    """A WAV file as the room's audio: 24 kHz, 16-bit, mono, at most CLIP_MAX_S long."""
    try:
        with wave.open(io.BytesIO(wav), "rb") as w:
            rate, channels, width = w.getframerate(), w.getnchannels(), w.getsampwidth()
            raw = w.readframes(w.getnframes())
    except (wave.Error, EOFError):
        return None
    if width != 2 or not raw:
        return None
    samples = np.frombuffer(raw, dtype=np.int16).astype(np.float64)
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)
    if rate != tuning.RATE:
        samples = np.interp(np.arange(0, len(samples) - 1, rate / tuning.RATE), np.arange(len(samples)), samples)
    samples = samples[: int(tuning.CLIP_MAX_S * tuning.RATE)]
    return np.clip(samples, -32768, 32767).astype(np.int16).tobytes()
