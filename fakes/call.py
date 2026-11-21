"""Fake call: publishes what bridge would publish during a call."""

from app.bus import Bus
from app.contracts import CallEnded, CallKind, CallStarted, Person, Role, TranscriptLine
from fakes import RAMESH, SUNITA


def start_call(
    bus: Bus, deal_id: str, people: list[Person] | None = None, kind: CallKind = CallKind.DEAL
) -> CallStarted:
    event = CallStarted(deal_id=deal_id, people=people or [SUNITA, RAMESH], kind=kind, room=f"fake-{deal_id}")
    bus.publish(event)
    return event


def say(
    bus: Bus, deal_id: str, speaker: Role, text: str, start: float = 0.0, end: float | None = None,
    line_no: int | None = None,
) -> TranscriptLine:
    event = TranscriptLine(
        deal_id=deal_id, speaker=speaker, text=text, start=start,
        end=start + 2.0 if end is None else end, line_no=line_no,
    )
    bus.publish(event)
    return event


def end_call(
    bus: Bus, deal_id: str, people: list[Person] | None = None, kind: CallKind = CallKind.DEAL,
    duration: float | None = None,
) -> CallEnded:
    event = CallEnded(
        deal_id=deal_id, people=people or [SUNITA, RAMESH], kind=kind, room=f"fake-{deal_id}",
        duration=duration, reason="fake",
    )
    bus.publish(event)
    return event
