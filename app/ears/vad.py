"""Finds where one person's spoken line starts and ends.

We do this ourselves because OpenAI's end-of-speech detection invented words in the
spike. A frame counts as voice only when two things agree:

- WebRTC's voice detector (the webrtcvad package) says it is speech, and
- it is louder than this person's own background, measured in the voice band (500-3400 Hz).

Neither is enough alone. Loudness alone called a silent room "speaking": a laptop
microphone sits at -41 to -54 dB with spikes to -26 dB from small sounds. The WebRTC
detector alone called a third of that same silent room speech.
"""

from collections import deque
from dataclasses import dataclass

import numpy as np
import webrtcvad

RATE = 16000
FRAME_SECONDS = 0.02
FRAME_BYTES = int(RATE * FRAME_SECONDS) * 2

END_SILENCE = 1.0  # this much quiet ends a line; people pause up to 0.9 s between two sentences
MIN_VOICED = 0.24  # a line with less voiced sound than this is a click or a knock, not words
QUIET_LINE = -36.0  # a line that never gets this loud (voice band, dB) is a small room sound
LONG_LINE = 12.0  # after this long, a shorter pause ends the line
LONG_LINE_SILENCE = 0.3
MAX_LINE = 20.0  # never hold a line longer than this
PRE_ROLL = 0.2  # sound kept before the first voiced frame, so the first consonant is not cut
TAIL = 0.2  # sound kept after the last voiced frame
START_FRAMES = 3  # voiced frames in a row that start a line

START_MODE, KEEP_MODE = 3, 2  # webrtcvad strictness, 0-3: strict to start a line, looser to keep it
START_MARGIN = 8.0  # dB above the background that starts a line and counts as voiced
KEEP_MARGIN = 3.0  # dB above the background that keeps a line open
SMOOTH_FRAMES = 5  # loudness is averaged over this many frames; background noise flickers
FLOOR_RISE = 1.5  # dB a second the background estimate may climb; it falls at once
QUIETEST = -55.0  # the background is never taken to be quieter than this
DEAD = -70.0  # quieter than any live microphone: a muted or absent track, not background

_freqs = np.fft.rfftfreq(FRAME_BYTES // 2, 1 / RATE)
_BAND = (_freqs >= 500) & (_freqs <= 3400)


def band_power(pcm: bytes) -> float:
    """Mean square of one frame, counting only the voice band."""
    samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float64)
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
    peak: float  # the loudest it got, in dB

    @property
    def is_noise(self) -> bool:
        return self.voiced < MIN_VOICED or self.peak < QUIET_LINE


class Segmenter:
    """Feed it one person's 20 ms frames in order; it hands back each finished line.
    One per person: the background level and the detector's own noise model are theirs."""

    def __init__(self) -> None:
        self.floor: float | None = None  # this person's background loudness, in dB
        self._start_vad, self._keep_vad = webrtcvad.Vad(START_MODE), webrtcvad.Vad(KEEP_MODE)
        self._powers: deque[float] = deque(maxlen=SMOOTH_FRAMES)
        self._recent: deque[bytes] = deque(maxlen=int(PRE_ROLL / FRAME_SECONDS) + START_FRAMES)
        self._frames: list[bytes] = []
        self._speaking = False
        self._run = 0  # voiced frames in a row
        self._keep_run = 0  # frames in a row loud enough to keep a line open
        self._start = self._last_voiced = self._next_at = 0.0
        self._voiced = 0
        self._peak = DEAD
        self._since_voiced = 0  # frames taken since the last voiced one

    @property
    def speaking(self) -> bool:
        return self._speaking

    def feed(self, pcm: bytes, at: float) -> Line | None:
        """Take one frame that starts `at` seconds into the call."""
        if len(pcm) != FRAME_BYTES:
            raise ValueError(f"a frame must be {FRAME_BYTES} bytes, got {len(pcm)}")
        finished = None
        if self._speaking and at - self._next_at >= LONG_LINE_SILENCE:
            finished = self._close()  # the audio stopped arriving: the person dropped
        self._next_at = at + FRAME_SECONDS

        self._powers.append(band_power(pcm))
        level = db(sum(self._powers) / len(self._powers))
        live = level > DEAD  # a muted track is digital silence: not speech, and not background
        if live:
            # The background is the quietest the microphone has been lately: speech always
            # dips back to it between words, and steady noise pulls it up within seconds.
            rise = FLOOR_RISE * FRAME_SECONDS
            floor = level if self.floor is None else min(level, self.floor + rise)
            self.floor = max(QUIETEST, floor)
        over = level - self.floor if live else 0.0
        # A click is one loud frame, and averaging smears it over five. To count, a frame
        # must also be loud by itself, and a line is only kept open by two such frames in a
        # row. So clicks neither add up to a line nor hold a finished one open.
        alone = db(self._powers[-1]) - self.floor if live else 0.0
        # Both detectors hear every frame, so each keeps its own picture of the noise.
        starts = self._start_vad.is_speech(pcm, RATE) and min(over, alone) > START_MARGIN
        keeps = self._keep_vad.is_speech(pcm, RATE) and min(over, alone) > KEEP_MARGIN
        self._keep_run = self._keep_run + 1 if keeps else 0
        self._run = self._run + 1 if starts else 0

        if not self._speaking:
            self._recent.append(pcm)
            if self._run >= START_FRAMES:
                self._speaking = True
                self._start = at - (START_FRAMES - 1) * FRAME_SECONDS
                self._frames = list(self._recent)
                self._recent.clear()
                self._voiced, self._since_voiced, self._peak = START_FRAMES, 0, level
                self._last_voiced = self._next_at
            return finished

        self._frames.append(pcm)
        self._since_voiced += 1
        self._voiced += starts
        self._peak = max(self._peak, level)
        if self._keep_run >= 2:
            self._last_voiced, self._since_voiced = self._next_at, 0
        quiet = self._since_voiced * FRAME_SECONDS
        length = self._next_at - self._start
        if quiet >= END_SILENCE or (length >= LONG_LINE and quiet >= LONG_LINE_SILENCE) or length >= MAX_LINE:
            return self._close()
        return finished

    def flush(self) -> Line | None:
        """The call is ending, or the person has left: hand back the line being spoken, if any."""
        return self._close() if self._speaking else None

    def _close(self) -> Line:
        extra = max(0, self._since_voiced - int(TAIL / FRAME_SECONDS))
        frames = self._frames[: len(self._frames) - extra]
        line = Line(self._start, self._last_voiced, b"".join(frames), self._voiced * FRAME_SECONDS, self._peak)
        self._speaking, self._frames, self._run = False, [], 0
        return line
