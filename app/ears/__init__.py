"""Stream: bridge. Owns per-person transcription.

Ears has no routes and no subscriptions of its own: the call (app/call) builds one Ears
per deal call and feeds it each person's audio.
"""

from fastapi import FastAPI

from app.bus import Bus


def register(app: FastAPI, bus: Bus) -> None:
    pass
