"""Sounds for the mouth's tests, as 20 ms frames at 24 kHz: recorded speech from
fixtures/audio, the noise of a real room, clicks, and silence."""

import wave
from functools import cache
from pathlib import Path

import numpy as np

from app.mouth import tuning

AUDIO = Path(__file__).resolve().parents[2] / "fixtures" / "audio"
N = tuning.FRAME_BYTES // 2  # samples in a frame
LINES = sorted(p.name for p in AUDIO.glob("paint-*.wav"))


def level(db: float) -> float:
    return 32768 * 10 ** (db / 20)


@cache
def line(name: str = "paint-09.wav") -> np.ndarray:
    """One recorded line, resampled from 16 kHz to the room's 24 kHz."""
    with wave.open(str(AUDIO / name), "rb") as w:
        samples = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float64)
    return np.interp(np.arange(0, len(samples) - 1, 16000 / tuning.RATE), np.arange(len(samples)), samples)


def silence(seconds: float) -> np.ndarray:
    return np.zeros(int(tuning.RATE * seconds))


def room_noise(seconds: float, db: float = -40.0, seed: int = 1, hum: bool = True) -> np.ndarray:
    """Steady noise at a given loudness: hiss, weighted to the low end like a fan, with mains hum."""
    rng = np.random.default_rng(seed)
    n = int(tuning.RATE * seconds)
    white = rng.standard_normal(n)
    low = np.convolve(white, np.ones(24) / 24, mode="same")  # most of the energy below 1 kHz
    mix = 0.5 * white / white.std() + low / low.std()
    if hum:
        mix += 0.7 * np.sin(2 * np.pi * 50 * np.arange(n) / tuning.RATE)
    return mix / np.sqrt(np.mean(mix * mix)) * level(db)


def clicks(seconds: float, every: float = 0.7, seed: int = 2) -> np.ndarray:
    """Sharp sounds: a 2 ms tick near full scale, and a 40 ms key press, in turn."""
    rng = np.random.default_rng(seed)
    out = np.zeros(int(tuning.RATE * seconds))
    for i, at in enumerate(np.arange(0.3, seconds - 0.1, every)):
        start = int(at * tuning.RATE)
        if i % 2:
            length = int(0.040 * tuning.RATE)
            out[start:start + length] += rng.standard_normal(length) * level(-15) * np.exp(-np.arange(length) / (0.008 * tuning.RATE))
        else:
            length = int(0.002 * tuning.RATE)
            out[start:start + length] += level(-3) * np.sign(rng.standard_normal(length))
    return out


def frames(samples: np.ndarray) -> list[bytes]:
    pcm = np.clip(samples, -32768, 32767).astype(np.int16)
    return [pcm[i:i + N].tobytes() for i in range(0, len(pcm) - N + 1, N)]


def db_of(samples: np.ndarray) -> float:
    return 20 * np.log10(max(np.sqrt(np.mean(samples * samples)), 1.0) / 32768)


# --- What else a phone's microphone picks up while Gawah speaks (measure_hearing.py) ---

SAMPLES = AUDIO.parent


@cache
def recording(path: str) -> np.ndarray:
    """Any mono 16-bit WAV under fixtures/, at the room's 24 kHz."""
    with wave.open(str(SAMPLES / path), "rb") as w:
        rate = w.getframerate()
        samples = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float64)
    return np.interp(np.arange(0, len(samples) - 1, rate / tuning.RATE), np.arange(len(samples)), samples)


def at_db(samples: np.ndarray, db: float) -> np.ndarray:
    """Scaled so that its loud half sits at this level: speech is measured while it is speech."""
    frame_db = [db_of(samples[i:i + N]) for i in range(0, len(samples) - N, N)]
    loud = np.median([d for d in frame_db if d > np.percentile(frame_db, 50)])
    return samples * 10 ** ((db - loud) / 20)


def gawah(seconds: float) -> np.ndarray:
    """Gawah's own recorded voice, looped: what it plays into the room."""
    voice = np.concatenate([recording("mouth-samples/opening-line.wav"), recording("mouth-samples/term-read-back.wav")])
    return np.resize(voice, int(tuning.RATE * seconds))


def tv(seconds: float, db: float) -> np.ndarray:
    """Someone talking in the background without pause: a TV, or a voice in the next room."""
    voice = np.concatenate([line(n) for n in LINES[::-1]])
    return np.resize(at_db(voice, db), int(tuning.RATE * seconds))


def traffic(seconds: float, db: float, seed: int = 3) -> np.ndarray:
    """Road noise through a window: a low rumble that swells by 10 dB as each vehicle passes."""
    rng = np.random.default_rng(seed)
    n = int(tuning.RATE * seconds)
    white = rng.standard_normal(n)
    rumble = np.convolve(white, np.ones(80) / 80, mode="same")  # mostly below 300 Hz
    t = np.arange(n) / tuning.RATE
    swell = np.ones(n)
    for at in np.arange(1.0, seconds, 4.0) + rng.uniform(-1, 1, len(np.arange(1.0, seconds, 4.0))):
        swell += 2.2 * np.exp(-(((t - at) / 0.8) ** 2))  # a passing vehicle, about 10 dB over the rest
    out = rumble / rumble.std() * swell
    return out / np.sqrt(np.mean(out * out)) * level(db)


def door(db: float = -12.0, seed: int = 4) -> np.ndarray:
    """A door shutting: a low thump and a crack, gone in a third of a second."""
    rng = np.random.default_rng(seed)
    n = int(0.35 * tuning.RATE)
    t = np.arange(n) / tuning.RATE
    thump = np.sin(2 * np.pi * 90 * t) * np.exp(-t / 0.06)
    crack = rng.standard_normal(n) * np.exp(-t / 0.02)
    out = thump + 0.6 * crack
    return out / np.abs(out).max() * level(db + 3)


def cough(db: float = -18.0, seed: int = 5) -> np.ndarray:
    """A cough: two voiced bursts of breath, 180 and 120 ms, about as loud as speech close to the phone."""
    rng = np.random.default_rng(seed)
    parts = []
    for ms in (180, 120):
        n = int(ms / 1000 * tuning.RATE)
        t = np.arange(n) / tuning.RATE
        breath = np.convolve(rng.standard_normal(n), np.ones(6) / 6, mode="same")
        voiced = np.sign(np.sin(2 * np.pi * 140 * t)) * 0.4  # the vocal folds slapping shut
        envelope = (1 - np.exp(-t / 0.01)) * np.exp(-t / (ms / 3000))
        parts += [(breath / breath.std() + voiced) * envelope, np.zeros(int(0.08 * tuning.RATE))]
    out = np.concatenate(parts)
    return out / np.sqrt(np.mean(out[out != 0] ** 2)) * level(db)


def delayed(samples: np.ndarray, ms: float) -> np.ndarray:
    pad = np.zeros(int(tuning.RATE * ms / 1000))
    return np.concatenate([pad, samples])[: len(samples)]
