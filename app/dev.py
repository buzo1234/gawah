"""Development-only route: put any event on the bus over HTTP.

The bus lives inside the server process, so the replayer and anything else running
outside it publish through here. Set DEV_ROUTES=false to remove it. It also refuses
anything that came in through the tunnel, so the public address cannot inject events.
"""

from fastapi import FastAPI, HTTPException, Request
from pydantic import ValidationError

from app.bus import Bus
from app.contracts import parse_event

PUBLISH_PATH = "/dev/publish"
_PROXY_HEADERS = ("cf-connecting-ip", "x-forwarded-for")


def register(app: FastAPI, bus: Bus) -> None:
    if not app.state.settings.dev_routes:
        return

    @app.post(PUBLISH_PATH)
    async def publish(request: Request) -> dict[str, str]:
        if any(h in request.headers for h in _PROXY_HEADERS):
            raise HTTPException(403, "local only")
        try:
            event = parse_event(await request.body())
        except ValidationError as e:
            raise HTTPException(422, e.errors(include_url=False, include_input=False)) from e
        bus.publish(event)
        return {"published": event.name, "event_id": event.event_id}
