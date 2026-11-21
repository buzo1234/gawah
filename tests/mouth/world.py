"""Stand-ins for LiveKit and OpenAI, so the mouth runs in tests with neither.

FakeRooms makes and deletes rooms. FakeSeat is Gawah's seat in a room: the test says who is talking, and reads back what
was played. FakeLink is the connection to the voice model: on the deal call it answers
every request with a short speech; on the call-back the test plays the model's part.
"""

import asyncio
import base64
import json
import time

import numpy as np

from app.bus import Bus
from app.contracts import CallStarted, Event, JudgeSpoke
from app.mouth import Mouth, tuning
from fakes import RAMESH, SUNITA
from tests.mouth import sounds

SPEECH = sounds.line("paint-09.wav") * 3  # a recorded line with no gap in it, at the level a browser's gain control gives


def audio(ms: int) -> str:
    return base64.b64encode(bytes(tuning.RATE * ms // 1000 * 2)).decode()


class FakeSeat:
    def __init__(self) -> None:
        self.on_frame = self.on_left = self.on_silent = lambda *a: None
        self.on_closed = lambda: None
        self.room: str | None = None
        self.gone = False
        self.played: list[float] = []  # when each frame was handed over
        self.cleared = 0

    async def join(self, room_name: str) -> None:
        self.room = room_name

    async def play(self, pcm: bytes) -> None:
        self.played.append(time.monotonic())
        await asyncio.sleep(tuning.FRAME_MS / 1000)

    def queued_ms(self) -> float:
        return 0.0

    def clear(self) -> None:
        self.cleared += 1

    async def played_out(self) -> None: ...

    async def leave(self) -> None:
        self.gone = True

    # what the test does to the room

    def hears(self, who: str, samples: np.ndarray) -> None:
        for frame in sounds.frames(samples):
            self.on_frame(who, frame)

    def says(self, who: str, ms: int) -> None:
        """Recorded speech from this person's microphone."""
        self.hears(who, SPEECH[: tuning.RATE * ms // 1000])

    def talks(self, who: str) -> None:
        """They are mid-sentence, and stay so until stops()."""
        self.says(who, 600)

    def stops(self, who: str) -> None:
        self.hears(who, sounds.room_noise((tuning.PAUSE_MS + 100) / 1000, -50))


class FakeRooms:
    url = "wss://livekit.invalid"

    def __init__(self) -> None:
        self.made: list[str] = []
        self.deleted: list[str] = []

    async def create(self, name: str, empty_timeout: int, max_participants: int) -> None:
        self.made.append(name)

    async def delete(self, name: str) -> None:
        self.deleted.append(name)

    def token(self, room: str, identity: str, name: str | None = None) -> str:
        return f"token:{room}:{identity}"


class FakeLink:
    def __init__(self, config: dict, on_event) -> None:
        self.config, self.on_event = config, on_event
        self.sent: list[dict] = []
        self.open_ = self.closed = False
        self.auto = config["audio"]["input"]["turn_detection"] is None  # the deal call: answer every request
        self.text = "Sunita ji, balance kab diya jayega?"
        self.pieces = [300]  # ms of speech in each piece the model sends
        self.gap = 0.0  # seconds between pieces
        self.silent = False  # the model never answers
        # The agent's replies, in order: {"text", "ms", "calls": [(tool, args)]}. When it runs out, the
        # model just says self.text. Speech outside the conversation (the acknowledgement) never takes one.
        self.replies: list[dict] = []
        self._n = 0

    async def open(self) -> None:
        self.open_ = True

    async def close(self) -> None:
        self.closed = True

    async def send(self, event: dict) -> None:
        self.sent.append(event)
        if event["type"] == "response.create" and self.auto and not self.silent:
            response = event["response"]
            reply = self.replies.pop(0) if self.replies and response.get("conversation") != "none" else {}
            asyncio.get_running_loop().create_task(self._speak(response.get("metadata"), reply))

    def of(self, kind: str) -> list[dict]:
        return [e for e in self.sent if e["type"] == kind]

    def items(self, role: str) -> list[str]:
        """The text of every message of this role added to the conversation."""
        return [e["item"]["content"][0]["text"] for e in self.of("conversation.item.create")
                if e["item"]["type"] == "message" and e["item"]["role"] == role]

    def outputs(self) -> list[str]:
        """What each tool call told the model."""
        return [e["item"]["output"] for e in self.of("conversation.item.create") if e["item"]["type"] == "function_call_output"]

    def asked(self) -> list[str]:
        """The instructions of every reply asked for in the conversation."""
        return [e["response"]["instructions"] for e in self.of("response.create") if e["response"].get("conversation") != "none"]

    async def _speak(self, metadata: dict | None, reply: dict) -> None:
        self._n += 1
        rid, item = f"resp_{self._n}", f"item_{self._n}"
        await self.on_event({"type": "response.created", "response": {"id": rid, "metadata": metadata}})
        pieces = [reply.get("ms", 0)] if reply else self.pieces  # a reply of tool calls alone has no speech
        for i, ms in enumerate(p for p in pieces if p):
            if i:
                await asyncio.sleep(self.gap)
            await self.on_event({"type": "response.output_audio.delta", "response_id": rid, "item_id": item, "delta": audio(ms)})
        text = reply.get("text", self.text if "calls" not in reply else "")
        if text:
            await self.on_event({"type": "response.output_audio_transcript.done", "response_id": rid, "transcript": text})
        output = [
            {"type": "function_call", "status": "completed", "name": name, "call_id": f"call_{self._n}_{i}", "arguments": json.dumps(args)}
            for i, (name, args) in enumerate(reply.get("calls", []))
        ]
        await self.on_event({"type": "response.done", "response": {"id": rid, "status": "completed", "output": output}})

    # the call-back: the test plays the model

    async def says(self, text: str, ms: int = 100, calls: list[tuple[str, dict]] = ()) -> str:
        """One reply from the model: some speech, then any tool calls."""
        self._n += 1
        rid, item = f"resp_{self._n}", f"item_{self._n}"
        await self.on_event({"type": "response.created", "response": {"id": rid}})
        if ms:
            await self.on_event({"type": "response.output_audio.delta", "response_id": rid, "item_id": item, "delta": audio(ms)})
            await self.on_event({"type": "response.output_audio.done", "response_id": rid, "item_id": item})
            await self.on_event({"type": "response.output_audio_transcript.done", "response_id": rid, "transcript": text})
        spoken = [{"type": "message", "status": "completed", "role": "assistant", "content": [{"type": "output_audio", "transcript": text}]}]
        output = (spoken if ms else []) + [
            {"type": "function_call", "status": "completed", "name": name, "call_id": f"call_{self._n}_{i}", "arguments": json.dumps(args)}
            for i, (name, args) in enumerate(calls)
        ]
        await self.on_event({"type": "response.done", "response": {"id": rid, "status": "completed", "output": output}})
        return item

    async def calls(self, name: str, **args) -> str:
        """The model reports an answer with a tool. Returns what it was told next."""
        before = len(self.of("conversation.item.create"))
        await self.says("", ms=0, calls=[(name, args)])
        return self.of("conversation.item.create")[before]["item"]["output"]


class World:
    """A mouth on a bus, with fake rooms and a fake voice model. mode is JUDGE_MODE; memory is
    what app.state.memory would hold."""

    def __init__(self, bus: Bus, mode: str = "live", memory=None) -> None:
        self.bus, self.mode, self.memory = bus, mode, memory
        self.seats: list[FakeSeat] = []
        self.links: list[FakeLink] = []
        self.events: list[Event] = []
        self.mouth = Mouth(bus, self.make_seat, self.make_link, mode, lambda: self.memory)
        bus.subscribe_all(self._collect)

    def make_seat(self, log=None) -> FakeSeat:
        self.seats.append(FakeSeat())
        return self.seats[-1]

    def make_link(self, config: dict, on_event, log=None) -> FakeLink:
        self.links.append(FakeLink(config, on_event))
        return self.links[-1]

    async def _collect(self, event: Event) -> None:
        self.events.append(event)

    def of(self, kind: type, deal_id: str | None = None) -> list:
        return [e for e in self.events if isinstance(e, kind) and deal_id in (None, e.deal_id)]

    async def call(self, deal_id: str = "d1", opening: bool = True, room_db: float = -50.0, **started) -> tuple[FakeSeat, FakeLink]:
        """Start a deal call and wait until Gawah is in the room and has said its opening line."""
        before = len(self.seats)
        started.setdefault("room", f"deal-{deal_id}")
        self.bus.publish(CallStarted(deal_id=deal_id, people=[SUNITA, RAMESH], **started))
        await until(lambda: deal_id in self.mouth.calls)
        for who in ("hirer", "worker"):  # both are in the room, and quiet
            self.seats[before].hears(who, sounds.room_noise(1.0, room_db))
        if opening:
            await until(lambda: self.of(JudgeSpoke, deal_id))
        return self.seats[before], self.links[before]


async def until(condition, timeout: float = 3.0):
    deadline = time.monotonic() + timeout
    while not (found := condition()):
        if time.monotonic() > deadline:
            raise AssertionError("did not happen in time")
        await asyncio.sleep(0.005)
    return found
