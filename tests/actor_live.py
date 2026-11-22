"""The actor's proof on a real call 1. Not a test: it uses the free plans, so run it by hand.

    uv run python tests/actor_live.py [last line no, default 26]

The real app on a free port (WhatsApp off: made-up numbers, no tokens), a deal, Sunita's call
link in a headless Chrome whose microphone plays her lines of fixtures/story/story_call_1.json
(the user's recordings, and generated speech for the rest) when the floor is free, and the
actor started as Ramesh through POST /actor/start. A second headless Chrome shows Ramesh's page
in a phone-shaped frame, which should say "AI is playing Ramesh". At the end Sunita leaves, the
actor is stopped, and the rooms left on LiveKit are listed.

Uses: one LiveKit room for 4 to 6 minutes (Sunita, the actor, Gawah and the listener: about
20 participant-minutes; the room is capped at 6.5 minutes), one Sage2 call, the actor's realtime
connection for the length of the call, Gawah's, about 20 transcription uploads, 2 S3 uploads.
Saves runs/actor-live/<deal>/ (report, page shots) and fixtures/actor-samples/ramesh-call1.wav.
"""

import asyncio
import json
import os
import socket
import sys
import tempfile
import time
import wave
from pathlib import Path

import httpx
import uvicorn

os.environ["ACTOR_ROUTES"] = "1"
sys.path[:0] = [str(Path(__file__).parent), str(Path(__file__).parent.parent)]
from browser import Chrome  # noqa: E402

from app.actor.realtime import RATE  # noqa: E402
from app.actor.room import Seat  # noqa: E402
from app.config import ROOT, get_settings  # noqa: E402
from app.contracts import DealRequested, Person, Role, call_path, new_id  # noqa: E402
from app.main import create_app  # noqa: E402
from tools import story  # noqa: E402
from tools.walk_browser import Person as Browser  # noqa: E402

SAMPLE = ROOT / "fixtures" / "actor-samples" / "ramesh-call1.wav"
SAMPLE_S = 40


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Taped(Seat):
    """The actor's seat, keeping what it says for the sample."""

    tape = bytearray()

    def say(self, pcm: bytes) -> None:
        Taped.tape += pcm
        super().say(pcm)


async def main(last: int) -> None:
    settings = get_settings().model_copy(update={
        "twilio_account_sid": None, "twilio_auth_token": None, "meta_whatsapp_token": None,
        "database_path": str(Path(tempfile.mkdtemp(prefix="actor-live-")) / "proof.db"),
    })
    key = settings.require("openai_api_key")
    call = story.call(1)
    lines = [line for line in call["lines"] if line["line_no"] <= last]
    speech = await story.speech([line for line in lines if line["speaker"] == "hirer"], key)

    app = create_app(settings)
    app.state.calls.limits.max_age = 390
    app.state.actor_seat = lambda log: Taped(log)
    events: list = []

    async def keep(event) -> None:
        events.append((time.monotonic(), event))

    app.state.bus.subscribe_all(keep)
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    serving = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.05)

    deal_id = f"actor{new_id()[:6]}"
    out = ROOT / "runs" / "actor-live" / deal_id
    out.mkdir(parents=True, exist_ok=True)
    report: dict = {"deal_id": deal_id, "steps": []}
    sunita = Browser(out, 9651, "sunita")
    t0 = time.monotonic()
    joined_at = None

    def got(name: str) -> list:
        return [e for _, e in events if e.name == name and e.deal_id == deal_id]

    def step(text: str) -> None:
        print(f"[{time.monotonic() - t0:6.1f}s] {text}", flush=True)
        report["steps"].append(f"{time.monotonic() - t0:.1f}s {text}")

    def actor():
        return app.state.actor

    async def floor_free(seconds: float, cap: float) -> None:
        """Nobody (the actor, Gawah) has spoken for this long."""
        end, still = time.monotonic() + cap, 0.0
        while time.monotonic() < end and still < seconds:
            busy = (actor() and actor().seat.speaking()) or await sunita.gawah_talking()
            still = 0.0 if busy else still + 0.2
            await asyncio.sleep(0.2)

    async def gawah_speaks(cap: float) -> bool:
        end = time.monotonic() + cap
        while time.monotonic() < end:
            if await sunita.gawah_talking():
                return True
            await asyncio.sleep(0.2)
        return False

    async def actor_says(since: int, cap: float) -> None:
        end = time.monotonic() + cap
        while time.monotonic() < end and len(actor().said) <= since:
            await asyncio.sleep(0.2)

    try:
        async with httpx.AsyncClient(base_url=base, timeout=40) as http, Chrome(port=9652, width=420, height=900) as frame:
            requested = DealRequested(
                deal_id=deal_id, requested_by=Person(role=Role.HIRER, name="Sunita", phone="+910000000001"),
                other=Person(role=Role.WORKER, phone="+910000000002"), text="Ramesh painter se flat paint karwana hai",
            )
            (await http.post("/dev/publish", content=requested.model_dump_json())).raise_for_status()
            await asyncio.sleep(0.5)
            await sunita.start()
            await sunita.open(base + call_path(deal_id, Role.HIRER))
            await sunita.click("join")
            joined_at = time.monotonic()
            started = await http.post("/actor/start", json={"deal_id": deal_id, "role": "worker", "kind": "deal"})
            step(f"actor start: {started.status_code} {started.json()}")
            started.raise_for_status()
            await frame.goto(base + "/health")
            await frame.js("document.open(); document.write(" + json.dumps(
                '<body style="margin:0;background:#e5e5ea;display:grid;place-items:center;height:100vh">'
                f'<iframe src="{call_path(deal_id, Role.WORKER)}" style="width:360px;height:780px;border:10px solid #111;'
                'border-radius:46px"></iframe></body>') + "); document.close()")
            while not got("call.started"):
                if time.monotonic() - joined_at > 30:
                    raise TimeoutError("no call.started")
                await asyncio.sleep(0.2)
            step(f"call.started in {got('call.started')[0].room}; Sunita's page: {await sunita.state()}")
            step(f"Gawah's opening: {'heard' if await gawah_speaks(25) else 'NOT heard in 25 s'}")
            await floor_free(2.0, 30)

            previous = None
            for line in lines:
                if line["speaker"] == "hirer":
                    if previous and previous["speaker"] == "worker":
                        await actor_says(said_before, 20)
                        await floor_free(1.5, 25)
                    pcm, rate = speech[line["line_no"]]
                    step(f"Sunita {line['line_no']}: {line['text']}")
                    said_before = len(actor().said)
                    await sunita.say(pcm, rate)
                    await floor_free(1.2, 3)
                if then := line.get("then"):
                    spoke = await gawah_speaks(then["within_s"])
                    step(f"  after line {line['line_no']}, Gawah {'spoke' if spoke else 'did NOT speak'} ({then['gawah']})")
                    await floor_free(3.0, 45)
                if line["line_no"] == 10:
                    await frame.shot(out / "ramesh-page-framed.png")
                    framed = await frame.js("(() => { const d = document.querySelector('iframe').contentDocument;"
                                            " return [d.body.dataset.state, d.getElementById('gawah-line').textContent,"
                                            " d.getElementById('timer').textContent]; })()")
                    step(f"Ramesh's page in the frame: {framed}")
                    report["ramesh_page"] = framed
                previous = line
            await actor_says(said_before, 20)
            await floor_free(4.0, 30)
            step("Sunita leaves; the actor is stopped")
            await sunita.click("leave")
            stopped = await http.post("/actor/stop", json={"deal_id": deal_id, "role": "worker"})
            step(f"actor stop: {stopped.json()}; it left because: {actor().reason}")
            end = time.monotonic() + 60
            while not got("call.ended") and time.monotonic() < end:
                await asyncio.sleep(0.5)
            in_room = time.monotonic() - joined_at
            joined_at = None
            ended = got("call.ended")
            step(f"call.ended: {ended[0].reason if ended else 'NOT RECEIVED'} after {ended[0].duration if ended else '?'} s")
            await asyncio.sleep(3)
            rooms = await app.state.calls.livekit.list_rooms()
            step(f"rooms open on LiveKit now: {rooms}")

            transcript = [(e.call_no, e.line_no, e.speaker.value, e.text) for e in got("transcript.line")]
            spoke = [e.text for e in got("judge.spoke") if e.text]
            report.update({
                "actor_said": actor().said, "actor_heard": actor().heard, "transcript": transcript, "gawah_said": spoke,
                "worker_lines_in_transcript": sum(1 for t in transcript if t[2] == "worker"),
                "checklist": [(i.key.value, i.state.value) for i in (got("checklist.updated") or [None])[-1].items] if got("checklist.updated") else None,
                "rooms_after": rooms, "seconds_in_room": round(in_room, 1),
                "participant_minutes_estimate": round(in_room * 4 / 60, 1),
            })
    finally:
        sunita.close()
        if joined_at:
            report["seconds_in_room"] = round(time.monotonic() - joined_at, 1)
        server.should_exit = True
        await serving
        if Taped.tape:
            SAMPLE.parent.mkdir(parents=True, exist_ok=True)
            with wave.open(str(SAMPLE), "wb") as w:
                w.setnchannels(1), w.setsampwidth(2), w.setframerate(RATE)
                w.writeframes(bytes(Taped.tape[: SAMPLE_S * RATE * 2]))
        (out / "report.json").write_text(json.dumps(report, indent=1, ensure_ascii=False, default=str))
        print(json.dumps({k: report.get(k) for k in ("actor_said", "gawah_said", "worker_lines_in_transcript", "rooms_after",
                                                     "seconds_in_room", "participant_minutes_estimate")}, indent=1, ensure_ascii=False))
        print(f"saved to {out}")


if __name__ == "__main__":
    asyncio.run(main(int(sys.argv[1]) if len(sys.argv) > 1 else 26))
