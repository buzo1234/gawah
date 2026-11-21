"""The whole app with every outside service replaced by a fake. No .env is read, so there
are no keys and every phone is a simulated one; WhatsApp records are read
by lookup (FakeReader) instead of by OpenAI; every call, in any room, gets the brain's
saved answers for the practice call it matches; the call's room is a fake LiveKit
(tests/bridge_world.py) whose audio is never transcribed or uploaded; Gawah's seat in a
room and its voice model are the mouth's fakes (tests/mouth/world.py), so a test plays
the room and the model by hand (app.state.fake_voice); the contract is worded by
restating each term, "printed" without Chrome, and kept in memory instead of S3.

tests/test_whole_flow.py runs on it. To walk a deal through a running server by hand:

    uv run python -m tests.offline --port 8000

With --whatsapp meta the bot sends in Meta's shapes (reply buttons, link buttons,
reactions, the contract as a captioned document), shown as text on the dashboard; every
phone is still simulated, and Meta's Graph API is the fake in tests/meta_fakes.py.

A stream that adds an outside service adds its fake here.
"""

import argparse
import tempfile
from pathlib import Path
from unittest.mock import patch

import uvicorn
from fastapi import FastAPI

from app import brain
from app.main import create_app
from app.whatsapp.meta import Meta
from app.whatsapp.settings import WhatsAppSettings
from tests.bridge_world import FakeLiveKit
from tests.contract_fakes import FakeFiles, FakeSpeaker, answer_to, fake_fingerprint, fake_render_pdf
from tests.meta_fakes import FakeGraph
from tests.mouth.world import FakeLink, FakeRooms, FakeSeat
from tests.whatsapp_world import FakeClock, FakeReader, FakeTwilio


class FakeContractModel(FakeSpeaker):
    """The contract stream's OpenAI: restates everything it is asked to word, and "speaks"."""

    async def write(self, instructions: str, text: str, schema: dict) -> dict:
        return answer_to(text)


class FakeVoice:
    """The mouth's outside world: the call-back rooms, Gawah's seat in each room, and one
    voice-model connection per call, newest last."""

    def __init__(self) -> None:
        self.rooms = FakeRooms()
        self.seats: list[FakeSeat] = []
        self.links: list[FakeLink] = []

    def make_rooms(self) -> FakeRooms:
        return self.rooms

    def make_seat(self, log=None) -> FakeSeat:
        self.seats.append(FakeSeat())
        return self.seats[-1]

    def make_link(self, config, on_event, log=None) -> FakeLink:
        self.links.append(FakeLink(config, on_event))
        return self.links[-1]


async def _no_words(pcm: bytes, prompt: str) -> str:
    return ""


async def _keep_key(path: str, key: str, content_type: str) -> str:
    return key


def offline_app(database_path: str | Path, clock: FakeClock | None = None, whatsapp: str = "twilio") -> FastAPI:
    """clock: pass a FakeClock to move the no-reply timer by hand; without one it is real time.
    whatsapp: the provider whose message shapes the bot uses, "twilio" or "meta"."""
    settings = WhatsAppSettings(_env_file=None, database_path=str(database_path), whatsapp_provider=whatsapp)
    fakes = {
        "Twilio": lambda settings: FakeTwilio(clock or FakeClock()), "Reader": lambda settings: FakeReader(),
        "Meta": lambda settings: Meta(settings, transport=FakeGraph().transport()),
    }
    if clock:
        fakes["Clock"] = lambda: clock
    contract = {
        "OpenAI": lambda settings: FakeContractModel(), "S3": lambda settings: FakeFiles(),
        "render_pdf": fake_render_pdf, "sha256_of": fake_fingerprint,
    }
    with patch.multiple("app.whatsapp", **fakes), patch.multiple("app.contract", **contract):
        app = create_app(settings)
    voice = app.state.fake_voice = FakeVoice()
    mouth = app.state.mouth
    mouth.rooms, mouth.make_seat, mouth.make_link = voice.make_rooms, voice.make_seat, voice.make_link
    app.state.brain.sources = brain.saved
    calls = app.state.calls
    calls.livekit, calls.transcribe, calls.upload = FakeLiveKit(), _no_words, _keep_key
    calls.folder = Path(database_path).parent / "recordings"
    return app


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Serve Gawah with every outside service faked.")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--whatsapp", choices=("twilio", "meta"), default="twilio")
    args = parser.parse_args()
    database = Path(tempfile.mkdtemp(prefix="gawah-offline-")) / "gawah.db"
    uvicorn.run(offline_app(database, whatsapp=args.whatsapp), host="127.0.0.1", port=args.port)
