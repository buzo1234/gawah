"""A rehearsal with no person: walks the demo once against a server started by
tools/demo.py, on the real services. Not a test: it uses the free plans.

    uv run python tools/demo.py          (in one terminal)
    uv run python tools/dry_run.py       (in another)

Both phones are simulated (numbers not in VERIFIED_NUMBERS), so nothing is sent on real
WhatsApp: every message goes through the dashboard's second phone and the real webhook.
The deal call is two headless Chrome browsers on the call links from those messages,
each playing recorded lines from fixtures/audio/ as its microphone, on one shared
timeline that leaves the balance out until Gawah asks. Each call-back is a headless
Chrome on its link, in a noisy room with a "haan theek hai" every 22 seconds.

Uses about: one deal call of 3.5 minutes (4 in the room: 2 people, the listener and
Gawah) and two call-backs of 2 to 3 minutes (2 in the room), so 25 LiveKit
participant-minutes; one Sage2 call (about 30 updates); OpenAI transcription, values,
two call-backs on the realtime model, the contract and its spoken summary; 2 S3
recordings and 2 contract files. Writes the events a dashboard client received, a
summary, and a dashboard screenshot to runs/dry-<time>/.
"""

import argparse
import asyncio
import json
import re
import subprocess
import sys
import time
import wave
from datetime import datetime
from pathlib import Path

import httpx
import numpy as np
from websockets.asyncio.client import connect

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.contracts import Role  # noqa: E402
from tests.bridge_live import CallBrowser  # noqa: E402
from tests.bridge_world import SPOKEN, recorded  # noqa: E402
from tests.browser import Chrome  # noqa: E402
from tests.mouth import rig  # noqa: E402
from tests.mouth.prove_callback import microphone as callback_microphone  # noqa: E402

PHONE = {"hirer": "+919000000001", "worker": "+919000000002"}
NAME = {"hirer": "Sunita", "worker": "Ramesh"}
SPEAKER = {"Sunita": "hirer", "Ramesh": "worker"}
RATE = 16000
GAP = 1.0
# The deal call: the balance is left out (paint-16 and 17) until after the dates come up;
# a silence follows for Gawah's question, then the answer, then the wrap-up and a silence
# for Gawah's last word. Numbers are seconds of silence for both people.
TIMELINE = [
    8.0, "paint-01", "paint-02", "paint-03", "paint-04", "paint-05", "paint-06", "paint-07", "paint-08",
    "paint-09", "paint-10", "paint-11", "paint-12", "paint-13", "paint-14", "paint-15", "paint-18", "paint-19",
    14.0, "paint-16", "paint-17", "paint-20", "paint-21", "paint-22", "paint-23", "paint-24", 16.0,
]
CALL_CAP_S = 240  # the brief's budget for the deal call
CALLBACK_CAP_S = 210


def now() -> float:
    return time.monotonic()


def build_microphones(folder: Path) -> tuple[dict[str, Path], float]:
    tracks: dict[str, list[np.ndarray]] = {"hirer": [], "worker": []}
    for step in TIMELINE:
        if isinstance(step, float):
            for t in tracks.values():
                t.append(np.zeros(int(step * RATE), dtype=np.int16))
            continue
        audio = np.frombuffer(recorded(step), dtype=np.int16)
        who = SPEAKER[SPOKEN[step]["speaker"]]
        for role, t in tracks.items():
            t.append(audio if role == who else np.zeros(len(audio), dtype=np.int16))
            t.append(np.zeros(int(GAP * RATE), dtype=np.int16))
    paths = {}
    for role, parts in tracks.items():
        raw, paths[role] = folder / f"{role}-16k.wav", folder / f"{role}.wav"
        with wave.open(str(raw), "wb") as w:
            w.setnchannels(1), w.setsampwidth(2), w.setframerate(RATE)
            w.writeframes(np.concatenate(parts).tobytes())
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(raw), "-ar", "48000", "-ac", "1", str(paths[role])], check=True)
        raw.unlink()
    return paths, sum(len(p) for p in tracks["hirer"]) / RATE


class Run:
    def __init__(self, url: str, out: Path) -> None:
        self.url, self.out = url, out
        self.http = httpx.AsyncClient(base_url=url, timeout=30)
        self.events: list[tuple[float, dict]] = []
        self.steps: list[dict] = []
        self.t0 = now()

    async def watch(self) -> None:
        async with connect(self.url.replace("http", "ws", 1) + "/dashboard/ws", max_size=None) as ws:
            async for raw in ws:
                self.events.append((now(), json.loads(raw)))

    def step(self, what: str, result: str, **extra) -> None:
        row = {"at_s": round(now() - self.t0, 1), "step": what, "result": result, **extra}
        self.steps.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)

    def of(self, name: str, **match) -> list[dict]:
        return [e for _, e in self.events if e.get("name") == name and all(e.get(k) == v for k, v in match.items())]

    async def until(self, test, timeout: float):
        end = now() + timeout
        while now() < end:
            if found := test():
                return found
            await asyncio.sleep(0.25)
        return None

    async def phone(self, role: str, text: str) -> None:
        """The dashboard's second phone: posts to the WhatsApp webhook as the provider does."""
        r = await self.http.post("/dashboard/phone/send", json={"phone": PHONE[role], "text": text, "profile_name": NAME[role]})
        r.raise_for_status()

    def sent_to(self, role: str) -> list[str]:
        return [e.get("text") or e.get("media_url") or "" for e in self.of("whatsapp.message", direction="out", phone=PHONE[role])]

    def link(self, role: str, kind: str) -> str | None:
        for text in reversed(self.sent_to(role)):
            if found := re.search(rf"https?://\S+/{kind}/\S+", text):
                return found.group()
        return None

    def save(self) -> None:
        start = self.events[0][0] if self.events else self.t0
        with (self.out / "events.jsonl").open("w") as f:
            for t, e in self.events:
                f.write(json.dumps({"at_s": round(t - start, 2), **e}, ensure_ascii=False) + "\n")
        (self.out / "steps.json").write_text(json.dumps(self.steps, indent=1, ensure_ascii=False))


async def main(url: str) -> None:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = ROOT / "runs" / f"dry-{stamp}"
    out.mkdir(parents=True)
    rig.SCRATCH.mkdir(parents=True, exist_ok=True)
    run = Run(url, out)
    watcher = asyncio.create_task(run.watch())
    browsers: list = []
    try:
        await asyncio.sleep(1)
        mics, call_length = build_microphones(out)

        # 1. Sunita sends Ramesh's number. Both get a call link.
        await run.phone("hirer", PHONE["worker"].removeprefix("+91"))
        links = await run.until(lambda: all(run.link(r, "call") for r in PHONE) and [run.link(r, "call") for r in PHONE], 30)
        deal = run.of("deal.requested")
        run.step("1 deal started on WhatsApp, both get a call link", "worked" if links else "broke")
        if not links:
            return
        deal_id = deal[0]["deal_id"]

        # 2. Both open their link and tap join.
        for role, link in zip(PHONE, links):
            browser = CallBrowser(rig.SCRATCH, Role(role), mics[role])
            browsers.append(browser)
            await browser.open(link)
        for browser in browsers:
            await browser.js("document.getElementById('join').click()")
        started = await run.until(lambda: run.of("call.started", kind="deal"), 40)
        run.step("2 both joined, call.started", "worked" if started else "broke")
        if not started:
            return
        call_t0 = now()
        opening = await run.until(lambda: run.of("judge.spoke"), 30)
        run.step("2b Gawah's opening line (recording notice)", "worked" if opening else "broke",
                 said=opening[0]["text"] if opening else None)

        # 3. The call plays out; Gawah should ask about the balance.
        ended = await run.until(lambda: now() - call_t0 > call_length + 2, CALL_CAP_S)
        for browser in browsers:
            try:
                await browser.js("document.getElementById('leave') && document.getElementById('leave').click()")
            except Exception:
                pass
        lines = run.of("transcript.line", kind="deal")
        speaks, spoke = run.of("judge.speak"), [e for e in run.of("judge.spoke") if e.get("speak_id")]
        run.step("3 transcript lines on the call", f"{len(lines)} lines", by_speaker={r: sum(1 for x in lines if x["speaker"] == r) for r in PHONE})
        run.step("3b Gawah asked", "worked" if speaks else "broke", asked=[
            {"item": s.get("item"), "reason": s["reason"], "after_line": s.get("after_line"), "instruction": s["instruction"]}
            for s in speaks
        ], said=[{"text": s["text"], "start": s.get("start"), "interrupted": s.get("interrupted")} for s in spoke])
        ended = await run.until(lambda: run.of("call.ended", kind="deal"), 60)
        run.step("4 call ended", "worked" if ended else "broke", reason=ended[0].get("reason") if ended else None,
                 recordings=list((ended[0].get("recording_keys") or {}).keys()) if ended else None)
        for browser in browsers:
            browser.proc.kill()
        browsers.clear()
        checklist = run.of("checklist.updated")
        if checklist:
            run.step("4b checklist at the end", "seen", items={i["key"]: (i["state"], i.get("value")) for i in checklist[-1]["items"]})

        # 5. The call-back for each person.
        callback_links = await run.until(lambda: all(run.link(r, "callback") for r in PHONE) and [run.link(r, "callback") for r in PHONE], 30)
        run.step("5 call-back links sent", "worked" if callback_links else "broke")
        mic = callback_microphone()
        for role, link in zip(PHONE, callback_links or []):
            before = len(run.of("call.ended", kind="callback"))
            opened = now()
            browsers.append(rig.chrome(f"{link}?auto=1", mic))
            done = await run.until(lambda: len(run.of("call.ended", kind="callback")) > before, CALLBACK_CAP_S)
            browsers.pop().kill()
            confirmed = [e for e in run.of("terms.confirmed") if e["person"] == role]
            disputed = [e for e in run.of("terms.disputed") if e["person"] == role]
            run.step(f"5 call-back {role}", "worked" if confirmed else ("disputed" if disputed else "broke"),
                     seconds=round(now() - opened), ended=done[-1].get("reason") if done else "still open at our cap",
                     disputed=[d.get("item") for d in disputed])

        # 6. The contract.
        ready = await run.until(lambda: run.of("contract.ready"), 150)
        run.step("6 contract.ready", "worked" if ready else "broke")
        if ready:
            await asyncio.sleep(3)
            run.step("6b contract on WhatsApp", "seen", hirer=run.sent_to("hirer")[-3:], worker=run.sent_to("worker")[-3:])

        # 7. A cash record, confirmed by the worker on WhatsApp.
        await run.phone("hirer", "2000 cash diya")
        asked = await run.until(lambda: run.of("record.confirm_requested"), 30)
        run.step("7 cash record: worker asked", "worked" if asked else "broke", question=asked[0].get("question") if asked else None)
        if asked:
            await run.phone("worker", "haan")
            confirmed = await run.until(lambda: run.of("record.confirmed"), 30)
            run.step("7b worker said haan, record confirmed", "worked" if confirmed else "broke",
                     told_hirer=run.sent_to("hirer")[-1:])

        # The dashboard at the end.
        async with Chrome(port=9555) as chrome:
            await chrome.goto(f"{url}/dashboard")
            await asyncio.sleep(3)
            await chrome.shot(out / "dashboard.png")
            run.step("dashboard screenshot", "saved", path=str((out / "dashboard.png").relative_to(ROOT)), page_errors=chrome.errors)
    finally:
        for browser in browsers:
            (browser.proc if hasattr(browser, "proc") else browser).kill()
        await asyncio.sleep(1)
        watcher.cancel()
        run.save()
        await run.http.aclose()
        print(f"written to {out.relative_to(ROOT)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Walk the demo once with no person, on the real services.")
    parser.add_argument("--url", default="http://localhost:8000")
    asyncio.run(main(parser.parse_args().url))
