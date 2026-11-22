"""Run the Scribe with the live OpenAI model over a practice call, print the facts, the
conflicts and the time per line, and (with --save) keep the replies in tests/memory/recorded/
so tests and replays answer without the model.

    uv run python -m tests.memory.record fixtures/call_two_amounts.json [--model gpt-5.4-nano] [--save]

Costs one small-model call per line that is not a greeting or a plain yes. A fixture's
`gawah` turns ({after_line, text, reason, item}) are sent as judge.spoke after that line, so
the model reads them as context, as on a live call.
"""

import argparse
import asyncio
import json
import statistics
import tempfile
from pathlib import Path

from app.bus import Bus
from app.config import get_settings
from app.contracts import FactConflict, FactRecorded, ItemKey, JudgeSpoke, TranscriptLine
from app.memory import Memory, extract
from app.memory.openai_client import OpenAIClient
from app.memory.vectors import WordHashEmbedder
from fakes.replayer import load, play


class Recorder:
    def __init__(self, inner) -> None:
        self.inner = inner
        self.replies: dict[str, list[dict]] = {}
        self.checks: dict[str, dict] = {}

    async def claims(self, request):
        found = await self.inner.claims(request)
        self.replies[request.line.text] = found
        return found

    async def check(self, check):
        found = await self.inner.check(check)
        self.checks[check.key] = found
        return found


async def play_with_gawah(bus: Bus, fixture: dict, speed: float, deal_id: str) -> str:
    """The fixture onto the bus, each of Gawah's turns as judge.spoke after its line."""
    turns = fixture.get("gawah", [])

    async def emit(event) -> None:
        bus.publish(event)
        if isinstance(event, TranscriptLine):
            for turn in turns:
                if turn["after_line"] == event.line_no:
                    await bus.drain()
                    bus.publish(JudgeSpoke(deal_id=event.deal_id, text=turn["text"], reason=turn.get("reason"), item=turn.get("item")))

    return await play(fixture, emit, speed, deal_id)


async def run(path: str, model: str, effort: str, speed: float, save: bool) -> dict:
    client = OpenAIClient(get_settings())
    recorder = Recorder(extract.LiveExtractor(client, model=model, effort=effort))
    bus = Bus()
    memory = Memory(bus, recorder, WordHashEmbedder(), root=Path(tempfile.mkdtemp()), embed_model="hash")
    memory.attach(bus)
    seen = []

    async def keep(event):
        if isinstance(event, FactRecorded | FactConflict):
            seen.append(event)

    bus.subscribe_all(keep)
    bus.start()
    deal = await play_with_gawah(bus, load(path), speed, f"record-{Path(path).stem}")
    await bus.drain()
    await memory.settle()
    await bus.drain()
    for e in seen:
        if isinstance(e, FactRecorded):
            f = e.fact
            print(f"  fact  line {f.line_no:>2} {f.item.value if f.item else '-':<18} {f.status.value:<9} "
                  f"{f.value_rupees if f.value_rupees is not None else '':>6} {f.value_date or ''} {f.text}")
        else:
            print(f"  CONFLICT line {e.line_no}: {e.explanation}")
    terms = {k.value: (await memory.get_term(deal, k)).current for k in ItemKey}
    print("terms:", json.dumps({k: (v.value_rupees, v.value) if v else None for k, v in terms.items()}, ensure_ascii=False))
    lat = memory.latency
    for name in ("fact", "conflict"):
        if lat[name]:
            print(f"{name}: median {statistics.median(lat[name]):.2f}s worst {max(lat[name]):.2f}s over {len(lat[name])}")
    print("openai calls:", dict(client.calls))
    if save:
        out = extract.RECORDED / f"{Path(path).stem}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"model": model, "effort": effort, "replies": recorder.replies, "checks": recorder.checks}, indent=1, ensure_ascii=False) + "\n")
        print("saved", out)
    await client.close()
    await bus.stop()
    return {"terms": terms, "conflicts": [e for e in seen if isinstance(e, FactConflict)], "latency": lat}


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("fixture")
    p.add_argument("--model", default=extract.MODEL)
    p.add_argument("--effort", default=extract.EFFORT)
    p.add_argument("--speed", type=float, default=4.0)
    p.add_argument("--save", action="store_true")
    a = p.parse_args()
    asyncio.run(run(a.fixture, a.model, a.effort, a.speed, a.save))
