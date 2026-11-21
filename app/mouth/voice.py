"""The deal call's use of the voice model: one English instruction in, one spoken Hindi
reply out. The model is never sent the room's audio and never replies by itself.
Each reply stands alone: nothing is kept in a conversation between them."""

import asyncio
import base64
import logging
import time
from dataclasses import dataclass, field
from typing import Protocol

from app.mouth import tuning
from app.mouth.realtime import session


class Link(Protocol):
    async def open(self) -> None: ...
    async def send(self, event: dict) -> None: ...
    async def close(self) -> None: ...


@dataclass
class Utterance:
    instruction: str
    asked_at: float = field(default_factory=time.monotonic)
    audio: bytearray = field(default_factory=bytearray)
    text: str = ""  # what the model says it said, so far
    response_id: str | None = None
    first_audio_at: float | None = None
    last_audio_at: float | None = None
    complete: bool = False  # the model has sent all of it
    failed: str | None = None
    cancelled: bool = False

    @property
    def audio_ms(self) -> float:
        return len(self.audio) / 2 * 1000 / tuning.RATE

    def ready(self) -> bool:
        """Enough is in hand to start without running dry (see PREBUFFER_MS in tuning)."""
        if self.complete:
            return bool(self.audio)
        if self.first_audio_at is None:
            return False
        held = (time.monotonic() - self.first_audio_at) * 1000
        return self.audio_ms >= tuning.PREBUFFER_MS or held >= tuning.PREBUFFER_HOLD_MS

    def stalled(self) -> bool:
        waiting_since = self.last_audio_at or self.asked_at
        return not self.complete and time.monotonic() - waiting_since > tuning.VOICE_TIMEOUT_S


def config() -> dict:
    return session(tuning.DEAL_PERSONA, turns=None)


class Voice:
    def __init__(self, log: logging.LoggerAdapter) -> None:
        self.log = log
        self.link: Link | None = None  # set by whoever makes the connection, with on_event as its handler
        self._asked: dict[str, Utterance] = {}  # our event id -> sent, and response.created has not come back
        self._by_id: dict[str, Utterance] = {}
        self._count = 0

    async def ask(self, instruction: str, who: str = "") -> Utterance:
        utterance = Utterance(instruction)
        self._count += 1
        ask_id = f"ask_{self._count}"
        self._asked[ask_id] = utterance
        # Per-reply instructions replace the session's, so the persona goes in every time.
        text = "\n\n".join(filter(None, [tuning.DEAL_PERSONA, who, f"The instruction: {instruction}"]))
        await self.link.send({
            "type": "response.create",
            "event_id": ask_id,  # an error about this request names it
            "response": {
                "conversation": "none", "input": [], "output_modalities": ["audio"], "instructions": text,
                "metadata": {"ask": ask_id},  # comes back on response.created, so replies cannot be mixed up
            },
        })
        return utterance

    async def cancel(self, utterance: Utterance) -> None:
        """Stop the model if it is still going, and ignore anything more it sends for this one."""
        utterance.cancelled = True
        if utterance.response_id and not utterance.complete:
            await self.link.send({"type": "response.cancel", "response_id": utterance.response_id})

    async def on_event(self, event: dict) -> None:
        kind = event["type"]
        if kind == "response.created":
            response_id = event["response"]["id"]
            if not self._asked:
                self.log.warning("the voice model started a reply nobody asked for; cancelling it")
                await self.link.send({"type": "response.cancel", "response_id": response_id})
                return
            ask_id = (event["response"].get("metadata") or {}).get("ask")
            if ask_id not in self._asked:
                ask_id = next(iter(self._asked))  # no label came back: replies are created in the order asked
            utterance = self._asked.pop(ask_id)
            utterance.response_id = response_id
            self._by_id[response_id] = utterance
            if utterance.cancelled:
                await self.link.send({"type": "response.cancel", "response_id": response_id})
        elif kind == "response.output_audio.delta":
            utterance = self._by_id.get(event.get("response_id"))
            if utterance and not utterance.cancelled:
                utterance.last_audio_at = time.monotonic()
                utterance.first_audio_at = utterance.first_audio_at or utterance.last_audio_at
                utterance.audio.extend(base64.b64decode(event["delta"]))
        elif kind == "response.output_audio_transcript.delta":
            utterance = self._by_id.get(event.get("response_id"))
            if utterance:
                utterance.text += event.get("delta", "")
        elif kind == "response.output_audio_transcript.done":
            utterance = self._by_id.get(event.get("response_id"))
            if utterance:
                utterance.text = event.get("transcript") or utterance.text
        elif kind == "response.done":
            utterance = self._by_id.pop(event["response"]["id"], None)
            if utterance:
                status = event["response"].get("status")
                if status not in ("completed", "cancelled"):
                    utterance.failed = f"reply {status}"
                utterance.complete = True
        elif kind == "error":
            error = event.get("error") or {}
            self.log.warning("voice model error: %s", str(error.get("message"))[:200])
            utterance = self._asked.pop(error.get("event_id"), None)
            if utterance:
                utterance.failed, utterance.complete = "request refused", True
        elif kind == "closed":
            for utterance in [*self._asked.values(), *self._by_id.values()]:
                utterance.failed, utterance.complete = "connection closed", True
            self._asked.clear()
            self._by_id.clear()
