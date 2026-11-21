"""The second-call proof on real calls. Not a test: pytest does not collect it, and it uses
the free plans, so run it by hand and count what it used.

    uv run python tests/bridge_followup_live.py

It starts the real app on a free port, creates a deal, and opens the two call links in two
headless Chrome browsers whose microphones play recorded Hinglish lines. Call 1: both join,
talk, and leave. The pages then show "Phir se baat karein"; both tap it on the same open
pages, and call 2 runs the same way. Then it checks, for each call: its own room, its
call.started and call.ended with the call number, transcript lines numbered from 1 with
times from that call's start, and the two recordings in S3 against those times. Gawah's
voice (mouth) joins each call as it does the first.

Uses: two LiveKit rooms one after the other, about 1 minute each, 4 participants (2 people,
the listener, Gawah's voice): about 8 participant-minutes in all. About 10 gpt-transcribe
uploads, 4 S3 uploads, two short realtime voice sessions for Gawah's opening line.
Sage2 and Twilio are switched off for this server.
"""

import asyncio
import json
import subprocess
import sys
import tempfile
import time
import wave
from datetime import UTC, datetime
from pathlib import Path

import httpx
import numpy as np
import uvicorn
from websockets.asyncio.client import connect

sys.path[:0] = [str(Path(__file__).parent), str(Path(__file__).parent.parent)]
from bridge_live import SPEAKER, CallBrowser, detected, free_port  # noqa: E402
from bridge_world import SPOKEN, recorded  # noqa: E402
from browser import Chrome  # noqa: E402

from app.config import ROOT, get_settings  # noqa: E402
from app.contracts import DealRequested, Person, Role, call_path, new_id, parse_event  # noqa: E402
from app.ears.vad import RATE  # noqa: E402
from app.store import S3  # noqa: E402
from app.main import create_app  # noqa: E402

PLAYED = ["paint-01", "paint-02", "paint-03", "paint-04"]
LEAD_IN = 12.0  # silence at the start of both microphones: the two join and Gawah says its opening line
BETWEEN = 1.0
OUT = ROOT / "recordings" / "proof"  # ignored by git


def build_microphones(folder: Path) -> tuple[dict[Role, Path], list[dict]]:
    tracks = {role: [np.zeros(int(LEAD_IN * RATE), dtype=np.int16)] for role in Role}
    plan, at = [], LEAD_IN
    for name in PLAYED:
        audio = np.frombuffer(recorded(name), dtype=np.int16)
        who = SPEAKER[SPOKEN[name]["speaker"]]
        for role in Role:
            tracks[role] += [audio if role is who else np.zeros(len(audio), dtype=np.int16),
                             np.zeros(int(BETWEEN * RATE), dtype=np.int16)]
        plan.append({"name": name, "speaker": who, "at": at, "until": at + len(audio) / RATE})
        at += len(audio) / RATE + BETWEEN
    paths = {}
    for role in Role:
        raw, paths[role] = folder / f"{role.value}-16k.wav", folder / f"{role.value}.wav"
        with wave.open(str(raw), "wb") as w:
            w.setnchannels(1), w.setsampwidth(2), w.setframerate(RATE)
            w.writeframes(np.concatenate(tracks[role]).tobytes())
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(raw), "-ar", "48000", "-ac", "1", str(paths[role])], check=True)
    return paths, plan


async def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    scratch = Path(tempfile.mkdtemp(prefix="followup-live-"))
    microphones, plan = build_microphones(scratch)
    settings = get_settings().model_copy(update={
        "sage_api_key": None, "twilio_account_sid": None, "twilio_auth_token": None,
        "database_path": str(scratch / "proof.db"),
    })
    app = create_app(settings)
    calls = app.state.calls
    calls.limits.max_age = 150
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    serving = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.05)

    deal_id = f"proof{new_id()[:6]}"
    rooms = [f"deal-{deal_id}-1", f"deal-{deal_id}-2"]
    received: list = []
    browsers: dict[Role, CallBrowser] = {}
    seconds_in_room = 0.0  # participant-seconds, summed
    report: dict = {"deal_id": deal_id, "rooms": rooms, "calls": []}
    try:
        async with httpx.AsyncClient() as http, connect(f"ws://127.0.0.1:{port}/dashboard/ws") as ws:
            async def watch() -> None:
                async for raw in ws:
                    received.append((datetime.now(UTC), parse_event(raw)))

            watching = asyncio.create_task(watch())

            def got(name: str, **match) -> list:
                return [e for _, e in received if e.name == name and e.deal_id == deal_id
                        and all(getattr(e, k) == v for k, v in match.items())]

            async def wait_for(test, timeout: float, what: str) -> None:
                end = time.monotonic() + timeout
                while not test():
                    if time.monotonic() > end:
                        raise TimeoutError(f"no {what} within {timeout}s")
                    await asyncio.sleep(0.05)

            requested = DealRequested(
                deal_id=deal_id, requested_by=Person(role=Role.HIRER, name="Sunita", phone="+910000000001"),
                other=Person(role=Role.WORKER, phone="+910000000002"), text="Ramesh painter se flat paint karwana hai",
            )
            (await http.post(f"{base}/dev/publish", content=requested.model_dump_json())).raise_for_status()
            for role in Role:
                browsers[role] = CallBrowser(scratch, role, microphones[role])
            await asyncio.gather(*(b.open(base + call_path(deal_id, b.role)) for b in browsers.values()))

            for call_no, room in enumerate(rooms, 1):
                button = await browsers[Role.HIRER].js("document.getElementById('join').textContent")
                t_click = time.monotonic()
                clicked = datetime.now(UTC)
                await asyncio.gather(*(b.js("document.getElementById('join').click()") for b in browsers.values()))
                await wait_for(lambda: got("call.started", call_no=call_no, room=room), 20, f"call.started {call_no}")
                started = got("call.started", call_no=call_no)[0]
                print(f"call {call_no}: button {button!r}, call.started {(started.ts - clicked).total_seconds():.1f}s "
                      f"after the taps, room={started.room}", flush=True)
                await asyncio.gather(*(b.until("document.body.dataset.state === 'on'") for b in browsers.values()))
                await asyncio.sleep(max(0.0, t_click + plan[-1]["until"] + 2.5 - time.monotonic()))
                mouth = app.state.mouth.calls.get(deal_id)
                gawah_room = mouth.room_name if mouth else None
                t_leave = time.monotonic()
                await asyncio.gather(*(b.js("document.getElementById('leave').click()") for b in browsers.values()))
                await wait_for(lambda: got("call.ended", call_no=call_no), 30, f"call.ended {call_no}")
                ended = got("call.ended", call_no=call_no)[0]
                seconds_in_room += 2 * (t_leave - t_click) + 2 * (time.monotonic() - t_click)  # people; listener and Gawah
                # Both tapped leave, so both pages say "you left". Then the two ways back: the hirer
                # taps join on the same open page and is told the call is over, with a new one on
                # offer; the worker opens the link afresh, as from WhatsApp days later.
                left = {b.role.value: await b.state() for b in browsers.values()}
                await browsers[Role.HIRER].js("document.getElementById('join').click()")
                await browsers[Role.WORKER].open(base + call_path(deal_id, Role.WORKER))
                await asyncio.gather(*(b.until("document.body.dataset.state === 'ended'", 15) for b in browsers.values()))
                pages = {b.role.value: [left[b.role.value]] + await b.js(
                    "[document.body.dataset.state, document.getElementById('join').textContent,"
                    " !document.getElementById('join').hidden]") for b in browsers.values()}
                lines = got("transcript.line", call_no=call_no)
                spoke = [e for e in got("judge.spoke") if started.ts <= e.ts <= ended.ts]
                print(f"call {call_no}: ended ({ended.reason}) after {ended.duration}s, keys={ended.recording_keys}; "
                      f"Gawah was in {gawah_room}, said {[s.text for s in spoke]}; pages after: {pages}", flush=True)
                report["calls"].append({
                    "call_no": call_no, "button": button, "room": started.room, "ended_room": ended.room,
                    "duration": ended.duration, "reason": ended.reason, "recording_keys": ended.recording_keys,
                    "gawah_room": gawah_room, "gawah_said": [s.text for s in spoke], "pages_after": pages,
                    "lines": [{"call_no": e.call_no, "line_no": e.line_no, "speaker": e.speaker.value,
                               "start": e.start, "end": e.end, "text": e.text} for e in lines],
                })
                await asyncio.sleep(2.0)  # "days later"
            await asyncio.sleep(0.5)
            watching.cancel()

        print("\nevents the dashboard client received, in order:")
        print("  " + " ".join(f"{e.name}#{getattr(e, 'call_no', '')}" for _, e in received
                              if e.deal_id == deal_id and e.name != "whatsapp.message"))
        async with Chrome(port=free_port()) as dashboard:
            await dashboard.goto(f"{base}/dashboard?deal={deal_id}")
            await asyncio.sleep(1.5)
            await dashboard.shot(OUT / "dashboard-after-call-2.png")

        print("\nrecordings in S3 against each call's transcript times:")
        s3 = S3(settings)
        async with httpx.AsyncClient(timeout=60) as http:
            for call in report["calls"]:
                for role in Role:
                    key = call["recording_keys"].get(role.value)
                    if not key:
                        print(f"  call {call['call_no']} {role.value}: NO RECORDING KEY")
                        continue
                    wav = (await http.get(await s3.signed_url(key, 120))).content
                    seconds, found = detected(wav)
                    said = [(x["start"], x["end"]) for x in call["lines"] if x["speaker"] == role.value]
                    print(f"  {key}: {seconds:.2f}s (call was {call['duration']}s)")
                    print(f"    lines found in the file: {found}")
                    print(f"    transcript lines:        {said}")
                    call.setdefault("recordings", {})[role.value] = {"key": key, "seconds": round(seconds, 2),
                                                                     "found_in_file": found, "transcript": said}
            for call in report["calls"]:
                print(f"\ncall {call['call_no']} lines:")
                for x in call["lines"]:
                    print(f"  call {x['call_no']} line {x['line_no']} {x['speaker']:6} {x['start']:5.1f}-{x['end']:5.1f}s  {x['text']}")
    finally:
        for b in browsers.values():
            b.kill()
        server.should_exit = True
        await serving
        from app.call.livekit import LiveKit

        livekit = LiveKit(settings)
        await asyncio.sleep(3)  # a deleted room can still be listed for a few seconds (spike 1)
        left = await livekit.list_rooms()
        for room in rooms:
            if room in left:
                await livekit.delete_room(room)
        await livekit.close()
        report.update(rooms_left_on_project=left, participant_minutes=round(seconds_in_room / 60, 2),
                      transcription_calls=calls.transcriber.calls)
        print(f"\nrooms on the LiveKit project now: {left}")
        print(f"participant-minutes (2 people, listener, Gawah): {report['participant_minutes']}  "
              f"transcription uploads: {calls.transcriber.calls}  "
              f"S3 uploads: {sum(len(c['recording_keys']) for c in report['calls'])}")
        (OUT / "live-followup.json").write_text(json.dumps(report, indent=1, ensure_ascii=False, default=str) + "\n")
        print(f"wrote {OUT / 'live-followup.json'} and {OUT / 'dashboard-after-call-2.png'}")


if __name__ == "__main__":
    asyncio.run(asyncio.wait_for(main(), 300))
