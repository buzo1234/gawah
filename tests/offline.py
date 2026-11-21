"""The whole app with every outside service replaced by a fake. No .env is read, so there
are no keys and every phone is a simulated one; WhatsApp records are read by lookup
(FakeReader) instead of by OpenAI; practice calls get the brain's saved answers; the
contract is worded by restating each term, "printed" without Chrome, and kept in memory
instead of S3.

tests/test_whole_flow.py runs on it. To walk a deal through a running server by hand:

    uv run python -m tests.offline --port 8000

A stream that adds an outside service adds its fake here.
"""

import argparse
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import uvicorn
from fastapi import FastAPI

from app.config import Settings
from app.contracts import ChecklistItem, ItemState
from app.main import create_app
from tests.contract_fakes import FakeFiles, FakeSpeaker, answer_for, fake_fingerprint, fake_render_pdf
from tests.whatsapp_world import FakeClock, FakeReader, FakeTwilio


class FakeContractModel(FakeSpeaker):
    """The contract stream's OpenAI: restates each term it is asked to word, and "speaks"."""

    async def write(self, instructions: str, text: str, schema: dict) -> dict:
        asked = json.loads(text)["terms"]
        return answer_for([ChecklistItem(key=t["key"], state=ItemState.AGREED, value=t["value"]) for t in asked])


def offline_app(database_path: str | Path, clock: FakeClock | None = None) -> FastAPI:
    """clock: pass a FakeClock to move the no-reply timer by hand; without one it is real time."""
    settings = Settings(_env_file=None, database_path=str(database_path))
    fakes = {"Twilio": lambda settings: FakeTwilio(clock or FakeClock()), "Reader": lambda settings: FakeReader()}
    if clock:
        fakes["Clock"] = lambda: clock
    contract = {
        "OpenAI": lambda settings: FakeContractModel(), "S3": lambda settings: FakeFiles(),
        "render_pdf": fake_render_pdf, "sha256_of": fake_fingerprint,
    }
    with patch.multiple("app.whatsapp", **fakes), patch.multiple("app.contract", **contract):
        return create_app(settings)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Serve Gawah with every outside service faked.")
    parser.add_argument("--port", type=int, default=8000)
    port = parser.parse_args().port
    database = Path(tempfile.mkdtemp(prefix="gawah-offline-")) / "gawah.db"
    uvicorn.run(offline_app(database), host="127.0.0.1", port=port)
