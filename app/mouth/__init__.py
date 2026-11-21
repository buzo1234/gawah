"""Stream: mouth. Owns the voice on the call and the call-back."""

from fastapi import FastAPI

from app.bus import Bus


def register(app: FastAPI, bus: Bus) -> None:
    """Add this stream's routes, bus subscriptions, and startup or shutdown work here."""
