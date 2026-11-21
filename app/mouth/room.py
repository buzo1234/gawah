"""Gawah's seat in a LiveKit room, and the few room calls the call-back needs. The only
file in this stream that talks to LiveKit. Uses the low-level client, not livekit-agents."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import timedelta

from livekit import api, rtc

from app.mouth import tuning

logging.getLogger("livekit").setLevel(logging.ERROR)  # it passes libwebrtc's chatter through at WARNING


async def _twice[T](what: str, call: Callable[[], Awaitable[T]], log: logging.Logger | logging.LoggerAdapter) -> T:
    """A timeout and one retry, for every call to LiveKit."""
    for attempt in (1, 2):
        try:
            async with asyncio.timeout(tuning.CONNECT_TIMEOUT_S):
                return await call()
        except Exception as e:
            if attempt == 2:
                raise
            log.warning("%s failed (%s), trying once more", what, type(e).__name__)
    raise AssertionError("unreachable")


class Rooms:
    """Tokens, and opening and closing rooms."""

    def __init__(self, url: str, key: str, secret: str) -> None:
        self.url, self._key, self._secret = url, key, secret
        self.log = logging.getLogger("gawah.mouth.rooms")

    def token(self, room: str, identity: str, name: str | None = None, publish: bool = True) -> str:
        grants = api.VideoGrants(room_join=True, room=room, can_publish=publish, can_subscribe=True)
        return (
            api.AccessToken(self._key, self._secret)
            .with_identity(identity)
            .with_name(name or identity)
            .with_ttl(timedelta(minutes=15))
            .with_grants(grants)
            .to_jwt()
        )

    async def create(self, name: str, empty_timeout: int, max_participants: int) -> None:
        request = api.CreateRoomRequest(
            name=name, empty_timeout=empty_timeout, departure_timeout=15, max_participants=max_participants
        )
        await self._call("create room", lambda lk: lk.room.create_room(request))

    async def delete(self, name: str) -> None:
        """Closing a room disconnects everyone in it. A room that is already gone is fine."""
        try:
            await self._call("delete room", lambda lk: lk.room.delete_room(api.DeleteRoomRequest(room=name)))
        except Exception as e:
            self.log.info("room %s not deleted (%s): it may already be gone", name, type(e).__name__)

    async def names(self) -> list[str]:
        rooms = await self._call("list rooms", lambda lk: lk.room.list_rooms(api.ListRoomsRequest()))
        return [f"{r.name} ({r.num_participants} in room)" for r in rooms.rooms]

    async def _call(self, what: str, call):
        async def once():
            # Made inside the running loop: it opens an http session.
            lk = api.LiveKitAPI(self.url, self._key, self._secret)
            try:
                return await call(lk)
            finally:
                await lk.aclose()

        return await _twice(what, once, self.log)


class Seat:
    """One participant in one room: publishes Gawah's voice, and hands over each person's
    audio as it arrives. Set the on_* callbacks before join(); they are plain functions."""

    def __init__(self, rooms: Rooms, log: logging.LoggerAdapter) -> None:
        self._rooms, self.log = rooms, log
        self.on_frame: Callable[[str, bytes], None] = lambda who, pcm: None  # 20 ms, 24 kHz, 16-bit mono
        self.on_left: Callable[[str], None] = lambda who: None
        self.on_silent: Callable[[str], None] = lambda who: None  # their track was muted or ended; they may still be here
        self.on_closed: Callable[[], None] = lambda: None  # the room is gone, or we were thrown out
        self._room: rtc.Room | None = None
        self._source: rtc.AudioSource | None = None
        self._listeners: set[asyncio.Task] = set()

    async def join(self, room_name: str) -> None:
        room = rtc.Room()

        @room.on("track_subscribed")
        def _subscribed(track: rtc.Track, publication: rtc.RemoteTrackPublication, participant: rtc.RemoteParticipant):
            if track.kind == rtc.TrackKind.KIND_AUDIO:
                task = asyncio.create_task(self._listen(participant.identity, track))
                self._listeners.add(task)
                task.add_done_callback(self._listeners.discard)

        @room.on("participant_disconnected")
        def _left(participant: rtc.RemoteParticipant):
            self.on_left(participant.identity)

        # A phone mutes its track when the screen locks or the page goes to the background.
        @room.on("track_muted")
        def _muted(participant: rtc.Participant, publication: rtc.TrackPublication):
            if publication.kind == rtc.TrackKind.KIND_AUDIO:
                self.on_silent(participant.identity)

        @room.on("disconnected")
        def _disconnected(reason=None):
            if self._room is room:
                self.log.info("out of room %s (%s)", room_name, reason)
                self.on_closed()

        token = self._rooms.token(room_name, tuning.IDENTITY, tuning.NAME)
        await _twice("join room", lambda: room.connect(self._rooms.url, token), self.log)
        self._room = room
        # The source takes the model's 24 kHz as it is. Its queue is what paces play().
        self._source = rtc.AudioSource(tuning.RATE, 1, queue_size_ms=tuning.ROOM_QUEUE_MS)
        track = rtc.LocalAudioTrack.create_audio_track("gawah-voice", self._source)
        await room.local_participant.publish_track(
            track, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE)
        )

    async def _listen(self, who: str, track: rtc.Track) -> None:
        stream = rtc.AudioStream(track, sample_rate=tuning.RATE, num_channels=1, frame_size_ms=tuning.FRAME_MS)
        try:
            async for event in stream:
                self.on_frame(who, bytes(event.frame.data))
        finally:
            self.on_silent(who)
            await stream.aclose()

    async def play(self, pcm: bytes) -> None:
        """Hand over one frame of speech. Waits while the room's queue is full, so calling
        it in a loop plays at the speed of speech."""
        await self._source.capture_frame(rtc.AudioFrame(pcm, tuning.RATE, 1, len(pcm) // 2))

    def queued_ms(self) -> float:
        return self._source.queued_duration * 1000 if self._source else 0.0

    def clear(self) -> None:
        """Drop what has been handed over and not yet heard."""
        if self._source:
            self._source.clear_queue()

    async def played_out(self) -> None:
        await self._source.wait_for_playout()

    async def leave(self) -> None:
        room, self._room = self._room, None
        for task in list(self._listeners):
            task.cancel()
        if room:
            await room.disconnect()
        if self._source:
            await self._source.aclose()
            self._source = None
