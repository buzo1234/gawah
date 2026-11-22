"""The actor's connection to OpenAI's realtime voice model. The only file in this folder that
talks to OpenAI. Unlike Gawah's, this model hears the room and replies by itself."""

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable

import websockets

MODEL = "gpt-realtime-2.1"
VOICES = {"hirer": "coral", "worker": "ash"}  # Gawah is "marin"
RATE = 24000
TIMEOUT_S = 10.0
URL = f"wss://api.openai.com/v1/realtime?model={MODEL}"
CLOSED = {"type": "closed"}

# The model's own speech detection decides when the others have finished. It hears the whole
# room mixed: both other people, Gawah included, and whatever noise their phones let through.
# Measured with tests/mouth/measure_turns.py (noise into a real session, replies off).
TURNS = {
    "type": "server_vad",
    # A TV, a short "haan" and Gawah's echo counted as speech at 0.5, 0.7 and 0.8 alike (fan, traffic, doors and
    # coughs at none): the threshold does little, interrupt_response below does the work. As the call-back.
    "threshold": 0.8,
    "prefix_padding_ms": 500,  # so a soft first word is not lost at 0.8
    "silence_duration_ms": 900,  # Gawah pauses inside a sentence: wait a little longer than the call-back does
    "create_response": True,
    # Off: a person reading their part finishes the line. With it on, any sound in the room (and Gawah's
    # voice, which is in the mix) cut the actor off mid-sentence. When it is not its turn it calls wait.
    "interrupt_response": False,
}
STOPS_WHEN_TALKED_OVER = TURNS["interrupt_response"]  # actor.py goes quiet on "speech started" only if this is on
# OpenAI's input noise reduction. Off: on the call-back's measurements it made up "haan" and "theek hai"
# before real lines, and the phones' browsers already suppress their own noise.
NOISE: dict | None = None
TRANSCRIPTION = {  # the log's record of what it heard. Unpinned, room noise came out as Chinese or Russian.
    "model": "gpt-transcribe",
    "languages": ["hi", "en"],
    "prompt": "Phone call in Hinglish (Hindi and English mixed) about a painting job and its payment.",
}


def session(instructions: str, voice: str, tools: list[dict]) -> dict:
    return {
        "type": "realtime",
        "output_modalities": ["audio"],
        "instructions": instructions,
        "tools": tools,
        "tool_choice": "auto",
        "audio": {
            "input": {"format": {"type": "audio/pcm", "rate": RATE}, "turn_detection": TURNS,
                      "transcription": TRANSCRIPTION, **({"noise_reduction": NOISE} if NOISE else {})},
            "output": {"format": {"type": "audio/pcm", "rate": RATE}, "voice": voice},
        },
    }


class Realtime:
    def __init__(self, key: str, config: dict, on_event: Callable[[dict], Awaitable[None]], log: logging.LoggerAdapter) -> None:
        self._key, self._config, self._on_event, self.log = key, config, on_event, log
        self._ws: websockets.ClientConnection | None = None
        self._reader: asyncio.Task | None = None

    async def open(self) -> None:
        for attempt in (1, 2):
            try:
                ws = await websockets.connect(
                    URL, additional_headers={"Authorization": f"Bearer {self._key}"}, max_size=None, open_timeout=TIMEOUT_S,
                )
                first = json.loads(await asyncio.wait_for(ws.recv(), TIMEOUT_S))
                if first.get("type") != "session.created":
                    raise RuntimeError(f"expected session.created, got {first.get('type')}")
                await ws.send(json.dumps({"type": "session.update", "session": self._config}))
                break
            except Exception as e:
                if attempt == 2:
                    raise
                self.log.warning("actor's voice model did not connect (%s), trying once more", type(e).__name__)
        self._ws = ws
        self._reader = asyncio.create_task(self._read(ws))

    async def send(self, event: dict) -> None:
        if self._ws is not None:
            await self._ws.send(json.dumps(event))

    async def close(self) -> None:
        ws, self._ws = self._ws, None
        if self._reader:
            self._reader.cancel()
        if ws:
            await ws.close()

    async def _read(self, ws: websockets.ClientConnection) -> None:
        try:
            async for raw in ws:
                try:
                    await self._on_event(json.loads(raw))
                except Exception:
                    self.log.exception("actor failed on an event from the voice model")
        except websockets.ConnectionClosed:
            pass
        if self._ws is ws:
            self._ws = None
            await self._on_event(CLOSED)
