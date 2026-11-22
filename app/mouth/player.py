"""Plays speech into the room at the speed it is spoken, and can be cut off.

The model sends speech far faster than it is spoken, so it lands here first. One
utterance at a time: begin(), feed() as audio arrives, finish() when no more is coming.
Then done is set when the last of it has been heard, or at once on stop(). After a stop the
audio is kept until the next begin(), so resume() can carry on from where it was.
"""

import asyncio
import time
from collections import deque
from typing import Protocol

from app.mouth import tuning
from app.mouth.hearing import frame_db


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
        self.given_ms = 0.0  # how far into this utterance's audio the room has been handed
        self.heard_ms = 0.0  # of that, how much was heard (the rest was dropped on stop)
        self.dry_ms = 0.0  # time spent mid-utterance with nothing to play: the model fell behind
        self.started_at: float | None = None  # time.monotonic() of the first frame
        self.ended_at: float | None = None
        self._audio = bytearray()  # the whole utterance so far
        self._pos = 0  # bytes of it handed to the room
        self._no_more = False
        self._wake = asyncio.Event()
        self._played: deque[tuple[float, float]] = deque()  # (time.monotonic(), dB) of each frame handed over lately

    def begin(self) -> None:
        self._audio.clear()
        self._pos = 0
        self.active, self.cut, self._no_more = True, False, False
        self.given_ms = self.heard_ms = self.dry_ms = 0.0
        self.started_at = self.ended_at = None
        self.done.clear()
        self._wake.set()

    def feed(self, pcm: bytes) -> None:
        if self.active or self.cut:
            self._audio.extend(pcm)  # kept while stopped too, in case it resumes
            self._wake.set()

    def finish(self) -> None:
        self._no_more = True
        self._wake.set()

    def heard_so_far(self) -> float:
        return max(0.0, self.given_ms - self.seat.queued_ms())

    def loudness(self) -> float | None:
        """The loudest Gawah has played lately (ECHO_WINDOW_MS), in dB: what may come back as echo."""
        horizon = time.monotonic() - tuning.ECHO_WINDOW_MS / 1000
        while self._played and self._played[0][0] < horizon:
            self._played.popleft()
        return max((db for _, db in self._played), default=None)

    def audio(self) -> bytes:
        return bytes(self._audio)

    def stop(self) -> None:
        """Go silent now."""
        if not self.active:
            return
        self.heard_ms = self.heard_so_far()
        self.seat.clear()
        self.cut = True
        self._end()

    def resume(self, from_ms: float) -> None:
        """After a stop, play the same utterance again from this far into it."""
        if self.active:
            return
        frame = tuning.FRAME_BYTES
        self._pos = min(int(from_ms * tuning.RATE / 1000) * 2 // frame * frame, len(self._audio))
        self.given_ms = self._pos / 2 * 1000 / tuning.RATE
        self.active, self.cut = True, False
        self.done.clear()
        self._wake.set()

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
            elif (left := len(self._audio) - self._pos) >= size or (left > 0 and self._no_more):
                frame = bytes(self._audio[self._pos:self._pos + size]).ljust(size, b"\0")
                self._pos += size
                if self.started_at is None:
                    self.started_at = time.monotonic()
                self._played.append((time.monotonic(), frame_db(frame)))
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


def phrase_start(pcm: bytes, at_ms: float) -> float:
    """Where the phrase that was playing at at_ms began: the end of the last pause in the speech
    before it, less a little of that pause. The start of the utterance if there was none."""
    frame = tuning.FRAME_BYTES
    last = min(int(at_ms / tuning.FRAME_MS), len(pcm) // frame)
    quiet = 0
    for i in range(last - 1, -1, -1):
        if frame_db(pcm[i * frame:(i + 1) * frame]) < tuning.PHRASE_QUIET_DB:
            quiet += 1
            if quiet * tuning.FRAME_MS >= tuning.PHRASE_GAP_MS:
                end = i + quiet  # the first frame after this pause
                while end < last and frame_db(pcm[end * frame:(end + 1) * frame]) < tuning.PHRASE_QUIET_DB:
                    end += 1
                return max(0.0, end * tuning.FRAME_MS - tuning.RESUME_LEAD_MS)
        else:
            quiet = 0
    return 0.0
