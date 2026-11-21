"""Hear a voice note: ffmpeg makes it 16 kHz mono WAV, OpenAI transcribes it. The only
place the whatsapp stream sends audio to OpenAI.

The settings are the bridge's (app/ears/transcribe.py, from spike 2): gpt-transcribe, Hindi
and English hints, and a short prompt about the deal. Copied, not imported: each stream
owns its own client."""

import asyncio
import io
import re
import wave

import httpx

from app.config import Settings
from app.contracts import Deal, Role

URL = "https://api.openai.com/v1/audio/transcriptions"
MODEL = "gpt-transcribe"
TIMEOUT = httpx.Timeout(20.0, connect=3.0)  # a voice note can run to a minute or more
RATE = 16000
MAX_SECONDS = 300  # longer than any voice note about a deal; nothing past it is heard


class HearingError(Exception):
    pass


def prompt_for(deal: Deal) -> str:
    """Who is talking and what to expect. The bridge's hint, for a voice note."""
    hirer, worker = deal.person(Role.HIRER), deal.person(Role.WORKER)
    who = " and ".join(
        f"{p.name}, {label}" if p and p.name else label
        for p, label in ((hirer, "the person giving the work"), (worker, "the worker"))
    )
    return (
        f"WhatsApp voice note in Hinglish (Hindi and English mixed) about a job agreed between {who}. "
        "Expect rupee amounts (hazaar, thousand), advance and balance, payments made, dates and weekdays, "
        "and short replies such as haan, theek hai, pakka."
    )


async def to_wav(audio: bytes) -> bytes:
    """Any audio WhatsApp sends (Ogg Opus, AMR, MP4, MP3) as 16 kHz mono 16-bit WAV."""
    try:
        process = await asyncio.create_subprocess_exec(
            "ffmpeg", "-loglevel", "error", "-i", "pipe:0", "-t", str(MAX_SECONDS),
            "-ar", str(RATE), "-ac", "1", "-c:a", "pcm_s16le", "-f", "wav", "pipe:1",
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as error:
        raise HearingError("ffmpeg is not installed") from error
    wav, err = await asyncio.wait_for(process.communicate(audio), 30)
    if process.returncode != 0 or not wav:
        raise HearingError(f"ffmpeg could not read the audio: {err.decode(errors='replace')[:200]}")
    return _fix_length(wav)


def seconds_of(wav: bytes) -> float:
    with wave.open(io.BytesIO(wav), "rb") as audio:
        return audio.getnframes() / audio.getframerate()


def _fix_length(wav: bytes) -> bytes:
    """ffmpeg writing to a pipe cannot go back to fill in the WAV header's lengths: write it
    again with them."""
    data = wav.find(b"data")
    pcm = wav[data + 8:] if data >= 0 else b""
    out = io.BytesIO()
    with wave.open(out, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(RATE)
        audio.writeframes(pcm[: len(pcm) - len(pcm) % 2])
    return out.getvalue()


class Transcriber:
    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._settings, self._transport = settings, transport
        self.calls = 0  # uploads made, retries included

    async def transcribe(self, wav: bytes, prompt: str) -> str:
        """The words of one voice note. Raises if both tries fail."""
        headers = {"Authorization": f"Bearer {self._settings.require('openai_api_key')}"}
        data = {"model": MODEL, "languages[]": ["hi", "en"], "prompt": prompt}
        async with httpx.AsyncClient(timeout=TIMEOUT, transport=self._transport) as client:
            for attempt in (1, 2):
                self.calls += 1
                try:
                    response = await client.post(
                        URL, headers=headers, data=data, files={"file": ("voice-note.wav", wav, "audio/wav")}
                    )
                    response.raise_for_status()
                    return re.sub(r"\s+", " ", response.json().get("text", "")).strip()
                except (httpx.TransportError, httpx.HTTPStatusError) as error:
                    if attempt == 2:
                        raise HearingError(f"transcription failed: {type(error).__name__}") from error
        raise AssertionError("unreachable")
