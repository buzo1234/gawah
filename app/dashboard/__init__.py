"""Stream: dashboard. This stub shows every event live, and is the worked example of
the register hook. The dashboard stream replaces it."""

from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

from app.bus import Bus
from app.contracts import Event

PAGE = Path(__file__).parent / "page.html"


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

    @app.get("/dashboard", response_class=HTMLResponse)
    async def page() -> str:
        return PAGE.read_text()

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
