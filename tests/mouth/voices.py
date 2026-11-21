"""Stand-in voices for the people on a proof call: lines of fixtures/call_two_amounts.json,
and the moments the proofs need, spoken by the realtime model in a voice other than Gawah's.
There are no recordings of that call, and memory's clips are cut from what people said.

Made once and kept in the scratch folder (outside the repo), keyed by voice and words.
Costs a few seconds of generated speech per line the first time. Not a test.
"""

import asyncio
import base64
import hashlib
import io
import logging
import wave
from pathlib import Path

from app.mouth import tuning
from app.mouth.realtime import Realtime, session

SUNITA, RAMESH = "coral", "cedar"
log = logging.LoggerAdapter(logging.getLogger("gawah.proof.voices"), {})


def wav_bytes(pcm: bytes, rate: int = tuning.RATE) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(rate)
        w.writeframes(pcm)
    return buffer.getvalue()


async def speak(key: str, folder: Path, lines: list[tuple[str, str]]) -> list[bytes]:
    """Each (voice, words) as 24 kHz 16-bit mono PCM, from the cache or made now."""
    folder.mkdir(parents=True, exist_ok=True)
    out: list[bytes] = []
    for voice, words in lines:
        path = folder / f"{voice}-{hashlib.sha1(words.encode()).hexdigest()[:12]}.pcm"
        if not path.exists():
            path.write_bytes(await _make(key, voice, words))
        out.append(path.read_bytes())
    return out


async def _make(key: str, voice: str, words: str) -> bytes:
    done, pcm = asyncio.Event(), bytearray()

    async def on_event(event: dict) -> None:
        if event["type"] == "response.output_audio.delta":
            pcm.extend(base64.b64decode(event["delta"]))
        elif event["type"] in ("response.done", "closed"):
            done.set()

    config = session("You read lines aloud for a recording, exactly as written.", turns=None)
    config["audio"]["output"]["voice"] = voice
    link = Realtime(key, config, on_event, log)
    await link.open()
    try:
        await link.send({"type": "response.create", "response": {
            "conversation": "none", "input": [], "output_modalities": ["audio"],
            "instructions": f"Say exactly this, in a natural everyday Hindi phone voice, and nothing else: \"{words}\"",
        }})
        await asyncio.wait_for(done.wait(), 30)
    finally:
        await link.close()
    return bytes(pcm)
