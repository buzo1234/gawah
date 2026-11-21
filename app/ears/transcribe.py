"""OpenAI transcription: one spoken line in, its text out. The only place ears calls OpenAI.

Settings are the ones spike 2 found best: gpt-transcribe, Hindi and English hints, and a
short prompt. The line is uploaded whole; OpenAI's own end-of-speech detection is not used.
"""

import io
import re
import wave

import httpx

from app.config import Settings
from app.contracts import Deal, Role
from app.ears.vad import RATE

URL = "https://api.openai.com/v1/audio/transcriptions"
MODEL = "gpt-transcribe"
TIMEOUT = httpx.Timeout(6.0, connect=3.0)


def prompt_for(deal: Deal, about: str | None = None) -> str:
    """The hint sent with every line of one call: who is talking and what to expect."""
    hirer, worker = deal.person(Role.HIRER), deal.person(Role.WORKER)
    who = " and ".join(
        f"{p.name}, {label}" if p and p.name else label
        for p, label in ((hirer, "the person giving the work"), (worker, "the worker"))
    )
    text = (
        f"Phone call in Hinglish (Hindi and English mixed) between {who}, agreeing a job and its payment. "
        "Expect rupee amounts (hazaar, thousand), advance and balance, dates and weekdays, "
        "and short replies such as haan, theek hai, pakka."
    )
    # The message that asked for the deal names the job. It also carries the other person's
    # phone number, which OpenAI has no need to see.
    about = re.sub(r"\+?\d[\d\s-]{5,}\d", " ", about or "").strip()
    if about:
        text += f" The job was first described as: {about[:200]}"
    return text


def as_wav(pcm: bytes) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(RATE)
        out.writeframes(pcm)
    return buffer.getvalue()


class Transcriber:
    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._settings, self._transport = settings, transport
        self._http: httpx.AsyncClient | None = None
        self.calls = 0  # uploads made, retries included

    async def transcribe(self, pcm: bytes, prompt: str) -> str:
        """Text of one line of 16 kHz mono 16-bit audio. Raises if both tries fail."""
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=TIMEOUT, transport=self._transport)
        headers = {"Authorization": f"Bearer {self._settings.require('openai_api_key')}"}
        data = {"model": MODEL, "languages[]": ["hi", "en"], "prompt": prompt}
        wav = as_wav(pcm)
        for attempt in (1, 2):
            self.calls += 1
            try:
                response = await self._http.post(
                    URL, headers=headers, data=data, files={"file": ("line.wav", wav, "audio/wav")}
                )
                response.raise_for_status()
                return response.json().get("text", "").strip()
            except (httpx.TransportError, httpx.HTTPStatusError):
                if attempt == 2:
                    raise
        raise AssertionError("unreachable")

    async def close(self) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None
