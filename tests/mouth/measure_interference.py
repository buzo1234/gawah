"""What cuts Gawah off on the deal call, besides a person really speaking. No room, no cost.

    uv run python -m tests.mouth.measure_interference

Each case plays a minute of one person's microphone into the barge-in detector while Gawah
speaks the whole time, over a quiet room (-50 dB) the detector has already learned:
steady fan and traffic noise, a TV or a voice in the next room, a door, a cough, a short
"haan", and Gawah's own voice coming back from a phone on loudspeaker. Then the real thing:
each of the recorded lines spoken over Gawah, with its echo present, must still stop it.
"""

from dataclasses import dataclass

import numpy as np

from app.mouth import tuning
from app.mouth.hearing import Hearing, frame_db
from tests.mouth import sounds

ROOM_DB = -50.0
LEAD_S = 3.0  # the person's room, heard before Gawah starts
SECONDS = 60.0
EVERY_S = 4.0  # one short sound this often
BROWSER_GAIN_DB = 10.0  # what Chrome's gain control added to the recorded lines in the real-room check
ECHO_DELAY_MS = 150.0
ECHO_FRAMES = int(tuning.ECHO_WINDOW_MS / tuning.FRAME_MS)  # the phone's loudspeaker back into its microphone, through the network both ways


@dataclass
class Result:
    cuts: int  # times Gawah was cut off (for burst cases: sounds that cut it off)
    events: int  # short sounds played, or 1 for a minute of steady sound
    final: int  # of the cuts, those it did not carry on from


def gawah_level() -> np.ndarray:
    """Gawah's output, for an echo of it."""
    return sounds.gawah(LEAD_S + SECONDS)


def listen(track: np.ndarray, gawah: np.ndarray | None = None) -> list[tuple[int, bool]]:
    """Gawah speaks from LEAD_S on while this track plays. (frame, for good) for each time it was
    cut off. After a cut it waits as deal_call.py does: if the sound is over within RESUME_WITHIN_MS
    it carries on, else the stop is for good and it speaks again after the next pause."""
    hearing = Hearing()
    loudness = np.array([frame_db(f) for f in sounds.frames(gawah)]) if gawah is not None else None
    start = int(LEAD_S * 1000 / tuning.FRAME_MS)
    cuts: list[tuple[int, bool]] = []
    speaking_since: int | None = None
    cut_at: int | None = None  # waiting to see if the sound is over
    stopped = False  # for good: silent until a pause
    for i, frame in enumerate(sounds.frames(track)):
        if i == start:
            hearing.gawah_starts()
            speaking_since = i
        if speaking_since is None or cut_at is not None or stopped:
            hearing.hear("hirer", frame)
            if cut_at is not None and hearing.quiet_ms() >= tuning.RESUME_QUIET_MS:
                cuts.append((cut_at, False))
                cut_at = None
                hearing.gawah_starts()
            elif cut_at is not None and (i - cut_at) * tuning.FRAME_MS >= tuning.RESUME_WITHIN_MS:
                cuts.append((cut_at, True))
                cut_at, stopped = None, True
            elif stopped and hearing.in_pause():
                stopped = False
                hearing.gawah_starts()
            continue
        gawah_ms = (i - speaking_since) * tuning.FRAME_MS + 1000
        loud = loudness[max(0, i - ECHO_FRAMES): i + 1].max() if loudness is not None else None
        if hearing.hear("hirer", frame, gawah_ms, loud):
            cut_at = i
    if cut_at is not None:
        cuts.append((cut_at, True))
    return cuts


def room(seconds: float, db: float = ROOM_DB, seed: int = 1) -> np.ndarray:
    return sounds.room_noise(seconds, db, seed)


def echo(gawah: np.ndarray, loss_db: float) -> np.ndarray:
    """Gawah's voice coming back this many dB below what it played, a little late."""
    return sounds.delayed(gawah, ECHO_DELAY_MS) * 10 ** (-loss_db / 20)


def steady(sound: np.ndarray) -> Result:
    """A sound that is there before Gawah starts and stays: cuts per minute."""
    gawah = gawah_level()
    cuts = listen(room(LEAD_S + SECONDS) + sound[: len(gawah)], gawah)
    return Result(len(cuts), 1, sum(final for _, final in cuts))


def bursts(make, every: float = EVERY_S, seed: int = 0) -> Result:
    """A short sound every few seconds while Gawah speaks: how many of them cut it off."""
    gawah = gawah_level()
    track = room(LEAD_S + SECONDS, seed=seed + 1)
    starts = []
    for k, at in enumerate(np.arange(LEAD_S + 1.0, LEAD_S + SECONDS - 1.0, every)):
        sound = make(k)
        i = int(at * tuning.RATE)
        track[i:i + len(sound)] += sound[: len(track) - i]
        starts.append(int(at * 1000 / tuning.FRAME_MS))
    cuts = listen(track, gawah)
    hit = {next(s for s in reversed(starts) if s <= c) for c, _ in cuts if c >= starts[0]}
    final = {next(s for s in reversed(starts) if s <= c) for c, f in cuts if f and c >= starts[0]}
    return Result(len(hit), len(starts), len(final))


def switched_on(db: float) -> Result:
    """A fan switched on while Gawah speaks, then left on."""
    gawah = gawah_level()
    track = room(LEAD_S + SECONDS)
    on = int((LEAD_S + 5.0) * tuning.RATE)
    track[on:] += sounds.room_noise((len(track) - on) / tuning.RATE, db, seed=9)
    cuts = listen(track, gawah)
    return Result(len(cuts), 1, sum(final for _, final in cuts))


def interruption(name: str, gain_db: float, echo_loss_db: float | None) -> tuple[float, bool] | None:
    """A recorded line spoken over Gawah, 2 s after it starts. (ms from the line's first sound to the cut,
    whether the stop was for good), or None if it never cut Gawah off."""
    gawah = gawah_level()[: int((LEAD_S + 10) * tuning.RATE)]
    track = room(len(gawah) / tuning.RATE, seed=int(name[6:8]))
    if echo_loss_db is not None:
        track += echo(gawah, echo_loss_db)
    speech = sounds.line(name) * 10 ** (gain_db / 20)
    at = int((LEAD_S + 2.0) * tuning.RATE)
    track[at:at + len(speech)] += speech[: len(track) - at]
    first = at // sounds.N + next(i for i, f in enumerate(sounds.frames(speech)) if sounds.db_of(np.frombuffer(f, np.int16).astype(float)) > ROOM_DB + 6)
    after = [(c, final) for c, final in listen(track, gawah) if c >= first]
    return ((after[0][0] - first + 1) * tuning.FRAME_MS, after[0][1]) if after else None


def short_word(k: int, ms: int, gain_db: float = BROWSER_GAIN_DB) -> np.ndarray:
    """The first ms of a recorded line: a "haan ji", or "Gawah, ruko"."""
    speech = sounds.line(sounds.LINES[k % len(sounds.LINES)]) * 10 ** (gain_db / 20)
    voiced = next(i for i, f in enumerate(sounds.frames(speech)) if sounds.db_of(np.frombuffer(f, np.int16).astype(float)) > -40)
    return speech[voiced * sounds.N: voiced * sounds.N + int(tuning.RATE * ms / 1000)]


def cases() -> dict[str, Result]:
    n = int(tuning.RATE * (LEAD_S + SECONDS))
    gawah = gawah_level()
    out: dict[str, Result] = {}
    for db in (-45, -40, -35, -30):
        out[f"fan at {db} dB"] = steady(sounds.room_noise(LEAD_S + SECONDS, db, seed=11) + sounds.clicks(LEAD_S + SECONDS, 0.7, 12) * 0.1)
    for db in (-40, -35):
        out[f"traffic at {db} dB, vehicles passing"] = steady(sounds.traffic(LEAD_S + SECONDS, db))
    out["fan switched on mid-sentence, -35 dB"] = switched_on(-35.0)
    for db in (-45, -40, -35):
        out[f"TV or a voice nearby at {db} dB"] = steady(sounds.tv(LEAD_S + SECONDS, db))
    out["door shutting (-12 dB peak)"] = bursts(lambda k: sounds.door(seed=k))
    out["cough near the phone (-18 dB)"] = bursts(lambda k: sounds.cough(seed=k))
    out["cough at arm's length (-28 dB)"] = bursts(lambda k: sounds.cough(-28.0, seed=k))
    out["a short 'haan' (400 ms of a line)"] = bursts(lambda k: short_word(k, 400))
    for loss in (15, 20, 25, 30):
        out[f"Gawah's echo, {loss} dB down"] = steady(echo(gawah, loss)[:n])
    return out


def real(gain_db: float, echo_loss_db: float | None) -> list[tuple[float, bool]]:
    """(ms from the line's first sound to the cut, for good) for each line that cut Gawah off."""
    return [t for t in (interruption(name, gain_db, echo_loss_db) for name in sounds.LINES) if t is not None]


def summary(values: list[float]) -> str:
    if not values:
        return "never"
    return f"median {np.median(values):.0f}, 90% {np.percentile(values, 90):.0f}, max {max(values):.0f} ms"


def ruko(ms: int) -> tuple[int, int]:
    """Short commands, each alone over a quiet room: of the 24, how many cut Gawah off, and how many for good.
    (One it carries on from still stops it when its line arrives, if it says "ruko" or names Gawah.)"""
    gawah = gawah_level()
    cut = final = 0
    for k in range(len(sounds.LINES)):
        track = room(LEAD_S + 4.0, seed=k + 1)
        word = short_word(k, ms)
        at = int((LEAD_S + 1.0) * tuning.RATE)
        track[at:at + len(word)] += word
        cuts = listen(track, gawah[: len(track)])
        cut += bool(cuts)
        final += any(f for _, f in cuts)
    return cut, final


if __name__ == "__main__":
    print(f"cut-off: voice {tuning.BARGE_OVER_NOISE_DB:.0f} dB over the floor, at least {tuning.BARGE_MIN_DB:.0f} dB, for {tuning.BARGE_MS} ms")
    print(f"\nGawah speaking for a minute over each (room at {ROOM_DB:.0f} dB):")
    print(f"  (a cut-off it carries on from: everyone quiet {tuning.RESUME_QUIET_MS} ms within {tuning.RESUME_WITHIN_MS} ms of it)")
    for name, r in cases().items():
        what = f"{r.cuts} of {r.events} cut it off" if r.events > 1 else f"{r.cuts} cut-offs"
        print(f"  {name:42s} {what}, {r.final} for good")
    print("\nThe 24 recorded lines spoken over Gawah:")
    for label, gain, loss in (
        ("at a browser's gain, no echo", BROWSER_GAIN_DB, None),
        ("at a browser's gain, echo 20 dB down", BROWSER_GAIN_DB, 20.0),
        ("as recorded (10 dB quieter), echo 20 dB down", 0.0, 20.0),
    ):
        ok = real(gain, loss)
        print(f"  {label:46s} stopped {len(ok)} of 24 ({sum(f for _, f in ok)} for good), "
              f"first sound to stop: {summary([t for t, _ in ok])}")
    for ms in (600, 900, 1200):
        cut, final = ruko(ms)
        print(f"  only the first {ms} ms of each line ('Gawah, ruko'): cut off by {cut} of 24, {final} for good")
