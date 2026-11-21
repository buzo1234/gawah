"""Plays speech into the room at the speed it is spoken, and can be cut off.

The model sends speech far faster than it is spoken, so it lands here first. One
utterance at a time: begin(), feed() as audio arrives, finish() when no more is coming.
Then done is set when the last of it has been heard, or at once on stop().
"""

import asyncio
import time
from typing import Protocol

from app.mouth import tuning


class Seat(Protocol):
    async def play(self, pcm: bytes) -> None: ...
    def queued_ms(self) -> float: ...
    def clear(self) -> None: ...
    async def played_out(self) -> None: ...


class Player:
    def __init__(self, seat: Seat) -> None:
        self.seat = seat
        self.active = False  # an utterance is being played
        self.cut = False  # the last utterance was stopped before its end
        self.done = asyncio.Event()
        self.done.set()
        self.given_ms = 0.0  # handed to the room in this utterance
        self.heard_ms = 0.0  # of that, how much was heard (the rest was dropped on stop)
        self.dry_ms = 0.0  # time spent mid-utterance with nothing to play: the model fell behind
        self.started_at: float | None = None  # time.monotonic() of the first frame
        self.ended_at: float | None = None
        self._buf = bytearray()
        self._no_more = False
        self._wake = asyncio.Event()

    def begin(self) -> None:
        self._buf.clear()
        self.active, self.cut, self._no_more = True, False, False
        self.given_ms = self.heard_ms = self.dry_ms = 0.0
        self.started_at = self.ended_at = None
        self.done.clear()
        self._wake.set()

    def feed(self, pcm: bytes) -> None:
        if self.active:
            self._buf.extend(pcm)
            self._wake.set()

    def finish(self) -> None:
        self._no_more = True
        self._wake.set()

    def heard_so_far(self) -> float:
        return max(0.0, self.given_ms - self.seat.queued_ms())

    def stop(self) -> None:
        """Go silent now."""
        if not self.active:
            return
        self.heard_ms = self.heard_so_far()
        self._buf.clear()
        self.seat.clear()
        self.cut = True
        self._end()

    def _end(self) -> None:
        self.active = False
        self.ended_at = time.monotonic()
        self.done.set()

    async def run(self) -> None:
        """The one task that feeds the room. Runs for the whole call."""
        size = tuning.FRAME_BYTES
        while True:
            await self._wake.wait()
            if not self.active:
                self._wake.clear()
            elif len(self._buf) >= size or (self._buf and self._no_more):
                frame = bytes(self._buf[:size]).ljust(size, b"\0")
                del self._buf[:size]
                if self.started_at is None:
                    self.started_at = time.monotonic()
                await self.seat.play(frame)
                if self.active:
                    self.given_ms += tuning.FRAME_MS
            elif self._no_more:
                await self.seat.played_out()
                if self.active:
                    self.heard_ms = self.given_ms
                    self._end()
            else:
                self._wake.clear()
                if self.started_at is not None:
                    dry = time.monotonic()
                    await self._wake.wait()
                    # The room still holds a little, so only the part beyond that was silence.
                    self.dry_ms += max(0.0, (time.monotonic() - dry) * 1000 - tuning.ROOM_QUEUE_MS)
