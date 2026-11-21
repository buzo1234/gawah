"""Stream: bridge. Owns rooms, join links, the call page."""

from fastapi import FastAPI

from app.bus import Bus


def register(app: FastAPI, bus: Bus) -> None:
    """Add this stream's routes, bus subscriptions, and startup or shutdown work here."""
