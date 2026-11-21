"""Who is talking, from each person's own audio track.

Loudness alone does not work on a real microphone: a silent room sits at -41 to -54 dB
and small sounds go well above that. So a frame counts as voice only when a
voice-activity detector (WebRTC's, run locally, about 16 microseconds a frame) calls it
speech and it stands clear of that person's own noise floor. Talking is voice sustained
for a while, so a click, a key press or a cough is not talking.

One call to hear() per 20 ms frame, so every length here is counted in frames of audio,
not on a clock. A muted track delivers silence, or nothing; both are quiet.
"""

import math
from dataclasses import dataclass, field

import numpy as np
import webrtcvad

from app.mouth import tuning


def frame_db(pcm: bytes) -> float:
    """Loudness of one frame of 16-bit audio, in dB below full scale (-90 is silence)."""
    samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float64)
    rms = math.sqrt(float(np.mean(samples * samples))) if len(samples) else 0.0
    return 20 * math.log10(max(rms, 1.0) / 32768)


@dataclass
class _Person:
    detector: webrtcvad.Vad = field(default_factory=lambda: webrtcvad.Vad(tuning.VAD_MODE))
    floor: float = tuning.FLOOR_START_DB  # this person's background noise, in dB
    voice_ms: float = 0.0  # recent voice: up on a voiced frame, down on any other
    quiet_ms: float = 0.0  # since voice was last sustained
    talking: bool = False
    has_talked: bool = False
    over_ms: float = 0.0  # the same count, by the stricter rule used while Gawah speaks
    may_cut_in: bool = True


class Hearing:
    def __init__(self) -> None:
        self.people: dict[str, _Person] = {}

    def in_pause(self) -> bool:
        return not any(p.talking for p in self.people.values())

    def talking(self) -> list[str]:
        return [who for who, p in self.people.items() if p.talking]

    def since_voice_ms(self) -> float | None:
        """How long since anyone last sustained voice, in ms of their audio. None before anyone has talked."""
        quiet = [p.quiet_ms for p in self.people.values() if p.has_talked]
        return min(quiet) if quiet else None

    def forget(self, who: str) -> None:
        """They left, or their track was muted or ended: no frames may follow, so stop counting them."""
        self.people.pop(who, None)

    def gawah_starts(self) -> None:
        """Gawah is about to speak. Someone already talking cannot cut it off by simply
        carrying on: that is Gawah speaking over them, and they have to pause first."""
        for p in self.people.values():
            p.may_cut_in = not p.talking
            p.over_ms = 0.0

    def hear(self, who: str, pcm: bytes, gawah_ms: float | None = None) -> bool:
        """One frame from one person. gawah_ms is how long Gawah has been speaking, or None
        if it is silent. True when this frame is the one that cuts Gawah off."""
        p = self.people.setdefault(who, _Person())
        db = frame_db(pcm)
        # A muted track is digital silence. It is quiet, and it says nothing about the room, so
        # the detector and the floor are left as they were. Fed silence, both take it for the
        # room's noise, and the real noise counts as talking for seconds when it returns.
        muted = db < tuning.MUTED_DB or len(pcm) != tuning.FRAME_BYTES
        speech = not muted and p.detector.is_speech(_at_48k(pcm), 48000)
        voiced = speech and db > p.floor + tuning.SPEECH_OVER_NOISE_DB
        over = speech and db > max(p.floor + tuning.BARGE_OVER_NOISE_DB, tuning.BARGE_MIN_DB)
        # The floor drops to a quieter frame quickly and rises slowly, so the gaps between
        # words hold it down while someone talks, and steady noise is still learned in seconds.
        if muted:
            pass
        elif db < p.floor:
            p.floor += tuning.FLOOR_FALL * (db - p.floor)
        else:
            p.floor += tuning.FLOOR_CREEP_DB if speech else tuning.FLOOR_RISE_DB
        p.floor = min(max(p.floor, tuning.FLOOR_MIN_DB), tuning.FLOOR_MAX_DB)

        p.voice_ms = _count(p.voice_ms, voiced, tuning.START_MS)
        if p.voice_ms >= tuning.START_MS:
            p.talking, p.has_talked, p.quiet_ms = True, True, 0.0
        else:
            p.quiet_ms += tuning.FRAME_MS
            if p.quiet_ms >= tuning.PAUSE_MS:
                p.talking = False
        if gawah_ms is None:
            p.over_ms = 0.0
            return False
        if not p.may_cut_in and p.quiet_ms >= tuning.BARGE_REARM_MS:
            p.may_cut_in = True
        p.over_ms = _count(p.over_ms, over, tuning.BARGE_MS)
        return p.may_cut_in and p.over_ms >= tuning.BARGE_MS and gawah_ms >= tuning.BARGE_HOLDOFF_MS


def _count(ms: float, voiced: bool, full: float) -> float:
    """Voice has to be sustained: a voiced frame adds its length and any other takes part of
    one back, so the gaps inside a word do not reset the count and a lone click never fills it."""
    step = tuning.FRAME_MS if voiced else -tuning.FRAME_MS * tuning.SUSTAIN_LEAK
    return min(max(ms + step, 0.0), full)


def _at_48k(pcm: bytes) -> bytes:
    """The detector takes 8, 16, 32 or 48 kHz; the room gives us the model's 24 kHz."""
    return np.repeat(np.frombuffer(pcm, dtype=np.int16), 2).tobytes()
