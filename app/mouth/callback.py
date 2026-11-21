"""The call-back: Gawah and one person in a room of their own, opened from a link.

Unlike the deal call, the voice model hears the person here and replies by itself. What
it may say comes one step at a time from script.py, and every answer comes back as a
tool call. The room is ours: made when the person taps join, deleted when the
conversation is done, the person leaves, or our time limit passes.
"""

import asyncio
import base64
import json
import logging
import time
from collections.abc import Callable
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.bus import Bus
from app.contracts import CallEnded, CallKind, CallStarted, Person, Role, new_id
from app.log import deal_log
from app.mouth import script, tuning
from app.mouth.player import Player
from app.mouth.realtime import session
from app.mouth.script import Script

HERE = Path(__file__).parent
log = logging.getLogger("gawah.mouth")


class Callback:
    def __init__(self, plan: Script, person: Person, bus: Bus, rooms, make_seat: Callable, make_link: Callable) -> None:
        self.plan, self.person, self.bus, self.rooms = plan, person, bus, rooms
        self.deal_id, self.identity = plan.deal_id, plan.role.value
        self.log = deal_log("gawah.mouth.callback", self.deal_id)
        self.seat = make_seat(self.log)
        config = session(plan.persona, turns=tuning.CALLBACK_TURNS, tools=script.TOOLS, speed=tuning.CALLBACK_SPEED)
        self.link = make_link(config, self.on_event, self.log)
        self.player = Player(self.seat)
        self.room_name: str | None = None
        self.over = False
        self.on_over: Callable[[Callback], None] = lambda call: None
        self._made = time.monotonic()
        self._joined: float | None = None  # when the person's audio first arrived
        self._left: float | None = None
        self._active = self._made  # the last time anybody spoke
        self._finished: float | None = None  # when the last step was answered
        self._listening = False  # the model hears the person only once it has finished its greeting
        self._mic: asyncio.Queue[bytes] = asyncio.Queue()
        self._reply: str | None = None  # the reply being played ...
        self._item: str | None = None  # ... and its place in the conversation, for telling the model where it was cut
        self._item_from_ms = 0.0
        self._fed_ms = 0.0
        self._cut: set[str] = set()  # replies the person talked over: ignore what is left of them
        self._tasks: set[asyncio.Task] = set()

    async def start(self, room_name: str) -> None:
        self.room_name = room_name
        self.seat.on_frame = self._on_frame
        self.seat.on_left = self._on_left
        self.seat.on_closed = lambda: self.end("the room closed")
        try:
            await self.seat.join(room_name)
            await self.link.open()
        except BaseException:
            await self._close("could not start")
            raise
        for work in (self.player.run(), self._send_mic(), self._watch()):
            self._spawn(work)

    def end(self, reason: str) -> None:
        if not self.over:
            self.over = True
            # Its own task: the one asking may be a task this is about to cancel.
            asyncio.get_running_loop().create_task(self._close(reason))

    async def _close(self, reason: str) -> None:
        self.over = True
        for task in self._tasks:
            task.cancel()
        self.player.stop()
        if self._joined is not None:
            self.bus.publish(CallEnded(
                deal_id=self.deal_id, people=[self.person], kind=CallKind.CALLBACK, room=self.room_name,
                duration=round(time.monotonic() - self._joined, 1), reason=reason,
            ))
        for close in (self.link.close, self.seat.leave, lambda: self.rooms.delete(self.room_name)):
            try:
                await close()
            except Exception:
                self.log.exception("did not close cleanly")
        self.log.info("call-back with %s over: %s", self.identity, reason)
        self.on_over(self)

    def _spawn(self, work) -> None:
        task = asyncio.get_running_loop().create_task(work)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    # ---- the person ----

    def _on_frame(self, who: str, pcm: bytes) -> None:
        if who != self.identity or self.over:
            return
        self._left = None
        if self._joined is None:
            self._joined = self._active = time.monotonic()
            self.bus.publish(CallStarted(deal_id=self.deal_id, people=[self.person], kind=CallKind.CALLBACK, room=self.room_name))
            self._spawn(self._begin())
        if self._listening:
            self._mic.put_nowait(pcm)

    def _on_left(self, who: str) -> None:
        if who == self.identity:
            self._left = time.monotonic()

    async def _begin(self) -> None:
        await self.link.send({"type": "conversation.item.create", "item": {
            "type": "message", "role": "system", "content": [{"type": "input_text", "text": self.plan.opening()}],
        }})
        await self.link.send({"type": "response.create"})

    async def _send_mic(self) -> None:
        while True:
            pcm = await self._mic.get()
            while not self._mic.empty():
                pcm += self._mic.get_nowait()
            await self.link.send({"type": "input_audio_buffer.append", "audio": base64.b64encode(pcm).decode()})

    async def _watch(self) -> None:
        """Our own limits: nobody came, nobody is speaking, the person left, too long."""
        while True:
            await asyncio.sleep(0.25)
            now = time.monotonic()
            if self.player.active:
                self._active = now
            if self.plan.done and self._finished is None:
                self._finished = now
            if self._joined is None and now - self._made > tuning.CALLBACK_JOIN_WAIT_S:
                return self.end("nobody joined")
            if self._left is not None and now - self._left > tuning.CALLBACK_LEFT_GRACE_S:
                return self.end("the person left")
            if now - self._made > tuning.CALLBACK_MAX_S:
                return self.end("time limit")
            if self._joined is not None and now - self._active > tuning.CALLBACK_IDLE_S:
                return self.end("nobody spoke")
            if self._finished is not None and now - self._finished > tuning.CALLBACK_LINGER_S:
                return self.end("done")

    # ---- the voice model ----

    async def on_event(self, event: dict) -> None:
        kind = event["type"]
        if kind == "response.output_audio.delta":
            if event.get("response_id") in self._cut:
                return
            if not self.player.active:
                self.player.begin()
                self._fed_ms = 0.0
            if event.get("item_id") != self._item:
                self._item, self._item_from_ms = event.get("item_id"), self._fed_ms
            self._reply = event.get("response_id")
            pcm = base64.b64decode(event["delta"])
            self._fed_ms += len(pcm) / 2 * 1000 / tuning.RATE
            self.player.feed(pcm)
        elif kind == "response.output_audio.done":
            if event.get("response_id") not in self._cut:
                self.player.finish()
        elif kind == "input_audio_buffer.speech_started":
            self._active = time.monotonic()
            await self._talked_over()
        elif kind == "response.done":
            await self._reply_done(event["response"])
        elif kind == "conversation.item.input_audio_transcription.completed":
            self.log.info("%s said: %s", self.identity, " ".join(str(event.get("transcript", "")).split())[:300])
        elif kind == "response.output_audio_transcript.done":
            self.log.info("gawah said: %s", " ".join(str(event.get("transcript", "")).split())[:300])
        elif kind == "error":
            self.log.warning("voice model error: %s", str((event.get("error") or {}).get("message"))[:200])
        elif kind == "closed":
            self.end("the voice model connection closed")

    async def _talked_over(self) -> None:
        """The person started speaking: go quiet, and tell the model how much of its reply was heard."""
        if not self.player.active:
            return
        heard = self.player.heard_so_far()
        self.player.stop()
        self._cut.add(self._reply)  # the model may still be sending the rest of it
        if self._item:
            await self.link.send({
                "type": "conversation.item.truncate", "item_id": self._item, "content_index": 0,
                "audio_end_ms": int(max(0.0, heard - self._item_from_ms)),
            })

    async def _reply_done(self, response: dict) -> None:
        self._listening = True
        calls = [o for o in response.get("output") or [] if o.get("type") == "function_call" and o.get("status") == "completed"]
        for call in calls:
            try:
                args = json.loads(call.get("arguments") or "{}")
            except ValueError:
                args = {}
            result = self.plan.call(call.get("name"), args if isinstance(args, dict) else {})
            self.log.info("tool %s %s -> step %s of %s", call.get("name"), args, self.plan.at, len(self.plan.steps))
            await self.link.send({"type": "conversation.item.create", "item": {
                "type": "function_call_output", "call_id": call.get("call_id"), "output": result,
            }})
        if self.plan.hang_up:
            self._spawn(self._hang_up())
        elif calls:
            await self.link.send({"type": "response.create"})

    async def _hang_up(self) -> None:
        try:
            await asyncio.wait_for(self.player.done.wait(), 20)
        except TimeoutError:
            pass
        await asyncio.sleep(tuning.CALLBACK_HANGUP_S)
        self.end("done")


def register(app: FastAPI, bus: Bus, rooms: Callable, make_seat: Callable, make_link: Callable) -> None:
    live: dict[tuple[str, Role], Callback] = {}
    joining = asyncio.Lock()
    page = (HERE / "page.html").read_text()
    app.mount("/mouth/static", StaticFiles(directory=HERE / "static"), name="mouth-static")

    # The same path as contracts.callback_path(deal_id, role).
    @app.get("/callback/{deal_id}/{role}", response_class=HTMLResponse)
    async def callback_page(deal_id: str, role: Role) -> str:
        return page

    @app.post("/callback/{deal_id}/{role}/join")
    async def join(deal_id: str, role: Role):
        """The page's join button: make the room, seat Gawah in it, and let the person in."""
        async with joining:
            call = live.get((deal_id, role))
            try:
                if call is None or call.over:
                    plan = await script.build(app.state.store, deal_id, role, bus.publish)
                    if plan is None:
                        return JSONResponse({"message": tuning.PAGE_NOTHING}, 404)
                    deal = await app.state.store.deal(deal_id)
                    room_name = f"callback-{deal_id}-{role.value}-{new_id()[:6]}"
                    await rooms().create(room_name, tuning.CALLBACK_EMPTY_S, max_participants=3)
                    call = Callback(plan, deal.person(role) or Person(role=role), bus, rooms(), make_seat, make_link)
                    call.on_over = lambda done: live.pop((deal_id, role), None) if live.get((deal_id, role)) is done else None
                    await call.start(room_name)
                    live[(deal_id, role)] = call
                desk = rooms()
                return {"url": desk.url, "token": desk.token(call.room_name, role.value, call.person.name)}
            except Exception as e:
                log.error("deal=%s call-back could not start: %s: %s", deal_id, type(e).__name__, str(e)[:200])
                return JSONResponse({"message": tuning.PAGE_FAILED}, 503)

    async def close() -> None:
        for call in list(live.values()):
            if not call.over:
                await call._close("server stopping")

    app.state.callbacks = live
    app.state.on_shutdown.append(close)
