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
