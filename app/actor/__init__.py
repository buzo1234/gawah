"""Stream: actor. For testing with one real phone: an AI that plays the second person on a call.

POST /actor/start   {deal_id, role, kind}   kind "deal" or "callback": take that person's seat
POST /actor/stop    {deal_id, role}
GET  /actor/status?deal_id=...              {active, role, kind, state, seconds, name, room}

Development only: the routes exist only with ACTOR_ROUTES=1 (shell or .env) and DEV_ROUTES on,
and refuse anything that came through the tunnel, as /dev/publish does.

The actor joins through the call page's own join route, so to the call it is that person: the
bridge opens the room, records and transcribes it, and Gawah hears it, as for a phone. One actor
at a time. It listens to call.ended and leaves with the call.

- persona.py   what it is told, from the demo story in fixtures/demo/ (adjust it there)
- realtime.py  OpenAI: its voice model, which hears the room and replies by itself
- room.py      LiveKit: its seat in the room
- actor.py     one actor on one call, and its limits
"""

import asyncio
import logging
from typing import Literal

import httpx
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel

from app.actor import persona
from app.actor.actor import Actor
from app.actor.realtime import Realtime
from app.actor.room import Seat
from app.bus import Bus
from app.config import Settings
from app.contracts import CallEnded, CallKind, Role, call_path, callback_path

log = logging.getLogger("gawah.actor")
_PROXY_HEADERS = ("cf-connecting-ip", "x-forwarded-for")


class ActorSettings(Settings):
    actor_routes: bool = False


class Start(BaseModel):
    deal_id: str
    role: Role
    kind: Literal["deal", "callback"] = "deal"


class Stop(BaseModel):
    deal_id: str
    role: Role


def enabled(settings: Settings) -> bool:
    if not settings.dev_routes:
        return False
    if isinstance(settings, ActorSettings):
        return settings.actor_routes
    return ActorSettings().actor_routes  # from the shell or .env; the shared settings stay as given


def register(app: FastAPI, bus: Bus) -> None:
    settings = app.state.settings
    if not enabled(settings):
        return
    app.state.actor = None
    lock = asyncio.Lock()
    # Tests swap these for fakes once the app is built.
    app.state.actor_seat = lambda call_log: Seat(call_log)
    app.state.actor_link = lambda config, on_event, call_log: Realtime(settings.require("openai_api_key"), config, on_event, call_log)

    def local(request: Request) -> None:
        if any(h in request.headers for h in _PROXY_HEADERS):
            raise HTTPException(403, "local only")

    def view(actor: Actor | None) -> dict:
        if actor is None or actor.state == "ended":
            return {"active": False, "role": None, "kind": None}
        return {"active": True, "role": actor.role.value, "kind": actor.kind, "state": actor.state,
                "seconds": actor.seconds(), "name": actor.name, "room": actor.room}

    async def join(deal_id: str, role: Role, kind: str) -> dict:
        """The token the person's own page would get, through the page's own join route."""
        path = call_path(deal_id, role) if kind == "deal" else callback_path(deal_id, role)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://actor", timeout=30) as http:
            answer = await http.post(f"{path}/join")
        if answer.status_code != 200:
            raise HTTPException(409 if answer.status_code in (404, 410) else 503, {"join": answer.status_code, **answer.json()})
        return answer.json()

    @app.post("/actor/start")
    async def start(body: Start, request: Request) -> dict:
        local(request)
        async with lock:
            running: Actor | None = app.state.actor
            if running and running.state != "ended":
                if (running.deal_id, running.role, running.kind) == (body.deal_id, body.role, body.kind):
                    return view(running)
                raise HTTPException(409, {"error": "busy", **view(running)})
            deal = await app.state.store.deal(body.deal_id)
            if deal is None:
                raise HTTPException(404, "no such deal")
            ticket = await join(body.deal_id, body.role, body.kind)
            call_no = ticket.get("call_no", 1)
            names = {r: (deal.person(r).name if deal.person(r) else None) for r in Role}
            actor = Actor(
                body.deal_id, body.role, body.kind, names[body.role],
                instructions=persona.instructions(body.role, body.kind, call_no, names),
                make_seat=app.state.actor_seat, make_link=app.state.actor_link,
            )
            room = f"deal-{body.deal_id}-{call_no}" if body.kind == "deal" else None
            try:
                await actor.start(ticket["url"], ticket["token"], room)
            except Exception as e:
                log.error("deal=%s actor could not start: %s: %s", body.deal_id, type(e).__name__, str(e)[:200])
                raise HTTPException(503, "the actor could not start") from e
            app.state.actor = actor
            return view(actor)

    @app.post("/actor/stop")
    async def stop(body: Stop, request: Request) -> dict:
        local(request)
        actor: Actor | None = app.state.actor
        if actor and actor.deal_id == body.deal_id and actor.role is body.role and actor.state != "ended":
            actor.stop("stopped from the dashboard")
            await actor.wait()
        return view(None)

    @app.get("/actor/status")
    async def status(deal_id: str, request: Request) -> dict:
        local(request)
        actor: Actor | None = app.state.actor
        if actor and actor.deal_id == deal_id and actor.name is None:
            # The deal began on WhatsApp without this person's name; the call itself may have told it since.
            deal = await app.state.store.deal(deal_id)
            actor.name = deal.person(actor.role).name if deal and deal.person(actor.role) else None
        return view(actor if actor and actor.deal_id == deal_id else None)

    async def call_over(event: CallEnded) -> None:
        actor: Actor | None = app.state.actor
        if actor and actor.deal_id == event.deal_id and actor.kind == event.kind.value and actor.state != "ended":
            if event.kind is CallKind.CALLBACK and actor.role not in {p.role for p in event.people}:
                return
            actor.stop("the call ended")

    async def shutdown() -> None:
        actor: Actor | None = app.state.actor
        if actor and actor.state != "ended":
            actor.stop("server stopping")
            await actor.wait()

    bus.subscribe(CallEnded, call_over)
    app.state.on_shutdown.append(shutdown)
