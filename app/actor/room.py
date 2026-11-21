"""The actor's seat in a LiveKit room. The only file in this folder that talks to LiveKit.

It joins with the same token a call page gets, so to the room it is that person. Everyone it
hears is mixed into one stream, 20 ms at a time, as a phone's earpiece would mix them; what it
says goes out as its microphone."""

import asyncio
import logging
import time
from collections import deque
from collections.abc import Callable

import numpy as np
from livekit import rtc

from app.actor.realtime import RATE

logging.getLogger("livekit").setLevel(logging.ERROR)

FRAME_MS = 20
FRAME_BYTES = RATE * FRAME_MS // 1000 * 2
SILENCE = bytes(FRAME_BYTES)
BEHIND = 25  # frames held per person before the oldest is dropped: half a second
QUEUE_MS = 200
TIMEOUT_S = 10.0


class Seat:
    def __init__(self, log: logging.LoggerAdapter) -> None:
        self.log = log
        self.on_heard: Callable[[bytes], None] = lambda pcm: None  # mixed, 20 ms, 24 kHz, 16-bit mono
        self.on_closed: Callable[[], None] = lambda: None
        self.room: rtc.Room | None = None
        self._source: rtc.AudioSource | None = None
        self._ears: dict[str, deque[bytes]] = {}
        self._tasks: set[asyncio.Task] = set()
        self._out = bytearray()  # the actor's speech, not yet in the room
        self._wake = asyncio.Event()
        self.given_ms = 0.0  # handed to the room since the last clear()

    def present(self) -> set[str]:
        return set(self.room.remote_participants) if self.room else set()

    async def join(self, url: str, token: str) -> None:
        room = rtc.Room()

        @room.on("track_subscribed")
        def _subscribed(track: rtc.Track, publication, participant: rtc.RemoteParticipant):
            if track.kind == rtc.TrackKind.KIND_AUDIO:
                self._spawn(self._listen(participant.identity, track))

        @room.on("disconnected")
        def _disconnected(reason=None):
            if self.room is room:
                self.log.info("actor out of room %s (%s)", room.name, reason)
                self.on_closed()

        for attempt in (1, 2):
            try:
                async with asyncio.timeout(TIMEOUT_S):
                    await room.connect(url, token)
                break
            except Exception as e:
                if attempt == 2:
                    raise
                self.log.warning("actor did not join the room (%s), trying once more", type(e).__name__)
        self.room = room
        self._source = rtc.AudioSource(RATE, 1, queue_size_ms=QUEUE_MS)
        track = rtc.LocalAudioTrack.create_audio_track("actor-voice", self._source)
        await room.local_participant.publish_track(track, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE))
        self._spawn(self._mix())
        self._spawn(self._speak())

    def _spawn(self, work) -> None:
        task = asyncio.get_running_loop().create_task(work)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _listen(self, who: str, track: rtc.Track) -> None:
        ear = self._ears.setdefault(who, deque(maxlen=BEHIND))
        stream = rtc.AudioStream(track, sample_rate=RATE, num_channels=1, frame_size_ms=FRAME_MS)
        try:
            async for event in stream:
                ear.append(bytes(event.frame.data))
        finally:
            self._ears.pop(who, None)
            await stream.aclose()

    async def _mix(self) -> None:
        """One mixed frame every 20 ms, silence included: the model's speech detector needs the gaps."""
        due = time.monotonic()
        while True:
            frames = [np.frombuffer(ear.popleft(), dtype=np.int16).astype(np.int32) for ear in list(self._ears.values()) if ear]
            frames = [f for f in frames if len(f) == FRAME_BYTES // 2]
            self.on_heard(np.clip(sum(frames), -32768, 32767).astype(np.int16).tobytes() if frames else SILENCE)
            due += FRAME_MS / 1000
            await asyncio.sleep(max(0.0, due - time.monotonic()))

    # ---- speaking ----

    def say(self, pcm: bytes) -> None:
        self._out.extend(pcm)
        self._wake.set()

    def speaking(self) -> bool:
        return bool(self._out) or (self._source is not None and self._source.queued_duration > 0)

    def heard_ms(self) -> float:
        """How much of what was handed over since the last clear() has been played into the room."""
        return max(0.0, self.given_ms - (self._source.queued_duration * 1000 if self._source else 0.0))

    def clear(self) -> None:
        """Go quiet now: drop what is not yet heard."""
        self._out.clear()
        self.given_ms = 0.0
        if self._source:
            self._source.clear_queue()

    async def _speak(self) -> None:
        while True:
            if len(self._out) < FRAME_BYTES:
                if self._out:
                    self._out.extend(bytes(FRAME_BYTES - len(self._out)))
                else:
                    self._wake.clear()
                    await self._wake.wait()
                    continue
            frame = bytes(self._out[:FRAME_BYTES])
            del self._out[:FRAME_BYTES]
            await self._source.capture_frame(rtc.AudioFrame(frame, RATE, 1, FRAME_BYTES // 2))  # waits while the queue is full
            self.given_ms += FRAME_MS

    async def leave(self) -> None:
        room, self.room = self.room, None
        for task in list(self._tasks):
            task.cancel()
        if room:
            await room.disconnect()
        if self._source:
            await self._source.aclose()
            self._source = None
