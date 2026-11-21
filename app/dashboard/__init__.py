"""Stream: dashboard. The big-screen view of one deal, and the "second phone".

The page keeps no state of its own on the server. On load it asks /dashboard/state for
the event log and folds it; after that it folds each event from the websocket with the
same code, so a reload always ends up where the live page was.
"""

from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.bus import Bus
from app.contracts import NO_DEAL, CallStarted, DealRequested, Event, WhatsAppMessage
from app.dashboard import phone

HERE = Path(__file__).parent
PAGE = HERE / "page.html"


def register(app: FastAPI, bus: Bus) -> None:
    clients: set[WebSocket] = set()

    async def send_to_clients(event: Event) -> None:
        message = event.model_dump_json()
        for ws in list(clients):
            try:
                await ws.send_text(message)
            except Exception:
                clients.discard(ws)

    bus.subscribe_all(send_to_clients)
    app.mount("/dashboard/static", StaticFiles(directory=HERE / "static"), name="dashboard-static")
    phone.register(app)

    @app.get("/dashboard", response_class=HTMLResponse)
    async def page() -> str:
        return PAGE.read_text()

    @app.get("/dashboard/state")
    async def state(deal: str | None = None) -> dict:
        """Everything a fresh page needs: the deals to pick from, the one being shown,
        and its events in the order they happened. WhatsApp messages come for every
        deal, because a phone's chat starts before its deal exists."""
        events = await app.state.store.events()
        deals: dict[str, dict] = {}
        for e in events:
            if e.deal_id == NO_DEAL:
                continue
            entry = deals.setdefault(e.deal_id, {"id": e.deal_id, "ts": e.ts.isoformat(), "names": {}})
            people = (
                [e.requested_by, e.other] if isinstance(e, DealRequested)
                else e.people if isinstance(e, CallStarted) else []
            )
            entry["names"].update({p.role.value: p.name for p in people if p.name})
        deal_id = deal if deal in deals else next(reversed(deals), None)
        return {
            "deal_id": deal_id,
            "deals": list(reversed(deals.values())),
            "events": [
                e.model_dump(mode="json")
                for e in events
                if e.deal_id == deal_id or isinstance(e, WhatsAppMessage)
            ],
        }

    @app.websocket("/dashboard/ws")
    async def events(ws: WebSocket) -> None:
        await ws.accept()
        clients.add(ws)
        try:
            while True:
                await ws.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            clients.discard(ws)
