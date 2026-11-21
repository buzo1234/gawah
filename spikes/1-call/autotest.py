"""Automated checks for spikes 1 and 3. No human: headless Chrome plays the user's recordings
as a fake microphone. Usage:  ./py.sh autotest.py prep|phase1|phase2|phase2b|phase3|rooms

Every phase opens one room, closes it in `finally`, and logs participant-minutes.
"""

import asyncio
import json
import os
import signal
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

import httpx
import numpy as np

import lk
from agent import Agent, Recorder
from lk import ENV, OUT, RESULTS, now
from server import PORT, build, serve

FIXTURES = Path("/Users/karan/Documents/personal/builders/fixtures/audio")
SCRATCH = Path(os.environ.get("SPIKE_SCRATCH", tempfile.gettempdir())) / "gawah-spike-1"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
TEXTS = json.loads((FIXTURES / "state.json").read_text())
transcribe_calls = 0

ASKS = [
    "Ask Sunita when the balance will be paid.",
    "Ask Ramesh on which date the work will be finished.",
    "Two different totals were said, 22 thousand and 25 thousand. Ask both of them which one is final.",
    "Ask Sunita how much advance she will give.",
    "Ask Ramesh what happens if the work is not finished on time.",
]
READ_BACK = (
    "Read back all of these agreed terms slowly, one by one, and at the end ask both if this is correct: "
    "painting of a two BHK flat in Indirapuram including the balcony grill; Tractor Emulsion, two coats, with putty touch-up; "
    "material is the painter's; total 22 thousand rupees; 5 thousand advance tomorrow by UPI; 7 thousand when half the work is done; "
    "10 thousand on completion; work starts next Monday at 9 in the morning; finished by Friday."
)


def read16k(name: str) -> np.ndarray:
    with wave.open(str(FIXTURES / name), "rb") as w:
        assert w.getframerate() == 16000 and w.getnchannels() == 1
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)


def write48k(path: Path, samples16k: np.ndarray) -> None:
    raw = path.with_suffix(".16k.wav")
    with wave.open(str(raw), "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(16000)
        w.writeframes(samples16k.astype(np.int16).tobytes())
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(raw), "-ar", "48000", "-ac", "1", str(path)], check=True)
    raw.unlink()


def prep() -> None:
    """Build the fake microphones in the scratch folder (the user's voice never enters the repo)."""
    SCRATCH.mkdir(parents=True, exist_ok=True)
    silence = lambda s: np.zeros(int(16000 * s), dtype=np.int16)
    tracks = {"Sunita": [], "Ramesh": []}
    for n in range(1, 11):
        key = f"paint-{n:02d}"
        audio = read16k(TEXTS[key]["wav"])
        for speaker, parts in tracks.items():
            parts.append(audio if TEXTS[key]["speaker"] == speaker else silence(len(audio) / 16000))
            parts.append(silence(0.6))
    write48k(SCRATCH / "sunita.wav", np.concatenate(tracks["Sunita"]))
    write48k(SCRATCH / "ramesh.wav", np.concatenate(tracks["Ramesh"]))
    write48k(SCRATCH / "barge.wav", np.concatenate([read16k("paint-03.wav"), silence(9)]))
    write48k(SCRATCH / "silent.wav", silence(10))
    for f in sorted(SCRATCH.glob("*.wav")):
        with wave.open(str(f)) as w:
            print(f.name, round(w.getnframes() / w.getframerate(), 1), "s")


def chrome(room: str, identity: str, wav: str) -> subprocess.Popen:
    profile = tempfile.mkdtemp(prefix=f"chrome-{identity}-", dir=SCRATCH)
    return subprocess.Popen(
        [
            CHROME, "--headless=new", f"--user-data-dir={profile}", "--no-first-run", "--no-default-browser-check",
            "--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream",
            f"--use-file-for-fake-audio-capture={SCRATCH / wav}",
            "--autoplay-policy=no-user-gesture-required", "--mute-audio", "--disable-gpu",
            "--disable-features=AudioServiceSandbox",  # without this the sandboxed audio service cannot read the wav and sends silence
            f"http://127.0.0.1:{PORT}/?room={room}&name={identity}&auto=1",
        ],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


async def until(cond, timeout: float, what: str) -> float | None:
    start = now()
    while now() - start < timeout:
        if cond():
            return round(now() - start, 2)
        await asyncio.sleep(0.02)
    print(f"TIMEOUT after {timeout}s waiting for {what}", flush=True)
    return None


def count(agent: Agent, kind: str, who: str) -> int:
    return sum(1 for e in agent.events if e["event"] == kind and e.get("who") == who)


async def transcribe(path: Path, seconds: float | None = None) -> str:
    global transcribe_calls
    data = path.read_bytes()
    if seconds:
        clip = path.with_suffix(".clip.wav")
        with wave.open(str(path)) as src, wave.open(str(clip), "wb") as dst:
            dst.setparams(src.getparams())
            dst.writeframes(src.readframes(int(src.getframerate() * seconds)))
        data = clip.read_bytes()
    transcribe_calls += 1
    async with httpx.AsyncClient(timeout=90) as client:
        r = await client.post(
            "https://api.openai.com/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {ENV['OPENAI_API_KEY']}"},
            files={"file": (path.name, data, "audio/wav")},
            data={"model": "gpt-transcribe"},
        )
    return r.json().get("text", f"ERROR {r.status_code}: {r.text[:200]}")


class Rig:
    def __init__(self, label: str, **agent_args):
        self.label = label
        self.agent_args = agent_args
        self.browsers: list[subprocess.Popen] = []

    async def __aenter__(self):
        self.room = await lk.open_room(self.label)
        print(f"room {self.room} opened", flush=True)
        try:
            self.out = OUT / self.label
            self.agent = Agent(self.room, self.out, **self.agent_args)
            self.app = build(self.room, self.agent)
            self.server, self.server_task = await serve(self.app)
            await self.agent.start()
            self.recorder = Recorder(self.room, self.out)
            await self.recorder.start()
        except BaseException:
            await lk.close_room(self.room)
            raise
        return self

    def browser(self, identity: str, wav: str) -> subprocess.Popen:
        proc = chrome(self.room, identity, wav)
        self.browsers.append(proc)
        return proc

    async def __aexit__(self, *exc):
        for proc in self.browsers:
            if proc.poll() is None:
                proc.send_signal(signal.SIGKILL)
        seconds = self.agent.seconds_by_identity()
        await self.recorder.stop()
        await self.agent.stop()
        await lk.close_room(self.room)
        self.server.should_exit = True
        await self.server_task
        self.minutes = lk.log_usage(self.room, self.label, seconds)
        print(f"room {self.room} closed. participant-minutes: {self.minutes}. rooms still open: {await lk.list_rooms()}", flush=True)


def save(name: str, data: dict) -> None:
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / name).write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n")
    print(f"wrote results/{name}")


async def phase1() -> None:
    """Spike 1: join, hear each other, separate tracks, drop and rejoin. Also 65 s of Gawah staying silent
    while the model is fed Sunita's audio with turn detection off."""
    res: dict = {}
    async with Rig("p1", feed_to_model="sunita") as rig:
        agent, rec = rig.agent, rig.recorder
        t_launch = now()
        rig.browser("sunita", "sunita.wav")
        ramesh = rig.browser("ramesh", "ramesh.wav")
        res["both_tracks_subscribed_after_s"] = await until(
            lambda: count(agent, "first_audio_frame", "sunita") and count(agent, "first_audio_frame", "ramesh"), 40, "both tracks")
        if res["both_tracks_subscribed_after_s"] is None:
            raise RuntimeError(f"browsers did not join; page reports: {rig.app.state.reports}")
        t_talk = now()
        for _ in range(13):
            await asyncio.sleep(5)
            print("levels", {p.identity: (p.db, p.speaking) for p in agent.people.values()}, "gawah frames heard:", len(rec.frames.get("gawah", [])), flush=True)
        gawah_frames = rec.frames.get("gawah", [])
        res["silence_test"] = {
            "seconds": round(now() - t_talk, 1),
            "people_speech_starts": {p.identity: len(p.speech_starts) for p in agent.people.values()},
            "responses_without_trigger": agent.mouth.unsolicited,
            "model_events_seen": agent.mouth.event_counts,
            "model_errors": agent.mouth.errors,
            "gawah_track_frames_at_recorder": len(gawah_frames),
            "gawah_track_loudest_db": max((db for _, db in gawah_frames), default=None),
            "gawah_frames_louder_than_-80db": sum(1 for _, db in gawah_frames if db > -80),
        }
        res["page_stats_before_drop"] = {k: v for k, v in rig.app.state.reports.items()}
        res["agent_receives"] = agent.first_frames
        res["recorder_receives_sdk_default"] = rec.first_frames

        t = now()
        ramesh.send_signal(signal.SIGKILL)
        gone = await until(lambda: count(agent, "participant_disconnected", "ramesh") >= 1, 60, "ramesh dropped")
        res["hard_drop_noticed_after_s"] = gone
        t = now()
        rig.browser("ramesh", "ramesh.wav")
        res["rejoin_audio_after_s"] = await until(lambda: count(agent, "first_audio_frame", "ramesh") >= 2, 40, "ramesh rejoined")
        await asyncio.sleep(6)

        rig.browser("sunita", "sunita.wav")  # same identity joins again while the first is still connected
        res["second_sunita_audio_after_s"] = await until(lambda: count(agent, "first_audio_frame", "sunita") >= 2, 40, "duplicate sunita")
        await asyncio.sleep(6)
        res["page_stats_after_rejoin"] = {k: v for k, v in rig.app.state.reports.items()}

        rig.app.state.leave.update({"sunita", "ramesh"})
        t = now()
        res["clean_leave_noticed_after_s"] = await until(
            lambda: count(agent, "participant_disconnected", "ramesh") >= 2 and count(agent, "participant_disconnected", "sunita") >= 2, 15, "clean leave")
        res["events"] = agent.events
        res["files"] = {p.identity: [Path(f).name for f in p.files] for p in agent.people.values()}
        files = {p.identity: p.files for p in agent.people.values()}
    res["participant_minutes"] = rig.minutes
    res["transcripts"] = {}
    for who in ("sunita", "ramesh"):
        expected = " ".join(TEXTS[f"paint-{n:02d}"]["text"] for n in range(1, 7) if TEXTS[f"paint-{n:02d}"]["speaker"].lower() == who)
        heard = await transcribe(Path(files[who][0]), seconds=40)
        res["transcripts"][who] = {"played_into_fake_mic": expected, "gpt_transcribe_of_agent_recording_first_40s": heard}
        print(f"\n{who}\n  played: {expected}\n  heard:  {heard}")
    res["transcribe_calls"] = transcribe_calls
    save("phase1.json", res)


async def rooms() -> None:
    print("rooms open on the project:", await lk.list_rooms())


if __name__ == "__main__":
    what = sys.argv[1]
    if what == "prep":
        prep()
    else:
        import autotest_mouth as m

        phases = {"phase1": phase1, "phase2": m.phase2, "phase2b": m.phase2b, "phase3": m.phase3, "rooms": rooms}
        asyncio.run(asyncio.wait_for(phases[what](), 420))
