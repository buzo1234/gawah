"""The FastAPI app. Frozen after the scaffold.

Streams never edit this file. Each stream package has register(app, bus), called once
below when the app is built. Inside register a stream can:

- add routes and websocket routes on app (app.get, app.post, app.websocket, app.mount),
- subscribe to events (bus.subscribe, bus.subscribe_all),
- append an async function to app.state.on_startup or app.state.on_shutdown,
- read app.state.settings and app.state.store (the store opens before on_startup runs).
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import actor, brain, call, contract, dashboard, dev, ears, memory, mouth, records, whatsapp
from app.bus import Bus
from app.config import Settings, get_settings
from app.store import Store

STREAMS = (call, memory, ears, brain, mouth, whatsapp, records, contract, dashboard, dev, actor)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    bus = Bus()
    store = Store(settings.database_path)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await store.open()
        bus.start()
        for hook in app.state.on_startup:
            await hook()
        yield
        for hook in reversed(app.state.on_shutdown):
            await hook()
        await bus.stop()
        await store.close()

    app = FastAPI(title="Gawah", lifespan=lifespan)
    app.state.settings = settings
    app.state.bus = bus
    app.state.store = store
    app.state.on_startup = []
    app.state.on_shutdown = []

    bus.subscribe_all(store.record_event)
    for stream in STREAMS:
        stream.register(app, bus)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
