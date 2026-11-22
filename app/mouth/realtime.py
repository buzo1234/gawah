"""The connection to OpenAI's realtime voice model. The only file in this stream that
talks to OpenAI. One websocket per call, held open for the whole call: opening one
takes about a second, so it is never opened at the moment Gawah has to speak."""

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable

import websockets

from app.mouth import tuning

URL = "wss://api.openai.com/v1/realtime?model={model}"
CLOSED = {"type": "closed"}  # handed to on_event when the connection drops by itself

OnEvent = Callable[[dict], Awaitable[None]]


def session(instructions: str, turns: dict | None = None, tools: list[dict] | None = None, speed: float = tuning.SPEED) -> dict:
    """The settings for one connection. turns=None switches automatic replies off: the
    model then speaks only when it is sent response.create."""
    audio_in: dict = {"format": {"type": "audio/pcm", "rate": tuning.RATE}, "turn_detection": turns}
    if turns:
        audio_in["transcription"] = tuning.CALLBACK_TRANSCRIPTION
        if tuning.CALLBACK_NOISE:
            audio_in["noise_reduction"] = tuning.CALLBACK_NOISE
    config: dict = {
        "type": "realtime",
        "output_modalities": ["audio"],
        "instructions": instructions,
        "audio": {
            "input": audio_in,
            "output": {"format": {"type": "audio/pcm", "rate": tuning.RATE}, "voice": tuning.VOICE, "speed": speed},
        },
    }
    if tools:
        config["tools"], config["tool_choice"] = tools, "auto"
    if tuning.EFFORT:
        config["reasoning"] = {"effort": tuning.EFFORT}
    return config


class Realtime:
    def __init__(self, key: str, config: dict, on_event: OnEvent, log: logging.LoggerAdapter) -> None:
        self._key, self._config, self._on_event, self.log = key, config, on_event, log
        self._ws: websockets.ClientConnection | None = None
        self._reader: asyncio.Task | None = None

    async def open(self) -> None:
        for attempt in (1, 2):
            try:
                ws = await websockets.connect(
                    URL.format(model=tuning.MODEL),
                    additional_headers={"Authorization": f"Bearer {self._key}"},
                    max_size=None,
                    open_timeout=tuning.CONNECT_TIMEOUT_S,
                )
                first = json.loads(await asyncio.wait_for(ws.recv(), tuning.CONNECT_TIMEOUT_S))
                if first.get("type") != "session.created":
                    raise RuntimeError(f"expected session.created, got {first.get('type')}")
                await ws.send(json.dumps({"type": "session.update", "session": self._config}))
                break
            except Exception as e:
                if attempt == 2:
                    raise
                self.log.warning("voice model did not connect (%s), trying once more", type(e).__name__)
        self._ws = ws
        self._reader = asyncio.create_task(self._read(ws))

    async def send(self, event: dict) -> None:
        if self._ws is None:  # dropped since the last time (a connection lasts 60 minutes at most)
            await self.open()
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
                    self.log.exception("failed on an event from the voice model")
        except websockets.ConnectionClosed:
            pass
        if self._ws is ws:
            self._ws = None
            self.log.warning("voice model connection closed")
            await self._on_event(CLOSED)
