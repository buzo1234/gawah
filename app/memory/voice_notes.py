"""A WhatsApp voice note, read by the Scribe like one line its sender said on a call.

The note is a line on its own: no lines before it, the deal's facts so far as context. Its
facts carry source voice_note, the note's key as media_url, no call or line number, and the
whole note as their span (start 0, end its length), so a fact's clip is the voice note
itself. A contradiction goes out with no call (fact.conflict call_no None), for the Sentinel
to answer on WhatsApp. Payments and work belong to records (app/records): a note that
became a record is not read here, and a payment or work claim from a note is dropped, so
one voice note is never two payment facts."""

import asyncio
import io
import logging
import subprocess
import time
import wave
from pathlib import Path

from app.contracts import (
    ChangeStatus, Fact, FactChanged, FactKind, FactSource, FactStatus, Role, TranscriptLine, VoiceNote,
)
from app.memory import echo
from app.memory.book import DealBook
from app.memory.claims import Claim
from app.memory.scribe import ORDER_WAIT_S, Scribe

log = logging.getLogger("gawah.memory")

VOICE_CALL = 0  # the call_no a note's line is read under: no deal call has it
OUT_RATE = 24000  # as clips.cut gives a call's clip


class VoiceScribe(Scribe):
    """The Scribe for one voice note: the same reading, the note's own source and span."""

    def __init__(self, memory, note: VoiceNote, tasks: set[asyncio.Task]) -> None:
        super().__init__(memory)
        self.note, self._tasks = note, tasks

    def _base(self, deal: DealBook, line: TranscriptLine, claim: Claim) -> dict:
        return super()._base(deal, line, claim) | dict(
            source=FactSource.VOICE_NOTE, media_url=self.note.media_key, call_no=None, line_no=None,
            start=0.0, end=line.end, valid_from=self.note.ts,
        )

    def _apply(self, deal: DealBook, line: TranscriptLine, claim: Claim, received: float) -> None:
        paid = claim.kind == FactKind.PAYMENT and not echo.promises_to_pay(claim.quote)
        if paid or claim.kind == FactKind.WORK:
            log.info("deal=%s voice note %s: %s claim left to the record", line.deal_id, self.note.message_id, claim.kind.value)
            return
        super()._apply(deal, line, claim, received)


class VoiceNotes:
    def __init__(self, memory) -> None:
        self.m = memory
        self._tasks: set[asyncio.Task] = set()
        self._tail: dict[str, asyncio.Future] = {}  # deal id -> the last note's "applied"
        self._count: dict[str, int] = {}

    async def on_note(self, note: VoiceNote) -> None:
        if note.record_id:
            return  # a payment or work record: memory has it from record.received
        deal = self.m.book.deal(note.deal_id)
        number = self._count[note.deal_id] = self._count.get(note.deal_id, 0) + 1
        line = TranscriptLine(
            deal_id=note.deal_id, ts=note.ts, speaker=note.speaker, text=note.text, start=0.0,
            end=note.seconds or 0.0, line_no=number, call_no=VOICE_CALL,
        )
        deal.call(VOICE_CALL).room = f"voice-{note.message_id}"
        self.m.vectors.want(self.m.line_text(line))
        previous, mine = self._tail.get(note.deal_id), asyncio.get_running_loop().create_future()
        self._tail[note.deal_id] = mine
        scribe = VoiceScribe(self.m, note, self._tasks)
        scribe._spawn(scribe._process(deal, line, previous, mine, time.monotonic()))
        self.m.note("scribe", f"voice note from {deal.name(note.speaker)} read as a line", line=line)

    async def settle(self) -> None:
        while pending := [t for t in self._tasks if not t.done()]:
            await asyncio.wait(pending, timeout=ORDER_WAIT_S * 2)


def is_voice(fact: Fact | None) -> bool:
    return fact is not None and fact.source is FactSource.VOICE_NOTE and bool(fact.media_url)


def asked_change(deal: DealBook, event: FactChanged) -> Fact | None:
    """The change fact a voice note made, that this fact.changed was put to the other person for."""
    old = deal.latest.get(event.fact_id)
    item = event.item or (old.item if old else None)
    asked = [
        f for f in deal.standing()
        if is_voice(f) and f.kind == FactKind.CHANGE and f.status == FactStatus.SAID and f.item == item
        and f.said_by == event.proposed_by
    ]
    return asked[-1] if asked else None


def settle_change(memory, deal: DealBook, event: FactChanged) -> dict:
    """A change asked by voice note, once answered: the asked fact is agreed (or disputed, on a
    no), and the new term keeps the voice note as its source and clip. Returns what the new
    term fact takes from it; empty for a change made on a call."""
    asked = asked_change(deal, event)
    if asked is None:
        return {}
    if event.status == ChangeStatus.WITHDRAWN:
        memory.record(asked.model_copy(update={"status": FactStatus.DISPUTED}))
        return {}
    memory.record(asked.model_copy(update={"status": FactStatus.AGREED, "agreed_by": [r for r in Role if r != asked.said_by]}))
    return dict(
        source=FactSource.VOICE_NOTE, media_url=asked.media_url, call_no=None, start=asked.start, end=asked.end,
        quote=asked.quote, said_by=asked.said_by,
    )


def whole(path: Path) -> bytes | None:
    """The whole voice note as 24 kHz mono WAV, as a call's clip is. None if it is not on disk."""
    if not path.is_file():
        return None
    done = subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-i", str(path), "-ar", str(OUT_RATE), "-ac", "1", "-f", "s16le", "-"],
        capture_output=True, timeout=30, check=False,
    )
    if done.returncode != 0 or not done.stdout:
        log.warning("could not read the voice note %s: %s", path.name, done.stderr.decode(errors="replace")[:200])
        return None
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(OUT_RATE)
        out.writeframes(done.stdout[: len(done.stdout) - len(done.stdout) % 2])
    return buffer.getvalue()
