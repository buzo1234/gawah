"""The actor against the real voice model, with no room: Sunita's lines of the demo's call 1
(recordings, and generated speech for the rest) are played straight into the actor as if it
heard them in the room, and what it says back is printed and saved. Not a test: it uses OpenAI
(about 2 minutes of a realtime connection), and no LiveKit, Sage2 or WhatsApp.

    uv run python tests/actor_try.py [last line no, default 13] [out folder]

It shows whether the actor says its own lines in turn, keeps the numbers, and stays quiet
(the wait tool) where Gawah is meant to speak.
"""

import asyncio
import json
import logging
import sys
import time
import wave
from pathlib import Path

import numpy as np

sys.path[:0] = [str(Path(__file__).parent.parent)]
from app.actor import persona  # noqa: E402
from app.actor.actor import Actor  # noqa: E402
from app.actor.realtime import RATE, Realtime  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.contracts import Role  # noqa: E402
from tools import demo_story  # noqa: E402

FRAME = RATE // 50  # 20 ms


class EarOnly:
    """Stands in for the room: what is played is heard, and what the actor says is kept."""

    def __init__(self, log) -> None:
        self.on_heard = lambda pcm: None
        self.on_closed = lambda: None
        self.room, self.given_ms, self.out, self.last_said = None, 0.0, bytearray(), 0.0

    async def join(self, url, token): ...
    def present(self): return {"hirer", "gawah"}
    def say(self, pcm):
        self.out += pcm
        self.last_said = time.monotonic()
    def speaking(self): return time.monotonic() - self.last_said < 0.6
    def heard_ms(self): return self.given_ms
    def clear(self): ...
    async def leave(self): ...


def to_24k(pcm: bytes, rate: int) -> np.ndarray:
    samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32)
    if rate == RATE:
        return samples.astype(np.int16)
    t = np.arange(0, len(samples) * RATE / rate) * rate / RATE
    return np.interp(t, np.arange(len(samples)), samples).astype(np.int16)


async def play(seat: EarOnly, samples: np.ndarray) -> None:
    due = time.monotonic()
    for i in range(0, len(samples), FRAME):
        frame = samples[i:i + FRAME]
        seat.on_heard(np.pad(frame, (0, FRAME - len(frame))).tobytes())
        due += 0.02
        await asyncio.sleep(max(0.0, due - time.monotonic()))


async def quiet(seat: EarOnly, seconds: float, cap: float) -> None:
    """Room hiss until the actor has been quiet this long (or the cap)."""
    end, hiss = time.monotonic() + cap, (np.random.default_rng(1).normal(0, 30, FRAME)).astype(np.int16)
    still = 0.0
    while time.monotonic() < end and still < seconds:
        await play(seat, hiss)
        still = 0.0 if seat.speaking() else still + 0.02


async def main(last: int, out: Path) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    settings = get_settings()
    key = settings.require("openai_api_key")
    call = demo_story.call(1)
    lines = [line for line in call["lines"] if line["line_no"] <= last]
    speech = await demo_story.speech([line for line in lines if line["speaker"] == "hirer"], key)
    names = {Role.HIRER: "Sunita", Role.WORKER: None}
    seats: list[EarOnly] = []
    actor = Actor(
        "try", Role.WORKER, "deal", None, instructions=persona.instructions(Role.WORKER, "deal", 1, names),
        make_seat=lambda log: seats.append(EarOnly(log)) or seats[-1],
        make_link=lambda config, on_event, log: Realtime(key, config, on_event, log),
    )
    t0 = time.monotonic()
    await actor.start("none", "none", "try")
    seat = seats[0]
    turns = []
    await quiet(seat, 1.0, 2.0)
    for line in lines:
        if line["speaker"] != "hirer":
            continue
        before = len(actor.said)
        pcm, rate = speech[line["line_no"]]
        await play(seat, to_24k(pcm, rate))
        await quiet(seat, 2.5, 14.0)
        turns.append({"line": line["line_no"], "sunita": line["text"], "actor": actor.said[before:]})
        print(f"{line['line_no']:>2} SUNITA: {line['text']}\n   ACTOR : {actor.said[before:] or '(quiet)'}", flush=True)
    actor.stop("done")
    await actor.wait()
    out.mkdir(parents=True, exist_ok=True)
    with wave.open(str(out / "actor-voice.wav"), "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(RATE)
        w.writeframes(bytes(seat.out))
    minutes = (time.monotonic() - t0) / 60
    (out / "actor-try.json").write_text(json.dumps({"turns": turns, "heard": actor.heard, "realtime_minutes": round(minutes, 2)}, indent=1, ensure_ascii=False))
    print(f"realtime connection: {minutes:.1f} minutes; saved to {out}")


if __name__ == "__main__":
    asyncio.run(main(int(sys.argv[1]) if len(sys.argv) > 1 else 13, Path(sys.argv[2] if len(sys.argv) > 2 else "runs/actor-try")))
