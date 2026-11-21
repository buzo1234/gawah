"""LiveKit: rooms, join tokens, and Gawah's listener. The only place bridge calls LiveKit.

Uses the low-level client (livekit.rtc), not the agent framework. The listener is a
hidden participant: it publishes nothing and the two people do not see it join.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Protocol

import aiohttp
from livekit import api, rtc

from app.config import Settings
from app.ears.vad import FRAME_SECONDS, RATE

log = logging.getLogger("gawah.call")
logging.getLogger("livekit").setLevel(logging.ERROR)  # libwebrtc is chatty at WARNING

LISTENER = "gawah-ears"
ROOM_PREFIX = "deal-"
TOKEN_MINUTES = 15
API_TIMEOUT = aiohttp.ClientTimeout(total=8)
CONNECT_TIMEOUT = 10.0


def room_name(deal_id: str, call_no: int) -> str:
    """One room per deal call: "deal-<deal id>-<call no>"."""
    return f"{ROOM_PREFIX}{deal_id}-{call_no}"


def deal_of(room: str) -> str:
    return room.removeprefix(ROOM_PREFIX).rsplit("-", 1)[0]


def call_of(room: str) -> int:
    return int(room.rsplit("-", 1)[1])


class RoomEvents(Protocol):
    """What the listener tells the call. Identities, never participant or track ids:
    a person who drops and rejoins gets new ids under the same identity."""

    def joined(self, identity: str) -> None: ...
    def left(self, identity: str) -> None: ...
    def audio(self, identity: str, pcm: bytes) -> None: ...
    def muted(self, identity: str, muted: bool) -> None: ...  # their device muted the microphone
    def lost(self) -> None: ...  # the listener is out of the room and did not ask to be


class Listener:
    def __init__(self, room: rtc.Room, pumps: dict[str, tuple[str, asyncio.Task]]) -> None:
        self._room, self._pumps = room, pumps

    def people(self) -> set[str]:
        """Who is in the room right now, as LiveKit has it. Ask this instead of remembering."""
        return set(self._room.remote_participants)

    async def disconnect(self) -> None:
        for _, task in self._pumps.values():
            task.cancel()
        self._pumps.clear()
        await self._room.disconnect()


class LiveKit:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._api: api.LiveKitAPI | None = None

    @property
    def url(self) -> str:
        return self._settings.require("livekit_url")

    def token(self, room: str, identity: str, name: str | None = None, listener: bool = False) -> str:
        grants = api.VideoGrants(
            room_join=True, room=room, can_subscribe=True, can_publish=not listener,
            can_publish_data=not listener, hidden=listener,
        )
        return (
            api.AccessToken(self._settings.require("livekit_api_key"), self._settings.require("livekit_api_secret"))
            .with_identity(identity)
            .with_name(name or identity)
            .with_ttl(timedelta(minutes=TOKEN_MINUTES))
            .with_grants(grants)
            .to_jwt()
        )

    async def create_room(self, name: str) -> None:
        # LiveKit has no maximum length for a room. Ours is a timer in the call session.
        request = api.CreateRoomRequest(name=name, empty_timeout=30, departure_timeout=15, max_participants=6)
        await self._twice(lambda: self._rooms().create_room(request))

    async def delete_room(self, name: str) -> None:
        """Ends the room for everyone in it. A room that is already gone is fine."""
        try:
            await self._twice(lambda: self._rooms().delete_room(api.DeleteRoomRequest(room=name)))
        except api.TwirpError as e:
            if e.code != api.TwirpErrorCode.NOT_FOUND:
                raise

    async def list_rooms(self) -> list[str]:
        rooms = await self._twice(lambda: self._rooms().list_rooms(api.ListRoomsRequest()))
        return [r.name for r in rooms.rooms]

    async def listen(self, room_name: str, events: RoomEvents) -> Listener:
        """Join as the hidden listener and report who comes, who goes, and what they say."""
        room = rtc.Room()
        pumps: dict[str, tuple[str, asyncio.Task]] = {}  # identity -> (participant id, its audio task)

        async def pump(identity: str, track: rtc.Track) -> None:
            stream = rtc.AudioStream(
                track, sample_rate=RATE, num_channels=1, frame_size_ms=int(FRAME_SECONDS * 1000)
            )
            try:
                async for event in stream:
                    events.audio(identity, bytes(event.frame.data))
            except Exception:
                log.exception("deal=%s audio from %s stopped", deal_of(room_name), identity)
            finally:
                await stream.aclose()

        def stop_pump(identity: str, participant_id: str | None = None) -> None:
            held = pumps.get(identity)
            if held and participant_id in (None, held[0]):
                del pumps[identity]
                held[1].cancel()

        @room.on("participant_connected")
        def _joined(p: rtc.RemoteParticipant) -> None:
            events.joined(p.identity)

        @room.on("participant_disconnected")
        def _left(p: rtc.RemoteParticipant) -> None:
            stop_pump(p.identity, p.sid)  # only this connection's audio: they may already be back
            events.left(p.identity)

        @room.on("track_subscribed")
        def _track(track: rtc.Track, publication: rtc.RemoteTrackPublication, p: rtc.RemoteParticipant) -> None:
            if track.kind != rtc.TrackKind.KIND_AUDIO:
                return
            stop_pump(p.identity)
            pumps[p.identity] = (p.sid, asyncio.create_task(pump(p.identity, track)))

        @room.on("track_muted")
        def _muted(p: rtc.Participant, publication: rtc.TrackPublication) -> None:
            events.muted(p.identity, True)

        @room.on("track_unmuted")
        def _unmuted(p: rtc.Participant, publication: rtc.TrackPublication) -> None:
            events.muted(p.identity, False)

        @room.on("disconnected")
        def _lost(*_: object) -> None:
            events.lost()

        token = self.token(room_name, LISTENER, listener=True)
        await room.connect(self.url, token, rtc.RoomOptions(connect_timeout=CONNECT_TIMEOUT))
        return Listener(room, pumps)

    async def close(self) -> None:
        if self._api is not None:
            await self._api.aclose()
            self._api = None

    def _rooms(self):
        if self._api is None:  # made lazily: it opens an aiohttp session, which needs the running loop
            s = self._settings
            self._api = api.LiveKitAPI(
                self.url, s.require("livekit_api_key"), s.require("livekit_api_secret"), timeout=API_TIMEOUT
            )
        return self._api.room

    @staticmethod
    async def _twice[T](call: Callable[[], Awaitable[T]]) -> T:
        try:
            return await call()
        except (aiohttp.ClientConnectionError, TimeoutError):
            return await call()
