"""The bridge's proof on a real call. Not a test: pytest does not collect it, and it uses
the free plans, so run it by hand and count what it used.

    uv run python tests/bridge_live.py [--drop | --leave hirer | --leave worker]

It starts the real app on a free port, creates a deal, and opens the two call links in two
headless Chrome browsers. Each browser plays some of the recorded Hinglish lines as its
microphone. Mid-call the worker's microphone is muted for a few seconds, as a phone does
when its screen locks, and a third browser screenshots the dashboard. Then both people
leave, and the script checks the events a dashboard client received, the transcript against
what was played, and the two recordings in S3 against the transcript's times.

With --leave hirer (or worker): that person taps leave after four lines and the other stays,
so the call ends on the "gone for a while" limit.

With --drop: the hirer reloads the page and rejoins mid-call, then the worker's browser is
killed and never comes back, so the call ends on the "gone for a while" limit.

Uses: one LiveKit room for 1 to 1.5 minutes (3 participants, 3 to 4 participant-minutes),
about 10 gpt-transcribe uploads, 2 S3 uploads. Sage2 and Twilio are switched off for this server.
"""

import asyncio
import json
import signal
import socket
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
from bridge_world import SPOKEN, frames, recorded  # noqa: E402
from browser import CHROME, Chrome  # noqa: E402

from app.config import ROOT, get_settings  # noqa: E402
from app.contracts import DealRequested, Person, Role, call_path, new_id, parse_event  # noqa: E402
from app.ears.vad import RATE, Segmenter  # noqa: E402
from app.main import create_app  # noqa: E402
from app.store import S3  # noqa: E402

PLAYED = ["paint-01", "paint-02", "paint-03", "paint-04", "paint-11", "paint-12", "paint-22", "paint-23"]
LEAD_IN = 8.0  # silence at the start of both microphones, while the two people join
BETWEEN = 1.0
OUT = ROOT / "recordings" / "proof"  # ignored by git
SPEAKER = {"Sunita": Role.HIRER, "Ramesh": Role.WORKER}


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def build_microphones(folder: Path) -> tuple[dict[Role, Path], list[dict]]:
    """One wav per person on a shared timeline: their own lines, silence during the other's."""
    tracks = {role: [np.zeros(int(LEAD_IN * RATE), dtype=np.int16)] for role in Role}
    plan, at = [], LEAD_IN
    for name in PLAYED:
        audio = np.frombuffer(recorded(name), dtype=np.int16)
        who = SPEAKER[SPOKEN[name]["speaker"]]
        for role in Role:
            tracks[role].append(audio if role is who else np.zeros(len(audio), dtype=np.int16))
            tracks[role].append(np.zeros(int(BETWEEN * RATE), dtype=np.int16))
        plan.append({"name": name, "speaker": who, "text": SPOKEN[name]["text"], "at": at, "until": at + len(audio) / RATE})
        at += len(audio) / RATE + BETWEEN
    paths = {}
    for role in Role:
        raw, paths[role] = folder / f"{role.value}-16k.wav", folder / f"{role.value}.wav"
        with wave.open(str(raw), "wb") as w:
            w.setnchannels(1), w.setsampwidth(2), w.setframerate(RATE)
            w.writeframes(np.concatenate(tracks[role]).tobytes())
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(raw), "-ar", "48000", "-ac", "1", str(paths[role])], check=True)
    return paths, plan


class CallBrowser:
    """Headless Chrome whose microphone is a wav file, driven over its debugging socket."""

    def __init__(self, folder: Path, role: Role, microphone: Path) -> None:
        self.role, self.port = role, free_port()
        self.proc = subprocess.Popen(
            [
                CHROME, "--headless=new", f"--user-data-dir={tempfile.mkdtemp(prefix=role.value, dir=folder)}",
                f"--remote-debugging-port={self.port}", "--no-first-run", "--no-default-browser-check",
                "--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream",
                f"--use-file-for-fake-audio-capture={microphone}%noloop",
                "--autoplay-policy=no-user-gesture-required", "--mute-audio", "--disable-gpu",
                # Without this the sandboxed audio service cannot read the wav and sends silence (spike 1).
                "--disable-features=AudioServiceSandbox",
                "about:blank",
            ],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        self._id = 0

    async def open(self, url: str) -> None:
        async with httpx.AsyncClient() as http:
            for _ in range(100):
                try:
                    pages = [t for t in (await http.get(f"http://127.0.0.1:{self.port}/json/list")).json() if t["type"] == "page"]
                    if pages:
                        break
                except httpx.HTTPError:
                    pass
                await asyncio.sleep(0.1)
            else:
                raise RuntimeError("Chrome did not start")
        self.ws = await connect(pages[0]["webSocketDebuggerUrl"], max_size=None)
        await self.js(f"location.href = {json.dumps(url)}")
        await self.until("document.readyState === 'complete' && !!document.getElementById('join')")

    async def js(self, expression: str):
        self._id += 1
        await self.ws.send(json.dumps({"id": self._id, "method": "Runtime.evaluate", "params": {
            "expression": expression, "awaitPromise": True, "returnByValue": True, "userGesture": True}}))
        while True:
            msg = json.loads(await asyncio.wait_for(self.ws.recv(), 30))
            if msg.get("id") == self._id:
                result = msg["result"]
                if "exceptionDetails" in result:
                    raise RuntimeError(str(result["exceptionDetails"])[:400])
                return result["result"].get("value")

    async def until(self, expression: str, timeout: float = 20.0) -> None:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            try:
                if await self.js(expression):
                    return
            except RuntimeError:
                pass
            await asyncio.sleep(0.1)
        raise TimeoutError(f"{self.role.value}: never true: {expression}")

    async def state(self) -> str:
        return await self.js("document.body.dataset.state")

    async def hears(self) -> dict:
        """Who this page sees in the room and how much audio it has received from each."""
        return await self.js("""(async () => {
          const out = {};
          for (const p of room.remoteParticipants.values()) {
            const entry = out[p.identity] = { packets: 0, energy: 0 };
            for (const pub of p.trackPublications.values()) {
              if (!pub.track || !pub.track.receiver) continue;
              (await pub.track.receiver.getStats()).forEach((s) => {
                if (s.type === 'inbound-rtp' && s.kind === 'audio') { entry.packets = s.packetsReceived; entry.energy = +s.totalAudioEnergy.toFixed(3); }
              });
            }
          }
          return out;
        })()""")

    def kill(self) -> None:
        if self.proc.poll() is None:
            self.proc.send_signal(signal.SIGKILL)


def offset_guess(started, clicked) -> float:
    """Seconds from the join taps to time zero: what to take off a microphone time to get a call time."""
    return (started.ts - clicked).total_seconds()


def detected(wav_bytes: bytes) -> tuple[float, list[tuple[float, float]]]:
    """The length of a recording and the lines our own detector finds in it."""
    import io

    with wave.open(io.BytesIO(wav_bytes)) as w:
        assert (w.getframerate(), w.getnchannels(), w.getsampwidth()) == (RATE, 1, 2)
        pcm = w.readframes(w.getnframes())
    segmenter, found = Segmenter(), []
    for i, frame in enumerate(frames(pcm)):
        line = segmenter.feed(frame, i * 0.02)
        if line and not line.is_noise:
            found.append((round(line.start, 2), round(line.end, 2)))
    return len(pcm) / 2 / RATE, found


async def main(drop: bool, leaver: Role | None) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    scratch = Path(tempfile.mkdtemp(prefix="bridge-live-"))
    microphones, plan = build_microphones(scratch)
    # The real settings, minus the services this stream must not touch: without a Sage2 key the
    # brain stays quiet on a real room, and the made-up numbers below are never messaged.
    settings = get_settings().model_copy(update={
        "sage_api_key": None, "twilio_account_sid": None, "twilio_auth_token": None,
        "database_path": str(scratch / "proof.db"),
    })
    app = create_app(settings)
    calls = app.state.calls
    calls.limits.max_age = 240
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    serving = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.05)

    deal_id = f"proof{new_id()[:6]}"
    room = f"deal-{deal_id}-1"
    received: list = []  # (when it arrived, event), as a dashboard client sees them
    browsers: dict[Role, CallBrowser] = {}
    seconds_in_room: dict[str, float] = {}
    report: dict = {"deal_id": deal_id, "room": room, "drop": drop, "one_leaves": leaver.value if leaver else None}
    try:
        async with httpx.AsyncClient() as http, connect(f"ws://127.0.0.1:{port}/dashboard/ws") as ws:
            async def watch() -> None:
                async for raw in ws:
                    received.append((datetime.now(UTC), parse_event(raw)))

            watching = asyncio.create_task(watch())

            def got(name: str) -> list:
                return [e for _, e in received if e.name == name and e.deal_id == deal_id]

            async def wait_for(name: str, timeout: float) -> None:
                end = time.monotonic() + timeout
                while not got(name):
                    if time.monotonic() > end:
                        raise TimeoutError(f"no {name} within {timeout}s")
                    await asyncio.sleep(0.05)

            requested = DealRequested(
                deal_id=deal_id, requested_by=Person(role=Role.HIRER, name="Sunita", phone="+910000000001"),
                other=Person(role=Role.WORKER, phone="+910000000002"), text="Ramesh painter se flat paint karwana hai",
            )
            (await http.post(f"{base}/dev/publish", content=requested.model_dump_json())).raise_for_status()
            assert (await http.get(f"{base}/call/{deal_id}/judge")).status_code == 404

            for role in Role:
                browsers[role] = CallBrowser(scratch, role, microphones[role])
            await asyncio.gather(*(b.open(base + call_path(deal_id, b.role)) for b in browsers.values()))
            assert calls.sessions == {}, "opening the page must not open a room"

            clicked = datetime.now(UTC)
            t_click = time.monotonic()
            await asyncio.gather(*(b.js("document.getElementById('join').click()") for b in browsers.values()))
            await wait_for("call.started", 20)
            started = got("call.started")[0]
            session = calls.sessions[deal_id]
            report["join_to_call_started_s"] = round((started.ts - clicked).total_seconds(), 2)
            print(f"call.started {report['join_to_call_started_s']}s after the two taps: room={started.room} people={[(p.role.value, p.name) for p in started.people]}", flush=True)
            await asyncio.gather(*(b.until("document.body.dataset.state === 'on'") for b in browsers.values()))

            async def sleep_until(at: float) -> None:
                await asyncio.sleep(max(0.0, at - time.monotonic()))

            if drop:
                # After two lines the hirer reloads the page and taps join again: the same identity
                # with a new participant and a new track. Their microphone file starts over.
                hirer = browsers[Role.HIRER]
                await sleep_until(t_click + plan[1]["until"] + 0.8)
                await hirer.js("location.reload()")
                await asyncio.sleep(0.5)
                await hirer.until("document.readyState === 'complete' && document.body.dataset.state === 'idle'")
                t_rejoin = time.monotonic()
                await hirer.js("document.getElementById('join').click()")
                await hirer.until("document.body.dataset.state === 'on'")
                report["reload_at_s"] = round(t_rejoin - t_click - offset_guess(started, clicked), 1)
                report["rejoin_took_s"] = round(time.monotonic() - t_rejoin, 2)
                print(f"hirer reloaded and rejoined in {report['rejoin_took_s']}s", flush=True)
                await sleep_until(t_rejoin + plan[0]["until"] + 1.5)  # their first line, played again
            elif leaver:
                await sleep_until(t_click + plan[3]["until"] + 2.0)  # four lines in
            else:
                # While the hirer says their second line, the worker's microphone is muted, as a
                # phone does when its screen locks. The worker has nothing to say in that stretch.
                worker = browsers[Role.WORKER]
                await sleep_until(t_click + plan[2]["at"] + 1.0)
                await worker.js("room.localParticipant.setMicrophoneEnabled(false)")
                await asyncio.sleep(1.0)
                report["while_muted"] = {
                    "worker_page_says_microphone_is_off": await worker.js("!document.getElementById('mic-quiet').hidden"),
                    "worker_page_says_keep_page_open": await worker.js("!document.getElementById('keep-open').hidden"),
                    "worker_page_state": await worker.state(),
                    "people_the_call_counts_as_present": sorted(r.value for r in session.present),
                }
                await sleep_until(t_click + plan[2]["until"] - 1.0)
                await worker.js("room.localParticipant.setMicrophoneEnabled(true)")
                await asyncio.sleep(0.5)
                report["after_unmute_worker_page_says_microphone_is_off"] = await worker.js("!document.getElementById('mic-quiet').hidden")
                print(f"worker muted for {plan[2]['until'] - plan[2]['at'] - 2.0:.1f}s: {report['while_muted']}", flush=True)
                # Mid-call: the dashboard as the big screen shows it.
                await sleep_until(t_click + plan[5]["at"])
                async with Chrome(port=free_port()) as dashboard:
                    await dashboard.goto(f"{base}/dashboard?deal={deal_id}")
                    await asyncio.sleep(1.5)
                    await dashboard.shot(OUT / "dashboard-midcall.png")
                await sleep_until(t_click + max(p["until"] for p in plan) + 2.5)

            report["pages"] = {b.role.value: {"state": await b.state(), "sees_and_hears": await b.hears()} for b in browsers.values()}
            if drop:
                browsers[Role.WORKER].kill()
                t_kill = time.monotonic()
                print("worker's browser killed; waiting for LiveKit to notice and for the 'gone' limit...", flush=True)
                await wait_for("call.ended", 60)
                report["kill_to_call_ended_s"] = round(time.monotonic() - t_kill, 1)
                seconds_in_room = {"hirer": time.monotonic() - t_click, "worker": t_kill - t_click + 22}
                report["hirer_page_after"] = await browsers[Role.HIRER].state()
            elif leaver:
                stays = leaver.other
                t_leave = time.monotonic()
                await browsers[leaver].js("document.getElementById('leave').click()")
                print(f"{leaver.value} tapped leave; {stays.value} stays on the line...", flush=True)
                await wait_for("call.ended", 60)
                report["one_leaves_to_call_ended_s"] = round(time.monotonic() - t_leave, 1)
                seconds_in_room = {leaver.value: t_leave - t_click, stays.value: time.monotonic() - t_click}
                report["pages_after"] = {b.role.value: await b.state() for b in browsers.values()}
            else:
                t_leave = time.monotonic()
                await asyncio.gather(*(b.js("document.getElementById('leave').click()") for b in browsers.values()))
                await wait_for("call.ended", 30)
                report["leave_to_call_ended_s"] = round(time.monotonic() - t_leave, 1)
                seconds_in_room = {r.value: t_leave - t_click for r in Role}
                report["pages_after"] = {b.role.value: await b.state() for b in browsers.values() if b.proc.poll() is None}
            seconds_in_room[" listener"] = time.monotonic() - t_click
            await asyncio.sleep(0.5)
            watching.cancel()

        ended = got("call.ended")[0]
        lines = got("transcript.line")
        offset = (started.ts - clicked).total_seconds()  # microphone time minus call time, roughly
        print(f"\ncall.ended reason={ended.reason} duration={ended.duration}s recording_keys={ended.recording_keys}")
        print("\nevents the dashboard client received for this deal, in order:")
        print("  " + " ".join(e.name for _, e in received if e.deal_id == deal_id and e.name != "whatsapp.message"))
        print(f"call.started events: {len(got('call.started'))}")
        if leaver:
            print(f"pages after: {report['pages_after']}; call.ended {report['one_leaves_to_call_ended_s']}s after {leaver.value} left")
        if drop:
            print("\ntranscript lines (the hirer's microphone started over when they rejoined):")
            for e in lines:
                print(f"  line {e.line_no} {e.speaker.value:6} {e.start:5.1f}-{e.end:5.1f}s  {e.text}")
        else:
            print("\nplayed (microphone file)                         | heard (transcript.line)")
        for p in plan if not drop else []:
            print(f"  {p['speaker'].value:6} {p['at'] - offset:5.1f}-{p['until'] - offset:5.1f}s  {p['text']}")
            for e in lines:
                if e.speaker is p["speaker"] and p["at"] - offset - 1.0 <= e.start <= p["until"] - offset + 0.5:
                    delay = (next(t for t, x in received if x is e) - started.ts).total_seconds() - e.end
                    print(f"      -> line {e.line_no} {e.speaker.value:6} {e.start:5.1f}-{e.end:5.1f}s  ({delay:.2f}s after it ended)  {e.text}")
        delays = sorted(session.ears.delays)
        report["delay_line_end_to_event_s"] = {"n": len(delays), "median": round(delays[len(delays) // 2], 2), "max": round(delays[-1], 2)} if delays else {}
        report["line_numbers"] = [e.line_no for e in lines]
        report["lines"] = [{"line_no": e.line_no, "speaker": e.speaker.value, "start": e.start, "end": e.end, "text": e.text} for e in lines]

        print("\nrecordings in S3 against the transcript's times:")
        s3 = S3(settings)
        async with httpx.AsyncClient(timeout=60) as http:
            for role in Role:
                key = ended.recording_keys.get(role.value)
                if not key:
                    print(f"  {role.value}: NO RECORDING KEY")
                    continue
                wav = (await http.get(await s3.signed_url(key, 120))).content
                seconds, found = detected(wav)
                said = [(e.start, e.end) for e in lines if e.speaker is role]
                print(f"  {key}: {len(wav)} bytes, {seconds:.2f}s (call was {ended.duration}s)")
                print(f"    lines found in the file: {found}")
                print(f"    transcript lines:        {said}")
                report.setdefault("recordings", {})[role.value] = {
                    "key": key, "bytes": len(wav), "seconds": round(seconds, 2), "found_in_file": found, "transcript": said}
    finally:
        for b in browsers.values():
            b.kill()
        server.should_exit = True  # shutdown closes every session: listener out, room deleted
        await serving
        from app.call.livekit import LiveKit

        livekit = LiveKit(settings)
        await asyncio.sleep(3)  # a deleted room can still be listed for a few seconds (spike 1)
        left = await livekit.list_rooms()
        if room in left:
            await livekit.delete_room(room)
        await livekit.close()
        minutes = round(sum(seconds_in_room.values()) / 60, 2)
        report.update(rooms_left_on_project=left, participant_minutes=minutes,
                      seconds_in_room={k.strip(): round(v) for k, v in seconds_in_room.items()},
                      transcription_calls=calls.transcriber.calls)
        print(f"\nrooms on the LiveKit project now: {left}")
        print(f"participant-minutes: {minutes}  transcription uploads: {calls.transcriber.calls}  S3 uploads: {len(report.get('recordings', {}))}")
        name = "live-drop.json" if drop else f"live-{leaver.value}-leaves.json" if leaver else "live.json"
        (OUT / name).write_text(json.dumps(report, indent=1, ensure_ascii=False, default=str) + "\n")
        print(f"wrote {OUT / name}" + ("" if drop or leaver else f" and {OUT / 'dashboard-midcall.png'}"))


if __name__ == "__main__":
    leaves = Role(sys.argv[sys.argv.index("--leave") + 1]) if "--leave" in sys.argv else None
    asyncio.run(asyncio.wait_for(main("--drop" in sys.argv, leaves), 300))
