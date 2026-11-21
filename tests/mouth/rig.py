"""The real-room rig behind prove_deal_call.py and prove_callback.py. Not a test: it opens
a real LiveKit room and talks to the real voice model, so pytest never runs it.

- The server is the real app (app.main.create_app) given only the OpenAI and LiveKit keys,
  so no other stream can reach Sage2, Twilio or S3 while the check runs.
- People are headless Chrome browsers on our own page, each playing a wav as its microphone.
- A listen-only bot records the room and stamps every 10 ms frame with its arrival time,
  so "when was it heard" is measured outside the code being checked.
- Recordings of people stay in a scratch folder outside the repo. Only Gawah's voice is kept.
"""

import asyncio
import json
import logging
import os
import signal
import socket
import subprocess
import tempfile
import time
import wave
from pathlib import Path

import httpx
import numpy as np
import uvicorn
from livekit import rtc

from app.config import Settings, get_settings
from app.contracts import Event
from app.main import create_app
from app.mouth.hearing import frame_db
from app.mouth.room import Rooms

ROOT = Path(__file__).resolve().parents[2]
AUDIO = ROOT / "fixtures" / "audio"
SAMPLES = ROOT / "fixtures" / "mouth-samples"
PAGE = ROOT / "app" / "mouth" / "page.html"
SCRATCH = Path(os.environ.get("MOUTH_SCRATCH", tempfile.gettempdir())) / "gawah-mouth-proof"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
now = time.monotonic


# ---- fake microphones ----

def recorded(name: str) -> np.ndarray:
    with wave.open(str(AUDIO / name), "rb") as w:
        assert w.getframerate() == 16000 and w.getnchannels() == 1
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)


def silence(seconds: float) -> np.ndarray:
    return np.zeros(int(16000 * seconds), dtype=np.int16)


def microphone(name: str, *parts: np.ndarray, rate: int = 16000) -> Path:
    """A wav Chrome plays, on a loop, as a person's microphone. Returns its path in the scratch folder."""
    SCRATCH.mkdir(parents=True, exist_ok=True)
    raw, path = SCRATCH / f"{name}.raw.wav", SCRATCH / f"{name}.wav"
    with wave.open(str(raw), "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(rate)
        w.writeframes(np.clip(np.concatenate(parts), -32768, 32767).astype(np.int16).tobytes())
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(raw), "-ar", "48000", "-ac", "1", str(path)], check=True)
    raw.unlink()
    return path


def noisy_room(seconds: float, db: float = -40.0) -> np.ndarray:
    """Steady noise with sharp clicks, at 24 kHz: a real room with nobody speaking."""
    from tests.mouth import sounds

    return sounds.room_noise(seconds, db) + sounds.clicks(seconds)


def chrome(url: str, wav: Path) -> subprocess.Popen:
    profile = tempfile.mkdtemp(prefix="chrome-", dir=SCRATCH)
    return subprocess.Popen(
        [
            CHROME, "--headless=new", f"--user-data-dir={profile}", "--no-first-run", "--no-default-browser-check",
            "--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream",
            f"--use-file-for-fake-audio-capture={wav}",
            "--autoplay-policy=no-user-gesture-required", "--mute-audio", "--disable-gpu",
            "--disable-features=AudioServiceSandbox",  # or the sandboxed audio service cannot read the wav and sends silence
            url,
        ],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


# ---- the listen-only bot ----

class Recorder:
    def __init__(self, rooms: Rooms, room_name: str) -> None:
        self.rooms, self.room_name = rooms, room_name
        self.room = rtc.Room()
        self.frames: dict[str, list[tuple[float, float]]] = {}  # identity -> (arrival time, dB) per 10 ms
        self.pcm: dict[str, bytearray] = {}
        self.rate = 48000
        self.seconds: dict[str, float] = {}  # identity -> time spent in the room, for the usage count
        self._since: dict[str, float] = {}
        self._tasks: list[asyncio.Task] = []

    async def start(self) -> None:
        @self.room.on("track_subscribed")
        def _subscribed(track, publication, participant):
            if track.kind == rtc.TrackKind.KIND_AUDIO:
                self._tasks.append(asyncio.create_task(self._listen(participant.identity, track)))

        @self.room.on("participant_connected")
        def _joined(participant):
            self._since[participant.identity] = now()

        @self.room.on("participant_disconnected")
        def _left(participant):
            self._gone(participant.identity)

        await self.room.connect(self.rooms.url, self.rooms.token(self.room_name, "recorder", publish=False))
        for identity in ["recorder", *self.room.remote_participants]:
            self._since[identity] = now()

    def _gone(self, identity: str) -> None:
        if identity in self._since:
            self.seconds[identity] = self.seconds.get(identity, 0.0) + now() - self._since.pop(identity)

    async def _listen(self, identity: str, track: rtc.Track) -> None:
        frames, pcm = self.frames.setdefault(identity, []), self.pcm.setdefault(identity, bytearray())
        async for event in rtc.AudioStream(track):  # SDK defaults: 48 kHz, 10 ms
            data = bytes(event.frame.data)
            frames.append((now(), frame_db(data)))
            pcm.extend(data)

    def heard(self, identity: str, after: float, before: float = 1e12, db: float = -50.0) -> list[float]:
        """Arrival times of this identity's frames louder than db."""
        return [t for t, level in self.frames.get(identity, []) if after <= t <= before and level > db]

    def levels(self, identity: str) -> str:
        levels = [db for _, db in self.frames.get(identity, [])]
        if not levels:
            return "no audio"
        p = np.percentile(levels, [5, 25, 50, 75, 95])
        return f"dB at 5/25/50/75/95%: {p[0]:.0f} {p[1]:.0f} {p[2]:.0f} {p[3]:.0f} {p[4]:.0f}, loudest {max(levels):.0f}"

    def save(self, identity: str, path: Path, after: float = 0.0, before: float = 1e12, pad: float = 0.25) -> float:
        """Write part of one identity's audio as a wav. Returns its length in seconds."""
        size = self.rate // 100 * 2
        frames = self.frames.get(identity, [])
        keep = [i for i, (t, _) in enumerate(frames) if after - pad <= t <= before + pad]
        path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(path), "wb") as w:
            w.setnchannels(1), w.setsampwidth(2), w.setframerate(self.rate)
            for i in keep:
                w.writeframes(bytes(self.pcm[identity][i * size:(i + 1) * size]))
        return len(keep) / 100

    def save_levels(self, path: Path) -> None:
        """Loudness of every frame with its arrival time, no audio: for trying thresholds offline."""
        path.write_text(json.dumps({who: [(round(t, 3), round(db, 1)) for t, db in frames] for who, frames in self.frames.items()}))

    async def stop(self) -> None:
        for identity in list(self._since):
            self._gone(identity)
        await self.room.disconnect()
        for task in self._tasks:
            task.cancel()


# ---- the server ----

class Server:
    """The real app in this process, on a free port, with only the mouth's keys."""

    def __init__(self) -> None:
        real = get_settings()
        SCRATCH.mkdir(parents=True, exist_ok=True)
        database = SCRATCH / f"proof-{int(time.time())}.db"
        self.settings = Settings(
            _env_file=None, database_path=str(database), openai_api_key=real.openai_api_key,
            livekit_url=real.livekit_url, livekit_api_key=real.livekit_api_key, livekit_api_secret=real.livekit_api_secret,
        )
        self.rooms = Rooms(
            real.require("livekit_url"), real.require("livekit_api_key"), real.require("livekit_api_secret")
        )
        self.app = create_app(self.settings)
        self.events: list[tuple[float, Event]] = []
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            self.port = s.getsockname()[1]
        self.url = f"http://127.0.0.1:{self.port}"

    def people_page(self, room_name: str) -> None:
        """Our own call page for the fake people on a deal call. Bridge will serve the real one;
        this reuses the call-back page, which finds its token at <its own address>/join."""
        page, rooms = PAGE.read_text(), self.rooms

        from fastapi.responses import HTMLResponse

        @self.app.get("/proof/{identity}", response_class=HTMLResponse)
        async def proof_page(identity: str) -> str:
            return page

        @self.app.post("/proof/{identity}/join")
        async def proof_join(identity: str) -> dict:
            return {"url": rooms.url, "token": rooms.token(room_name, identity)}

    async def __aenter__(self) -> "Server":
        logging.getLogger("uvicorn.error").setLevel(logging.WARNING)
        self._server = uvicorn.Server(uvicorn.Config(self.app, host="127.0.0.1", port=self.port, log_level="warning"))
        self._task = asyncio.create_task(self._server.serve())
        while not self._server.started:
            await asyncio.sleep(0.05)
        self.http = httpx.AsyncClient(base_url=self.url, timeout=10)

        async def collect(event: Event) -> None:
            self.events.append((now(), event))

        self.app.state.bus.subscribe_all(collect)
        return self

    async def __aexit__(self, *exc) -> None:
        await self.http.aclose()
        self._server.should_exit = True  # the app's shutdown hooks take Gawah out of any room
        await self._task

    async def publish(self, event: Event) -> float:
        """Through the development route, as the replayer does. Returns when it was sent."""
        sent = now()
        response = await self.http.post("/dev/publish", content=event.model_dump_json())
        response.raise_for_status()
        return sent

    def of(self, kind: type) -> list:
        return [e for _, e in self.events if isinstance(e, kind)]


# ---- helpers ----

async def until(condition, timeout: float, what: str):
    start = now()
    while not (found := condition()):
        if now() - start > timeout:
            raise TimeoutError(f"waited {timeout} s for {what}")
        await asyncio.sleep(0.02)
    return found


def kill(browsers: list[subprocess.Popen]) -> None:
    for browser in browsers:
        if browser.poll() is None:
            browser.send_signal(signal.SIGKILL)


def log_usage(label: str, room: str, seconds: dict[str, float], realtime_seconds: float) -> float:
    """Append this run's use of the free plans to the scratch folder and return the participant-minutes."""
    minutes = round(sum(seconds.values()) / 60, 2)
    with (SCRATCH / "usage.jsonl").open("a") as f:
        f.write(json.dumps({
            "at": time.strftime("%Y-%m-%d %H:%M:%S"), "label": label, "room": room, "participant_minutes": minutes,
            "seconds": {k: round(v, 1) for k, v in seconds.items()}, "realtime_connection_seconds": round(realtime_seconds, 1),
        }) + "\n")
    return minutes


def show(event: Event) -> str:
    return json.dumps(event.model_dump(mode="json", exclude={"ts", "event_id", "people"}, exclude_none=True), ensure_ascii=False)
