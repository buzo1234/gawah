"""Stream: contract. Owns contract text, PDF, spoken summary.

Listens to terms.confirmed, terms.disputed, checklist.updated, call.started, call.ended,
fact.recorded and fact.changed, and reads each term from memory (MemoryQueries). When both
people have confirmed, it writes the contract and publishes contract.ready; whatsapp does
the sending. When a change both confirmed reaches memory, it writes the next version.
On start it writes whatever the event log says is due and was never written.
"""

from fastapi import FastAPI

from app.bus import Bus
from app.contract.fingerprint import sha256_of
from app.contract.openai_client import OpenAI
from app.contract.pdf import render_pdf
from app.contract.stream import ContractStream
from app.contracts import MEMORY_STATE
from app.store import S3


def register(app: FastAPI, bus: Bus) -> None:
    settings = app.state.settings
    openai = OpenAI(settings)
    stream = ContractStream(
        bus, app.state.store, openai, openai, S3(settings), render_pdf, sha256_of,
        memory=lambda: getattr(app.state, MEMORY_STATE, None),
    )
    # One subscription for every event it watches, so they are handled in the order they were published.
    bus.subscribe_all(stream.on_event)
    app.state.contract = stream  # for tests: stream.idle() waits for a contract being written
    app.state.on_startup.append(stream.start)  # memory registers first, so its facts are rebuilt by then
    app.state.on_shutdown.append(stream.close)
