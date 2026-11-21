"""Manual check of Gawah the agent on a deal call, in a real LiveKit room. Not a test.

    uv run python -m tests.mouth.prove_agent [--dry]

The server runs with JUDGE_MODE=live and a fake memory holding the facts of
fixtures/call_two_amounts.json, with clips of the agreed amount and advance. Two headless
Chrome browsers join: one plays the people's lines (both voices, stand-ins made by the
realtime model, see voices.py), the other is a noisy room (steady -40 dB, a click every
0.7 s). There is no bridge, so the ears are played by this script: each line goes out as
transcript.line EARS_S after the room heard it end (the measured delay of the real ears),
and the brain's judge.speak for a skipped term or a contradiction JUDGE_S after that.

The moments: four questions put to Gawah by name (one in Devanagari), two skipped terms,
and two contradictions with a clip. For each, a listen-only bot measures from the room:
the person's last sound, then Gawah's first sound (and for a question, the answer's).

About 15 LiveKit participant-minutes and four minutes of a realtime connection. The room
is deleted at the end whatever happens. Keeps three samples of Gawah in fixtures/mouth-samples/.
--dry builds the microphone and prints the timeline, with no room.
"""

import asyncio
import json
import secrets
import statistics
import sys

import numpy as np

from app.config import get_settings
from app.contracts import (
    MEMORY_STATE, Audience, CallEnded, CallStarted, FactRecorded, ItemKey, JudgeSpeak, JudgeSpoke, Role, SpeakReason,
    TranscriptLine,
)
from fakes import RAMESH, SUNITA
from fakes.memory import FakeMemory, two_amounts_facts
from tests.mouth import rig, voices
from tests.mouth.rig import now, until
from tests.mouth.try_agent import CLIPS

EARS_S = 1.5  # a line reaches the bus about 1.5 s after the person stops (spikes/2-ears.md)
JUDGE_S = 0.5  # and the brain's judge.speak about half a second after that (Sage2 165-490 ms)
LEAD_S = 18.0  # quiet at the start, for the opening line
S, R = Role.HIRER, Role.WORKER
VOICE = {S: voices.SUNITA, R: voices.RAMESH}
SAMPLE = {"question": "agent-question.wav", "skipped term": "agent-skipped-term.wav", "contradiction": "agent-contradiction-clip.wav"}


def ask(reason: SpeakReason, instruction: str, to: Audience, item: ItemKey, facts: list[str] = ()) -> dict:
    return {"reason": reason, "instruction": instruction, "to": to, "item": item, "fact_ids": list(facts)}


# (who, words, seconds of quiet after, kind of moment or None, the brain's judge.speak or None)
SCRIPT = [
    (S, "Theek hai, 13 hazaar. Sirf labour, material mera.", 1.5, None, None),
    (R, "Ji, done.", 2.0, None, None),
    (R, "Gawah ji, total kitna tay hua tha?", 13.0, "question", None),
    (R, "Parson se shuru karunga madam, Wednesday ko.", 10.0, "skipped term",
     ask(SpeakReason.TERM_UNCLEAR, "Ask Sunita when the balance will be paid.", Audience.HIRER, ItemKey.BALANCE)),
    (S, "गवाह जी, एडवांस कितना तय हुआ था?", 13.0, "question", None),
    (R, "To total 14 hazaar mein se 3 advance, baaki finish hone pe.", 26.0, "contradiction",
     ask(SpeakReason.CONTRADICTS_RECORD, "Ramesh just said the total is 14,000; the total amount was agreed at 13,000.",
         Audience.BOTH, ItemKey.AMOUNT, ["f-amount"])),
    (S, "Haan, 13 hi tay hua tha.", 4.0, None, None),
    (S, "Gawah ji, material kaun laayega, iski baat hui thi?", 13.0, "question", None),
    (S, "Theek hai, kaam dekh ke hi payment karungi.", 10.0, "skipped term",
     ask(SpeakReason.TERM_UNCLEAR, "Ask Sunita and Ramesh what will happen if the work is late or left unfinished.",
         Audience.BOTH, ItemKey.LATE_OR_UNFINISHED)),
    (S, "Advance to maine 5 hazaar diya tha na?", 26.0, "contradiction",
     ask(SpeakReason.CONTRADICTS_RECORD, "Sunita just said the advance was 5,000; the advance was agreed at 3,000.",
         Audience.BOTH, ItemKey.ADVANCE, ["f-advance"])),
    (R, "Nahi madam, 3 hi mila tha.", 4.0, None, None),
    (R, "Gawah ji, ab tak kitna paisa mila hai?", 13.0, "question", None),
]


def level(pcm: bytes, db: float = -24.0) -> np.ndarray:
    samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float64)
    rms = np.sqrt(np.mean(samples * samples)) or 1.0
    return samples * (32768 * 10 ** (db / 20)) / rms


async def build(key: str) -> tuple[list[dict], np.ndarray]:
    """The talking microphone at 24 kHz, and when each line starts and ends in it."""
    spoken = await voices.speak(key, rig.SCRATCH / "voices", [(VOICE[who], words) for who, words, *_ in SCRIPT])
    parts, at, timeline = [np.zeros(int(24000 * LEAD_S))], LEAD_S, []
    for (who, words, gap, kind, speak), pcm in zip(SCRIPT, spoken):
        samples = level(pcm)
        timeline.append({"who": who, "words": words, "start": at, "end": at + len(samples) / 24000, "kind": kind, "speak": speak})
        parts += [samples, np.zeros(int(24000 * gap))]
        at += len(samples) / 24000 + gap
    return timeline, np.concatenate(parts + [np.zeros(24000 * 3)])


def stats(values: list[float]) -> dict:
    values = [v for v in values if v is not None]
    if not values:
        return {"n": 0}
    return {"n": len(values), "median_ms": round(statistics.median(values)), "worst_ms": round(max(values)), "all_ms": [round(v) for v in values]}


async def main(dry: bool) -> None:
    key = get_settings().require("openai_api_key")
    timeline, talk = await build(key)
    print(f"talking microphone {len(talk) / 24000:.0f} s:")
    for n, line in enumerate(timeline, 1):
        print(f"  {line['start']:6.1f}-{line['end']:6.1f} {line['who'].value:6} {line['kind'] or '':14} {line['words']}")
    if dry:
        return
    clips = {fid: voices.wav_bytes(b"".join(await voices.speak(key, rig.SCRATCH / "voices", parts))) for fid, parts in CLIPS.items()}
    talker = rig.microphone("agent-talker", talk, rate=24000)
    noise = rig.microphone("agent-noise", rig.noisy_room(len(talk) / 24000), rate=24000)
    server = rig.Server()
    room, deal_id = f"agent-proof-{secrets.token_hex(3)}", f"proof-{secrets.token_hex(3)}"
    facts = two_amounts_facts(deal_id)
    setattr(server.app.state, MEMORY_STATE, FakeMemory(facts, clips))
    server.people_page(room)
    result: dict = {"room": room, "deal_id": deal_id, "moments": []}
    browsers, recorder, opened = [], None, now()
    await server.rooms.create(room, empty_timeout=30, max_participants=6)
    print(f"room {room} opened")
    try:
        async with server:
            recorder = rig.Recorder(server.rooms, room)
            await recorder.start()
            for fact in facts:
                await server.publish(FactRecorded(deal_id=deal_id, fact=fact))
            await server.publish(CallStarted(deal_id=deal_id, people=[SUNITA, RAMESH], room=room))
            call = await until(lambda: server.app.state.mouth.calls.get(deal_id), 20, "Gawah to join")
            browsers += [rig.chrome(f"{server.url}/proof/hirer?auto=1", talker), rig.chrome(f"{server.url}/proof/worker?auto=1", noise)]
            await until(lambda: len(call.hearing.people) == 2, 40, "both people's audio")
            # The first line's first sound pins the microphone's timeline to the room's clock.
            first = await until(lambda: recorder.heard("hirer", after=0, db=-40), LEAD_S + 20, "the first line")
            zero = first[0] - timeline[0]["start"]
            for n, line in enumerate(timeline, 1):
                # The ears' delay counts from the person's last sound, as the real ears' does.
                await asyncio.sleep(max(0.0, zero + line["end"] + 0.2 - now()))
                sound = recorder.heard("hirer", after=zero + line["start"] - 0.2, db=-45)
                ended = sound[-1] if sound else zero + line["end"]
                await asyncio.sleep(max(0.0, ended + EARS_S - now()))
                sent = await server.publish(TranscriptLine(
                    deal_id=deal_id, speaker=line["who"], text=line["words"], start=round(ended - zero - 3, 2),
                    end=round(ended - zero, 2), line_no=12 + n,
                ))
                line.update(n=12 + n, transcript_at=sent, outcomes_before=len(call.outcomes))
                if line["speak"]:
                    await asyncio.sleep(JUDGE_S)
                    speak = JudgeSpeak(deal_id=deal_id, after_line=12 + n, **line["speak"])
                    line["speak_id"], line["speak_at"] = speak.event_id, await server.publish(speak)
                print(f"line {12 + n} out: {line['words']}")
            await asyncio.sleep(timeline[-1]["end"] - timeline[-2]["end"] + 6)
            await server.publish(CallEnded(deal_id=deal_id, people=[SUNITA, RAMESH], room=room, reason="proof over"))
            await until(lambda: call.seat._room is None, 10, "Gawah to leave on call.ended")
            result["gawah_left_on_call_ended"] = deal_id not in server.app.state.mouth.calls

            # ---- measure each moment from the room's recording ----
            saved: set[str] = set()
            for i, line in enumerate(timeline):
                if not line["kind"] or "transcript_at" not in line:
                    continue
                upto = timeline[i + 1]["transcript_at"] if i + 1 < len(timeline) and "transcript_at" in timeline[i + 1] else 1e12
                mine = ("ack", "addressed_directly") if line["kind"] == "question" else (line["speak"]["item"].value,)
                said = [o for o in call.outcomes[line["outcomes_before"]:] if o["said"] and o.get("at", 0) < upto and o["what"] in mine]
                person = recorder.heard("hirer", after=zero + line["start"] - 0.2, before=line["transcript_at"], db=-45)
                last = person[-1] if person else zero + line["end"]
                moment = {"line": line["n"], "kind": line["kind"], "words": line["words"], "person_stopped_to_transcript_ms": round((line["transcript_at"] - last) * 1000)}
                sounds = []
                for o in said:
                    heard = recorder.heard("gawah", after=o["at"] - 0.05, before=o["at"] + 3)
                    sounds.append({"what": o["what"], "text": o.get("text"), "tools": o.get("tools"), "clip": o.get("clip"),
                                   "ms_person_stopped_to_heard": round((heard[0] - last) * 1000) if heard else None,
                                   "ms_handed_to_heard": round((heard[0] - o["at"]) * 1000) if heard else None,
                                   "interrupted": o.get("interrupted")})
                moment["gawah"] = sounds
                if line["kind"] != "question":
                    moment["judge_spoke"] = next((json.loads(rig.show(e)) for e in server.of(JudgeSpoke) if e.speak_id == line.get("speak_id")), None)
                result["moments"].append(moment)
                print(json.dumps(moment, ensure_ascii=False))
                name = SAMPLE[line["kind"]]
                if said and name not in saved:  # the first of each kind
                    heard = recorder.heard("gawah", after=said[0]["at"] - 0.05, before=said[-1]["at"] + said[-1].get("speech_ms", 0) / 1000 + 1)
                    if heard:
                        recorder.save("gawah", rig.SAMPLES / name, after=heard[0], before=heard[-1])
                        saved.add(name)

            def first_sound(kind: str, which: str) -> list[float]:
                out = []
                for m in result["moments"]:
                    if m["kind"] == kind:
                        hits = [g for g in m["gawah"] if (g["what"] == "ack") == (which == "ack")]
                        out.append(hits[0]["ms_person_stopped_to_heard"] if hits else None)
                return out

            result["delays_person_stopped_to_gawah_heard"] = {
                "question_ack": stats(first_sound("question", "ack")),
                "question_answer": stats(first_sound("question", "answer")),
                "skipped_term": stats(first_sound("skipped term", "answer")),
                "contradiction_with_clip": stats(first_sound("contradiction", "answer")),
            }
            result["missed"] = [m["line"] for m in result["moments"] if not m["gawah"]]
            await asyncio.sleep(0.5)
    finally:
        rig.kill(browsers)
        if recorder:
            result["levels_in_the_room"] = {who: recorder.levels(who) for who in recorder.frames}
            await recorder.stop()
        if "call" in locals():
            result["everything_gawah_did"] = [{k: v for k, v in o.items() if k != "at"} for o in call.outcomes]
        await server.rooms.delete(room)
        await asyncio.sleep(6)  # a deleted room shows in the list for a few seconds
        result["rooms_open_after"] = await server.rooms.names()
        result["participant_minutes"] = rig.log_usage("agent", room, recorder.seconds if recorder else {}, now() - opened)
        result["realtime_seconds"] = round(now() - opened)
        (rig.SCRATCH / "agent-result.json").write_text(json.dumps(result, indent=1, ensure_ascii=False))
        print(json.dumps({k: v for k, v in result.items() if k != "everything_gawah_did"}, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(asyncio.wait_for(main("--dry" in sys.argv), 480))
