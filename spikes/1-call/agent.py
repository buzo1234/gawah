"""Gawah's agent for the spike: joins a room with the low-level LiveKit client (no AgentSession),
takes each person's audio as its own track, records it, tracks a level, and stops the mouth
when a person starts talking over it. Also a passive recorder bot used as the room's "third ear".
"""

import asyncio
import json
import logging
import math
import wave
from pathlib import Path

import numpy as np
from livekit import rtc

from lk import LIVEKIT_URL, now, token
from mouth import RATE, Mouth

SPEECH_DB = -40.0  # a 20 ms frame louder than this counts as voiced
START_FRAMES = 3  # 60 ms of voiced frames in a row = speech started
END_FRAMES = 30  # 600 ms of quiet = speech ended
NOT_PEOPLE = {"gawah", "recorder"}
logging.getLogger("livekit").setLevel(logging.ERROR)  # libwebrtc is chatty at WARNING


def frame_db(pcm: bytes) -> float:
    samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float64)
    rms = math.sqrt(float(np.mean(samples * samples))) if len(samples) else 0.0
    return round(20 * math.log10(max(rms, 1.0) / 32768), 1)


class Person:
    def __init__(self, identity: str):
        self.identity = identity
        self.db = -90.0
        self.speaking = False
        self.voiced = 0
        self.quiet = 0
        self.files: list[str] = []
        self.speech_starts: list[float] = []
        self.joined_at: float | None = None
        self.seconds = 0.0


class Agent:
    def __init__(self, room_name: str, out_dir: Path, model: str = "gpt-realtime-2.1", feed_to_model: str | None = None):
        self.room_name = room_name
        self.out = out_dir
        self.out.mkdir(parents=True, exist_ok=True)
        self.model = model
        self.feed_to_model = feed_to_model  # identity whose audio the model hears (silence test only)
        self.room = rtc.Room()
        self.source = rtc.AudioSource(RATE, 1, queue_size_ms=200)
        self.mouth: Mouth | None = None
        self.people: dict[str, Person] = {}
        self.events: list[dict] = []
        self.barge_ins: list[dict] = []
        self.barge_in_enabled = True
        self.first_frames: dict[str, dict] = {}
        self._listeners: dict[str, asyncio.Task] = {}
        self.joined_at = 0.0

    def log(self, kind: str, **fields) -> None:
        event = {"t": now(), "event": kind, **fields}
        self.events.append(event)
        print(f"[agent {event['t']:8.2f}] {kind} " + " ".join(f"{k}={v}" for k, v in fields.items()), flush=True)

    def person(self, identity: str) -> Person:
        return self.people.setdefault(identity, Person(identity))

    async def start(self) -> None:
        room = self.room

        @room.on("participant_connected")
        def _joined(p: rtc.RemoteParticipant):
            self.log("participant_connected", who=p.identity, sid=p.sid)
            self.person(p.identity).joined_at = now()

        @room.on("participant_disconnected")
        def _left(p: rtc.RemoteParticipant):
            reason = rtc.DisconnectReason.Name(p.disconnect_reason) if p.disconnect_reason is not None else None
            self.log("participant_disconnected", who=p.identity, sid=p.sid, reason=reason)
            person = self.person(p.identity)
            if person.joined_at is not None:
                person.seconds += now() - person.joined_at
                person.joined_at = None

        @room.on("track_published")
        def _published(pub: rtc.RemoteTrackPublication, p: rtc.RemoteParticipant):
            self.log("track_published", who=p.identity, track=pub.sid, media=rtc.TrackKind.Name(pub.kind))

        @room.on("track_unpublished")
        def _unpublished(pub: rtc.RemoteTrackPublication, p: rtc.RemoteParticipant):
            self.log("track_unpublished", who=p.identity, track=pub.sid)

        @room.on("track_subscribed")
        def _subscribed(track: rtc.Track, pub: rtc.RemoteTrackPublication, p: rtc.RemoteParticipant):
            self.log("track_subscribed", who=p.identity, track=pub.sid, media=rtc.TrackKind.Name(track.kind))
            if track.kind == rtc.TrackKind.KIND_AUDIO and p.identity not in NOT_PEOPLE:
                self._listeners[pub.sid] = asyncio.create_task(self._listen(p.identity, track, pub.sid))

        @room.on("track_unsubscribed")
        def _unsubscribed(track: rtc.Track, pub: rtc.RemoteTrackPublication, p: rtc.RemoteParticipant):
            self.log("track_unsubscribed", who=p.identity, track=pub.sid)

        @room.on("track_muted")
        def _muted(p: rtc.Participant, pub: rtc.TrackPublication):
            self.log("track_muted", who=p.identity, track=pub.sid)

        @room.on("track_unmuted")
        def _unmuted(p: rtc.Participant, pub: rtc.TrackPublication):
            self.log("track_unmuted", who=p.identity, track=pub.sid)

        @room.on("connection_state_changed")
        def _state(state: int):
            self.log("connection_state_changed", state=rtc.ConnectionState.Name(state))

        @room.on("reconnecting")
        def _reconnecting():
            self.log("reconnecting")

        @room.on("reconnected")
        def _reconnected():
            self.log("reconnected")

        @room.on("disconnected")
        def _disconnected(reason=None):
            self.log("disconnected", reason=str(reason))

        t = now()
        await room.connect(LIVEKIT_URL, token(self.room_name, "gawah"))
        self.joined_at = now()
        self.log("agent_connected", ms=round((now() - t) * 1000), already_here=list(room.remote_participants))
        for p in room.remote_participants.values():
            self.person(p.identity).joined_at = now()
        track = rtc.LocalAudioTrack.create_audio_track("gawah-voice", self.source)
        await room.local_participant.publish_track(
            track, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE)
        )
        self.mouth = Mouth(self.model, self.source)
        await self.mouth.connect()
        self.log("mouth_connected", model=self.model, ms=self.mouth.connect_ms)

    async def use_model(self, model: str, effort: str | None = None) -> None:
        if self.mouth:
            await self.mouth.close()
        self.model = model
        self.mouth = Mouth(model, self.source, effort=effort)
        await self.mouth.connect()
        self.log("mouth_connected", model=model, effort=effort, ms=self.mouth.connect_ms)

    async def _listen(self, identity: str, track: rtc.Track, track_sid: str) -> None:
        person = self.person(identity)
        path = self.out / f"{identity}-{len(person.files) + 1}-{track_sid}.wav"
        person.files.append(str(path))
        stream = rtc.AudioStream(track, sample_rate=RATE, num_channels=1, frame_size_ms=20)
        wav = wave.open(str(path), "wb")
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(RATE)
        frames = 0
        try:
            async for ev in stream:
                pcm = bytes(ev.frame.data)
                if frames == 0:
                    info = {
                        "sample_rate": ev.frame.sample_rate,
                        "channels": ev.frame.num_channels,
                        "samples_per_frame": ev.frame.samples_per_channel,
                        "sample_format": "int16 PCM",
                    }
                    self.first_frames[identity] = info
                    self.log("first_audio_frame", who=identity, track=track_sid, **info)
                frames += 1
                wav.writeframes(pcm)
                self._vad(person, frame_db(pcm))
                if self.feed_to_model == identity and self.mouth:
                    await self.mouth.feed(pcm)
        finally:
            wav.close()
            await stream.aclose()
            self.log("track_audio_ended", who=identity, track=track_sid, seconds=round(frames * 0.02, 1), file=path.name)

    def _vad(self, person: Person, db: float) -> None:
        person.db = db
        if db > SPEECH_DB:
            person.voiced += 1
            person.quiet = 0
        else:
            person.quiet += 1
            person.voiced = 0
        if not person.speaking and person.voiced >= START_FRAMES:
            person.speaking = True
            person.speech_starts.append(now())
            if self.barge_in_enabled and self.mouth and self.mouth.speaking and self.mouth.current.get("t_first_frame"):
                barge = {"t_detected": now(), "who": person.identity, "db": db}
                self.barge_ins.append(barge)
                self.log("barge_in", who=person.identity, db=db)
                asyncio.create_task(self.mouth.stop(f"barge-in by {person.identity}"))
        elif person.speaking and person.quiet >= END_FRAMES:
            person.speaking = False

    def seconds_by_identity(self) -> dict[str, float]:
        seconds = {"gawah": now() - self.joined_at}
        for person in self.people.values():
            extra = now() - person.joined_at if person.joined_at is not None else 0
            seconds[person.identity] = person.seconds + extra
        return seconds

    async def stop(self) -> None:
        if self.mouth:
            await self.mouth.close()
        await self.room.disconnect()
        for task in self._listeners.values():
            task.cancel()
        (self.out / "events.jsonl").write_text("\n".join(json.dumps(e) for e in self.events) + "\n")


class Recorder:
    """A listen-only participant. Records every track with the arrival time of each 10 ms frame,
    so "when was it heard in the room" is measured outside the agent."""

    def __init__(self, room_name: str, out_dir: Path):
        self.room_name = room_name
        self.out = out_dir
        self.room = rtc.Room()
        self.frames: dict[str, list[tuple[float, float]]] = {}  # identity -> (arrival time, dB)
        self.pcm: dict[str, bytearray] = {}
        self.first_frames: dict[str, dict] = {}
        self._tasks: list[asyncio.Task] = []
        self.joined_at = 0.0

    async def start(self) -> None:
        @self.room.on("track_subscribed")
        def _subscribed(track: rtc.Track, pub: rtc.RemoteTrackPublication, p: rtc.RemoteParticipant):
            if track.kind == rtc.TrackKind.KIND_AUDIO:
                self._tasks.append(asyncio.create_task(self._listen(p.identity, track)))

        await self.room.connect(LIVEKIT_URL, token(self.room_name, "recorder", publish=False))
        self.joined_at = now()

    async def _listen(self, identity: str, track: rtc.Track) -> None:
        stream = rtc.AudioStream(track)  # SDK defaults, to see what arrives untouched
        frames = self.frames.setdefault(identity, [])
        pcm_all = self.pcm.setdefault(identity, bytearray())
        async for ev in stream:
            pcm = bytes(ev.frame.data)
            if identity not in self.first_frames:
                self.first_frames[identity] = {
                    "sample_rate": ev.frame.sample_rate,
                    "channels": ev.frame.num_channels,
                    "samples_per_frame": ev.frame.samples_per_channel,
                }
            frames.append((now(), frame_db(pcm)))
            pcm_all.extend(pcm)

    def heard(self, identity: str, after: float, before: float = 1e9, db: float = -50.0) -> list[float]:
        """Arrival times of frames from this identity that were louder than db."""
        return [t for t, level in self.frames.get(identity, []) if after <= t <= before and level > db]

    def save(self, identity: str, path: Path, after: float = 0, before: float = 1e9) -> None:
        frames = self.frames.get(identity, [])
        rate = self.first_frames[identity]["sample_rate"]
        size = self.first_frames[identity]["samples_per_frame"] * 2
        wav = wave.open(str(path), "wb")
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        for i, (t, _) in enumerate(frames):
            if after <= t <= before:
                wav.writeframes(bytes(self.pcm[identity][i * size : (i + 1) * size]))
        wav.close()

    async def stop(self) -> None:
        await self.room.disconnect()
        for task in self._tasks:
            task.cancel()

