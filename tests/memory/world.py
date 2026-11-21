"""The memory stream's test world: a scripted Scribe model, word-hash embeddings, and
calls whose recordings are written as tones, one pitch per person."""

import math
import wave
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.bus import Bus
from app.contracts import (
    CallEnded, CallStarted, Event, Fact, FactConflict, FactRecorded, Person, Role, TranscriptLine,
)
from app.memory import Memory
from app.memory.vectors import WordHashEmbedder

DEAL = "d-mem"
DAY1 = datetime(2026, 11, 21, 10, 0, tzinfo=UTC)
PEOPLE = [Person(role=Role.HIRER, name="Sunita"), Person(role=Role.WORKER, name="Ramesh")]
RATE = 16000


def claim(item, stance="state", rupees=None, quote="", text=None, kind="term", value=None, date=None,
          accepts_line=None, contradicts=None) -> dict:
    """One claim in the shape the Scribe's model returns it."""
    return {
        "item": item, "kind": kind, "stance": stance, "text": text or f"The {item} is {value or rupees}.",
        "value": value or (f"{rupees:,} rupees" if rupees is not None else None), "rupees": rupees,
        "date": date, "quote": quote, "accepts_line": accepts_line, "contradicts": contradicts,
    }


class ScriptedExtractor:
    """Answers by the words of the line, like the recorded replies; unknown lines get none."""

    def __init__(self, script: dict[str, list[dict]]) -> None:
        self.script = script
        self.asked: list[str] = []

    async def claims(self, request) -> list[dict] | None:
        self.asked.append(request.line.text)
        return self.script.get(request.line.text, [])


def write_tone(path: Path, seconds: float, hz: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frames = bytearray()
    for i in range(int(seconds * RATE)):
        frames += int(8000 * math.sin(2 * math.pi * hz * i / RATE)).to_bytes(2, "little", signed=True)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(RATE)
        wav.writeframes(bytes(frames))


class World:
    def __init__(self, bus: Bus, tmp_path: Path, script: dict[str, list[dict]] | None = None) -> None:
        self.bus, self.tmp = bus, tmp_path
        self.extractor = ScriptedExtractor(script or {})
        self.embedder = WordHashEmbedder()
        self.memory = Memory(bus, self.extractor, self.embedder, root=tmp_path, cache_dir=tmp_path / "cache", embed_model="hash")
        self.memory.attach(bus)
        self.events: list[Event] = []

        async def keep(event: Event) -> None:
            self.events.append(event)

        bus.subscribe_all(keep)

    async def settle(self) -> None:
        for _ in range(3):
            await self.bus.drain()
            await self.memory.settle()
        await self.bus.drain()

    async def send(self, *events: Event) -> None:
        for event in events:
            self.bus.publish(event)
        await self.settle()

    async def call(self, lines: list[tuple[Role, str]], call_no: int = 1, at: datetime = DAY1) -> list[TranscriptLine]:
        """A whole deal call: each line 3 s long with 1 s between, then the two recordings."""
        sent = []
        self.bus.publish(CallStarted(deal_id=DEAL, people=PEOPLE, call_no=call_no, room=f"room-{call_no}", ts=at))
        for n, (role, text) in enumerate(lines, 1):
            line = TranscriptLine(
                deal_id=DEAL, speaker=role, text=text, start=1.0 + 4 * (n - 1), end=4.0 + 4 * (n - 1),
                line_no=n, call_no=call_no, ts=at + timedelta(seconds=4 * n),
            )
            sent.append(line)
            self.bus.publish(line)
        duration = 4.0 * len(lines) + 2
        keys = {}
        for role, hz in ((Role.HIRER, 440.0), (Role.WORKER, 220.0)):
            key = f"recordings/{DEAL}/{call_no}/{role.value}.wav"
            write_tone(self.tmp / key, duration, hz)
            keys[role.value] = key
        self.bus.publish(CallEnded(
            deal_id=DEAL, people=PEOPLE, call_no=call_no, duration=duration, recording_keys=keys,
            ts=at + timedelta(seconds=duration),
        ))
        await self.settle()
        return sent

    @property
    def versions(self) -> list[Fact]:
        return [e.fact for e in self.events if isinstance(e, FactRecorded)]

    @property
    def conflicts(self) -> list[FactConflict]:
        return [e for e in self.events if isinstance(e, FactConflict)]

    def fact_from_line(self, call_no: int, line_no: int) -> Fact:
        return next(f for f in reversed(self.versions) if (f.call_no, f.line_no) == (call_no, line_no))
