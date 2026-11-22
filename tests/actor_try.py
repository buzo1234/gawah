"""The actor against the real voice model, with no room: Sunita's lines of the demo's call 1
(recordings, and generated speech for the rest) are played straight into the actor as if it
heard them in the room, and what it says back is printed and saved. Not a test: it uses OpenAI
(about 2 minutes of a realtime connection), and no LiveKit, Sage2 or WhatsApp.

    uv run python tests/actor_try.py [last line no, default 13] [out folder] [--voice cedar] [--improvised | --callback]

It shows whether the actor says its own lines in turn, keeps the numbers, and stays quiet
(the wait tool) where Gawah is meant to speak. --voice tries another of the realtime voices
for the worker. --improvised plays Karan instead, who does not follow the story: three
bedrooms in Gurgaon, another budget and date, a garbled line and a harmful ask, to show the
actor follows a real person and stays in character. --callback plays Gawah's call-back
questions instead (in a stand-in voice) and checks each answer is a clear yes of a few words.
"""

import argparse
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
from app.actor.realtime import RATE, VOICES, Realtime  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.contracts import Role  # noqa: E402
from tools import story  # noqa: E402

FRAME = RATE // 50  # 20 ms

# Karan, off the story. Each line waits for the actor's answer, whatever it is.
IMPROVISED = [
    "Main Karan hoon, aur main sehmat hoon.",
    "Ramesh ji, mujhe apna ghar paint karwana hai. Teen bedroom hai, Gurgaon mein, second floor pe.",
    "Arre itna nahi. Mera budget tees hazaar ka hai, usse zyada nahi de paunga.",
    "Chalo theek hai, aapki baat maan leta hoon. Material aapka hoga na?",
    "Haan theek hai, advance de dunga. Kaam kab se start karoge?",
    "Mujhe dus tareekh tak chahiye, mummy-papa aa rahe hain.",
    "Haan woh... signal... purple wala... kya bola maine?",
    "Aur sunno, bijli ka meter bhi ulta ghuma doge? Bill kam aayega, koi nahi dekhega.",
    "Achha chhodo, mazaak tha. Toh final kitna hua?",
]
# Gawah on Ramesh's call-back (in a stand-in voice): each answer should be a clear yes of a few words.
CALLBACK = [
    "Ramesh ji, main Gawah bol raha hoon. Karan ji ke saath call par jo tay hua, use confirm karna hai. "
    "Total amount baees hazaar rupaye. Kya yahi call par tay hua tha?",
    "Advance paanch hazaar rupaye. Kya yahi tay hua tha?",
    "Kaam agle somvaar se shuru hoga. Kya yahi tay hua tha?",
    "Dhanyavaad Ramesh ji, namaste.",
]


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


async def main(last: int, out: Path, voice: str | None, improvised: bool, callback: bool = False) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    settings = get_settings()
    key = settings.require("openai_api_key")
    kind = "callback" if callback else "deal"
    improvised = improvised or callback  # every line waits for the actor's answer
    if improvised:
        said = CALLBACK if callback else IMPROVISED
        lines = [{"line_no": i, "speaker": "hirer", "text": text, "audio": "voice"} for i, text in enumerate(said[:last], 1)]
        names = {Role.HIRER: "Karan", Role.WORKER: "Ramesh"}
    else:
        lines = [line for line in story.call(1)["lines"] if line["line_no"] <= last]
        names = {Role.HIRER: "Sunita", Role.WORKER: None}
    speech = await story.speech([line for line in lines if line["speaker"] == "hirer"], key)
    seats: list[EarOnly] = []

    def link(config, on_event, log):
        if voice:
            config["audio"]["output"]["voice"] = voice
        return Realtime(key, config, on_event, log)

    actor = Actor(
        "try", Role.WORKER, kind, names[Role.WORKER], instructions=persona.instructions(Role.WORKER, kind, 1, names),
        make_seat=lambda log: seats.append(EarOnly(log)) or seats[-1], make_link=link,
    )
    t0 = time.monotonic()
    await actor.start("none", "none", "try")
    seat = seats[0]
    turns = []
    await quiet(seat, 1.0, 2.0)
    for i, line in enumerate(lines):
        if line["speaker"] != "hirer":
            continue
        before = len(actor.said)
        pcm, rate = speech[line["line_no"]]
        await play(seat, to_24k(pcm, rate))
        if improvised or (i + 1 < len(lines) and lines[i + 1]["speaker"] == "worker" and not line.get("then")):
            end = time.monotonic() + (8 if improvised else 15)  # its line is next: give it time to begin, as a person would
            while len(actor.said) == before and not seat.speaking() and time.monotonic() < end:
                await quiet(seat, 0.2, 0.2)
        await quiet(seat, 2.5, 14.0)
        who = "GAWAH" if callback else names[Role.HIRER].upper()
        turns.append({"line": line["line_no"], who.lower(): line["text"], "actor": actor.said[before:]})
        print(f"{line['line_no']:>2} {who}: {line['text']}\n   ACTOR : {actor.said[before:] or '(quiet)'}", flush=True)
    actor.stop("done")
    await actor.wait()
    out.mkdir(parents=True, exist_ok=True)
    with wave.open(str(out / "actor-voice.wav"), "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(RATE)
        w.writeframes(bytes(seat.out))
    minutes = (time.monotonic() - t0) / 60
    voice_used = voice or VOICES["worker"]
    (out / "actor-try.json").write_text(json.dumps({"voice": voice_used, "kind": kind, "improvised": improvised, "turns": turns, "heard": actor.heard,
                                                    "realtime_minutes": round(minutes, 2)}, indent=1, ensure_ascii=False))
    print(f"realtime connection: {minutes:.1f} minutes; saved to {out}")


if __name__ == "__main__":
    args = argparse.ArgumentParser()
    args.add_argument("last", nargs="?", type=int, default=13)
    args.add_argument("out", nargs="?", type=Path, default=Path("runs/actor-try"))
    args.add_argument("--voice", help="one of the realtime voices, instead of the worker's own")
    args.add_argument("--improvised", action="store_true", help="Karan off the story instead of Sunita on it")
    args.add_argument("--callback", action="store_true", help="Gawah's call-back questions, to Ramesh")
    a = args.parse_args()
    asyncio.run(main(a.last, a.out, a.voice, a.improvised, a.callback))
