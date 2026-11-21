"""One call's ears: each person's audio in, transcript.line events out.

Lines are numbered and published in the order they ended, across both people. A line
that is still being transcribed holds back the ones behind it, for at most the
transcriber's timeout; a line that fails is logged and skipped.
"""

import asyncio
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from app.bus import Bus
from app.contracts import Role, TranscriptLine
from app.ears.vad import Line, Segmenter
from app.log import deal_log

Transcribe = Callable[[bytes], Awaitable[str]]


@dataclass
class _Waiting:
    speaker: Role
    line: Line
    text: str | None = None
    done: bool = False


def has_words(text: str) -> bool:
    return any(ch.isalnum() for ch in text)


class Ears:
    def __init__(self, deal_id: str, bus: Bus, transcribe: Transcribe, clock: Callable[[], float]) -> None:
        """clock gives seconds since the call started, the same timeline the audio is on."""
        self.deal_id, self.bus, self._transcribe, self._clock = deal_id, bus, transcribe, clock
        self.log = deal_log("gawah.ears", deal_id)
        self.delays: list[float] = []  # seconds from a line's last word to its event
        self._segmenters = {role: Segmenter() for role in Role}
        self._waiting: deque[_Waiting] = deque()
        self._tasks: set[asyncio.Task] = set()
        self._line_no = 0

    def hear(self, speaker: Role, pcm: bytes, at: float) -> None:
        """One frame of one person's audio, starting `at` seconds into the call."""
        line = self._segmenters[speaker].feed(pcm, at)
        if line:
            self._take(speaker, line)

    def forget(self, speaker: Role) -> None:
        """This person has left. Publish what they were in the middle of saying and keep
        nothing else of theirs: if they come back, their background is learnt afresh."""
        line = self._segmenters[speaker].flush()
        if line:
            self._take(speaker, line)
        self._segmenters[speaker] = Segmenter()

    async def finish(self) -> None:
        """The call is over: close any line being spoken and wait for the last texts."""
        for speaker, segmenter in self._segmenters.items():
            line = segmenter.flush()
            if line:
                self._take(speaker, line)
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

    def _take(self, speaker: Role, line: Line) -> None:
        if line.is_noise:
            self.log.info("dropped %.2fs of noise from %s at %.1fs", line.voiced, speaker.value, line.start)
            return
        waiting = _Waiting(speaker, line)
        self._waiting.append(waiting)
        task = asyncio.create_task(self._text(waiting))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _text(self, waiting: _Waiting) -> None:
        try:
            waiting.text = await self._transcribe(waiting.line.pcm)
        except Exception as e:
            self.log.warning(
                "lost the line from %s at %.1f-%.1fs: transcription failed (%s)",
                waiting.speaker.value, waiting.line.start, waiting.line.end, type(e).__name__,
            )
        waiting.done = True
        while self._waiting and self._waiting[0].done:
            self._publish(self._waiting.popleft())

    def _publish(self, waiting: _Waiting) -> None:
        line = waiting.line
        if not waiting.text or not has_words(waiting.text):
            if waiting.text is not None:
                self.log.info("dropped a line with no words from %s at %.1fs", waiting.speaker.value, line.start)
            return
        self._line_no += 1
        delay = self._clock() - line.end
        self.delays.append(delay)
        self.log.info(
            "line %d %s %.1f-%.1fs, published %.2fs after it ended",
            self._line_no, waiting.speaker.value, line.start, line.end, delay,
        )
        self.bus.publish(TranscriptLine(
            deal_id=self.deal_id, speaker=waiting.speaker, text=waiting.text,
            start=round(line.start, 2), end=round(line.end, 2), line_no=self._line_no,
        ))
