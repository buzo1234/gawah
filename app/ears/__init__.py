"""Stream: bridge. Owns per-person transcription."""

from fastapi import FastAPI

from app.bus import Bus


def register(app: FastAPI, bus: Bus) -> None:
    """Add this stream's routes, bus subscriptions, and startup or shutdown work here."""
