"""Sage2: the fast yes/no decisions about the call so far.

The brain talks to `Decisions`. `SageStream` is the live service; `RecordedDecisions`
replays saved answers, so tests and development cost nothing. Every append to the live
stream is one billed update that re-bills every question, so `SageStream` counts them.
"""

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Protocol
from zoneinfo import ZoneInfo

from websockets.asyncio.client import ClientConnection, connect

from app.brain import tuning
from app.contracts import Person, Role

log = logging.getLogger("gawah.brain.sage")

WS_URL = "wss://sage.levanto.ai/v1/stream"

# Only the questions the brain reads: Sage2 bills every question on every line. The terms and
# contradictions come from the memory's facts, so the six term questions and conflicting_figures
# from the spike are no longer asked; saved recordings still hold their answers, which nothing reads.
# The first three are the v2 wording from spikes/5-sage2.md. Changing a word changes the answers:
# re-record the practice calls (tests/brain/record.py) if you do.
QUESTIONS: dict[str, str] = {
    "addressed_gawah": "In the last line of the transcript, is the speaker talking directly to Gawah, the AI witness, for example by calling it by name?",
    "topic_left_unclear": "Is there a contract term (price, advance, when the balance is paid, or dates) that one speaker asked about, where the other speaker has already replied without giving a clear answer and moved on to a different topic? A question in the last line that the other speaker has not yet had a chance to answer does not count. Answer yes only if that term is still unsettled.",
    "wrapping_up": "Is the call ending right now? Answer yes only if, in the last two lines, a speaker says goodbye, says they are hanging up, or thanks the other person to close the conversation. Agreeing to a term (for example 'theek hai', 'pakka', 'done') or promising to finish the work on time is not ending the call.",
    # Not in the spike. topic_left_unclear needs someone to have asked; in the usual case
    # nobody asks about the balance at all, and this catches that.
    "balance_skipped": "Have the speakers agreed on an advance and then started talking about a different subject, such as the dates of the work or what happens if it is late, without anyone saying when the remaining balance will be paid? Answer no if when the balance is paid has been agreed, if no advance has been agreed yet, or if the speakers are still talking about payments.",
    # Not in the spike. wrapping_up waits for a goodbye, which is often the last line; this
    # says yes a line or two earlier, and once alone mid-call, so the brain wants it twice
    # in a row, or followed by a silence (judge.py, tuning.py).
    "closing_soon": "Have the speakers finished discussing the terms and started closing the conversation, for example by confirming when and where they will meet next, thanking each other, or saying goodbye? Answer no while a price, a payment, a date or any other term is still being discussed.",
}


def speaker_name(people: list[Person], role: Role) -> str:
    person = next((p for p in people if p.role == role), None)
    return (person.name if person and person.name else role.value.capitalize()).split()[0]


def preamble(people: list[Person], today: datetime | None = None) -> str:
    """What Sage2 is told before the first line: who is talking, and today's date."""
    today = today or datetime.now(ZoneInfo("Asia/Kolkata"))
    hirer, worker = speaker_name(people, Role.HIRER), speaker_name(people, Role.WORKER)
    return (
        f"Phone call between {hirer} (the hirer, who is paying for a job) and {worker} (the worker, who will do it). "
        "Gawah is an AI witness listening on the call. "
        f"Today is {today:%A} {today.day} {today:%B %Y}. Amounts are in Indian rupees.\n\n"
    )


def line_text(name: str, text: str) -> str:
    return f"{name}: {' '.join(text.split())}\n"


# question id -> probability of yes, or None for Sage2's near-tie. See `yes()`.
Answers = dict[str, float | None]


def yes(answers: Answers, question: str) -> bool:
    """A missing or null answer is no."""
    p = answers.get(question)
    return p is not None and p >= 0.5


class Decisions(Protocol):
    async def open(self, preamble: str) -> Answers | None:
        """Start a call. Returns the answers before any line, or None if there are none."""

    async def append(self, seq: int, text: str) -> Answers | None:
        """Add one line. Returns the answers after it, or None if none came in time."""

    async def close(self) -> None: ...


def _answers(frame: dict) -> Answers:
    out: Answers = {}
    for qid, body in (frame.get("answers") or {}).items():
        result = (body or {}).get("result") or {}
        answer, p = result.get("answer"), result.get("probability")
        if answer not in ("yes", "no"):
            out[qid] = None
        else:
            out[qid] = float(p) if p is not None else (1.0 if answer == "yes" else 0.0)
    return out


class SageStream:
    """One live Sage2 stream for one call."""

    def __init__(
        self, api_key: str, questions: dict[str, str] | None = None, log: logging.Logger | logging.LoggerAdapter = log
    ) -> None:
        self._key = api_key
        self._log = log  # pass one that carries the deal id
        self._questions = questions or QUESTIONS
        self._ws: ClientConnection | None = None
        self._content = ""
        self._reopens = 0
        self.updates = 0  # billed updates on this call: one per start and one per append

    async def open(self, preamble: str) -> Answers | None:
        self._content = preamble
        return await self._start()

    async def append(self, seq: int, text: str) -> Answers | None:
        self._content += text
        if self._ws is None:
            # The stream is down. Reopen with the whole call so far, a few times at most:
            # each try can hold the next line up for SAGE_OPEN_TIMEOUT_S.
            if self._reopens >= tuning.SAGE_REOPENS:
                return None
            self._reopens += 1
            return await self._start()
        try:
            await self._ws.send(json.dumps({"type": "append", "text": text, "seq": seq}))
            self.updates += 1
            return await self._decision(seq)
        except TimeoutError:
            self._log.warning("sage2 gave no answer for line %s in %.1fs", seq, tuning.SAGE_TIMEOUT_S)
            return None
        except Exception as e:
            self._log.warning("sage2 stream failed on line %s (%s); reopening", seq, type(e).__name__)
            await self._drop()
            self._reopens += 1
            return await self._start()

    async def close(self) -> None:
        if self._ws is not None:
            try:
                await self._ws.send(json.dumps({"type": "close"}))
            except Exception:
                pass
        await self._drop()
        self._log.info("sage2 stream closed after %s updates", self.updates)

    async def _start(self) -> Answers | None:
        questions = [{"id": q, "kind": "yesno", "instructions": text} for q, text in self._questions.items()]
        try:
            self._ws = await connect(
                WS_URL, additional_headers={"Authorization": f"Bearer {self._key}"}, open_timeout=tuning.SAGE_OPEN_TIMEOUT_S
            )
            # emit=all: one decision per append, so we know when a line has been answered.
            await self._ws.send(
                json.dumps({"type": "start", "questions": questions, "content": self._content, "emit": "all"})
            )
            self.updates += 1
            return await self._decision(None)
        except Exception as e:
            self._log.warning("sage2 stream did not open (%s); carrying on without it", type(e).__name__)
            await self._drop()
            return None

    async def _decision(self, seq: int | None) -> Answers:
        """The decision frame for this seq. Skips sig, ready, ping and older decisions."""
        assert self._ws is not None
        async with asyncio.timeout(tuning.SAGE_TIMEOUT_S):
            while True:
                frame = json.loads(await self._ws.recv())
                kind = frame.get("type")
                if kind == "decision" and frame.get("seq") == seq:
                    return _answers(frame)
                if kind == "error":
                    self._log.warning("sage2 error frame: %s", str(frame.get("message") or frame.get("code"))[:200])
                    if frame.get("fatal"):
                        raise ConnectionError("sage2 fatal error")

    async def _drop(self) -> None:
        ws, self._ws = self._ws, None
        if ws is not None:
            try:
                await ws.close()
            except Exception:
                pass


class RecordedDecisions:
    """Answers saved from a real Sage2 stream, replayed by line number."""

    def __init__(self, path: str | Path) -> None:
        saved = json.loads(Path(path).read_text())
        self._by_seq: dict[str, Answers] = saved["answers"]
        self.lines: dict[str, str] = saved["lines"]  # line number -> the line as Sage2 was sent it

    async def open(self, preamble: str) -> Answers | None:
        return self._by_seq.get("0")

    async def append(self, seq: int, text: str) -> Answers | None:
        return self._by_seq.get(str(seq))

    async def close(self) -> None:
        pass
