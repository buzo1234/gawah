"""How OpenAI's realtime turn detection hears noise: the call-back's and the actor's settings.

    uv run python -m tests.mouth.measure_turns [before|after|<name> ...]

Costs money, a little: one realtime connection per setting, fed about three minutes of
sound as fast as it takes it (input audio and its transcription only; replies are switched
off, so the model never speaks). Not a test. No room, no WhatsApp.

The sounds are those of measure_interference.py, as one person's microphone: a quiet room,
a fan, traffic, a TV, a door and a cough, a short "haan", Gawah's echo, then six real lines.
Prints, per case, how many times the model would have taken it for someone starting to
speak (each one cuts Gawah off on the call-back, and makes the actor reply or stop), and
what its transcription made of the noise.
"""

import asyncio
import base64
import logging
import sys
import time

import numpy as np

from app.actor import realtime as actor
from app.config import get_settings
from app.mouth import tuning
from app.mouth.realtime import Realtime
from tests.mouth import measure_interference as m
from tests.mouth import sounds

log = logging.LoggerAdapter(logging.getLogger("gawah.measure"), {})
GAP_S = 2.5  # quiet room between cases, so one case's detection does not run into the next


def quiet() -> np.ndarray:
    return m.room(GAP_S, seed=40)


def with_bursts(make, count: int, every: float = 4.0, seed: int = 0) -> np.ndarray:
    track = m.room(count * every + 1.0, seed=seed + 20)
    for k in range(count):
        sound = make(k)
        at = int((0.5 + k * every) * tuning.RATE)
        track[at:at + len(sound)] += sound
    return track


def cases() -> dict[str, tuple[np.ndarray, int]]:
    """name -> (sound, how many times someone really starts speaking in it)"""
    gawah = sounds.gawah(20.0)
    lines = [sounds.line(n) * 10 ** (m.BROWSER_GAIN_DB / 20) for n in sounds.LINES[:6]]
    real = np.concatenate([np.concatenate([m.room(1.5, seed=30 + k), s]) for k, s in enumerate(lines)] + [m.room(1.5, seed=39)])
    return {
        "quiet room, -50 dB": (m.room(15.0), 0),
        "fan, -35 dB": (m.room(15.0) + sounds.room_noise(15.0, -35, seed=11), 0),
        "traffic, -35 dB": (m.room(20.0) + sounds.traffic(20.0, -35), 0),
        "TV nearby, -40 dB": (m.room(20.0) + sounds.tv(20.0, -40), 0),
        "4 doors and 4 coughs": (with_bursts(lambda k: sounds.door(seed=k) if k % 2 else sounds.cough(seed=k), 8), 0),
        "4 short 'haan' (400 ms)": (with_bursts(lambda k: m.short_word(k, 400), 4), 0),
        "Gawah's echo, 20 dB down": (m.room(20.0) + m.echo(gawah, 20.0), 0),
        "6 recorded lines": (real, len(lines)),
    }


def config(turns: dict, noise: dict | None, transcription: dict) -> dict:
    turns = {**turns, "create_response": False, "interrupt_response": False}  # measuring: the model never replies
    audio_in: dict = {"format": {"type": "audio/pcm", "rate": tuning.RATE}, "turn_detection": turns,
                      "transcription": transcription}
    if noise:
        audio_in["noise_reduction"] = noise
    return {"type": "realtime", "output_modalities": ["audio"], "instructions": "Listen only.", "audio": {"input": audio_in}}


SETTINGS = {
    "before": config(
        {"type": "server_vad", "threshold": 0.5, "prefix_padding_ms": 300, "silence_duration_ms": 700}, None,
        {"model": "gpt-transcribe"},
    ),
    "callback": config(tuning.CALLBACK_TURNS, tuning.CALLBACK_NOISE, tuning.CALLBACK_TRANSCRIPTION),
    "actor": config(actor.TURNS, actor.NOISE, actor.TRANSCRIPTION),
    # Tried and not taken (see the comments on CALLBACK_TURNS and CALLBACK_NOISE):
    "0.7": config({**tuning.CALLBACK_TURNS, "threshold": 0.7}, None, tuning.CALLBACK_TRANSCRIPTION),
    "near-field": config(tuning.CALLBACK_TURNS, {"type": "near_field"}, tuning.CALLBACK_TRANSCRIPTION),
    "semantic-low": config({"type": "semantic_vad", "eagerness": "low"}, {"type": "near_field"}, tuning.CALLBACK_TRANSCRIPTION),
}


async def measure(key: str, name: str) -> dict[str, dict]:
    events: list[dict] = []

    async def on_event(event: dict) -> None:
        events.append(event)

    link = Realtime(key, SETTINGS[name], on_event, log)
    await link.open()
    out: dict[str, dict] = {}
    sent_s = 0.0
    try:
        await asyncio.sleep(1.0)
        if errors := [e for e in events if e["type"] == "error"]:
            raise RuntimeError(errors[0].get("error"))
        for case, (sound, expected) in cases().items():
            before = len(events)
            track = np.concatenate([sound, quiet()])
            for i in range(0, len(track), tuning.RATE // 5):  # 200 ms at a time, about 5 times real speed
                pcm = np.clip(track[i:i + tuning.RATE // 5], -32768, 32767).astype(np.int16).tobytes()
                await link.send({"type": "input_audio_buffer.append", "audio": base64.b64encode(pcm).decode()})
                await asyncio.sleep(0.04)
            sent_s += len(track) / tuning.RATE
            deadline = time.monotonic() + 8.0  # the last transcriptions come after the sound
            while time.monotonic() < deadline:
                await asyncio.sleep(0.5)
                mine = events[before:]
                started = sum(e["type"] == "input_audio_buffer.speech_started" for e in mine)
                done = sum(e["type"] == "conversation.item.input_audio_transcription.completed" for e in mine)
                stopped = sum(e["type"] == "input_audio_buffer.speech_stopped" for e in mine)
                if stopped >= started and done >= stopped:
                    break
            mine = events[before:]
            out[case] = {
                "expected": expected,
                "started": sum(e["type"] == "input_audio_buffer.speech_started" for e in mine),
                "heard": [e.get("transcript", "").strip() for e in mine
                          if e["type"] == "conversation.item.input_audio_transcription.completed"],
                "errors": [str((e.get("error") or {}).get("message"))[:120] for e in mine if e["type"] == "error"],
            }
    finally:
        await link.close()
    print(f"[{name}] sent {sent_s:.0f} s of audio", flush=True)
    return out


async def main(names: list[str]) -> None:
    key = get_settings().require("openai_api_key")
    for name in names:
        results = await measure(key, name)
        print(f"\n{name}: {SETTINGS[name]['audio']['input']['turn_detection']}, noise reduction "
              f"{SETTINGS[name]['audio']['input'].get('noise_reduction')}")
        for case, r in results.items():
            want = f" (of {r['expected']} real)" if r["expected"] else ""
            heard = "; ".join(t[:40] for t in r["heard"] if t)[:200]
            print(f"  {case:28s} speech started {r['started']}{want}  heard: {heard or '-'}"
                  + (f"  ERRORS: {r['errors']}" if r["errors"] else ""))


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    asyncio.run(main(sys.argv[1:] or ["before", "callback", "actor"]))
