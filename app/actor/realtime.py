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

# The model's own speech detection decides when the others have finished. Gawah pauses inside a
# sentence, so this waits a little longer than the call-back does before it replies.
TURNS = {
    "type": "server_vad", "threshold": 0.5, "prefix_padding_ms": 300, "silence_duration_ms": 900,
    "create_response": True, "interrupt_response": True,
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
                      "transcription": {"model": "gpt-transcribe"}},
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
