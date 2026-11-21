"""Spike 7 prototype: the real dashboard, twice per call, with the six static names and with the
names gpt-6-luna generated for that call (7-results/gen-luna6.json, its read of the whole call).

    PYTHONPATH=. uv run python spikes/7-prototype.py

Nothing outside is called: the offline app (tests/offline.py) runs in this process, memory answers
from saved replies, and the brain stays quiet on a replay. Two things are changed in this process
only, never on disk:
- memory's saved replies also come from tests/brain/holdout/recorded/scribe/ (the cook call's);
- /dashboard/static/state.js is served with ITEMS renamed, which every panel reads its names from.
Extras (raised by both) have no place on today's board, so they are drawn as extra rows after load,
marked "Also discussed", and the facts panel is moved down to make room. Shots go to spikes/7-results/prototype/.
"""

import asyncio
import json
import sys
import tempfile
from pathlib import Path

import httpx
import uvicorn
from fastapi.responses import Response
from starlette.routing import Route

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from browser import Chrome  # noqa: E402

import app.memory.extract as extract  # noqa: E402
from app.contracts import CallEnded, CallStarted, Person, TranscriptLine  # noqa: E402

OUT = ROOT / "spikes/7-results/prototype"
STATE_JS = ROOT / "app/dashboard/static/state.js"
STATIC = [["work", "Work"], ["amount", "Amount"], ["advance", "Advance"], ["balance", "Balance"],
          ["dates", "Dates"], ["late_or_unfinished", "If late or unfinished"]]
KEYS = [k for k, _ in STATIC]

CALLS = {
    "cook": {"fixture": "fixtures/holdout/cook_month.json", "gen": "holdout_cook_month"},
    "painter": {"fixture": "fixtures/demo/demo_call_1.json", "gen": "demo_call_1",
                "names": {"hirer": "Sunita", "worker": "Ramesh"}},
}

_init = extract.RecordedExtractor.__init__


def _more_replies(self, folder=extract.RECORDED):
    _init(self, folder)
    for path in sorted((ROOT / "tests/brain/holdout/recorded/scribe").glob("*.json")):
        saved = json.loads(path.read_text())
        self.replies.update(saved["replies"])
        self.checks.update(saved.get("checks", {}))


extract.RecordedExtractor.__init__ = _more_replies
from tests.offline import offline_app  # noqa: E402


def lint_ok(label: str) -> bool:
    import importlib.util
    spec = importlib.util.spec_from_file_location("l7", ROOT / "spikes/7-labels.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return not m.lint(label)


def generated(cid: str) -> tuple[list[list[str]], list[dict], dict]:
    """The read of the whole call; a label that fails the lint keeps its static name."""
    out = json.loads((ROOT / "spikes/7-results/gen-luna6.json").read_text())["calls"][cid]["end"]["out"]
    items = [[k, out["terms"][k]["label"] if lint_ok(out["terms"][k]["label"]) else dict(STATIC)[k]] for k in KEYS]
    return items, out["extras"], out["terms"]


async def main(port: int = 8765) -> None:
    home = Path(tempfile.mkdtemp(prefix="gawah-labels-"))
    app = offline_app(home / "gawah.db")
    names = {"items": STATIC}
    original = STATE_JS.read_text()
    static_block = original[original.index("export const ITEMS = ["):original.index("];", original.index("export const ITEMS = [")) + 2]

    async def state_js(request):
        block = "export const ITEMS = " + json.dumps(names["items"]) + ";"
        return Response(original.replace(static_block, block), media_type="text/javascript",
                        headers={"Cache-Control": "no-store"})

    app.router.routes.insert(0, Route("/dashboard/static/state.js", state_js))
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    serving = asyncio.create_task(server.serve())
    url = f"http://127.0.0.1:{port}"
    report = {}
    async with httpx.AsyncClient(base_url=url, timeout=10) as http:
        while not server.started:
            await asyncio.sleep(0.05)

        async def publish(e):
            (await http.post("/dev/publish", content=e.model_dump_json())).raise_for_status()

        async def settle(deal):
            last = None
            while True:
                state = (await http.get("/memory/state", params={"deal": deal})).json()
                if state["versions"] == last:
                    return state
                last = state["versions"]
                await asyncio.sleep(1.5)

        for name, c in CALLS.items():
            f = json.loads((ROOT / c["fixture"]).read_text())
            people = [Person(**{**p, "name": p["name"] or c.get("names", {}).get(p["role"])}) for p in f["people"]]
            deal = f"labels-{name}"
            await publish(CallStarted(deal_id=deal, people=people, room=f"replay-{deal}"))
            for i, line in enumerate(f["lines"], 1):
                await publish(TranscriptLine(deal_id=deal, **{**line, "line_no": line.get("line_no") or i}))
                await asyncio.sleep(0.15)
            await publish(CallEnded(deal_id=deal, people=people, room=f"replay-{deal}", duration=f["lines"][-1]["end"]))
            state = await settle(deal)
            report[name] = {"facts": len(state["facts"])}

        async with Chrome(port=port + 1000) as chrome:
            await chrome.send("Network.enable")
            await chrome.send("Network.setCacheDisabled", cacheDisabled=True)
            for name, c in CALLS.items():
                items, extras, terms = generated(c["gen"])
                for variant in ("static", "generated"):
                    names["items"] = STATIC if variant == "static" else items
                    await chrome.goto(f"{url}/dashboard?deal=labels-{name}")
                    await chrome.wait_for("document.body.dataset.loaded === 'true'")
                    await asyncio.sleep(2.5)
                    if variant == "generated" and extras:
                        rows = [{"label": e["label"], "hint": e["hint"]} for e in extras]
                        await chrome.js(EXTRA_ROWS % json.dumps(rows))
                    shown = await chrome.js("[...document.querySelectorAll('#items .name')].map(e => e.textContent)")
                    await chrome.shot(OUT / f"{name}-{variant}.png")
                    report[name][variant] = shown
                report[name]["asks"] = {k: terms[k]["ask"] for k in KEYS}
            report["errors"] = chrome.errors
    server.should_exit = True
    await serving
    (OUT / "report.json").write_text(json.dumps(report, indent=1, ensure_ascii=False))
    print(json.dumps(report, indent=1, ensure_ascii=False))


# Extra rows after the six, in the checklist's own markup; a pill says what they are.
EXTRA_ROWS = """(() => {
  const ul = document.getElementById('items');
  const extras = %s;
  const style = document.createElement('style');  // room for the extra rows: the facts move down
  style.textContent = `#items { height: auto; } .feed { top: ${556 + 64 * extras.length}px; }
    .item.extra { background: var(--paper-2, rgba(0,0,0,0.025)); }`;
  document.head.appendChild(style);
  for (const e of extras) {
    const li = document.createElement('li');
    li.className = 'item extra';
    li.title = e.hint;
    li.innerHTML = `<span class="top-line"><span class="name label"></span><span class="state pill">Also discussed</span></span>
      <span class="foot"><span class="value none"></span></span>`;
    li.querySelector('.name').textContent = e.label;
    li.querySelector('.value').textContent = e.hint;
    ul.appendChild(li);
  }
  return true;
})()"""


if __name__ == "__main__":
    asyncio.run(main())
