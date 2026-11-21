"""Finds where one person's spoken line starts and ends, from loudness alone.

We do this ourselves because OpenAI's end-of-speech detection invented words in the
spike. Loudness is measured in the voice band only (500-3400 Hz): laptop and phone
microphones carry hum and rumble below that which is as loud as quiet speech.
"""

from collections import deque
from dataclasses import dataclass

import numpy as np

RATE = 16000
FRAME_SECONDS = 0.02
FRAME_BYTES = int(RATE * FRAME_SECONDS) * 2

END_SILENCE = 0.6  # this much quiet ends a line
MIN_VOICED = 0.24  # a line with less voiced sound than this is a click or a knock, not words
LONG_LINE = 12.0  # after this long, a shorter pause ends the line
LONG_LINE_SILENCE = 0.3
MAX_LINE = 20.0  # never hold a line longer than this
PRE_ROLL = 0.2  # sound kept before the first voiced frame, so the first consonant is not cut
TAIL = 0.2  # sound kept after the last voiced frame
START_FRAMES = 3  # voiced frames in a row that start a line

SMOOTH_FRAMES = 5  # loudness is averaged over this many frames; background noise flickers
START_MARGIN = 12.0  # dB above the background that starts a line and counts as voiced
KEEP_MARGIN = 6.0  # dB above the background that keeps a line open
FLOOR_RISE = 1.5  # dB a second the background estimate may climb; it falls at once
QUIETEST = -55.0  # the background is never taken to be quieter than this
DEAD = -70.0  # quieter than any live microphone: a muted or absent track, not background

_freqs = np.fft.rfftfreq(FRAME_BYTES // 2, 1 / RATE)
_BAND = (_freqs >= 500) & (_freqs <= 3400)


def band_power(pcm: bytes) -> float:
    """Mean square of one frame, counting only the voice band."""
    samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float64)
    if len(samples) != FRAME_BYTES // 2:
        return float(np.mean(samples * samples)) if len(samples) else 0.0
    spectrum = np.abs(np.fft.rfft(samples)) ** 2
    return 2 * float(spectrum[_BAND].sum()) / len(samples) ** 2


def db(power: float) -> float:
    return 10 * float(np.log10(max(power, 1.0) / 32768**2))


@dataclass
class Line:
    start: float  # seconds on the call's timeline: the first voiced frame
    end: float  # the end of the last voiced frame
    pcm: bytes  # 16 kHz mono 16-bit, with a little sound kept either side
    voiced: float  # seconds of voiced sound in it

    @property
    def is_noise(self) -> bool:
        return self.voiced < MIN_VOICED


class Segmenter:
    """Feed it one person's frames in order; it hands back each finished line."""

    def __init__(self) -> None:
        self.floor: float | None = None  # the background's loudness, in dB
        self._powers: deque[float] = deque(maxlen=SMOOTH_FRAMES)
        self._recent: deque[tuple[float, bytes]] = deque(maxlen=int(PRE_ROLL / FRAME_SECONDS) + START_FRAMES)
        self._frames: list[bytes] = []
        self._speaking = False
        self._run = 0  # voiced frames in a row
        self._start = self._last_voiced = self._next_at = 0.0
        self._voiced = 0
        self._since_voiced = 0  # frames taken since the last voiced one

    @property
    def speaking(self) -> bool:
        return self._speaking

    def feed(self, pcm: bytes, at: float) -> Line | None:
        """Take one frame that starts `at` seconds into the call."""
        finished = None
        if self._speaking and at - self._next_at >= LONG_LINE_SILENCE:
            finished = self._close()  # the audio stopped arriving: the person dropped
        self._next_at = at + FRAME_SECONDS

        self._powers.append(band_power(pcm))
        level = db(sum(self._powers) / len(self._powers))
        if level > DEAD:
            # The background is the quietest the microphone has been lately: speech always
            # dips back to it between words, and steady noise pulls it up within seconds.
            rise = FLOOR_RISE * FRAME_SECONDS
            floor = level if self.floor is None else min(level, self.floor + rise)
            self.floor = max(QUIETEST, floor)
        over = level - self.floor if self.floor is not None and level > DEAD else 0.0
        loud = over > START_MARGIN
        self._run = self._run + 1 if loud else 0

        if not self._speaking:
            self._recent.append((at, pcm))
            if self._run >= START_FRAMES:
                self._speaking = True
                self._start = at - (START_FRAMES - 1) * FRAME_SECONDS
                self._frames = [frame for _, frame in self._recent]
                self._recent.clear()
                self._voiced, self._since_voiced = START_FRAMES, 0
                self._last_voiced = self._next_at
            return finished

        self._frames.append(pcm)
        self._since_voiced += 1
        self._voiced += loud
        if over > KEEP_MARGIN:
            self._last_voiced, self._since_voiced = self._next_at, 0
        quiet = self._since_voiced * FRAME_SECONDS
        length = self._next_at - self._start
        if quiet >= END_SILENCE or (length >= LONG_LINE and quiet >= LONG_LINE_SILENCE) or length >= MAX_LINE:
            return self._close()
        return finished

    def flush(self) -> Line | None:
        """The call is ending: hand back the line being spoken, if any."""
        return self._close() if self._speaking else None

    def _close(self) -> Line:
        extra = max(0, self._since_voiced - int(TAIL / FRAME_SECONDS))
        frames = self._frames[: len(self._frames) - extra]
        line = Line(self._start, self._last_voiced, b"".join(frames), self._voiced * FRAME_SECONDS)
        self._speaking, self._frames, self._run = False, [], 0
        return line
