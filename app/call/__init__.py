"""Stream: bridge. Owns rooms, join links, the call page.

GET  /call/{deal_id}/{role}        the call page (a link preview may fetch it: it opens nothing)
POST /call/{deal_id}/{role}/join   the join button: opens the room if needed, returns a token
"""

import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.bus import Bus
from app.call.session import Calls
from app.contracts import Deal, Role
from app.log import deal_log

HERE = Path(__file__).parent
PAGE = HERE / "page.html"
NOT_VALID = HERE / "not_valid.html"
ROLE_WORDS = {Role.HIRER: "kaam dene wale", Role.WORKER: "kaam karne wale"}


def register(app: FastAPI, bus: Bus) -> None:
    calls = app.state.calls = Calls(app.state.settings, bus, app.state.store)

    async def shutdown() -> None:
        await calls.close_all()
        # This hook runs last, and the store closes right after it. An event still being
        # written then (call.ended, or anything another stream just sent) crashes the
        # process, so wait for the bus to go quiet first.
        try:
            await bus.drain()
        except TimeoutError:
            pass

    app.state.on_shutdown.append(shutdown)
    # Mounted before the page route, which would otherwise match /call/static/<file>.
    app.mount("/call/static", StaticFiles(directory=HERE / "static"), name="call-static")

    async def find(deal_id: str, role: str) -> tuple[Deal, Role] | None:
        if role not in Role:
            return None
        deal = await app.state.store.deal(deal_id)
        if deal is None or any(deal.person(r) is None for r in Role):
            return None
        return deal, Role(role)

    @app.get("/call/{deal_id}/{role}", response_class=HTMLResponse)
    async def page(deal_id: str, role: str) -> HTMLResponse:
        found = await find(deal_id, role)
        if found is None:
            return HTMLResponse(NOT_VALID.read_text(), status_code=404)
        deal, me = found
        config = {
            "role": me.value,
            "other": me.other.value,
            "name": deal.person(me).name,
            "otherName": deal.person(me.other).name,
            "roleWords": ROLE_WORDS[me],
            "over": calls.is_over(deal),
        }
        # "<" is escaped so a name cannot close the script tag.
        return HTMLResponse(PAGE.read_text().replace("__CONFIG__", json.dumps(config).replace("<", "\\u003c")))

    @app.post("/call/{deal_id}/{role}/join")
    async def join(deal_id: str, role: str) -> JSONResponse:
        found = await find(deal_id, role)
        if found is None:
            return JSONResponse({"error": "not_valid"}, status_code=404)
        deal, me = found
        try:
            token = await calls.join(deal, me)
        except Exception:
            deal_log("gawah.call", deal_id).exception("could not open the room")
            return JSONResponse({"error": "unavailable"}, status_code=503)
        if token is None:
            return JSONResponse({"error": "over"}, status_code=410)
        return JSONResponse({"url": calls.livekit.url, "token": token})
