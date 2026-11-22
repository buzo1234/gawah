"""One actor on one call: it takes a person's seat with the token their page would get, hears
the room, and talks with the realtime voice model as that person would.

It leaves when the call ends (the room closes, or call.ended), when nobody else comes, when the
voice model drops, or at its own time limit, whichever is first."""

import asyncio
import base64
import json
import logging
import time
from collections.abc import Callable

from app.actor import persona
from app.actor.realtime import STOPS_WHEN_TALKED_OVER, VOICES, Realtime, session
from app.actor.room import Seat
from app.contracts import Role
from app.log import deal_log

MAX_S = {"deal": 660.0, "callback": 330.0}  # the bridge caps a call at 10 minutes, the call-back at 5
ALONE_S = 120.0  # in the room and nobody else came: leave rather than hold it open
CHUNK_FRAMES = 5  # what it hears goes to the model 100 ms at a time


class Actor:
    def __init__(
        self, deal_id: str, role: Role, kind: str, name: str | None, *, instructions: str,
        make_seat: Callable[[logging.LoggerAdapter], Seat], make_link: Callable[..., Realtime],
    ) -> None:
        self.deal_id, self.role, self.kind, self.name = deal_id, role, kind, name
        self.log = deal_log("gawah.actor", deal_id)
        self.seat = make_seat(self.log)
        config = session(instructions, VOICES[role.value], [persona.WAIT_TOOL])
        self.link = make_link(config, self.on_event, self.log)
        self.state = "joining"  # joining, waiting, on, ended
        self.reason: str | None = None
        self.room: str | None = None
        self.said: list[str] = []  # what it said, for the log and the proof
        self.heard: list[str] = []  # what the model's transcription made of the room
        self.on_over: Callable[["Actor"], None] = lambda actor: None
        self._made = time.monotonic()
        self._on_at: float | None = None
        self._chunk = bytearray()
        self._reply: str | None = None  # the reply being played, and its item, for telling the model where it was cut
        self._item: str | None = None
        self._cut: set[str] = set()
        self._tasks: set[asyncio.Task] = set()
        self._done = asyncio.Event()

    def seconds(self) -> float | None:
        return round(time.monotonic() - self._on_at, 1) if self._on_at else None

    async def start(self, url: str, token: str, room: str | None = None) -> None:
        self.seat.on_heard = self._heard
        self.seat.on_closed = lambda: self.stop("the room closed")
        try:
            await self.link.open()
            await self.seat.join(url, token)
        except BaseException:
            await self._close("could not start")
            raise
        self.room = room or getattr(self.seat.room, "name", None)
        self.state = "waiting"
        self.log.info("actor playing %s on %s (%s)", self.role.value, self.room, self.kind)
        self._spawn(self._watch())

    def stop(self, reason: str) -> None:
        if self.state != "ended" and self.reason is None:
            self.reason = reason
            asyncio.get_running_loop().create_task(self._close(reason))

    async def wait(self) -> None:
        await self._done.wait()

    async def _close(self, reason: str) -> None:
        self.reason = self.reason or reason
        for task in list(self._tasks):
            if task is not asyncio.current_task():
                task.cancel()
        for close in (self.seat.leave, self.link.close):  # the room first: that is what costs minutes
            try:
                await close()
            except Exception:
                self.log.exception("actor did not close cleanly")
        self.state = "ended"
        self.log.info("actor left %s: %s; it said %d lines", self.room, reason, len(self.said))
        self._done.set()
        self.on_over(self)

    def _spawn(self, work) -> None:
        task = asyncio.get_running_loop().create_task(work)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _watch(self) -> None:
        while True:
            await asyncio.sleep(0.5)
            now = time.monotonic()
            others = self.seat.present() - {"gawah-ears"}
            needed = {self.role.other.value} if self.kind == "deal" else {"gawah"}
            if needed <= others and self._on_at is None:
                self._on_at, self.state = now, "on"
            if now - self._made > MAX_S[self.kind]:
                return self.stop("time limit")
            if self._on_at is None and now - self._made > ALONE_S:
                return self.stop("nobody else came")

    # ---- the room to the model ----

    def _heard(self, pcm: bytes) -> None:
        self._chunk.extend(pcm)
        if len(self._chunk) >= len(pcm) * CHUNK_FRAMES:
            audio = base64.b64encode(bytes(self._chunk)).decode()
            self._chunk.clear()
            self._spawn(self.link.send({"type": "input_audio_buffer.append", "audio": audio}))

    # ---- the model to the room ----

    async def on_event(self, event: dict) -> None:
        kind = event["type"]
        if kind == "response.output_audio.delta":
            if event.get("response_id") in self._cut:
                return
            if event.get("item_id") != self._item:
                self._item = event.get("item_id")
                self.seat.given_ms = 0.0
            self._reply = event.get("response_id")
            self.seat.say(base64.b64decode(event["delta"]))
        elif kind == "input_audio_buffer.speech_started":
            await self._talked_over()
        elif kind == "response.output_audio_transcript.done":
            text = " ".join(str(event.get("transcript", "")).split())
            if text:
                self.said.append(text)
                self.log.info("actor (%s) said: %s", self.role.value, text[:300])
        elif kind == "conversation.item.input_audio_transcription.completed":
            text = " ".join(str(event.get("transcript", "")).split())
            if text:
                self.heard.append(text)
                self.log.info("actor heard: %s", text[:300])
        elif kind == "response.done":
            await self._answer_tools(event["response"])
        elif kind == "error":
            self.log.warning("actor's voice model error: %s", str((event.get("error") or {}).get("message"))[:200])
        elif kind == "closed":
            self.stop("the voice model connection closed")

    async def _talked_over(self) -> None:
        """Someone started speaking: a person stops when talked over, so go quiet and tell the model."""
        if not STOPS_WHEN_TALKED_OVER or not self.seat.speaking():
            return
        heard = self.seat.heard_ms()
        self.seat.clear()
        self._cut.add(self._reply)
        if self._item:
            await self.link.send({
                "type": "conversation.item.truncate", "item_id": self._item, "content_index": 0, "audio_end_ms": int(heard),
            })

    async def _answer_tools(self, response: dict) -> None:
        """The only tool is wait. Answer it so the conversation stays whole, and ask for nothing more."""
        for out in response.get("output") or []:
            if out.get("type") == "function_call" and out.get("status") == "completed":
                await self.link.send({"type": "conversation.item.create", "item": {
                    "type": "function_call_output", "call_id": out.get("call_id"), "output": json.dumps({"ok": True}),
                }})
