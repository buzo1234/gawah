"""How the speech detector does on noise and on the recorded lines. No room, no cost.

    uv run python -m tests.mouth.measure_hearing

Prints false cut-offs on noise and clicks (target: none) and how long recorded speech
over noise takes to cut Gawah off. The tests in test_hearing.py assert the same numbers.
"""

import numpy as np

from app.mouth import tuning
from app.mouth.hearing import Hearing, frame_db
from tests.mouth import sounds

NOISES = {  # name -> (loudness of the steady noise, seconds between clicks)
    "noise at -40 dB, a click every 0.7 s": (-40.0, 0.7),
    "noise at -50 dB, a click every 0.7 s": (-50.0, 0.7),
    "noise at -33 dB, a click every 0.7 s": (-33.0, 0.7),
    "noise at -40 dB, a click every 0.15 s": (-40.0, 0.15),
}
BROWSER_GAIN_DB = 10.0  # what Chrome's gain control added to these recordings in the real-room check
LEAD_S = 2.0


def noisy(seconds: float, db: float = -40.0, every: float = 0.7, seed: int = 1) -> np.ndarray:
    return sounds.room_noise(seconds, db, seed) + sounds.clicks(seconds, every, seed + 10)


def on_noise(db: float, every: float, seconds: float = 60.0, seed: int = 1) -> tuple[int, float]:
    """Gawah speaking the whole time over noise and clicks: (cut-offs, seconds wrongly heard as talking)."""
    hearing, cuts, talking = Hearing(), 0, 0
    for frame in sounds.frames(noisy(seconds, db, every, seed)):
        if hearing.hear("worker", frame, gawah_ms=1000.0):
            cuts += 1
            hearing.people["worker"].over_ms = 0.0
        talking += not hearing.in_pause()
    return cuts, talking * tuning.FRAME_MS / 1000


def line_over_noise(name: str, gain_db: float = 0.0, noise_db: float = -40.0) -> tuple[np.ndarray, int, int]:
    """Two seconds of noise and clicks, then a recorded line on top of more of it.
    Returns the sound, and the frames at which the line's first sound and its end fall."""
    speech = sounds.line(name) * 10 ** (gain_db / 20)
    mix = noisy(LEAD_S + len(speech) / tuning.RATE + 2.0, noise_db, seed=int(name[6:8]))
    start = int(LEAD_S * tuning.RATE)
    mix[start:start + len(speech)] += speech
    first = next(i for i, f in enumerate(sounds.frames(speech)) if frame_db(f) > noise_db + 3)
    return mix, start // sounds.N + first, (start + len(speech)) // sounds.N


def cut_off_ms(name: str, gain_db: float = 0.0, noise_db: float = -40.0) -> tuple[float | None, bool]:
    """Gawah is speaking; the line starts. (ms from the line's first sound to the cut-off, cut before it started?)"""
    mix, first, _ = line_over_noise(name, gain_db, noise_db)
    hearing = Hearing()
    for i, frame in enumerate(sounds.frames(mix)):
        if hearing.hear("hirer", frame, gawah_ms=1000.0):
            return ((i - first + 1) * tuning.FRAME_MS, False) if i >= first else (None, True)
    return None, False


def talking_ms(name: str, gain_db: float = 0.0, noise_db: float = -40.0) -> tuple[float | None, float, float | None]:
    """Nobody else speaking. (ms to notice the line started, share of the line heard as talking,
    ms from the line's end to the pause)"""
    mix, first, end = line_over_noise(name, gain_db, noise_db)
    hearing, state = Hearing(), []
    for frame in sounds.frames(mix):
        hearing.hear("hirer", frame)
        state.append(not hearing.in_pause())
    noticed = next((i for i in range(first, end) if state[i]), None)
    paused = next((i for i in range(end, len(state)) if not state[i]), None)
    return (
        None if noticed is None else (noticed - first + 1) * tuning.FRAME_MS,
        sum(state[first:end]) / (end - first),
        None if paused is None else (paused - end) * tuning.FRAME_MS,
    )


def summary(values: list[float]) -> str:
    return f"min {min(values):.0f}, median {np.median(values):.0f}, 90% {np.percentile(values, 90):.0f}, max {max(values):.0f} ms"


if __name__ == "__main__":
    print(f"detector: webrtcvad mode {tuning.VAD_MODE}; cut-off needs {tuning.BARGE_MS} ms of voice {tuning.BARGE_OVER_NOISE_DB:.0f} dB over the floor")
    print("\nGawah speaking over noise, nobody talking (3 minutes of each):")
    for name, (db, every) in NOISES.items():
        results = [on_noise(db, every, 60.0, seed) for seed in (1, 2, 3)]
        print(f"  {name}: {sum(c for c, _ in results)} cut-offs, {sum(t for _, t in results):.1f} s heard as talking")
    for label, gain in (("as recorded (about 7 dB above the noise)", 0.0), (f"lifted {BROWSER_GAIN_DB:.0f} dB, as a browser's gain control does", BROWSER_GAIN_DB)):
        cuts = [cut_off_ms(name, gain) for name in sounds.LINES]
        times = [ms for ms, _ in cuts if ms is not None]
        heard = [talking_ms(name, gain) for name in sounds.LINES]
        print(f"\nThe {len(sounds.LINES)} recorded lines over noise at -40 dB with clicks, {label}:")
        print(f"  cut Gawah off: {len(times)} of {len(cuts)}, {sum(early for _, early in cuts)} before the line began; first sound to cut-off: {summary(times)}")
        print(f"  noticed as talking: {summary([n for n, _, _ in heard if n is not None])}; heard as talking for {100 * np.mean([s for _, s, _ in heard]):.0f}% of the line")
        print(f"  pause found after the line's end: {sum(p is not None for _, _, p in heard)} of {len(heard)}; {summary([p for _, _, p in heard if p is not None])}")
