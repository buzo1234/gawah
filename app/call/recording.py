"""One person's audio as a wav file on the call's timeline.

The file starts at time zero (the moment call.started was sent) and has silence wherever
the person was not in the room, so a time in the transcript is the same time in the file.
"""

import wave
from pathlib import Path

from app.ears.vad import RATE

GAP = 0.5  # audio this far behind the clock means the person was away, not that frames ran late


class Recording:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._wav = wave.open(str(path), "wb")
        self._wav.setnchannels(1)
        self._wav.setsampwidth(2)
        self._wav.setframerate(RATE)
        self._samples = 0

    @property
    def seconds(self) -> float:
        return self._samples / RATE

    def write(self, pcm: bytes, now: float) -> float:
        """Add audio that arrived `now` seconds into the call. Returns where it starts in the file."""
        began = now - len(pcm) / 2 / RATE  # a frame arrives when its last sample has been heard
        if began - self.seconds > GAP:
            self._silence(began)
        at = self.seconds
        self._wav.writeframes(pcm)
        self._samples += len(pcm) // 2
        return at

    def close(self, duration: float) -> None:
        """Pad with silence to the call's full length and finish the file."""
        self._silence(duration)
        self._wav.close()

    def _silence(self, until: float) -> None:
        missing = round(until * RATE) - self._samples
        if missing > 0:
            self._wav.writeframes(bytes(missing * 2))
            self._samples += missing
