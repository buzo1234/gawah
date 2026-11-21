"""Gawah's mouth: OpenAI realtime voice model, used only as text-instruction -> Hindi speech.

One websocket is held open. Nothing is spoken until say() sends a response.create.
The audio is pushed into a LiveKit AudioSource. stop() cuts it mid-speech.
"""

import asyncio
import base64
import json

import websockets
from livekit import rtc

from lk import ENV, now

RATE = 24000  # the only PCM rate the realtime model outputs
FRAME_BYTES = RATE // 50 * 2  # 20 ms of 16-bit mono

PERSONA = (
    "You are Gawah, a neutral witness on a phone call between two people in India. "
    "You are given one instruction in English that describes a single thing to say. "
    "Say only that, in natural, polite, spoken Hindi, the way people in Delhi talk on the phone "
    "(common English words like 'advance' or 'balance' are fine). One or two short sentences. "
    "Address the person by name if a name is given. "
    "Do not greet, do not explain, do not add anything that is not in the instruction, "
    "do not suggest any term, do not say whether anything is fair, and do not ask a second question. "
    "Then stop."
)


class Mouth:
    def __init__(self, model: str, source: rtc.AudioSource, voice: str = "marin", effort: str | None = None):
        self.model = model
        self.voice = voice
        self.effort = effort
        self.source = source
        self.ws = None
        self.buf = bytearray()
        self.current: dict | None = None  # the utterance being generated or played
        self.speaking = False
        self.utterances: list[dict] = []
        self.unsolicited = 0  # responses the model started without a trigger
        self.errors: list[dict] = []
        self.event_counts: dict[str, int] = {}
        self.usage: list[dict] = []
        self._dropped: set[str] = set()
        self._tasks: list[asyncio.Task] = []
        self._idle = asyncio.Event()
        self._idle.set()
        self.connect_ms: float | None = None

    async def connect(self) -> None:
        t = now()
        self.ws = await websockets.connect(
            f"wss://api.openai.com/v1/realtime?model={self.model}",
            additional_headers={"Authorization": f"Bearer {ENV['OPENAI_API_KEY']}"},
            max_size=None,
            open_timeout=15,
        )
        first = json.loads(await self.ws.recv())
        assert first["type"] == "session.created", first
        session = {
            "type": "realtime",
            "output_modalities": ["audio"],
            "instructions": PERSONA,
            "audio": {
                "input": {"format": {"type": "audio/pcm", "rate": RATE}, "turn_detection": None},
                "output": {"format": {"type": "audio/pcm", "rate": RATE}, "voice": self.voice},
            },
        }
        if self.effort:
            session["reasoning"] = {"effort": self.effort}
        await self._send({"type": "session.update", "session": session})
        self.connect_ms = round((now() - t) * 1000)
        self._tasks = [asyncio.create_task(self._read()), asyncio.create_task(self._play())]

    async def close(self) -> None:
        for task in self._tasks:
            task.cancel()
        if self.ws:
            await self.ws.close()

    async def _send(self, event: dict) -> None:
        await self.ws.send(json.dumps(event))

    async def feed(self, pcm24k: bytes) -> None:
        """Optional test only: let the model hear the room, to see if it ever replies on its own."""
        await self._send({"type": "input_audio_buffer.append", "audio": base64.b64encode(pcm24k).decode()})

    async def say(self, instruction: str) -> dict:
        if self.speaking:
            raise RuntimeError("already speaking")
        u = {"model": self.model, "instruction": instruction, "t_trigger": now(), "audio_ms": 0, "played_ms": 0}
        self.current = u
        self.utterances.append(u)
        self.speaking = True
        self._idle.clear()
        await self._send(
            {
                "type": "response.create",
                "response": {
                    "conversation": "none",
                    "input": [],
                    "output_modalities": ["audio"],
                    "instructions": f"{PERSONA}\n\nThe instruction: {instruction}",
                },
            }
        )
        return u

    async def wait_done(self, timeout: float = 60) -> None:
        await asyncio.wait_for(self._idle.wait(), timeout)

    async def stop(self, reason: str) -> None:
        u = self.current
        if not u or not self.speaking:
            return
        self.buf.clear()
        self.source.clear_queue()
        u["t_stop"] = now()
        u["stop_reason"] = reason
        self.speaking = False
        if rid := u.get("response_id"):
            self._dropped.add(rid)
            if "t_done" not in u:
                await self._send({"type": "response.cancel", "response_id": rid})
        else:
            u["cancel_when_created"] = True
        self._idle.set()

    async def _read(self) -> None:
        async for raw in self.ws:
            ev = json.loads(raw)
            kind = ev["type"]
            self.event_counts[kind] = self.event_counts.get(kind, 0) + 1
            u = self.current
            if kind == "response.created":
                rid = ev["response"]["id"]
                if u is None or "response_id" in u:
                    self.unsolicited += 1
                    self._dropped.add(rid)
                    await self._send({"type": "response.cancel", "response_id": rid})
                    continue
                u["response_id"] = rid
                u["t_created"] = now()
                if u.pop("cancel_when_created", False):
                    self._dropped.add(rid)
                    await self._send({"type": "response.cancel", "response_id": rid})
            elif kind in ("response.output_audio.delta", "response.audio.delta"):
                if ev.get("response_id") in self._dropped or u is None:
                    continue
                pcm = base64.b64decode(ev["delta"])
                u.setdefault("t_first_delta", now())
                u["audio_ms"] += len(pcm) // 2 * 1000 // RATE
                u.setdefault("deltas", []).append((round((now() - u["t_trigger"]) * 1000), u["audio_ms"]))
                self.buf.extend(pcm)
            elif kind in ("response.output_audio_transcript.done", "response.audio_transcript.done"):
                if u and ev.get("response_id") == u.get("response_id"):
                    u["said"] = ev.get("transcript")
            elif kind == "response.done":
                resp = ev["response"]
                self.usage.append({"model": self.model, "status": resp.get("status"), "usage": resp.get("usage")})
                if u and resp["id"] == u.get("response_id"):
                    u["t_done"] = now()
                    u["status"] = resp.get("status")
            elif kind == "error":
                self.errors.append(ev.get("error", ev))

    async def _play(self) -> None:
        """Feed the source in real time. The source holds at most its queue (200 ms) ahead."""
        while True:
            u = self.current
            if not self.speaking or u is None:
                await asyncio.sleep(0.005)
                continue
            if len(self.buf) >= FRAME_BYTES or (self.buf and "t_done" in u):
                chunk = bytes(self.buf[:FRAME_BYTES]).ljust(FRAME_BYTES, b"\0")
                del self.buf[:FRAME_BYTES]
                frame = rtc.AudioFrame(chunk, RATE, 1, FRAME_BYTES // 2)
                u.setdefault("t_first_frame", now())
                await self.source.capture_frame(frame)
                if self.speaking:
                    u["played_ms"] += 20
            elif "t_done" in u:
                await self.source.wait_for_playout()
                if self.speaking:
                    u["t_play_end"] = now()
                    self.speaking = False
                    self._idle.set()
            else:
                if "t_first_frame" in u:  # started speaking and ran dry: the model is behind real time
                    u["starved_ms"] = u.get("starved_ms", 0) + 5
                await asyncio.sleep(0.005)
