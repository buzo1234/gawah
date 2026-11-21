"""Who is talking, from the loudness of each person's own audio track. No model.

One call to hear() per 20 ms frame, so every length here is counted in frames of audio,
not on a clock.
"""

import math
from dataclasses import dataclass

import numpy as np

from app.mouth import tuning


def frame_db(pcm: bytes) -> float:
    """Loudness of one frame of 16-bit audio, in dB below full scale (-90 is silence)."""
    samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float64)
    rms = math.sqrt(float(np.mean(samples * samples))) if len(samples) else 0.0
    return 20 * math.log10(max(rms, 1.0) / 32768)


@dataclass
class _Person:
    voiced: int = 0  # frames in a row above SPEECH_DB
    quiet_ms: float = 0.0  # since the last voiced frame
    talking: bool = False
    loud: int = 0  # frames in a row above BARGE_DB
    may_cut_in: bool = True


class Hearing:
    def __init__(self) -> None:
        self.people: dict[str, _Person] = {}

    def in_pause(self) -> bool:
        return not any(p.talking for p in self.people.values())

    def talking(self) -> list[str]:
        return [who for who, p in self.people.items() if p.talking]

    def forget(self, who: str) -> None:
        self.people.pop(who, None)

    def gawah_starts(self) -> None:
        """Gawah is about to speak. Someone already talking cannot cut it off by simply
        carrying on: that is Gawah speaking over them, and they have to pause first."""
        for p in self.people.values():
            p.may_cut_in = not p.talking
            p.loud = 0

    def hear(self, who: str, db: float, gawah_ms: float | None = None) -> bool:
        """One frame from one person. gawah_ms is how long Gawah has been speaking, or None
        if it is silent. True when this frame is the one that cuts Gawah off."""
        p = self.people.setdefault(who, _Person())
        if db > tuning.SPEECH_DB:
            p.voiced += 1
            p.quiet_ms = 0.0
            if p.voiced >= tuning.START_FRAMES:
                p.talking = True
        else:
            p.voiced = 0
            p.quiet_ms += tuning.FRAME_MS
            if p.quiet_ms >= tuning.PAUSE_MS:
                p.talking = False
        if gawah_ms is None:
            return False
        if not p.may_cut_in and p.quiet_ms >= tuning.BARGE_REARM_MS:
            p.may_cut_in = True
        p.loud = p.loud + 1 if db > tuning.BARGE_DB else 0
        return p.may_cut_in and p.loud >= tuning.BARGE_FRAMES and gawah_ms >= tuning.BARGE_HOLDOFF_MS
