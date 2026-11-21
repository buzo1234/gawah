"""Gawah the agent on a deal call (JUDGE_MODE=live): one realtime conversation that is fed
every line of the call as text, labelled with who said it, and Memory's facts as notes.
It never hears the room's audio and never replies by itself.

A moment to speak becomes a turn: the model is asked for a reply with the situation as
its instructions, may call tools (each result goes back and it is asked again), and its
speech, with any clip it played, collects in one stream of audio in the order it is to be
heard. The deal call decides when that audio goes into the room, as it does for the voice.
"""

import base64
import json
import logging
import time
from dataclasses import dataclass, field

from app.contracts import Event
from app.mouth import tuning
from app.mouth.moments import Names
from app.mouth.realtime import session
from app.mouth.tools import TOOLS, Tools
from app.mouth.voice import Link


@dataclass
class Turn:
    """One reply, possibly over several requests to the model. Looks like voice.Utterance to
    the deal call: audio grows as it arrives, complete when nothing more is coming."""

    situation: str
    asked_at: float = field(default_factory=time.monotonic)
    audio: bytearray = field(default_factory=bytearray)
    text: str = ""
    response_id: str | None = None
    first_audio_at: float | None = None
    last_audio_at: float | None = None
    progress_at: float = field(default_factory=time.monotonic)  # the last sign of life: audio, or a tool round
    complete: bool = False
    failed: str | None = None
    cancelled: bool = False
    silent: bool = False  # the model chose stay_silent
    clip_fact_id: str | None = None
    tools: list[str] = field(default_factory=list)  # every tool called, in order
    effects: list[Event] = field(default_factory=list)  # what the tools publish if the turn is carried out
    items: list[list] = field(default_factory=list)  # [item id, where its audio starts in ms, its length in ms]
    rounds: int = 0
    use_tools: bool = True
    first_choice: str = "auto"  # tool_choice for the first request: "required" makes it look up before it speaks
    then: list[tuple] = field(default_factory=list)  # fixed steps after the model's reply: ("clip", fact_id), ("say", situation)
    speak_after: set[str] | None = None  # it may speak only after one of these tools; None: after any

    @property
    def audio_ms(self) -> float:
        return len(self.audio) / 2 * 1000 / tuning.RATE

    def ready(self) -> bool:
        if self.complete:
            return bool(self.audio)
        if self.first_audio_at is None:
            return False
        held = (time.monotonic() - self.first_audio_at) * 1000
        return self.audio_ms >= tuning.PREBUFFER_MS or held >= tuning.PREBUFFER_HOLD_MS

    def stalled(self) -> bool:
        return not self.complete and time.monotonic() - self.progress_at > tuning.VOICE_TIMEOUT_S


def config(names: Names) -> dict:
    return session(tuning.AGENT_PERSONA + "\n" + names.who(), turns=None, tools=TOOLS)


class Agent:
    def __init__(self, tools: Tools, names: Names, log: logging.LoggerAdapter) -> None:
        self.tools, self.names, self.log = tools, names, log
        self.link: Link | None = None  # set by whoever makes the connection, with on_event as its handler
        self._asked: dict[str, Turn] = {}  # our request id -> sent, response.created not back yet
        self._by_response: dict[str, Turn] = {}
        self._n = 0

    # ---- the conversation ----

    async def hear(self, text: str) -> None:
        """One line of the call. A user message: what people said, never instructions."""
        await self._add("user", text)

    async def note(self, text: str) -> None:
        await self._add("system", text)

    async def _add(self, role: str, text: str) -> None:
        await self.link.send({"type": "conversation.item.create", "item": {
            "type": "message", "role": role, "content": [{"type": "input_text", "text": text}],
        }})

    # ---- turns ----

    async def turn(
        self, situation: str, use_tools: bool = True, first_choice: str = "auto", then: list[tuple] = (),
        speak_after: set[str] | None = None,
    ) -> Turn:
        turn = Turn(situation, use_tools=use_tools, first_choice=first_choice, then=list(then), speak_after=speak_after)
        await self._respond(turn)
        return turn

    async def say_once(self, instructions: str) -> Turn:
        """Speech outside the conversation, remembered by nobody: the acknowledgement."""
        turn = Turn(instructions, use_tools=False)
        await self._respond(turn, conversation="none")
        return turn

    async def _respond(self, turn: Turn, conversation: str = "auto") -> None:
        self._n += 1
        ask = f"turn_{self._n}"
        self._asked[ask] = turn
        instructions = turn.situation
        if conversation == "auto":
            instructions = f"{tuning.AGENT_PERSONA}\n{self.names.who()}\n\n{turn.situation}"
        response: dict = {
            "conversation": conversation, "output_modalities": ["audio"], "instructions": instructions,
            "metadata": {"ask": ask},  # comes back on response.created, so replies cannot be mixed up
        }
        if conversation == "none":
            response["input"] = []
        if not turn.use_tools or turn.rounds >= tuning.TOOL_ROUNDS:
            response["tool_choice"] = "none"
        elif turn.rounds == 0 and turn.first_choice != "auto":
            # Text only: the model talks while it calls a tool ("let me check the record"), and nobody
            # should hear that. Its words come in the next request, after the tool's answer.
            response["tool_choice"], response["output_modalities"] = turn.first_choice, ["text"]
        await self.link.send({"type": "response.create", "event_id": ask, "response": response})

    async def cancel(self, turn: Turn, heard_ms: float | None = None) -> None:
        """Stop a turn. heard_ms: it was cut off after that much was heard; None: never said.
        Either way the conversation is made to hold only what the room heard."""
        turn.cancelled = True
        if turn.response_id and turn.response_id in self._by_response:
            await self.link.send({"type": "response.cancel", "response_id": turn.response_id})
        heard = heard_ms or 0.0
        for item_id, start, ms in turn.items:
            if start >= heard:
                await self.link.send({"type": "conversation.item.delete", "item_id": item_id})
            elif start + ms > heard:
                await self.link.send({"type": "conversation.item.truncate", "item_id": item_id, "content_index": 0,
                                      "audio_end_ms": int(heard - start)})
        if heard_ms is None and turn.situation and turn.use_tools:
            await self.note(tuning.DROPPED_NOTE)

    # ---- what the model sends ----

    async def on_event(self, event: dict) -> None:
        kind = event["type"]
        if kind == "response.created":
            await self._created(event["response"])
            return
        turn = self._by_response.get(event.get("response_id") or (event.get("response") or {}).get("id"))
        if kind == "response.output_audio.delta" and turn and not turn.cancelled:
            now = time.monotonic()
            turn.first_audio_at = turn.first_audio_at or now
            turn.last_audio_at = turn.progress_at = now
            item = event.get("item_id")
            if item and (not turn.items or turn.items[-1][0] != item):
                turn.items.append([item, turn.audio_ms, 0.0])
            pcm = base64.b64decode(event["delta"])
            turn.audio.extend(pcm)
            if item:
                turn.items[-1][2] += len(pcm) / 2 * 1000 / tuning.RATE
        elif kind == "response.output_audio_transcript.done" and turn:
            turn.text = " ".join(filter(None, [turn.text, (event.get("transcript") or "").strip()]))
        elif kind == "response.done" and turn:
            self._by_response.pop(event["response"]["id"], None)
            await self._done(turn, event["response"])
        elif kind == "error":
            error = event.get("error") or {}
            self.log.warning("agent model error: %s", str(error.get("message"))[:200])
            failed = self._asked.pop(error.get("event_id"), None)
            if failed:
                failed.failed, failed.complete = "request refused", True
        elif kind == "closed":
            for t in [*self._asked.values(), *self._by_response.values()]:
                t.failed, t.complete = "connection closed", True
            self._asked.clear()
            self._by_response.clear()

    async def _created(self, response: dict) -> None:
        if not self._asked:
            self.log.warning("the agent model started a reply nobody asked for; cancelling it")
            await self.link.send({"type": "response.cancel", "response_id": response["id"]})
            return
        ask = (response.get("metadata") or {}).get("ask")
        turn = self._asked.pop(ask if ask in self._asked else next(iter(self._asked)))
        turn.response_id = response["id"]
        self._by_response[response["id"]] = turn
        if turn.cancelled:
            await self.link.send({"type": "response.cancel", "response_id": response["id"]})

    async def _done(self, turn: Turn, response: dict) -> None:
        status = response.get("status")
        kinds = [o.get("type") for o in response.get("output") or []]
        self.log.info("agent reply %s: %s, %s, %.0f ms of speech so far, %.1f s after the turn began", response.get("id"),
                      status, kinds, turn.audio_ms, time.monotonic() - turn.asked_at)
        if turn.cancelled or status == "cancelled":
            turn.complete = True
            return
        if status not in (None, "completed"):
            turn.failed, turn.complete = f"reply {status}", True
            return
        calls = [o for o in response.get("output") or [] if o.get("type") == "function_call"]
        if not calls and turn.rounds == 0 and turn.first_choice != "auto":
            turn.rounds = 1  # the lookup round called nothing: ask again, for words this time
            await self._respond(turn)
            return
        if not calls:
            await self._next(turn)
            return
        turn.rounds += 1
        for call in calls:
            try:
                args = json.loads(call.get("arguments") or "{}")
            except ValueError:
                args = {}
            name = str(call.get("name"))
            result = await self.tools.run(name, args if isinstance(args, dict) else {})
            self.log.info("tool %s %s -> %s", name, json.dumps(args, ensure_ascii=False)[:200], result.output[:160])
            turn.tools.append(name)
            turn.effects.extend(result.effects)
            turn.silent = turn.silent or result.silent
            if result.clip:
                turn.audio.extend(result.clip)
                turn.clip_fact_id = result.clip_fact_id
                turn.text = " ".join(filter(None, [turn.text, "[clip]"]))
            await self.link.send({"type": "conversation.item.create", "item": {
                "type": "function_call_output", "call_id": call.get("call_id"), "output": result.output,
            }})
        turn.progress_at = time.monotonic()
        if turn.speak_after is not None and not turn.speak_after & {str(c.get("name")) for c in calls}:
            turn.silent = True  # looked something up, but this turn may only speak to a change
        if turn.silent or turn.cancelled:
            turn.complete = True  # nothing more to say: stay_silent ends the turn
            return
        await self._respond(turn)

    async def _next(self, turn: Turn) -> None:
        """The turn's fixed steps, if any are left; else it is complete."""
        while turn.then and not turn.cancelled:
            step = turn.then.pop(0)
            if step[0] == "clip":
                result = await self.tools.run("play_clip", {"fact_id": step[1]})
                turn.effects.extend(result.effects)
                if result.clip:
                    turn.audio.extend(result.clip)
                    turn.clip_fact_id = result.clip_fact_id
                    turn.text = " ".join(filter(None, [turn.text, "[clip]"]))
                await self.note(result.output)
            else:
                turn.situation, turn.use_tools = step[1], False
                await self._respond(turn)
                return
        turn.complete = True
