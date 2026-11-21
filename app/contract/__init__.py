"""Stream: contract. Owns contract text, PDF, spoken summary.

Listens to terms.confirmed, terms.disputed, checklist.updated and call.ended. When both
people have confirmed, it writes the contract and publishes contract.ready; whatsapp
does the sending.
"""

from fastapi import FastAPI

from app.bus import Bus
from app.contract.openai_client import OpenAI
from app.contract.pdf import render_pdf
from app.contract.stream import ContractStream
from app.store import S3


def register(app: FastAPI, bus: Bus) -> None:
    settings = app.state.settings
    openai = OpenAI(settings)
    stream = ContractStream(bus, app.state.store, openai, openai, S3(settings), render_pdf)
    # One subscription for all four events, so they are handled in the order they were published.
    bus.subscribe_all(stream.on_event)
    app.state.on_shutdown.append(stream.close)
