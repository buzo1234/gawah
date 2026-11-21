"""Manual check of the call-back in a real LiveKit room. Not a test.

    uv run python -m tests.mouth.prove_callback

Publishes a finished deal through /dev/publish (four agreed terms, two never agreed, and
one cash payment Ramesh has not answered), then opens Ramesh's call-back page in a
headless Chrome whose microphone is a room's noise (-40 dB, a click every 0.7 s) with a
recorded "haan theek hai" every 22 s. Gawah should ask about the cash, read the four
terms one at a time, say which two were never agreed, and hang up; the events should run
call.started, record.confirmed, terms.confirmed, call.ended.

Uses about 8 LiveKit participant-minutes and about 3 minutes of a realtime connection.
Keeps one sample of Gawah reading a term in fixtures/mouth-samples/.
"""

import asyncio
import json
import logging
import secrets

from app.contracts import (
    Backing, CallEnded, CallKind, CallStarted, ChecklistItem, ChecklistUpdated, DealRequested, ItemKey,
    ItemState, Record, RecordConfirmed, RecordConfirmRequested, RecordKind, RecordReceived, Role,
    TermsConfirmed, TermsDisputed, callback_path,
)
from fakes import RAMESH, SUNITA
from tests.mouth import rig, sounds
from tests.mouth.rig import now, until

AGREED = {
    ItemKey.WORK: "painting the 2BHK flat in Indirapuram, both bedrooms, hall, kitchen and the balcony grill, two coats",
    ItemKey.AMOUNT: "22,000 rupees including material",
    ItemKey.ADVANCE: "5,000 rupees tomorrow by UPI",
    ItemKey.DATES: "starting next Monday, finished by Friday",
}
EVERY_S, ANSWER_AT_S = 22.0, 16.0


def microphone():
    """A noisy room, and a clear "haan theek hai" once in every loop."""
    room = rig.noisy_room(EVERY_S)
    answer = sounds.line("paint-12.wav") * 3  # as loud as a person answering into a phone
    start = int(ANSWER_AT_S * 24000)
    room[start:start + len(answer)] += answer
    return rig.microphone("ramesh-answers", room, rate=24000)


class Notes(logging.Handler):
    """What the call-back logged (what each side said, each tool call), with when."""

    def __init__(self) -> None:
        super().__init__()
        self.lines: list[tuple[float, str]] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append((now(), record.getMessage().split(" ", 1)[-1]))  # without the deal id


async def main() -> None:
    mic = microphone()
    server = rig.Server()
    deal_id = f"proof-{secrets.token_hex(3)}"
    notes = Notes()
    logging.getLogger("gawah.mouth.callback").addHandler(notes)
    result: dict = {"deal_id": deal_id}
    browsers, recorder, room, opened = [], None, None, now()
    try:
        async with server:
            cash = Record(sender=Role.HIRER, kind=RecordKind.PAYMENT, backing=Backing.UNBACKED, text="2000 cash diya", amount=2000)
            items = [ChecklistItem(key=k, state=ItemState.AGREED if k in AGREED else ItemState.PENDING, value=AGREED.get(k)) for k in ItemKey]
            for event in (
                DealRequested(deal_id=deal_id, requested_by=SUNITA, other=RAMESH),
                ChecklistUpdated(deal_id=deal_id, items=items),
                RecordReceived(deal_id=deal_id, record=cash),
                RecordConfirmRequested(deal_id=deal_id, record_id=cash.id, confirm_by=Role.WORKER, record=cash),
            ):
                await server.publish(event)
            await server.app.state.bus.drain()

            browsers.append(rig.chrome(f"{server.url}{callback_path(deal_id, Role.WORKER)}?auto=1", mic))
            call = await until(lambda: server.app.state.callbacks.get((deal_id, Role.WORKER)), 30, "the page to ask to join")
            room = call.room_name
            print(f"room {room} opened by the page's join button")
            recorder = rig.Recorder(server.rooms, room)
            await recorder.start()
            ours = (CallStarted, RecordConfirmed, TermsConfirmed, TermsDisputed, CallEnded)

            def mine() -> list:
                return [(t, e) for t, e in server.events if isinstance(e, ours) and e.deal_id == deal_id]

            await until(lambda: any(isinstance(e, CallEnded) and e.kind is CallKind.CALLBACK for _, e in mine()), 290, "call.ended")
            await asyncio.sleep(1.0)
            start = mine()[0][0]
            result["events"] = [{"at_s": round(t - start, 1), **json.loads(rig.show(e))} for t, e in mine()]
            result["conversation"] = [{"at_s": round(t - start, 1), "log": line} for t, line in notes.lines]
            result["ended_in_terms_confirmed"] = any(isinstance(e, TermsConfirmed) and e.item is None for _, e in mine())
            result["times_ramesh_talked_over_gawah"] = sum("talked over Gawah" in line for _, line in notes.lines)
            result["room_deleted_by_the_app"] = call.over
            # Gawah reading the second term: from the first term's answer to the second's.
            answered = [t for t, line in notes.lines if line.startswith("tool term_answer")]
            if len(answered) >= 2:
                heard = recorder.heard("gawah", after=answered[0], before=answered[1])
                # Only the reading itself: stop at the first long silence, where Gawah waits for the answer.
                heard = heard[: next((i for i in range(1, len(heard)) if heard[i] - heard[i - 1] > 1.5), len(heard))]
                if heard:
                    rig.SAMPLES.mkdir(exist_ok=True)
                    result["sample_seconds"] = recorder.save("gawah", rig.SAMPLES / "term-read-back.wav", after=heard[0], before=heard[-1])
    finally:
        rig.kill(browsers)
        if recorder:
            for who in recorder.frames:
                recorder.save(who, rig.SCRATCH / f"callback-{who}.wav")
            result["levels_in_the_room"] = {who: recorder.levels(who) for who in recorder.frames}
            await recorder.stop()
        if room:
            await server.rooms.delete(room)
        await asyncio.sleep(6)  # a deleted room shows in the list for a few seconds
        result["rooms_open_after"] = await server.rooms.names()
        result["participant_minutes"] = rig.log_usage("callback", room or "-", recorder.seconds if recorder else {}, now() - opened)
        (rig.SCRATCH / "callback-result.json").write_text(json.dumps(result, indent=1, ensure_ascii=False))
        print(json.dumps(result, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(asyncio.wait_for(main(), 420))
