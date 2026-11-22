"""Who plays the two people in the dry run.

Live: two headless Chrome browsers on the real call links, each saying its lines into the
call when the dry run says so (tools/walk_browser.py), and one headless Chrome on each
call-back, in a noisy room with a "haan theek hai" every 22 seconds (as
tests/mouth/prove_callback.py does).

Offline: the app of tests/offline.py, in this process, with every outside service faked.
The rooms are fake, so a line is sent as the ears would send it (a transcript.line), the
voice model is the fake one, which answers every turn with a short line, and a call-back
is played by answering each agreed term yes with the model's own tool. Gawah's change by
voice needs the real model, so offline it is stood in for: fact.changed is sent as the
mouth sends it, on the lines where both agree the change (CHANGE).
"""

import asyncio
import re
import tempfile
import time
from pathlib import Path

import httpx

from tools.walk_browser import Person

ROLES = ("hirer", "worker")
# Offline only: call 2's line -> the step of the change it stands in for (see the docstring).
CHANGE = {8: ("proposed", []), 9: ("confirmed_one", ["hirer"]), 10: ("confirmed_both", ["hirer", "worker"])}


def deal_of(link: str) -> str:
    return re.search(r"/(?:call|callback)/([^/]+)/", link).group(1)


def path_of(link: str) -> str:
    return re.sub(r"^https?://[^/]+", "", link).split("?")[0].rstrip("/")


class LivePlayers:
    offline = False

    def __init__(self, folder: Path, speech: dict[int, dict[int, tuple[bytes, int]]], local: str) -> None:
        self.folder, self.speech, self.local = folder, speech, local  # speech: call no -> line no -> (pcm, rate)
        self.people: dict[str, Person] = {}
        self.callbacks: list = []
        self.joined_at: dict[str, float] = {}  # role -> when its browser joined the current call
        self.minutes = 0.0  # the people's own participant-minutes; the listener and Gawah add as much again

    async def join(self, role: str, link: str) -> None:
        if role not in self.people:
            self.people[role] = Person(Path(tempfile.mkdtemp(prefix="gawah-dry-")), 9600 + len(self.people), role)
            await self.people[role].start()
        person = self.people[role]
        try:
            await person.open(link)
        except TimeoutError:
            # The laptop may not resolve a new tunnel's name yet (tools/LIVE-RUN.md, step 1): same page, locally.
            print(f"{role}: {link} did not load; opening it on {self.local}", flush=True)
            await person.open(self.local + path_of(link))
        await person.click("join")
        self.joined_at[role] = time.monotonic()
        if not await person.until("['waiting', 'on'].includes(document.body.dataset.state)", 30):
            raise RuntimeError(f"{role}: the call page says {await person.state()!r}")

    async def say(self, call_no: int, line: dict) -> None:
        pcm, rate = self.speech[call_no][line["line_no"]]
        await self.people[line["speaker"]].say(pcm, rate)

    async def gawah_talking(self) -> bool:
        return any([await p.gawah_talking() for p in self.people.values()])

    async def after_line(self, call_no: int, line: dict, deal_id: str) -> None: ...

    async def leave(self) -> None:
        for role, person in self.people.items():
            try:
                await person.click("leave")
            except Exception:
                pass
            self.minutes += (time.monotonic() - self.joined_at.pop(role, time.monotonic())) / 60

    async def call_back(self, link: str) -> None:
        """Opens the call-back with the noisy-room microphone; it runs until end_call_back."""
        from tests.mouth import rig
        from tests.mouth.prove_callback import microphone

        rig.SCRATCH.mkdir(parents=True, exist_ok=True)
        self.callbacks.append((rig.chrome(f"{link}?auto=1", microphone()), time.monotonic()))

    def end_call_back(self) -> None:
        proc, opened = self.callbacks.pop()
        proc.kill()
        self.minutes += (time.monotonic() - opened) / 60

    def close(self) -> None:
        for person in self.people.values():
            person.close()
        while self.callbacks:
            self.end_call_back()


class OfflinePlayers:
    """Serves the offline app in this process and plays both people, and Gawah's model, on it."""

    offline = True

    def __init__(self, folder: Path, port: int, whatsapp: str) -> None:
        from app.records import tuning
        from tests.offline import offline_app

        tuning.BALANCE_REMINDER_SECONDS = 15.0  # the offline run need not wait a minute
        self.app = offline_app(folder / "offline.db", whatsapp=whatsapp)
        self.port, self.url = port, f"http://127.0.0.1:{port}"
        self._read_the_story_screenshot()
        self.http = httpx.AsyncClient(base_url=self.url, timeout=20)
        self.room: str | None = None
        self.call_t0 = 0.0
        self.minutes = 0.0
        self._change: dict | None = None
        self._events: list = []

    def _read_the_story_screenshot(self) -> None:
        """The fake reader reads any picture as the tests' 8,000 screenshot: read the story's as what it shows."""
        from app.records.reader import Reading
        from tests.whatsapp_world import FakeReader

        self.app.state.whatsapp.intake.reader.readings[FakeReader.IMAGE] = Reading(
            kind="advance", amount=5000, date="22 Nov 2026", transaction_id="632514790517", payment_screenshot=True,
        )

    async def start(self) -> None:
        import uvicorn

        self._server = uvicorn.Server(uvicorn.Config(self.app, host="127.0.0.1", port=self.port, log_level="warning"))
        self._serving = asyncio.create_task(self._server.serve())
        while not self._server.started:
            await asyncio.sleep(0.05)

        async def keep(event) -> None:
            self._events.append(event)

        self.app.state.bus.subscribe_all(keep)

    async def stop(self) -> None:
        await self.http.aclose()
        self._server.should_exit = True
        await self._serving

    @property
    def voice(self):
        return self.app.state.fake_voice

    @property
    def livekit(self):
        return self.app.state.calls.livekit

    async def join(self, role: str, link: str) -> None:
        from tests.mouth import sounds

        deal_id = deal_of(link)
        ended = sum(1 for s in self.voice.seats if s.gone)
        (await self.http.post(f"{path_of(link)}/join?after={ended}")).raise_for_status()
        self.room = max((n for n in self.livekit.open if n.startswith(f"deal-{deal_id}-")), key=lambda n: int(n.rsplit("-", 1)[1]))
        self.livekit.open[self.room].joined(role)
        self.call_t0 = time.monotonic()
        for _ in range(100):
            if seats := [s for s in self.voice.seats if s.room == self.room and not s.gone]:
                for who in ROLES:
                    seats[0].hears(who, sounds.room_noise(1.0, -50))
                return
            await asyncio.sleep(0.05)

    async def say(self, call_no: int, line: dict) -> None:
        from app.contracts import Role, TranscriptLine

        start = round(time.monotonic() - self.call_t0, 2)
        self.app.state.bus.publish(TranscriptLine(
            deal_id=self.room.split("-")[1], speaker=Role(line["speaker"]), text=line["text"], start=start,
            end=round(start + line["end"] - line["start"], 2), line_no=line["line_no"], call_no=call_no,
        ))
        await asyncio.sleep(0.3)

    async def gawah_talking(self) -> bool:
        return False

    async def after_line(self, call_no: int, line: dict, deal_id: str) -> None:
        from app.contracts import MEMORY_STATE, ChangeStatus, FactChanged, ItemKey, Role

        if call_no != 2 or line["line_no"] not in CHANGE:
            return
        status, confirmed = CHANGE[line["line_no"]]
        memory = getattr(self.app.state, MEMORY_STATE)
        await memory.settle()
        if status == "proposed":
            amount = (await memory.get_term(deal_id, ItemKey.AMOUNT)).current
            if amount is None:
                print("offline: memory has no agreed amount, so the change cannot be stood in for", flush=True)
            self._change = amount and {
                "deal_id": deal_id, "change_id": f"offline-{amount.id}", "fact_id": amount.id,
                "new_value": "24,000 rupees", "item": ItemKey.AMOUNT, "proposed_by": Role.HIRER,
            }
        if self._change:
            self.app.state.bus.publish(FactChanged(
                **self._change, status=ChangeStatus(status), confirmed_by=[Role(r) for r in confirmed], said=line["text"],
            ))

    async def leave(self) -> None:
        if self.room in self.livekit.open:
            for role in ROLES:
                self.livekit.open[self.room].left(role)

    async def call_back(self, link: str) -> None:
        from app.contracts import ChecklistUpdated, ItemState
        from tests.mouth import sounds

        role = path_of(link).rsplit("/", 1)[-1]
        (await self.http.post(f"{path_of(link)}/join")).raise_for_status()
        seat, model = self.voice.seats[-1], self.voice.links[-1]
        seat.hears(role, sounds.silence(0.1))
        for _ in range(100):
            if model.of("response.create"):
                break
            await asyncio.sleep(0.05)
        await model.says("Namaste, main Gawah hoon.")
        lists = [e for e in self._events if isinstance(e, ChecklistUpdated)]
        for item in [i.key.value for i in lists[-1].items if i.state is ItemState.AGREED] if lists else []:
            await model.calls("term_answer", item=item, agrees=True, said="haan ji")
        await model.says("Shukriya, namaste.")

    def end_call_back(self) -> None: ...

    def close(self) -> None: ...
