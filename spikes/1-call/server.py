"""The spike's tiny local server: the call page, join tokens for one room, page stats,
and local-only triggers for Gawah. The agent runs in the same asyncio loop as this server,
which is how the real build will run it."""

import asyncio
import socket

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse

from agent import Agent
from lk import HERE, LIVEKIT_URL, now, token



def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


PORT = free_port()


def is_local(request: Request) -> bool:
    return request.client.host in ("127.0.0.1", "::1") and "cf-connecting-ip" not in request.headers


def build(room_name: str, agent: Agent | None) -> FastAPI:
    app = FastAPI()
    app.state.reports = {}  # identity -> latest stats the page sent
    app.state.report_log = []
    app.state.leave = set()

    @app.get("/", response_class=HTMLResponse)
    async def page():
        return (HERE / "page.html").read_text()

    @app.get("/token")
    async def join_token(room: str, identity: str):
        if room != room_name or identity in ("gawah", "recorder") or not identity.isalnum():
            raise HTTPException(403, "not this room")
        return {"url": LIVEKIT_URL, "token": token(room, identity)}

    @app.post("/report")
    async def report(request: Request):
        body = await request.json()
        body["t"] = now()
        app.state.reports[body.get("identity")] = body
        app.state.report_log.append(body)
        return {"leave": body.get("identity") in app.state.leave}

    @app.post("/say")
    async def say(request: Request):
        if not is_local(request) or agent is None:
            raise HTTPException(403, "local only")
        body = await request.json()
        return await agent.mouth.say(body["text"])

    @app.post("/stop")
    async def stop(request: Request):
        if not is_local(request) or agent is None:
            raise HTTPException(403, "local only")
        await agent.mouth.stop("manual")
        return {"ok": True}

    return app


async def serve(app: FastAPI) -> tuple[uvicorn.Server, asyncio.Task]:
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="warning"))
    task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.05)
    return server, task
