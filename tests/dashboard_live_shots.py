"""Proof run for the dashboard on the real memory, in a real browser at 1920 by 1080. Not
collected by pytest. Reaches nothing outside: it serves the offline app (tests/offline.py,
with memory answering from its saved replies) in this process, so it knows where the call
recordings go.

    PYTHONPATH=. uv run python tests/dashboard_live_shots.py

0. The board with no deal, then a deal started on WhatsApp before its call: the designed
   empty states (0-no-deal, 0b-before-the-call).
1. call_missing_balance to line 17, then the shot: mid-call; five lines more, caught while
   their facts come in (1b). The user's recorded lines (fixtures/audio) are laid out as the
   call's two recordings, at the times of the call's lines, so a clip button plays real
   audio from memory. Pointing at a timeline entry lights its chip in the graph, and
   pointing at a term shows memory's current term in the detail card.
2. call_two_amounts to line 21, a line every 0.3 seconds, filmed (2-facts-arriving.mp4 and
   a contact sheet, with ffmpeg) so the motion can be judged: memory's contradiction on
   line 19, then the shot, also at 1440 by 900 and 1280 by 720. The amount's lane must hold
   the 14,000 as a claim with the red edge back to the agreed 13,000, the detail card must
   be slide 7, and its "Original moment" must play (this call's recordings are laid down
   silent, so the clip is real but quiet).
2b. On the same deal (started on WhatsApp, as a real one is), voice notes from
   fixtures/voice-notes/ through the webhook: Sunita's on the work, and Ramesh's change of
   the amount to 25,000, which Sunita says yes to. The voice-note facts carry their own
   mark, the amount reads "Changed by voice note, both said yes" and the detail card shows
   the voice note's fact, then the shot.
3. The first call finished, an advance paid on WhatsApp, and the amount changed by both:
   payments, what they count towards, and a replaced version, then the shot; then the
   timeline scrolled down while a new fact arrives: what the viewer reads stays put and a
   pill says one entry is newer (3b). Then the call-backs: both confirm every term, as the
   mouth tells memory (terms.confirmed), so the timeline has entries with both people and
   their status, each with its clip (3c).

After each shot: the board is checked against memory's own answers (/memory/state, terms,
owed, /memory/chain; every fact in the timeline, at memory's status; the chip marked as
standing memory's current term; a payment in the lane of the term it counts towards), the
checklist against the brain's, and a reload must rebuild exactly the same page.
4. One past fact is altered inside memory, and the chain must name the link that broke.
5. The second phone on its own page, at phone size: a message typed and sent goes through
   the webhook and comes back in the chat. The actor's endpoints are stood in for here
   (they belong to another stream): answering 404, the "AI plays this person" toggle is
   hidden; answering, with the toggle on, a call link that arrives starts the actor with
   the link's deal, role and kind. On the board, a call link tapped in the frame opens the
   call page in the frame (nothing is joined: the join button is not pressed).
7. The second phone on Meta's message shapes, as WhatsApp draws them: a call link as a
   button in its bubble, yes or no questions as reply buttons; one tapped on the page goes
   to the intake as Meta's button reply for that question, and its buttons look used;
   "+" opens Photo and Voice note; the send button waits for something to send.
"""

import argparse
import asyncio
import base64
import io
import json
import re
import shutil
import subprocess
import tempfile
import wave
from pathlib import Path

import httpx
import uvicorn
from browser import Chrome

from fastapi import Request
from fastapi.responses import JSONResponse

from app.contracts import (
    WHATSAPP_WEBHOOK_PATH, CallEnded, CallKind, CallStarted, ChangeStatus, Direction, FactChanged, ItemKey, Person, Record,
    RecordKind, RecordReceived, Role, TermsConfirmed, TranscriptLine, WhatsAppMessage, new_id,
)
from fakes.replayer import load
from tests.offline import offline_app

PANELS = ["rows", "settled-count", "timeline", "fact-count", "detail", "chain", "chain-head"]
SNAPSHOT = """JSON.stringify({
  text: Object.fromEntries(%r.map((id) => [id, document.getElementById(id).textContent])),
  cards: [...document.querySelectorAll('#rows .term, #rows .chip:not([hidden]), #timeline > li, #ticks i')].map((p) => p.getAttribute('class').replace(/ ?(enter|moved|pulse|landed|swap|lit)\\b/g, '')),
})""" % PANELS
LOADED = "document.body.dataset.conn === 'live' && document.body.dataset.loaded === 'true'"
VERIFIED = "document.getElementById('chain').textContent.includes('verified') && !document.getElementById('chain').textContent.includes('new')"
# Every fact in the timeline at its newest status (its newest entry is the first), and the
# chips: which facts each stands for, in which term's lane, and whether the term stands on it.
TIMELINE = """JSON.stringify([...document.querySelectorAll('#timeline .entry')].map((el) => ({
  id: el.dataset.fact, status: el.dataset.status, item: el.dataset.item, word: el.querySelector('.word')?.textContent || 'Said' })))"""
CHIPS = """JSON.stringify([...document.querySelectorAll('#rows .chip:not(.stub)')].map((el) => ({
  ids: el.dataset.facts.split(' '), item: el.closest('.term').dataset.item, stands: el.classList.contains('stands'), value: el.dataset.value,
  status: [...el.classList].find((c) => ['said','agreed','confirmed','superseded','disputed','claim','paid'].includes(c)) })))"""
OWED = "JSON.stringify([...document.querySelectorAll('#rows .owed')].map((el) => [el.closest('.term').dataset.item, el.textContent]))"
DETAIL = """JSON.stringify({ fact: document.querySelector('#detail .fact-card')?.dataset.fact || null, text: document.getElementById('detail').textContent })"""
# A term's value is cut at a word when it is too long for its node; its full text is the
# first line of the node's hover text.
CHECKLIST = """JSON.stringify(Object.fromEntries([...document.querySelectorAll('#rows .term')].map((el) => [el.dataset.item, {
  state: el.querySelector('.state')?.textContent || '', value: el.querySelector('.node').title.split('\\n')[0] || el.querySelector('.value').textContent,
  node: el.querySelector('.node').dataset.value, lane: el.querySelectorAll('.chip:not(.stub)').length,
  shown: el.querySelector('.value').textContent, title: el.querySelector('.node').title,
  when: el.dataset.when || '', contradicted: el.querySelector('.contradicted')?.title || '',
}])))"""
GONE = ["flow", "decisions", "records", "lanes", "real-chat", "deal-picker", "conn", "people", "status", "graph", "nodes", "edges", "card-slot",
        "chain-links", "feed", "tracks", "layer", "chain-row", "below", "items", "graph-count", "layer-time"]
IN_VIEW = """(() => { const r = document.querySelector('%s').getBoundingClientRect();
  return r.top >= 0 && r.bottom <= innerHeight && r.left >= 0 && r.right <= innerWidth; })()"""
# Nothing overlaps anything it should not: the cards and columns, and the chips of a lane.
OVERLAPS = """(() => {
  const box = (el) => el.getBoundingClientRect();
  const hit = (a, b) => a.left < b.right - 0.5 && b.left < a.right - 0.5 && a.top < b.bottom - 0.5 && b.top < a.bottom - 0.5;
  const out = [];
  const blocks = ['#terms', '#detail', '.timeline-card', '.device', '.top'].map((s) => [s, box(document.querySelector(s))]);
  blocks.forEach(([a, ra], i) => blocks.slice(i + 1).forEach(([b, rb]) => { if (hit(ra, rb)) out.push(a + ' / ' + b); }));
  for (const lane of document.querySelectorAll('.chips')) {
    const chips = [...lane.children].filter((c) => !c.hidden).map(box);
    chips.forEach((a, i) => chips.slice(i + 1).forEach((b) => { if (hit(a, b)) out.push('chips in ' + lane.closest('.term').dataset.item); }));
    const lr = box(lane.closest('.lane'));
    chips.forEach((c) => { if (c.right > lr.right + 0.5) out.push('chip past its lane in ' + lane.closest('.term').dataset.item); });
  }
  const stage = document.getElementById('stage');
  const scale = stage.getBoundingClientRect().width / stage.offsetWidth;
  for (const node of document.querySelectorAll('.node')) {
    const edge = box(node).right - 24 * scale;
    for (const el of node.querySelectorAll('.l1 > *, .pills > *, .l2 > *')) if (box(el).right > edge + 0.5) out.push('into the padding of ' + node.closest('.term').dataset.item + ': ' + el.textContent.slice(0, 30));
  }
  for (const el of document.querySelectorAll('.node .value, .node .l1, .entry .text, #detail .hero, #detail .value')) {
    if (el.scrollWidth > el.clientWidth + 1) out.push('cut by its box: ' + el.className + ' ' + el.textContent.slice(0, 30));
  }
  return JSON.stringify(out); })()"""
ARRIVING = """new Promise((done) => {
  const seen = new MutationObserver(() => {
    if (document.querySelector('#timeline .entry.enter')) { seen.disconnect(); done(true); }
  });
  seen.observe(document.getElementById('timeline'), { subtree: true, childList: true, attributes: true });
})"""
# What the review crops are judged on, in the stage's own px (the board at 1920 wide):
# paddings of the page, the header's logo, a timeline entry, each term row and each chip.
MEASURE = """(() => {
  const stage = document.getElementById('stage');
  const k = stage.getBoundingClientRect().width / stage.offsetWidth;
  const box = (el) => el.getBoundingClientRect();
  const r = (n) => Math.round(n / k * 10) / 10;
  const textBox = (el) => { const range = document.createRange(); range.selectNodeContents(el); return range.getBoundingClientRect(); };
  const kids = (el) => [...el.children].filter((c) => !c.hidden && getComputedStyle(c).display !== 'none');
  const out = {};
  const top = box(document.querySelector('.top')), deal = box(document.querySelector('.deal')), phone = box(document.querySelector('#phone'));
  out.page = { window: [innerWidth, innerHeight], stage: [stage.offsetWidth, stage.offsetHeight], left: r(top.left), top: r(top.top),
    right: r(innerWidth - phone.right), bottom: r(innerHeight - deal.bottom) };
  const logo = document.querySelector('.top .logo'), h1 = document.getElementById('deal-title'), pill = document.getElementById('call-pill');
  const mid = (b) => r(b.top + b.height / 2);
  out.header = { logo: [r(box(logo).width), r(box(logo).height)], radius: getComputedStyle(logo).borderRadius, alt: logo.alt,
    logoMid: mid(box(logo)), titleMid: mid(box(h1)), pillMid: mid(box(pill)), logoRight: r(innerWidth - box(logo).right) };
  const entries = [...document.querySelectorAll('#timeline .entry')];
  const e = entries.find((x) => x.querySelectorAll('.people > *').length >= 3 && x.querySelector('.play')) || entries.find((x) => x.querySelector('.play'));
  if (e) {
    const eb = box(e), list = document.getElementById('timeline'), lb = box(list);
    const play = box(e.querySelector('.play .mark')), people = [...e.querySelectorAll('.people > *')].map(box);
    const main = box(e.querySelector('.main')), time = box(e.querySelector('.time'));
    out.entry = { fact: e.dataset.fact, pills: people.length, pillRows: new Set(people.map((b) => Math.round(b.top))).size,
      padLeft: r(time.left - eb.left), padRight: r(eb.right - play.right), pillsPastMain: r(Math.max(...people.map((b) => b.right)) - main.right),
      playToMain: r(play.left - main.right), playMidVsEntryMid: r((play.top + play.height / 2) - (eb.top + eb.height / 2)),
      scrollbarGutter: r(lb.right - eb.right), entryWidth: r(eb.width) };
  }
  out.rows = [...document.querySelectorAll('#rows .term')].map((t) => {
    const tb = box(t), node = t.querySelector('.node'), parts = kids(node).map(box);
    const lane = t.querySelector('.lane'), chips = kids(lane.querySelector('.chips')).map(box);
    return { item: t.dataset.item, height: r(tb.height), nodeTop: r(parts[0].top - tb.top), nodeBottom: r(tb.bottom - 1 - parts.at(-1).bottom),
      laneHeight: r(box(lane).height), chipTop: chips.length ? r(Math.min(...chips.map((c) => c.top)) - tb.top) : null,
      chipBottom: chips.length ? r(tb.bottom - 1 - Math.max(...chips.map((c) => c.bottom))) : null };
  });
  out.chips = [...document.querySelectorAll('#rows .chip')].filter((c) => !c.hidden).map((c) => {
    const cb = box(c), parts = kids(c), b = parseFloat(getComputedStyle(c).borderLeftWidth);
    const tb = (x) => (x.classList.contains('v') ? textBox(x) : box(x));
    const first = parts.length ? tb(parts[0]) : textBox(c), last = parts.length ? tb(parts.at(-1)) : textBox(c);
    const cy = cb.top + cb.height / 2;
    const off = (pb) => Math.abs(r(pb.top + pb.height / 2 - cy));
    return { kind: [...c.classList].filter((x) => !['chip', 'lit', 'enter', 'landed'].includes(x)).join(' '), text: c.textContent.slice(0, 24),
      left: r(first.left - cb.left - b), right: r(cb.right - b - last.right),
      offCentre: parts.length ? Math.max(...parts.map((x) => off(tb(x)))) : off(textBox(c)) };
  });
  return JSON.stringify(out); })()"""
AUDIO = Path("fixtures/audio")
FRAME = "document.getElementById('phone-frame').contentWindow"
PHONE_TITLE = "document.getElementById('phone-title')"
PROBE = "/actor/status"  # the phone asks once whether the actor is there; its 404 is the answer "not yet"
money = lambda text: text.replace(" ", "").replace(" ", "").replace(",", "")
# How the board writes memory's value: "13,000 rupees" as ₹ 13,000, a few words after the figure kept.
board = lambda value: re.sub(r"^([\d,]+) rupees\b[\s,;:]*", r"₹\1 ", value or "").strip()


def errors(browser) -> list[str]:
    return [e for e in browser.errors if not (PROBE in e and "404" in e)]


def stand_in_actor(app) -> dict:
    """The actor's three endpoints, as another stream will serve them: 404 until switched on."""
    actor = {"on": False, "started": [], "stopped": [], "active": None}

    async def status(request: Request):
        if not actor["on"]:
            return JSONResponse({"detail": "Not Found"}, 404)
        a = actor["active"]
        return {"active": bool(a), "role": a and a["role"], "kind": a and a["kind"]}

    async def start(request: Request):
        if not actor["on"]:
            return JSONResponse({"detail": "Not Found"}, 404)
        actor["active"] = await request.json()
        actor["started"].append(actor["active"])
        return {"ok": True}

    async def stop(request: Request):
        if not actor["on"]:
            return JSONResponse({"detail": "Not Found"}, 404)
        actor["stopped"].append(await request.json())
        actor["active"] = None
        return {"ok": True}

    app.add_api_route("/actor/status", status, methods=["GET"])
    app.add_api_route("/actor/start", start, methods=["POST"])
    app.add_api_route("/actor/stop", stop, methods=["POST"])
    return actor


def film_to(frames: Path, video: Path, sheet: Path) -> None:
    """The frames as a video at their real pace, and a contact sheet of every third one.
    Needs ffmpeg; without it the frames are left where they are."""
    shots = sorted(frames.glob("*.jpg"))
    if not shutil.which("ffmpeg"):
        print(f"  no ffmpeg: {len(shots)} frames left in {frames}")
        return
    seconds = max(1.0, (shots[-1].stat().st_mtime - shots[0].stat().st_mtime)) if shots else 1.0
    rate = f"{len(shots) / seconds:.2f}"
    common = ["ffmpeg", "-loglevel", "error", "-y", "-framerate", rate, "-i", str(frames / "%04d.jpg")]
    subprocess.run([*common, "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video)], check=True)
    rows = max(1, -(-len(shots) // 12))
    subprocess.run([*common, "-vf", f"select='not(mod(n\\,3))',scale=480:-1,tile=4x{rows}", "-frames:v", "1", str(sheet)], check=True)
    print(f"  {len(shots)} frames over {seconds:.1f} s: {video}, {sheet}")


async def press(chrome, selector: str) -> None:
    """A real mouse press in the middle of the element, as a person's: the page may only
    start sound from one."""
    box = json.loads(await chrome.js(f"""(() => {{ const r = document.querySelector('{selector}').getBoundingClientRect();
        return JSON.stringify([r.x + r.width / 2, r.y + r.height / 2]); }})()"""))
    for kind in ("mousePressed", "mouseReleased"):
        await chrome.send("Input.dispatchMouseEvent", type=kind, x=box[0], y=box[1], button="left", clickCount=1)


def silent_recordings(folder: Path, seconds: int) -> None:
    """A call's two recordings, silent, where the bridge would leave them: a clip from them
    plays, with nothing to hear."""
    folder.mkdir(parents=True, exist_ok=True)
    for role in ("hirer", "worker"):
        with wave.open(str(folder / f"{role}.wav"), "wb") as w:
            w.setnchannels(1), w.setsampwidth(2), w.setframerate(16000)
            w.writeframes(bytes(seconds * 16000 * 2))


def lay_recordings(folder: Path, fixture: dict) -> list[int]:
    """The user's recorded lines, each at the time of the call line with the same number
    and the same kind of speaker, in one track per role. Returns the lines covered."""
    said = json.loads((AUDIO / "state.json").read_text())
    role_of = {"Sunita": "hirer", "Ramesh": "worker"}
    tracks = {"hirer": bytearray(), "worker": bytearray()}
    rate, covered = 16000, []
    for line in fixture["lines"]:
        take = said.get(f"paint-{line['line_no']:02d}")
        if not take or role_of[take["speaker"]] != line["speaker"]:
            continue
        with wave.open(str(AUDIO / take["wav"]), "rb") as w:
            assert (w.getframerate(), w.getnchannels(), w.getsampwidth()) == (rate, 1, 2)
            pcm = w.readframes(w.getnframes())
        track = tracks[line["speaker"]]
        at = int(line["start"] * rate) * 2
        track.extend(b"\0" * max(0, at - len(track)))
        track[at:at + len(pcm)] = pcm
        covered.append(line["line_no"])
    folder.mkdir(parents=True, exist_ok=True)
    for role, pcm in tracks.items():
        with wave.open(str(folder / f"{role}.wav"), "wb") as w:
            w.setnchannels(1), w.setsampwidth(2), w.setframerate(rate)
            w.writeframes(bytes(pcm))
    return covered


async def point_at(chrome, selector: str | None) -> None:
    """The mouse over the middle of an element, as a person's, or away from everything."""
    if selector is None:
        x, y = 1, 1
    else:
        x, y = json.loads(await chrome.js(f"""(() => {{ const el = document.querySelector({json.dumps(selector)}); el.scrollIntoView({{block: 'nearest'}});
            const r = el.getBoundingClientRect(); return JSON.stringify([r.x + r.width / 2, r.y + r.height / 2]); }})()"""))
    await chrome.send("Input.dispatchMouseEvent", type="mouseMoved", x=x, y=y)
    await asyncio.sleep(0.15)


async def sized(chrome, width: int, height: int, path: Path) -> dict:
    """The same page in a smaller window: the board scales to it, whole, with the same
    margin on all four sides. Returns the page's margins, in the stage's px."""
    await chrome.send("Emulation.setDeviceMetricsOverride", width=width, height=height, deviceScaleFactor=1, mobile=False)
    await asyncio.sleep(0.4)
    await chrome.shot(path)
    page = json.loads(await chrome.js(MEASURE))["page"]
    await chrome.send("Emulation.setDeviceMetricsOverride", width=1920, height=1080, deviceScaleFactor=1, mobile=False)
    await asyncio.sleep(0.3)
    return page


async def review(chrome, folder: Path, tag: str) -> dict:
    """2x crops of a timeline entry, the six term rows, the busiest lane, the header and the
    four page corners, with what they are judged on (MEASURE), printed and returned."""
    folder.mkdir(parents=True, exist_ok=True)
    found = json.loads(await chrome.js(MEASURE))
    await chrome.send("Emulation.setDeviceMetricsOverride", width=1920, height=1080, deviceScaleFactor=2, mobile=False)
    await asyncio.sleep(0.4)

    async def crop(name: str, selector: str | None = None, rect: list | None = None, pad: int = 8) -> None:
        if selector:
            rect = json.loads(await chrome.js(f"""(() => {{ const b = document.querySelector({json.dumps(selector)}).getBoundingClientRect();
              return JSON.stringify([b.x, b.y, b.width, b.height]); }})()"""))
        x, y, w, h = rect
        clip = {"x": max(0, x - pad), "y": max(0, y - pad), "width": w + 2 * pad, "height": h + 2 * pad, "scale": 1}
        data = (await chrome.send("Page.captureScreenshot", format="png", clip=clip))["data"]
        (folder / f"{tag}-{name}.png").write_bytes(base64.b64decode(data))

    if "entry" in found:
        entry = f"#timeline .entry[data-fact='{found['entry']['fact']}']"
        await chrome.js(f"document.querySelector({json.dumps(entry)}).scrollIntoView({{block: 'nearest'}})")
        await crop("timeline-entry", entry, pad=24)
    await crop("term-rows", "#rows")
    busiest = await chrome.js("[...document.querySelectorAll('#rows .term')].sort((a, b) => b.querySelectorAll('.chip:not([hidden])').length - a.querySelectorAll('.chip:not([hidden])').length)[0].dataset.item")
    await crop("lane-chips", f"#rows .term[data-item='{busiest}'] .lane")
    await crop("header", ".top", pad=16)
    for name, rect in {"corner-top-left": [0, 0, 240, 240], "corner-top-right": [1680, 0, 240, 240],
                       "corner-bottom-left": [0, 840, 240, 240], "corner-bottom-right": [1680, 840, 240, 240]}.items():
        await crop(name, rect=rect, pad=0)
    await chrome.js("document.getElementById('timeline').scrollTop = 0")
    await chrome.send("Emulation.setDeviceMetricsOverride", width=1920, height=1080, deviceScaleFactor=1, mobile=False)
    await asyncio.sleep(0.3)
    print(f"  review {tag}: {json.dumps(found)}")
    return found


async def whatsapp_look(port: int, out: Path, check) -> int:
    """7. The second phone as WhatsApp draws a Meta chat, on its own offline app with Meta's
    message shapes: Sunita starts a deal (her call link a button), Ramesh reports two things
    she is asked about (yes or no buttons). One is tapped on the page: it must reach the
    intake as Meta's button reply for that question only. Returns the messages sent in."""
    home = Path(tempfile.mkdtemp(prefix="gawah-phone-meta-"))
    app = offline_app(home / "gawah.db", whatsapp="meta")
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    serving = asyncio.create_task(server.serve())
    url, sent = f"http://127.0.0.1:{port}", 0
    sunita, ramesh = "+919811100001", "+919822200002"
    while not server.started:
        await asyncio.sleep(0.05)
    async with httpx.AsyncClient(base_url=url, timeout=10) as http:
        async def whatsapp(phone: str, body: str) -> None:
            nonlocal sent
            form = {"From": f"whatsapp:{phone}", "Body": body, "NumMedia": "0", "MessageSid": f"SM{new_id()[:10]}"}
            (await http.post(WHATSAPP_WEBHOOK_PATH, data=form)).raise_for_status()
            sent += 1
            await asyncio.sleep(0.6)

        await whatsapp(sunita, "Ramesh " + ramesh.removeprefix("+91"))
        await whatsapp(ramesh, "2000 cash diya")
        await whatsapp(ramesh, "kaam poora ho gaya")
        deal = (await http.get("/dashboard/state")).json()["deal_id"]
        events = (await http.get("/dashboard/state", params={"deal": deal})).json()["events"]
        asked = [e["record_id"] for e in events if e["name"] == "record.confirm_requested"]
        REPLIES = "JSON.stringify([...document.querySelectorAll('.reply')].map((b) => [b.textContent, b.dataset.id, b.disabled]))"
        async with Chrome(port=port + 1000, width=390, height=844) as phone:
            await phone.send("Emulation.setDeviceMetricsOverride", width=390, height=844, deviceScaleFactor=2, mobile=False)
            await phone.goto(f"{url}/dashboard/phone?deal={deal}&number={sunita.replace('+', '%2B')}")
            await phone.wait_for("document.body.dataset.loaded === 'true'")
            await asyncio.sleep(0.6)
            cta = json.loads(await phone.js("""JSON.stringify([...document.querySelectorAll('.bubble .cta')].map((a) =>
              [a.textContent, a.getAttribute('href'), a.closest('.bubble').querySelector('.text').textContent]))"""))
            check(cta and cta[0][0] == "Call kholiye" and cta[0][1] == f"/call/{deal}/hirer" and "http" not in cta[0][2],
                  f"the call link is a button in its bubble, no address shown: {cta}")
            replies = json.loads(await phone.js(REPLIES))
            check([r[1] for r in replies] == [f"{w}:{a}" for a in asked for w in ("yes", "no")] and not any(r[2] for r in replies)
                  and [r[0] for r in replies[:2]] == ["Haan, sahi hai", "Nahi"],
                  f"each question's buttons carry the ids it was sent with: {replies}")
            check(await phone.js("document.getElementById('send').disabled"), "the send button waits for something to send")
            await phone.js("document.getElementById('text').value = 'ok'; document.getElementById('text').dispatchEvent(new Event('input'))")
            check(not await phone.js("document.getElementById('send').disabled"), "words typed: the send button works")
            await phone.js("document.getElementById('text').value = ''; document.getElementById('text').dispatchEvent(new Event('input'))")
            await phone.shot(out / "5c-phone-buttons.png")
            await press(phone, "#attach")
            await asyncio.sleep(0.3)
            items = await phone.js("[...document.querySelectorAll('#attach-menu button')].filter((b) => b.offsetParent).map((b) => b.textContent)")
            check(items == ["Photo", "Voice note"], f"'+' opens Photo and Voice note: {items}")
            await phone.shot(out / "5e-phone-attach-menu.png")
            await press(phone, "#text")
            check(await phone.js("document.getElementById('attach-menu').hidden"), "a tap elsewhere closes the menu")
            await press(phone, ".reply")  # the first question's "Haan, sahi hai", tapped as a person would
            await phone.wait_for("document.querySelector('.replies').classList.contains('used')", timeout=5)
            await asyncio.sleep(1.0)
            events = (await http.get("/dashboard/state", params={"deal": deal})).json()["events"]
            answered = [(e["record_id"], e["confirmed"]) for e in events if e["name"] == "record.confirmed"]
            check(answered == [(asked[0], True)], f"the tap reached the intake as Meta's button reply for that question only: {answered}")
            replies = json.loads(await phone.js(REPLIES))
            picked = await phone.js("document.querySelector('.reply.picked')?.textContent")
            check([r[2] for r in replies] == [True, True, False, False] and picked == "Haan, sahi hai",
                  f"the answered buttons look used, the other question's do not: {replies}")
            await phone.js("document.getElementById('chat').scrollTop = 1e6")
            await phone.send("Input.dispatchMouseEvent", type="mouseMoved", x=1, y=1)
            await asyncio.sleep(0.3)
            await phone.shot(out / "5d-phone-answered.png")
            check(not errors(phone), f"no errors in the phone page: {errors(phone)}")
    server.should_exit = True
    await serving
    return sent


async def main(port: int, out: Path) -> None:
    home = Path(tempfile.mkdtemp(prefix="gawah-live-shots-"))
    app = offline_app(home / "gawah.db")
    actor = stand_in_actor(app)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    serving = asyncio.create_task(server.serve())
    url = f"http://127.0.0.1:{port}"
    failures: list[str] = []
    sent = 0

    def check(ok: bool, what: str) -> None:
        print(f"  {'ok  ' if ok else 'FAIL'} {what}")
        if not ok:
            failures.append(what)

    async with httpx.AsyncClient(base_url=url, timeout=10) as http:
        while not server.started:
            await asyncio.sleep(0.05)

        async def publish(*events) -> None:
            nonlocal sent
            for e in events:
                (await http.post("/dev/publish", content=e.model_dump_json())).raise_for_status()
                sent += 1

        async def settle(deal: str) -> dict:
            """Until memory has written nothing new for a second."""
            last = None
            while True:
                state = (await http.get("/memory/state", params={"deal": deal})).json()
                count = len((await http.get("/dashboard/state", params={"deal": deal})).json()["events"])
                if (state["versions"], count) == last:
                    return state
                last = (state["versions"], count)
                await asyncio.sleep(1.0)

        async def play(deal: str, fixture: dict, lines: range, start: bool = True, end: bool = False, gap: float = 0.05) -> None:
            people = [Person(**p) for p in fixture["people"]]
            if start:
                await publish(CallStarted(deal_id=deal, people=people, room=f"replay-{deal}"))
            for line in fixture["lines"]:
                if line["line_no"] in lines:
                    await publish(TranscriptLine(deal_id=deal, **line))
                    await asyncio.sleep(gap)
            if end:
                await publish(CallEnded(deal_id=deal, people=people, room=f"replay-{deal}", duration=fixture["lines"][-1]["end"]))

        async with Chrome(port=port + 1000) as chrome:

            async def matches_memory(deal: str) -> None:
                """The timeline and the graph, fact by fact, against what memory holds."""
                memory = await settle(deal)
                await chrome.wait_for(VERIFIED)
                await asyncio.sleep(1.0)  # a term's node changes last, after its chip
                entries = json.loads(await chrome.js(TIMELINE))
                newest = {}
                for e in entries:
                    newest.setdefault(e["id"], e)
                held = {f["id"]: f for f in memory["facts"]}
                check(newest.keys() == held.keys(), f"every fact memory holds is in the timeline, and no other ({len(held)})")
                wrong = [i for i in held if i in newest and newest[i]["status"] != held[i]["status"]]
                check(not wrong, f"each entry shows memory's latest status{f': wrong on {wrong}' if wrong else ''}")
                chips = json.loads(await chrome.js(CHIPS))
                for item in ItemKey:
                    term = (await http.get(f"/memory/term/{deal}/{item.value}")).json()["current"]
                    stands = [c for c in chips if c["stands"] and c["item"] == item.value]
                    check((term is None and not stands) or (len(stands) == 1 and term["id"] in stands[0]["ids"]),
                          f"{item.value}: the chip marked as standing holds memory's current term"
                          + ("" if (term is None and not stands) or (len(stands) == 1 and term["id"] in stands[0]["ids"]) else f" (memory: {term and (term['id'], term['value'])}, page: {stands})"))
                rows = json.loads(await chrome.js(CHECKLIST))
                for item in ItemKey:
                    term = (await http.get(f"/memory/term/{deal}/{item.value}")).json()["current"]
                    stand = next((c for c in chips if c["stands"] and c["item"] == item.value), None)
                    row = rows[item.value]
                    if term:
                        same = bool(stand) and row["node"] == stand["value"] and money(row["value"]).startswith(money(row["node"])) \
                            and money(row["value"]) == money(board(term["value"] or term["text"]))
                        check(same, f"{item.value}: the node and the standing chip show memory's current term, {row['node']!r}"
                              + ("" if same else f" (node {row['node']!r} / {row['value']!r}, chip {stand and stand['value']!r}, memory {term['value']!r})"))
                    else:
                        want = "Not agreed yet" if row["lane"] else "Not said yet"
                        check(row["shown"] == want and not row["state"], f"{item.value}: nothing stands, the node says {row['shown']!r} and no pill")
                for i, f in held.items():
                    target = held.get(f.get("counts_towards") or "")
                    if target and target["item"]:
                        lane = next((c["item"] for c in chips if i in c["ids"]), None)
                        check(newest[i]["item"] == target["item"] and lane == target["item"],
                              f"{f['kind']} {f['value']} sits with the {target['item']} term it counts towards")
                owed = {r["item"]: r for r in memory["owed"]}
                for label, text in json.loads(await chrome.js(OWED)):
                    r = owed[label]
                    want = f"Paid₹{r['paid_rupees']}·₹{r['owed_rupees']}left"
                    check(money(text) == want, f"{label}: {text!r} is memory's owed ({r['paid_rupees']} paid, {r['owed_rupees']} owed)")
                chain = (await http.get(f"/memory/chain/{deal}")).json()
                text = await chrome.js("document.getElementById('chain').textContent")
                title = await chrome.js("document.getElementById('chain').title")
                ticks = await chrome.js("document.querySelectorAll('#ticks i.verified').length")
                check(chain["verified"] and text == f"Witness chain verified · {chain['links']} links" and chain["head"] in title
                      and ticks == min(chain["links"], 64), f"chain: {text!r}, {ticks} ticks")
                # Pointing at each term shows memory's current term in the detail card.
                for item in ItemKey:
                    term = (await http.get(f"/memory/term/{deal}/{item.value}")).json()["current"]
                    if not term:
                        continue
                    await point_at(chrome, f"#rows .term[data-item='{item.value}'] .node-slot")
                    shown = json.loads(await chrome.js(DETAIL))
                    check(shown["fact"] == term["id"], f"pointing at {item.value} shows memory's current term, {term['value']!r}")
                await point_at(chrome, None)
                overlaps = json.loads(await chrome.js(OVERLAPS))
                check(not overlaps, f"nothing overlaps or is cut by its box: {overlaps}")
                await checklist_matches(deal)

            async def checklist_matches(deal: str) -> dict:
                """Each term as the brain's latest checklist has it: agreed with its value, or waiting."""
                events = (await http.get("/dashboard/state", params={"deal": deal})).json()["events"]
                latest = next((e for e in reversed(events) if e["name"] == "checklist.updated"), None)
                rows = json.loads(await chrome.js(CHECKLIST))
                changed = {e["item"] for e in events if e["name"] == "fact.changed" and e["status"] == "confirmed_both"}
                for item in (latest or {}).get("items", []):
                    row = rows[item["key"]]
                    if item["key"] in changed:
                        continue
                    if item["state"] == "agreed":
                        check(row["state"] in ("Agreed", "Confirmed by both"), f"checklist {item['key']}: {row['state']}, as the brain has it agreed")
                        check(row["when"].startswith("Call 1 · "), f"checklist {item['key']}: settled at {row['when']!r}")
                    if row["value"] and money(row["shown"]) != money(row["value"]) and not row["shown"].startswith("Not "):
                        kept = row["shown"].removesuffix("…").replace(" ", " ")
                        full = row["value"].replace(" ", " ")
                        check(row["shown"].endswith("…") and full.startswith(kept) and full[len(kept)] in " ;,.",
                              f"checklist {item['key']}: cut at a word, {row['shown']!r}")
                gone = await chrome.js(f"JSON.stringify({GONE!r}.filter((id) => document.getElementById(id)))")
                check(gone == "[]", f"nothing else on the board: {gone}")
                return rows

            async def reload_check(label: str) -> None:
                before = await chrome.js(SNAPSHOT)
                await chrome.reload()
                await chrome.wait_for(LOADED)
                await chrome.wait_for(VERIFIED)
                await asyncio.sleep(0.8)
                after = await chrome.js(SNAPSHOT)
                check(before == after, f"reload rebuilds the same page ({label}, {len(before)} characters)")
                if before != after:
                    b, a = json.loads(before), json.loads(after)
                    for k in b["text"]:
                        if b["text"][k] != a["text"][k]:
                            print(f"    {k} before: {b['text'][k][-200:]!r}\n    {k} after:  {a['text'][k][-200:]!r}")
                    if b["cards"] != a["cards"]:
                        print(f"    cards differ: {[x for x in zip(b['cards'], a['cards']) if x[0] != x[1]][:5]}")

            # ---------- 0. no deal, then a deal before its call ----------
            print("0. the empty board")
            await chrome.goto(f"{url}/dashboard")
            await chrome.wait_for(LOADED)
            await asyncio.sleep(0.6)
            text = await chrome.js("document.getElementById('detail').textContent")
            check("No deal yet" in text and "On WhatsApp" in text and await chrome.js("[...document.querySelectorAll('#rows .term .value')].filter((v) => v.textContent === 'Not said yet').length") == 6,
                  f"no deal: the six terms wait, and the card says how a deal starts: {text[:80]!r}")
            check(await chrome.js(f"{PHONE_TITLE}.textContent") == "Second phone", "no deal: the phone is the second phone")
            await chrome.shot(out / "0-no-deal.png")

            # ---------- 1. mid-call, with a clip from the user's recorded voice ----------
            print("1. call_missing_balance, mid-call")
            mb = load("fixtures/call_missing_balance.json")
            deal = f"live-mb-{new_id()[:4]}"
            covered = lay_recordings(home / "recordings" / deal / "1", mb)
            print(f"  the user's recordings laid on lines {covered}")
            await chrome.goto(f"{url}/dashboard?deal={deal}")
            await chrome.wait_for(LOADED)
            await play(deal, mb, range(1, 18))
            await settle(deal)
            await matches_memory(deal)
            await asyncio.sleep(0.5)
            await chrome.wait_for(f"{PHONE_TITLE}.innerText === \"RAMESH'S PHONE\"", timeout=5)
            check(True, "the frame is titled for whose phone it shows: RAMESH'S PHONE")
            await chrome.shot(out / "1-mid-call.png")
            # Facts arriving: five more lines, caught while the first new entry comes in.
            entering = asyncio.create_task(chrome.js(ARRIVING))
            await play(deal, mb, range(18, 23), start=False, gap=0.6)
            await asyncio.wait_for(entering, 10)
            await asyncio.sleep(0.45)  # the entry is in, its chip landing
            await chrome.shot(out / "1b-facts-arriving.png")
            await settle(deal)

            # Pointing links the timeline and the graph both ways.
            memory = await settle(deal)
            fact = next(f for f in memory["facts"] if f["line_no"] == 3 and f["kind"] == "term")
            await point_at(chrome, f"#timeline .entry[data-fact='{fact['id']}']")
            lit = await chrome.js(f"!!document.querySelector('#rows .chip.lit[data-facts~=\"{fact['id']}\"]')")
            shown = json.loads(await chrome.js(DETAIL))
            check(lit and shown["fact"] == fact["id"], "pointing at a timeline entry lights its chip and shows it in the detail card")
            await point_at(chrome, f"#rows .chip[data-facts~='{fact['id']}']")
            lit = await chrome.js(f"!!document.querySelector('#timeline .entry.lit[data-fact=\"{fact['id']}\"]')")
            check(lit, "pointing at a chip lights its timeline entry")
            await point_at(chrome, None)

            # A clip: the line-3 entry's button, clicked as a person would, plays to its end.
            clip = await http.get(f"/memory/clip/{fact['id']}")
            with wave.open(io.BytesIO(clip.content)) as w:
                seconds = w.getnframes() / w.getframerate()
            check(clip.status_code == 200 and clip.headers["content-type"] == "audio/wav" and seconds > 5, f"memory's clip for line 3: {seconds:.1f} s of WAV")
            (home / "clip-line-3.wav").write_bytes(clip.content)
            print(f"  the clip, to listen to: {home / 'clip-line-3.wav'}")
            button = f'#timeline .entry[data-fact="{fact['id']}"] .play'
            await chrome.js(f"document.querySelector({json.dumps(button)}).scrollIntoView({{block: 'center'}})")
            await press(chrome, button)
            classes = f"document.querySelector({json.dumps(button)}).classList"
            await chrome.wait_for(f"{classes}.contains('playing')", timeout=3)
            await asyncio.sleep(1.0)
            check(await chrome.js(f"{classes}.contains('playing') && !{classes}.contains('missing')"), "the clip button is playing after a second")
            await chrome.wait_for(f"!{classes}.contains('playing')", timeout=seconds + 5)
            check(not await chrome.js(f"{classes}.contains('missing')"), f"the clip played to its end ({seconds:.1f} s) and stopped by itself")
            await chrome.js("document.getElementById('timeline').scrollTop = 0")
            await point_at(chrome, None)
            await reload_check("mid-call")

            # ---------- 2. the contradiction on call_two_amounts ----------
            print("2. call_two_amounts, the contradiction")
            ta = load("fixtures/call_two_amounts.json")
            sunita, ramesh_phone = "+919811100001", "+919822200002"

            async def whatsapp(phone: str, body: str = "", note: str | None = None) -> None:
                """One message into the webhook in Twilio's form; a note is a file in fixtures/voice-notes."""
                nonlocal sent
                form = {"From": f"whatsapp:{phone}", "Body": body, "NumMedia": "0", "MessageSid": f"SM{new_id()[:10]}"}
                if note:
                    form |= {"NumMedia": "1", "MediaContentType0": "audio/ogg",
                             "MediaUrl0": f"https://api.twilio.com/2010-04-01/Accounts/AC0/Messages/MM0/Media/{note}"}
                (await http.post(WHATSAPP_WEBHOOK_PATH, data=form)).raise_for_status()
                sent += 1

            await whatsapp(sunita, ramesh_phone.removeprefix("+91"))
            await asyncio.sleep(1.0)
            deal2 = (await http.get("/dashboard/state")).json()["deal_id"]
            print(f"  the deal started on WhatsApp: {deal2}")
            await chrome.goto(f"{url}/dashboard?deal={deal2}")
            await chrome.wait_for(LOADED)
            await asyncio.sleep(0.6)
            text = await chrome.js("document.getElementById('detail').textContent")
            check("Waiting for the call" in text and await chrome.js("document.getElementById('call-pill').textContent") == "Before the call",
                  f"before the call: the six terms wait, the card says what happens next: {text[:60]!r}")
            await chrome.shot(out / "0b-before-the-call.png")
            # The phone shows Ramesh's number before anyone has said his name: titled by his role.
            await chrome.wait_for(f"{FRAME}.document.body.dataset.loaded === 'true'")
            show_number = f"(n) => {{ const i = {FRAME}.document.getElementById('number'); i.value = n; i.dispatchEvent(new Event('change')); }}"
            await chrome.js(f"({show_number})({json.dumps(ramesh_phone)})")
            await chrome.wait_for(f"{PHONE_TITLE}.textContent === \"The worker's phone\"", timeout=5)
            check(await chrome.js(f"{FRAME}.document.getElementById('name').textContent") == "The worker's phone",
                  "no name yet: the board and the phone both say The worker's phone")
            frames = home / "frames"
            frames.mkdir(parents=True, exist_ok=True)
            shooting = True

            async def film() -> None:
                """Half-size frames, as fast as Chrome gives them (about ten a second)."""
                n = 0
                while shooting:
                    data = (await chrome.send("Page.captureScreenshot", format="jpeg", quality=80,
                                              clip={"x": 0, "y": 0, "width": 1920, "height": 1080, "scale": 0.5}))["data"]
                    (frames / f"{n:04d}.jpg").write_bytes(base64.b64decode(data))
                    n += 1

            camera = asyncio.create_task(film())
            silent_recordings(home / "recordings" / deal2 / "1", seconds=int(ta["lines"][-1]["end"]) + 5)
            await play(deal2, ta, range(1, 22), gap=0.3)  # the contradiction is on line 19; two lines on, it is still in view
            await chrome.wait_for(f"{PHONE_TITLE}.textContent === \"Ramesh's phone\" && {FRAME}.document.getElementById('name').textContent === \"Ramesh's phone\"", timeout=5)
            check(True, "once the call names him, the title turns to Ramesh's phone, live, on the board and in the phone")
            await chrome.js(f"({show_number})('+910000000002')")
            await asyncio.sleep(2.0)
            shooting = False
            await camera
            film_to(frames, out / "2-facts-arriving.mp4", out / "2-facts-arriving-sheet.png")
            await matches_memory(deal2)
            conflict = await chrome.js("document.querySelector('#detail .conflict-card')?.textContent || ''")
            check("14,000" in conflict and "13,000" in conflict and "Original moment" in conflict and "Contradicted" in conflict, f"slide 7: {conflict[:160]!r}")
            struck = await chrome.js("document.querySelector('#detail .conflict-card .now s')?.textContent || ''")
            check("14,000" in struck, f"the claim is struck through: {struck!r}")
            chips = json.loads(await chrome.js(CHIPS))
            term = (await http.get(f"/memory/term/{deal2}/amount")).json()["current"]
            claim = [c for c in chips if c["item"] == "amount" and c["status"] == "claim"]
            arc = await chrome.js("document.querySelector(\"#rows .term[data-item='amount'] svg.arcs\").textContent")
            check(len(claim) == 1 and arc == "contradicts", f"the amount's lane: the claim as its own chip, the red edge labelled: {claim}, {arc!r}")
            tip = await chrome.js("Number(document.querySelector(\"#rows .term[data-item='amount'] .arc path.head\").getAttribute('d').match(/-?[\\d.]+/g)[2])")
            standing_x = await chrome.js(f"""(() => {{ const c = document.querySelector("#rows .term[data-item='amount'] .chip.stands"); return c.parentElement.offsetLeft + c.offsetLeft + c.offsetWidth / 2; }})()""")
            check(abs(tip - standing_x) < 1 and term["id"] in next(c for c in chips if c["stands"] and c["item"] == "amount")["ids"],
                  "the red edge ends on the chip of the agreed 13,000, memory's current amount")
            check(await chrome.js(IN_VIEW % "#detail .conflict-card"), "the contradiction card is in view")
            rows = json.loads(await chrome.js(CHECKLIST))
            check(rows["amount"]["contradicted"].startswith("Contradicted · Call 1 · "), f"the amount's node is marked: {rows['amount']}")
            await asyncio.sleep(1.2)
            await chrome.shot(out / "2-contradiction.png")
            margins = [json.loads(await chrome.js(MEASURE))["page"],
                       await sized(chrome, 1440, 900, out / "2-contradiction-1440x900.png"),
                       await sized(chrome, 1280, 720, out / "2-contradiction-1280x720.png")]
            for m in margins:
                sides = [m["left"], m["top"], m["right"], m["bottom"]]
                check(max(sides) - min(sides) < 1, f"the page margin is the same on all four sides at {m['window']}: {sides} (stage {m['stage']})")
            await review(chrome, out / "review", "contradiction")
            await reload_check("contradiction")
            await press(chrome, "#detail .conflict-card .play")
            await chrome.wait_for("document.querySelector('#detail .conflict-card .play').classList.contains('playing') || document.querySelector('#detail .conflict-card .play').classList.contains('missing')", timeout=3)
            agreed = await chrome.js("document.querySelector('#detail .conflict-card .play').getAttribute('data-fact')")
            heard = await http.get(f"/memory/clip/{agreed}")
            check(await chrome.js("document.querySelector('#detail .conflict-card .play').classList.contains('playing')") and agreed == term["id"],
                  f"Original moment plays the agreed clip (memory answers {heard.status_code}, {len(heard.content)} bytes)")
            await press(chrome, "#detail .conflict-card .play")  # and stop it

            # ---------- 2b. voice notes on the same deal ----------
            print("2b. voice notes: one on the work, and a change of the amount both say yes to")
            await play(deal2, ta, range(22, 100), start=False, end=True)
            await settle(deal2)
            await whatsapp(sunita, note="paint-05.ogg")
            await settle(deal2)
            await whatsapp(ramesh_phone, note="paint-08.ogg")
            await settle(deal2)
            await whatsapp(sunita, "haan")
            memory = await settle(deal2)
            voiced = [f for f in memory["facts"] if f["source"] == "voice_note"]
            check(len(voiced) >= 2, f"memory holds the voice notes' facts: {[(f['kind'], f['value'], f['status']) for f in voiced]}")
            await matches_memory(deal2)
            marks = json.loads(await chrome.js("""JSON.stringify([...new Set([...document.querySelectorAll('#timeline .src-voice_note')].map((m) => m.closest('.entry').dataset.fact))])"""))
            check(sorted(marks) == sorted(f["id"] for f in voiced), f"every voice-note fact carries the voice-note mark ({len(marks)} of {len(voiced)})")
            moments = await chrome.js("JSON.stringify([...document.querySelectorAll('#timeline .moment .label:first-child')].map((m) => m.textContent))")
            check("Voice note · day 1" in moments, f"the voice notes have their own moment in the timeline: {moments}")
            rows = json.loads(await chrome.js(CHECKLIST))
            amount = rows["amount"]
            check(amount["state"] == "Changed" and money(amount["value"]).startswith("₹25000") and amount["when"] == "WhatsApp voice note"
                  and "Changed by voice note, both said yes" in amount["title"], f"the amount changed by voice note: {amount}")
            await point_at(chrome, "#rows .term[data-item='amount'] .node-slot")
            shown = json.loads(await chrome.js(DETAIL))
            check("WhatsApp voice note" in shown["text"] and "Both, by voice note" in shown["text"] and "Changed" in shown["text"],
                  f"the detail card shows the voice note's fact: {shown['text'][:200]!r}")
            await chrome.shot(out / "2b-voice-notes.png")
            await point_at(chrome, None)
            await reload_check("voice notes")

            # ---------- 3. after call 1: a payment, and a change both agree to ----------
            print("3. call_missing_balance finished, an advance paid, the amount changed")
            await chrome.goto(f"{url}/dashboard?deal={deal}")
            await chrome.wait_for(LOADED)
            await play(deal, mb, range(23, 100), start=False, end=True)
            await settle(deal)
            await publish(RecordReceived(deal_id=deal, record=Record(sender=Role.HIRER, kind=RecordKind.ADVANCE, amount=8000, text="8000 advance GPay kar diya")))
            await publish(RecordReceived(deal_id=deal, record=Record(sender=Role.HIRER, kind=RecordKind.PAYMENT, amount=5000, text="5000 aur diye")))
            amount = (await http.get(f"/memory/term/{deal}/amount")).json()["current"]
            change = FactChanged(deal_id=deal, fact_id=amount["id"], new_value="26,000 rupees, with the balcony", item=ItemKey.AMOUNT,
                                 proposed_by=Role.HIRER, status=ChangeStatus.CONFIRMED_BOTH, confirmed_by=[Role.WORKER, Role.HIRER])
            await publish(change)
            await settle(deal)
            await matches_memory(deal)
            chips = json.loads(await chrome.js(CHIPS))
            old = next((c for c in chips if amount["id"] in c["ids"]), None)
            check(old and old["status"] == "superseded", f"the old amount shows as replaced: {old}")
            check(len(json.loads(await chrome.js(OWED))) == 3, "paid and owed shown on the amount, the advance and the balance")
            rows = json.loads(await chrome.js(CHECKLIST))
            check(rows["amount"]["state"] == "Changed" and money(rows["amount"]["value"]) == money(board("26,000 rupees, with the balcony")), f"the checklist shows the change: {rows['amount']}")
            await asyncio.sleep(0.5)
            await chrome.shot(out / "3-payments-and-change.png")
            await review(chrome, out / "review", "payments")
            await reload_check("payments and change")

            # The timeline scrolled away from the newest: a new fact goes in above, what is read stays put.
            await chrome.js("document.getElementById('timeline').scrollTop = 420")
            await asyncio.sleep(0.3)
            first = await chrome.js("""(() => { const t = document.getElementById('timeline');
              const el = [...t.children].find((c) => c.offsetTop + c.offsetHeight > t.scrollTop + 41);
              return JSON.stringify([el.dataset.key, el.getBoundingClientRect().top]); })()""")
            await publish(RecordReceived(deal_id=deal, record=Record(sender=Role.HIRER, kind=RecordKind.PAYMENT, amount=2000, text="2000 aur diye")))
            await settle(deal)
            await asyncio.sleep(0.6)
            key, top = json.loads(first)
            after = await chrome.js(f"document.querySelector('#timeline > [data-key=\"{key}\"]').getBoundingClientRect().top")
            pill = await chrome.js("document.getElementById('newer').hidden ? '' : document.getElementById('newer').textContent")
            check(abs(after - top) < 1 and pill == "↑ 1 newer entry", f"scrolled away, the entry being read stays put ({top:.0f} → {after:.0f}) and a pill says {pill!r}")
            await chrome.shot(out / "3b-timeline-scrolled.png")
            await chrome.js("document.getElementById('newer').click()")
            await chrome.wait_for("document.getElementById('timeline').scrollTop === 0 && document.getElementById('newer').hidden", timeout=3)
            check(True, "the pill scrolls back to the newest and goes away")

            # The call-backs: both confirm every term; the timeline's Call-backs moment shows both people on each.
            people = [Person(**p) for p in mb["people"]]
            await publish(CallStarted(deal_id=deal, people=people, room=f"replay-{deal}-callback", kind=CallKind.CALLBACK))
            for role in (Role.WORKER, Role.HIRER):
                await publish(TermsConfirmed(deal_id=deal, person=role))
            await publish(CallEnded(deal_id=deal, people=people, room=f"replay-{deal}-callback", kind=CallKind.CALLBACK, duration=60))
            await settle(deal)
            await matches_memory(deal)
            both = await chrome.js("[...document.querySelectorAll('#timeline .entry')].filter((e) => e.querySelectorAll('.people .tag').length === 2 && e.querySelector('.word')?.textContent === 'Confirmed by both' && e.querySelector('.play')).length")
            moments = await chrome.js("JSON.stringify([...document.querySelectorAll('#timeline .moment .label:first-child')].map((m) => m.textContent))")
            check("Call-backs" in moments and both >= 1, f"the call-backs: {both} entries with both people, Confirmed by both and a clip, under {moments}")
            await asyncio.sleep(0.5)
            await chrome.shot(out / "3c-call-backs.png")
            await review(chrome, out / "review", "call-backs")
            await reload_check("call-backs")

            # ---------- 4. a past fact altered inside memory: the chain must say where ----------
            print("4. the chain, with link 5 altered after it was written")
            versions = app.state.memory.book.deal(deal).versions
            versions[4] = versions[4].model_copy(update={"value": "99,000 rupees"})
            await chrome.reload()
            await chrome.wait_for(LOADED)
            await chrome.wait_for("document.getElementById('chain').textContent.includes('broken')")
            text = await chrome.js("document.getElementById('chain').textContent")
            check(text == "Witness chain broken at link 5 (Work, call 1 line 5)", f"chain: {text!r}")
            broken = await chrome.js("[document.querySelectorAll('#ticks i.broken').length, document.querySelectorAll('#ticks i').length, document.querySelectorAll('#rows .chip.broken').length]")
            links = (await http.get(f"/memory/chain/{deal}")).json()["links"]
            check(broken[0] == broken[1] - max(0, 4 - (links - broken[1])) and broken[2] >= 1, f"the ticks from link 5 on are red, and the chip of link 5 is marked: {broken}")
            await chrome.shot(out / "4-chain-broken.png")

            # ---------- 5. the second phone on its own page ----------
            print("5. /dashboard/phone at phone size")
            ramesh = next(p for p in mb["people"] if p["role"] == "worker")
            async with Chrome(port=port + 1001, width=390, height=844) as phone:
                await phone.goto(f"{url}/dashboard/phone?deal={deal}")
                await phone.wait_for("document.body.dataset.loaded === 'true'")
                await asyncio.sleep(0.5)
                check(await phone.js("document.getElementById('actor').hidden"), "the actor's endpoints answer 404: no toggle")
                check(await phone.js("document.getElementById('number').value") == ramesh["phone"], "it plays Ramesh's number")
                check(await phone.js("document.getElementById('name').textContent") == "Ramesh's phone", "its header: Ramesh's phone")
                before = await phone.js("document.querySelectorAll('.bubble').length")
                await phone.js("document.getElementById('text').value = 'Namaste ji'; document.getElementById('composer').requestSubmit()")
                await phone.wait_for("document.getElementById('send-status').textContent === 'Delivered to Gawah'")
                await phone.wait_for("[...document.querySelectorAll('.bubble.in')].some((b) => b.textContent.includes('Namaste ji'))")
                check(True, "a message sent from the page went through the webhook and came back as whatsapp.message")
                try:
                    await phone.wait_for(f"document.querySelectorAll('.bubble').length > {before + 1}", timeout=8)
                    check(True, "Gawah's answer is in the chat")
                except TimeoutError:
                    check(False, "Gawah's answer is in the chat")
                await asyncio.sleep(0.4)
                await phone.shot(out / "5-phone.png")

                actor["on"] = True
                await phone.reload()
                await phone.wait_for("document.body.dataset.loaded === 'true' && !document.getElementById('actor').hidden")
                await phone.js("document.getElementById('actor-on').click()")
                await publish(WhatsAppMessage(deal_id=deal, direction=Direction.OUT, phone=ramesh["phone"], role=Role.WORKER, simulated=True,
                                              text=f"Ramesh ji, terms sun ke haan boliye: {url}/callback/{deal}/worker"))
                await phone.wait_for("document.getElementById('call-state').textContent.includes('joining')")
                check(actor["started"] == [{"deal_id": deal, "role": "worker", "kind": "callback"}], f"a call link arriving started the actor: {actor['started']}")
                await publish(CallStarted(deal_id=deal, people=[Person(**ramesh)], room=f"replay-{deal}-callback", kind=CallKind.CALLBACK))
                await phone.wait_for("document.getElementById('call-state').textContent === 'The AI is on the call-backStop'")
                check(True, "the frame shows the AI on the call-back")
                await asyncio.sleep(0.4)
                await phone.shot(out / "5b-phone-ai-plays.png")
                await phone.js("document.querySelector('#call-state button').click()")
                await asyncio.sleep(0.3)
                check(actor["stopped"] == [{"deal_id": deal, "role": "worker"}], f"Stop stopped the actor: {actor['stopped']}")
                check(not errors(phone), f"no errors in the phone page: {errors(phone)}")

            # ---------- 6. a call link tapped in the board's frame opens there ----------
            print("6. the board's phone frame: a call link opens inside it")
            await chrome.goto(f"{url}/dashboard?deal={deal}")
            await chrome.wait_for(LOADED)
            await chrome.wait_for(f"{FRAME}.document.body.dataset.loaded === 'true'")
            check(await chrome.js("document.getElementById('phone-frame').getAttribute('allow')") == "microphone *; autoplay *", "the frame allows the microphone and autoplay")
            await publish(WhatsAppMessage(deal_id=deal, direction=Direction.OUT, phone=ramesh["phone"], role=Role.WORKER, simulated=True,
                                          text=f"Phir se baat karne ke liye: {url}/call/{deal}/worker"))
            await chrome.wait_for(f"!!{FRAME}.document.querySelector('a.call-link[href=\"/call/{deal}/worker\"]')")
            await chrome.js(f"{FRAME}.document.querySelector('a.call-link[href=\"/call/{deal}/worker\"]').click()")
            await chrome.wait_for(f"{FRAME}.location.pathname === '/call/{deal}/worker'")
            await chrome.wait_for("!document.getElementById('phone-back').hidden")
            check(True, "the call page opened inside the frame, with a way back to the chat")
            await asyncio.sleep(1.0)
            await chrome.shot(out / "6-call-in-frame.png")
            await chrome.js("document.getElementById('phone-back').click()")
            await chrome.wait_for(f"{FRAME}.location.pathname === '/dashboard/phone'")
            check(True, "back to the chat")
            check(not errors(chrome), f"no errors in the page: {errors(chrome)}")

    server.should_exit = True
    await serving
    print("7. the second phone as WhatsApp draws it, on Meta's message shapes")
    sent += await whatsapp_look(port + 2, out, check)
    print(f"events published: {sent}; real rooms 0, messages 0")
    print("FAILED:\n  " + "\n  ".join(failures) if failures else "all checks passed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=8021)
    parser.add_argument("--out", type=Path, default=Path("fixtures/dashboard-shots/polish"))
    args = parser.parse_args()
    asyncio.run(main(args.port, args.out))
