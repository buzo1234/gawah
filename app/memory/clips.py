"""Cut a fact's few seconds out of the call's recordings, as 24 kHz mono WAV.

The bridge writes one WAV per person on the call's timeline (silence where they were not
talking), so a time in the transcript is the same time in each file. The clip mixes every
track over the span, so an offer and its "theek hai" are heard in both voices."""

import io
import wave
from pathlib import Path

import numpy as np

OUT_RATE = 24000
PAD_S = 0.3


def _read(path: Path, start: float, end: float) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as wav:
        rate, width, channels = wav.getframerate(), wav.getsampwidth(), wav.getnchannels()
        first = max(0, int(start * rate))
        wav.setpos(min(first, wav.getnframes()))
        frames = wav.readframes(max(0, int((end - start) * rate)))
    if width != 2:
        raise ValueError(f"{path.name}: {width * 8}-bit audio, expected 16-bit")
    samples = np.frombuffer(frames, dtype=np.int16).astype(np.float32)
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)
    return samples, rate


def _resample(samples: np.ndarray, rate: int) -> np.ndarray:
    if rate == OUT_RATE or len(samples) == 0:
        return samples
    count = int(round(len(samples) * OUT_RATE / rate))
    return np.interp(np.linspace(0, len(samples) - 1, count), np.arange(len(samples)), samples)


def cut(paths: list[Path], start: float, end: float, pad: float = PAD_S) -> bytes | None:
    """The span [start - pad, end + pad] of every track, mixed. None if no track exists."""
    start, end = max(0.0, start - pad), end + pad
    tracks = [_resample(*_read(p, start, end)) for p in paths if p.exists()]
    if not tracks:
        return None
    length = max(len(t) for t in tracks)
    mix = np.zeros(length, dtype=np.float32)
    for track in tracks:
        mix[: len(track)] += track
    pcm = np.clip(mix, -32768, 32767).astype(np.int16)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(OUT_RATE)
        out.writeframes(pcm.tobytes())
    return buffer.getvalue()
