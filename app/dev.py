"""Development-only route: put any event on the bus over HTTP.

The bus lives inside the server process, so the replayer and tests publish through
here. Nothing in the app does: the LiveKit agent runs in-process and uses the bus.
Set DEV_ROUTES=false to remove it. It also refuses anything that came in through the
tunnel or a proxy, so the public address cannot inject events; on a server with ACCESS_KEY
set, it takes them only with the key (app/access.py guards /dev).
"""

from fastapi import FastAPI, HTTPException, Request
from pydantic import ValidationError

from app.access import local_or_keyed
from app.bus import Bus
from app.contracts import parse_event

PUBLISH_PATH = "/dev/publish"


def register(app: FastAPI, bus: Bus) -> None:
    if not app.state.settings.dev_routes:
        return

    @app.post(PUBLISH_PATH)
    async def publish(request: Request) -> dict[str, str]:
        local_or_keyed(request)
        try:
            event = parse_event(await request.body())
        except ValidationError as e:
            raise HTTPException(422, e.errors(include_url=False, include_input=False)) from e
        bus.publish(event)
        return {"published": event.name, "event_id": event.event_id}
