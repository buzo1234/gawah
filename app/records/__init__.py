"""Stream: whatsapp. Owns record intake, backed or unbacked.

Nothing is registered here. The bot hands messages straight to Intake, so app.whatsapp
builds it together with the bot: see wire() in app/whatsapp/__init__.py."""

from fastapi import FastAPI

from app.bus import Bus


def register(app: FastAPI, bus: Bus) -> None:
    pass
