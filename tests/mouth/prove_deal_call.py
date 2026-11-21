"""Manual check of Gawah's voice on a deal call, in a real LiveKit room. Not a test.

    uv run python -m tests.mouth.prove_deal_call

Opens one room, puts two headless Chrome browsers in it as Sunita (a recorded line on a
loop: 20 s quiet, 7 s talking) and Ramesh (never speaks: steady noise at -40 dB with a
sharp click every 0.7 s, the whole call), publishes call.started and five
judge.speak events through /dev/publish, and measures from a listen-only bot's recording:

  1. asked in a pause            -> heard, and how long after the event
  2. asked while Sunita talks    -> heard after she stops, and how long after her last sound
  3. asked while she talks, and the item is agreed before she stops -> nothing said
  4. asked as she starts a long line (no pause in time) -> nothing said
  5. a long read-back that Sunita then talks over -> cut off, and how fast

Uses about 10 LiveKit participant-minutes and about a minute of generated speech.
The room is deleted at the end whatever happens. Keeps three samples of Gawah's voice
in fixtures/mouth-samples/.
"""

import asyncio
import json
import secrets

from app.contracts import (
    Audience, CallEnded, CallStarted, ChecklistItem, ChecklistUpdated, ItemKey, ItemState, JudgeSpeak,
    JudgeSpoke, SpeakReason,
)
from fakes import RAMESH, SUNITA
from tests.mouth import rig
from tests.mouth.rig import now, until

READ_BACK = (
    "They are about to hang up. Read back the agreed terms and ask Sunita and Ramesh to confirm them. "
    "The terms: the work: painting the 2BHK flat in Indirapuram, both bedrooms, hall, kitchen and the balcony grill, "
    "two coats of Tractor Emulsion with putty touch-up; the total amount: 22,000 rupees including material; "
    "the advance: 5,000 rupees tomorrow by UPI; the balance: 7,000 rupees when half the work is done and 10,000 on "
    "completion; the dates: starting next Monday at 9 in the morning, finished by Friday."
)


def ms(seconds: float | None) -> int | None:
    return None if seconds is None else round(seconds * 1000)


async def main() -> None:
    sunita = rig.microphone("sunita", rig.silence(20), rig.recorded("paint-03.wav"))
    ramesh = rig.microphone("ramesh", rig.noisy_room(27.0), rate=24000)
    server = rig.Server()
    room, deal_id = f"mouth-proof-{secrets.token_hex(3)}", f"proof-{secrets.token_hex(3)}"
    server.people_page(room)
    result: dict = {"room": room, "deal_id": deal_id, "checks": {}}
    browsers, recorder, opened = [], None, now()
    await server.rooms.create(room, empty_timeout=30, max_participants=6)
    print(f"room {room} opened")
    try:
        async with server:
            recorder = rig.Recorder(server.rooms, room)
            await recorder.start()
            await server.publish(CallStarted(deal_id=deal_id, people=[SUNITA, RAMESH], room=room))
            call = await until(lambda: server.app.state.mouth.calls.get(deal_id), 20, "Gawah to join")
            joined = now()
            browsers += [rig.chrome(f"{server.url}/proof/hirer?auto=1", sunita), rig.chrome(f"{server.url}/proof/worker?auto=1", ramesh)]
            await until(lambda: len(call.hearing.people) == 2, 40, "both people's audio")
            both = now()

            talked: set[str] = set()  # everyone the detector has ever heard as talking

            def talking() -> bool:
                talked.update(call.hearing.talking())
                return "hirer" in call.hearing.talking()

            async def watch() -> None:
                while True:
                    talking()
                    await asyncio.sleep(0.05)

            watching = asyncio.create_task(watch())

            def spoke_for(speak: JudgeSpeak) -> JudgeSpoke | None:
                return next((e for e in server.of(JudgeSpoke) if e.speak_id == speak.event_id), None)

            def outcome() -> dict:
                return call.outcomes[-1]

            async def ask(instruction: str, to: Audience, reason: SpeakReason, item: ItemKey | None) -> tuple[JudgeSpeak, float]:
                speak = JudgeSpeak(deal_id=deal_id, instruction=instruction, to=to, reason=reason, item=item)
                return speak, await server.publish(speak)

            # The opening line: said without being asked, once both people are in.
            opening = (await until(lambda: server.of(JudgeSpoke), 40, "the opening line"))[0]
            heard = recorder.heard("gawah", after=joined)
            result["checks"]["opening"] = {"event": json.loads(rig.show(opening)), "ms_both_people_in_to_heard": ms(heard[0] - both)}
            rig.SAMPLES.mkdir(exist_ok=True)
            recorder.save("gawah", rig.SAMPLES / "opening-line.wav", after=heard[0], before=heard[-1])
            print("opening:", rig.show(opening))

            # 1. In a pause.
            await until(talking, 60, "Sunita's first line")
            await until(lambda: not talking(), 20, "Sunita to stop")
            await asyncio.sleep(2.0)
            speak, sent = await ask("Ask Sunita when the balance will be paid.", Audience.HIRER, SpeakReason.TERM_UNCLEAR, ItemKey.BALANCE)
            spoke = await until(lambda: spoke_for(speak), 20, "judge.spoke 1")
            await asyncio.sleep(0.6)
            heard = recorder.heard("gawah", after=sent)
            result["checks"]["1_in_a_pause"] = {
                "event": json.loads(rig.show(spoke)), "ms_judge_speak_to_heard_in_room": ms(heard[0] - sent),
                "ms_model_to_first_sound": outcome()["model_ms"], "ms_ran_dry": outcome()["dry_ms"],
            }
            recorder.save("gawah", rig.SAMPLES / "question-balance.wav", after=heard[0], before=heard[-1])
            print("1:", rig.show(spoke), result["checks"]["1_in_a_pause"])

            # 2. While Sunita is talking: it waits for her to stop.
            await until(talking, 40, "Sunita's second line")
            await asyncio.sleep(4.3)
            speak, sent = await ask("Ask Ramesh on which date the work will start and by which date it will finish.", Audience.WORKER, SpeakReason.TERM_UNCLEAR, ItemKey.DATES)
            was_talking = talking()
            spoke = await until(lambda: spoke_for(speak), 20, "judge.spoke 2")
            await asyncio.sleep(0.6)
            heard = recorder.heard("gawah", after=sent)
            last_word = recorder.heard("hirer", after=sent - 5, before=heard[0], db=-45)[-1]
            result["checks"]["2_while_talking"] = {
                "event": json.loads(rig.show(spoke)), "sunita_was_talking_when_asked": was_talking,
                "ms_judge_speak_to_heard_in_room": ms(heard[0] - sent),
                "ms_sunitas_last_sound_to_heard_in_room": ms(heard[0] - last_word),
                "ms_gawah_overlapping_sunita": ms(max(0.0, last_word - heard[0])), "ms_ran_dry": outcome()["dry_ms"],
            }
            print("2:", rig.show(spoke), result["checks"]["2_while_talking"])

            # 3. Asked while she talks, and the item is agreed before she stops: nothing is said.
            await until(talking, 40, "Sunita's third line")
            await asyncio.sleep(4.3)
            said_before = len(server.of(JudgeSpoke))
            speak, sent = await ask("Ask Sunita and Ramesh how much the advance is and when it will be paid.", Audience.BOTH, SpeakReason.TERM_UNCLEAR, ItemKey.ADVANCE)
            await asyncio.sleep(1.0)
            items = [ChecklistItem(key=k, state=ItemState.AGREED if k is ItemKey.ADVANCE else ItemState.PENDING,
                                   value="5,000 rupees tomorrow by UPI" if k is ItemKey.ADVANCE else None) for k in ItemKey]
            await server.publish(ChecklistUpdated(deal_id=deal_id, items=items, changed=[ItemKey.ADVANCE]))
            await until(lambda: not talking(), 20, "Sunita to stop")
            await asyncio.sleep(5.0)
            result["checks"]["3_agreed_meanwhile"] = {
                "judge_spoke_events": len(server.of(JudgeSpoke)) - said_before, "why": outcome().get("why"),
                "gawah_frames_heard_since_asked": len(recorder.heard("gawah", after=sent)),
            }
            print("3:", result["checks"]["3_agreed_meanwhile"])

            # 4. Asked as she starts a 7 s line: no pause within PAUSE_WAIT_S, so it is dropped.
            await until(talking, 40, "Sunita's fourth line")
            await asyncio.sleep(0.4)
            said_before = len(server.of(JudgeSpoke))
            speak, sent = await ask("Ask Sunita and Ramesh what will happen if the work is late or left unfinished.", Audience.BOTH, SpeakReason.TERM_UNCLEAR, ItemKey.LATE_OR_UNFINISHED)
            await until(lambda: not talking(), 20, "Sunita to stop")
            await asyncio.sleep(2.0)
            result["checks"]["4_no_pause_in_time"] = {
                "judge_spoke_events": len(server.of(JudgeSpoke)) - said_before, "why": outcome().get("why"),
                "gawah_frames_heard_since_asked": len(recorder.heard("gawah", after=sent)),
            }
            print("4:", result["checks"]["4_no_pause_in_time"])

            # 5. A long read-back; Sunita's next line lands on top of it.
            await asyncio.sleep(4.0)
            speak, sent = await ask(READ_BACK, Audience.BOTH, SpeakReason.WRAPPING_UP, None)
            spoke = await until(lambda: spoke_for(speak), 60, "judge.spoke 5")
            await asyncio.sleep(1.5)
            heard = recorder.heard("gawah", after=sent)
            onset = recorder.heard("hirer", after=heard[0] + 2.0, db=-45)
            onset = onset[0] if onset else None
            result["checks"]["5_talked_over"] = {
                "event": json.loads(rig.show(spoke)), "ms_judge_speak_to_heard_in_room": ms(heard[0] - sent),
                "ms_of_speech_made": outcome()["speech_ms"], "ms_heard_before_cut": ms(heard[-1] - heard[0]),
                "ms_sunitas_first_sound_to_gawah_silent_in_room": ms(heard[-1] - onset) if onset else None,
                "gawah_frames_heard_later": len(recorder.heard("gawah", after=heard[-1] + 0.3)),
            }
            recorder.save("gawah", rig.SAMPLES / "read-back-cut-off.wav", after=heard[0], before=heard[-1])
            print("5:", rig.show(spoke), result["checks"]["5_talked_over"])

            watching.cancel()
            await server.publish(CallEnded(deal_id=deal_id, people=[SUNITA, RAMESH], room=room, reason="proof over"))
            await until(lambda: call.seat._room is None, 10, "Gawah to leave on call.ended")
            result["gawah_left_on_call_ended"] = deal_id not in server.app.state.mouth.calls
            await asyncio.sleep(0.5)
            recorder.save_levels(rig.SCRATCH / "deal-call-levels.json")
            result["everything_gawah_was_asked"] = call.outcomes
            result["rameshs_noise_ever_counted_as_talking"] = "worker" in talked
            result["noise_floors_db"] = {who: round(p.floor, 1) for who, p in call.hearing.people.items()}
            result["levels_in_the_room"] = {who: recorder.levels(who) for who in recorder.frames}
    finally:
        rig.kill(browsers)
        if recorder:
            await recorder.stop()
        await server.rooms.delete(room)
        await asyncio.sleep(6)  # a deleted room shows in the list for a few seconds
        result["rooms_open_after"] = await server.rooms.names()
        result["participant_minutes"] = rig.log_usage("deal-call", room, recorder.seconds if recorder else {}, now() - opened)
        (rig.SCRATCH / "deal-call-result.json").write_text(json.dumps(result, indent=1, ensure_ascii=False))
        print(json.dumps(result, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(asyncio.wait_for(main(), 420))
