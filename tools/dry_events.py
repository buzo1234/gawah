"""The dry run's view of the server: every event a dashboard client gets, the simulated
phones, a dashboard open in headless Chrome for screenshots, and the steps as they went."""

import asyncio
import json
import re
import time
from pathlib import Path

import httpx
from websockets.asyncio.client import connect

from tests.browser import Chrome

PHONE = {"hirer": "+919000000001", "worker": "+919000000002"}
NAME = {"hirer": "Sunita", "worker": "Ramesh"}


def now() -> float:
    return time.monotonic()


class Run:
    def __init__(self, url: str, out: Path) -> None:
        self.url, self.out = url, out
        self.http = httpx.AsyncClient(base_url=url, timeout=30)
        self.events: list[dict] = []  # as received, each with "_at": when, on this clock
        self.steps: list[dict] = []
        self.usage: dict = {}
        self.deal_id: str | None = None
        self.t0 = now()
        self.dashboard: Chrome | None = None

    async def begin(self) -> None:
        self._watcher = asyncio.create_task(self._watch())
        self.dashboard = await Chrome(port=9655).__aenter__()
        await self.dashboard.goto(f"{self.url}/dashboard")
        await asyncio.sleep(1)

    async def end(self) -> None:
        await asyncio.sleep(1)
        self._watcher.cancel()
        if self.dashboard:
            self.steps.append({"dashboard page errors": self.dashboard.errors})
            await self.dashboard.__aexit__(None, None, None)
        self.save()
        await self.http.aclose()

    async def _watch(self) -> None:
        async with connect(self.url.replace("http", "ws", 1) + "/dashboard/ws", max_size=None) as ws:
            async for raw in ws:
                event = json.loads(raw)
                event["_at"] = now()
                self.events.append(event)
                if event.get("name") == "fact.changed" and event.get("status") == "confirmed_both":
                    asyncio.create_task(self._later_shot(3, "3-change-confirmed"))

    async def _later_shot(self, seconds: float, name: str) -> None:
        await asyncio.sleep(seconds)
        await self.shot(name)

    async def load_past(self) -> None:
        """The latest deal's events so far, as a freshly opened dashboard gets them."""
        state = (await self.http.get("/dashboard/state")).json()
        self.events = [{**e, "_at": self.t0} for e in state["events"]] + self.events
        requested = self.of("deal.requested")
        if not requested:
            raise SystemExit("the server has no deal to carry on")
        self.deal_id = requested[-1]["deal_id"]

    async def shot(self, name: str) -> None:
        if self.dashboard is None:
            return
        try:
            path = self.out / f"{name}.png"
            await self.dashboard.shot(path)
            self.step(f"screenshot {name}", "saved", path=str(path))
        except Exception as e:
            self.step(f"screenshot {name}", f"failed: {type(e).__name__}")

    def step(self, what: str, result: str, **extra) -> dict:
        row = {"at_s": round(now() - self.t0, 1), "step": what, "result": result, **extra}
        self.steps.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
        return row

    def at(self, event: dict) -> float:
        return event["_at"]

    def of(self, name: str, **match) -> list[dict]:
        return [e for e in self.events if e.get("name") == name and all(e.get(k) == v for k, v in match.items())
                and (self.deal_id is None or name == "whatsapp.message" or e.get("deal_id") == self.deal_id)]

    def gawah_said(self, after: float) -> list[str]:
        """What Gawah finished saying on the deal call since then: judge.spoke, and its own turns' notes."""
        said = [e["text"] for e in self.of("judge.spoke") if e["_at"] >= after and e.get("text")]
        notes = [e["text"][6:] for e in self.of("agent.note", agent="gawah") if e["_at"] >= after and e["text"].startswith("said: ")]
        return said + [n for n in notes if n not in said]

    def speaks_since(self, after: float) -> list[dict]:
        return [{"reason": e["reason"], "item": e.get("item"), "after_line": e.get("after_line")}
                for e in self.of("judge.speak") if e["_at"] >= after - 5]

    async def until(self, test, timeout: float):
        end = now() + timeout
        while now() < end:
            if found := test():
                return found
            await asyncio.sleep(0.25)
        return None

    async def phone(self, role: str, text: str, media_url: str | None = None, media_type: str | None = None) -> None:
        """The dashboard's second phone: posts to the WhatsApp webhook as the provider does."""
        body = {"phone": PHONE[role], "text": text, "profile_name": NAME[role], "media_url": media_url, "media_type": media_type}
        (await self.http.post("/dashboard/phone/send", json=body)).raise_for_status()

    async def upload(self, image: Path) -> str:
        r = await self.http.post("/dashboard/media", content=image.read_bytes(), headers={"content-type": "image/png"})
        r.raise_for_status()
        return r.json()["url"]

    def sent_to(self, role: str) -> list[str]:
        return [e.get("text") or e.get("media_url") or "" for e in self.of("whatsapp.message", direction="out", phone=PHONE[role])]

    def link(self, role: str, kind: str, since: int = 0) -> str | None:
        """The newest link of this kind Gawah sent the person, among their messages from index since."""
        sent = self.sent_to(role)
        for text in reversed(sent[since:] if kind == "callback" else sent):
            if found := re.search(rf"https?://\S+/{kind}/\S+", text):
                return found.group()
        return None

    @staticmethod
    def shown(texts: list[str]) -> list[str]:
        """For the printout: a signed S3 link carries the temporary AWS session token."""
        return [re.sub(r"https://\S+\.amazonaws\.com/\S+", "<signed S3 link>", t) for t in texts]

    def save(self) -> None:
        start = self.events[0]["_at"] if self.events else self.t0
        with (self.out / "events.jsonl").open("w") as f:
            for e in self.events:
                row = {"at_s": round(e["_at"] - start, 2), **{k: v for k, v in e.items() if k != "_at"}}
                f.write(re.sub(r"https://[^\"\s]+\.amazonaws\.com/[^\"\s]+", "<signed S3 link>", json.dumps(row, ensure_ascii=False)) + "\n")
        (self.out / "steps.json").write_text(json.dumps({"steps": self.steps, "usage": self.usage}, indent=1, ensure_ascii=False))
