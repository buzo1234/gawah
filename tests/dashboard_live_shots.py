"""Proof run for the dashboard on the real memory, in a real browser at 1920 by 1080. Not
collected by pytest. Reaches nothing outside: it serves the offline app (tests/offline.py,
with memory answering from its saved replies) in this process, so it knows where the call
recordings go.

    PYTHONPATH=. uv run python tests/dashboard_live_shots.py

1. call_missing_balance to line 17, then the shot: mid-call; two lines more, caught while
   their nodes come in (1b; lines 18 to 22).
   The user's recorded lines (fixtures/audio) are laid out as the call's two recordings,
   at the times of the call's lines, so a clip button plays real audio from memory.
2. call_two_amounts to line 21, a line every 0.3 seconds, filmed (2-facts-arriving.mp4 and
   a contact sheet, with ffmpeg) so the motion can be judged: memory's contradiction on
   line 19, then the shot.
2b. On the same deal (started on WhatsApp, as a real one is), voice notes from
   fixtures/voice-notes/ through the webhook: Sunita's on the work, and Ramesh's change of
   the amount to 25,000, which Sunita says yes to. The voice-note facts carry their own
   mark, the amount reads "Changed by voice note, both said yes", then the shot.
3. The first call finished, an advance paid on WhatsApp, and the amount changed by both:
   payments, what they count towards, and a superseded version, then the shot.

After each shot: the graph is checked against memory's own answers (/memory/state, terms,
owed, /memory/chain), the checklist against the brain's, and a reload must rebuild exactly
the same page. Then one past fact is altered inside memory, and the chain must name the
link that broke.

5. The second phone on its own page, at phone size: a message typed and sent goes through
   the webhook and comes back in the chat. The actor's endpoints are stood in for here
   (they belong to another stream): answering 404, the "AI plays this person" toggle is
   hidden; answering, with the toggle on, a call link that arrives starts the actor with
   the link's deal, role and kind. On the board, a call link tapped in the frame opens the
   call page in the frame (nothing is joined: the join button is not pressed).
"""

import argparse
import asyncio
import base64
import io
import json
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
    RecordKind, RecordReceived, Role, TranscriptLine, WhatsAppMessage, new_id,
)
from fakes.replayer import load
from tests.offline import offline_app

PANELS = ["items", "settled-count", "graph", "graph-count", "chain"]
SNAPSHOT = """JSON.stringify({
  text: Object.fromEntries(%r.map((id) => [id, document.getElementById(id).textContent])),
  links: [...document.querySelectorAll('#graph path.link')].map((p) => p.getAttribute('class')).sort(),
})""" % PANELS
LOADED = "document.body.dataset.conn === 'live' && document.body.dataset.loaded === 'true'"
VERIFIED = "document.getElementById('chain').textContent.includes('verified') && !document.getElementById('chain').textContent.includes('new')"
# Every fact is a node: a pill or a dot on its speaker's side of its term, or, for the fact a
# term stands on, the line under the term itself.
GRAPH = """JSON.stringify([...document.querySelectorAll('#graph [id^="fact-"]')].map((el) => ({
  id: el.id.slice(5), status: [...el.classList].find((c) => ['said','agreed','confirmed','disputed','superseded'].includes(c)),
  stands: el.classList.contains('stands'), item: el.dataset.item || el.closest('.item')?.dataset.item || '',
})))"""
OWED = "JSON.stringify([...document.querySelectorAll('#graph .owed')].map((el) => [el.closest('.item').dataset.item, el.textContent]))"
# A term's value is cut at a word when it is too long for the row; its full text is the
# first line of the row's hover text.
CHECKLIST = """JSON.stringify(Object.fromEntries([...document.querySelectorAll('#items .item')].map((el) => [el.dataset.item, {
  state: el.querySelector('.state').textContent, value: el.title.split('\\n')[0] || el.querySelector('.value').textContent,
  shown: el.querySelector('.value').textContent, foot: el.querySelector('.foot').textContent,
  when: el.querySelector('.when')?.textContent || '', contradicted: el.querySelector('.contradicted')?.textContent || '',
}])))"""
GONE = ["flow", "decisions", "records", "lanes", "real-chat", "deal-picker", "conn", "people", "status"]
IN_VIEW = """(() => { const el = document.querySelector('%s'), g = document.getElementById('graph').getBoundingClientRect();
  const r = el.getBoundingClientRect(); return r.top >= g.top && r.bottom <= g.bottom; })()"""
ARRIVING = """new Promise((done) => {
  const seen = new MutationObserver(() => {
    if (document.querySelector('#graph .node.enter')) { seen.disconnect(); done(true); }
  });
  seen.observe(document.getElementById('graph'), { subtree: true, childList: true, attributes: true });
})"""
AUDIO = Path("fixtures/audio")
FRAME = "document.getElementById('phone-frame').contentWindow"
PROBE = "/actor/status"  # the phone asks once whether the actor is there; its 404 is the answer "not yet"


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
                """The graph, card by card, against what memory holds."""
                memory = await settle(deal)
                await chrome.wait_for(VERIFIED)
                shown = {c["id"]: c for c in json.loads(await chrome.js(GRAPH))}
                held = {f["id"]: f for f in memory["facts"]}
                check(shown.keys() == held.keys(), f"every fact memory holds is a node, and no other ({len(held)})")
                wrong = [i for i in held if i in shown and shown[i]["status"] != held[i]["status"]]
                check(not wrong, f"each card shows memory's latest status{f': wrong on {wrong}' if wrong else ''}")
                for item in ItemKey:
                    term = (await http.get(f"/memory/term/{deal}/{item.value}")).json()["current"]
                    stands = [i for i, c in shown.items() if c["stands"] and held[i]["item"] == item.value and held[i]["kind"] == "term"]
                    check(stands == ([term["id"]] if term else []), f"{item.value}: the card marked as standing is memory's current term")
                for i, f in held.items():
                    target = held.get(f.get("counts_towards") or "")
                    if target and target["item"] and i in shown:
                        check(shown[i]["item"] == target["item"], f"{f['kind']} {f['value']} sits with the {target['item']} term it counts towards")
                owed = {r["item"]: r for r in memory["owed"]}
                for label, text in json.loads(await chrome.js(OWED)):
                    r = owed[label]
                    want = f"Paid ₹{r['paid_rupees']} · ₹{r['owed_rupees']} left"
                    check(text.replace(",", "") == want, f"{label}: {text!r} is memory's owed ({r['paid_rupees']} paid, {r['owed_rupees']} owed)")
                chain = (await http.get(f"/memory/chain/{deal}")).json()
                text = await chrome.js("document.getElementById('chain').textContent")
                title = await chrome.js("document.getElementById('chain').title")
                check(chain["verified"] and text == f"Witness chain verified · {chain['links']} links" and chain["head"] in title, f"chain: {text!r}")
                await checklist_matches(deal)

            async def checklist_matches(deal: str) -> dict:
                """Each term as the brain's latest checklist has it: agreed with its value, or pending."""
                events = (await http.get("/dashboard/state", params={"deal": deal})).json()["events"]
                latest = next((e for e in reversed(events) if e["name"] == "checklist.updated"), None)
                rows = json.loads(await chrome.js(CHECKLIST))
                changed = {e["item"] for e in events if e["name"] == "fact.changed" and e["status"] == "confirmed_both"}
                for item in (latest or {}).get("items", []):
                    row = rows[item["key"]]
                    if item["key"] in changed:
                        continue
                    want = ("Agreed", item["value"]) if item["state"] == "agreed" else ("Pending", "Not agreed yet")
                    check((row["state"], row["value"]) == want, f"checklist {item['key']}: {row['state']} {row['value']!r}")
                    if row["shown"] != row["value"]:
                        kept = row["shown"].removesuffix("…")
                        check(row["shown"].endswith("…") and row["value"].startswith(kept) and row["value"][len(kept)] in " ;,.",
                              f"checklist {item['key']}: cut at a word, {row['shown']!r}")
                    if item["state"] == "agreed":
                        check(row["when"].startswith("Call 1 · "), f"checklist {item['key']}: settled at {row['when']!r}")
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
            await chrome.shot(out / "1-mid-call.png")
            # Facts arriving: five more lines, caught while the first new node and its edges
            # come in (watched from inside the page: the motion is over in 400 ms).
            entering = asyncio.create_task(chrome.js(ARRIVING))
            await play(deal, mb, range(18, 23), start=False, gap=0.6)
            await asyncio.wait_for(entering, 10)
            await asyncio.sleep(0.12)
            await chrome.shot(out / "1b-facts-arriving.png")
            await settle(deal)

            # A clip: the line-3 card, clicked as a person would, plays to its end.
            memory = await settle(deal)
            fact = next(f for f in memory["facts"] if f["line_no"] == 3 and f["kind"] == "term")
            clip = await http.get(f"/memory/clip/{fact['id']}")
            with wave.open(io.BytesIO(clip.content)) as w:
                seconds = w.getnframes() / w.getframerate()
            check(clip.status_code == 200 and clip.headers["content-type"] == "audio/wav" and seconds > 5, f"memory's clip for line 3: {seconds:.1f} s of WAV")
            (home / "clip-line-3.wav").write_bytes(clip.content)
            print(f"  the clip, to listen to: {home / 'clip-line-3.wav'}")
            box = json.loads(await chrome.js(f"""(() => {{ const b = document.querySelector('#fact-{fact["id"]} .play');
                b.scrollIntoView({{block: 'center'}}); const r = b.getBoundingClientRect(); return JSON.stringify([r.x + r.width / 2, r.y + r.height / 2]); }})()"""))
            for kind in ("mousePressed", "mouseReleased"):
                await chrome.send("Input.dispatchMouseEvent", type=kind, x=box[0], y=box[1], button="left", clickCount=1)
            button = f"document.querySelector('#fact-{fact['id']} .play').classList"
            await chrome.wait_for(f"{button}.contains('playing')", timeout=3)
            await asyncio.sleep(1.0)
            check(await chrome.js(f"{button}.contains('playing') && !{button}.contains('missing')"), "the clip button is playing after a second")
            await chrome.wait_for(f"!{button}.contains('playing')", timeout=seconds + 5)
            check(not await chrome.js(f"{button}.contains('missing')"), f"the clip played to its end ({seconds:.1f} s) and stopped by itself")
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
            await play(deal2, ta, range(1, 22), gap=0.3)  # the contradiction is on line 19; two lines on, it is still in view
            await asyncio.sleep(2.0)
            shooting = False
            await camera
            film_to(frames, out / "2-facts-arriving.mp4", out / "2-facts-arriving-sheet.png")
            await matches_memory(deal2)
            conflict = await chrome.js("document.querySelector('#graph div.conflict')?.textContent || ''")
            check("14,000" in conflict and "13,000" in conflict, f"contradiction card: {conflict[:140]!r}")
            check(await chrome.js("!!document.querySelector('#graph path.link.conflict')"), "the contradiction points at the agreed 13,000")
            check(await chrome.js(IN_VIEW % "#graph div.conflict"), "the contradiction is in view in the graph")
            rows = json.loads(await chrome.js(CHECKLIST))
            check(rows["amount"]["contradicted"].startswith("Contradicted · Call 1 · "), f"the checklist marks the amount: {rows['amount']}")
            await asyncio.sleep(1.2)  # the contradiction's red wash, part faded: as the room sees it a second on
            await chrome.shot(out / "2-contradiction.png")
            await reload_check("contradiction")
            card = json.loads(await chrome.js("""(() => { const c = document.querySelector('#graph div.conflict').getBoundingClientRect();
              const hit = [...document.querySelectorAll('#graph .node, #items .item')].filter((n) => { const r = n.getBoundingClientRect();
                return r.left < c.right && c.left < r.right && r.top < c.bottom && c.top < r.bottom; }).map((n) => n.id || n.dataset.item);
              return JSON.stringify(hit); })()"""))
            check(card == [], f"the contradiction card covers no node and no term: {card}")
            check(await chrome.js("!!document.querySelector('#graph path.link.card-link')"), "the card's red link runs to what was just said")

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
            marks = json.loads(await chrome.js("""JSON.stringify([...document.querySelectorAll('#graph .src-voice_note')].map((m) =>
              m.closest('[id^="fact-"]')?.id.slice(5)).filter(Boolean))"""))
            on_graph = [f["id"] for f in voiced if f["id"] in marks]
            check(on_graph and set(on_graph) <= {f["id"] for f in voiced}, f"voice-note facts carry the voice-note mark ({len(on_graph)} of {len(voiced)}; the rest are dots)")
            rows = json.loads(await chrome.js(CHECKLIST))
            amount = rows["amount"]
            title = await chrome.js("document.querySelector('#items .item[data-item=amount]').title")
            check(amount["state"] == "Changed" and amount["value"].startswith("25,000") and amount["foot"].startswith("WhatsApp voice note") and amount["foot"].endswith("· both said yes")
                  and "Changed by voice note, both said yes" in title, f"the amount changed by voice note: {amount}, hover {title!r}")
            await asyncio.sleep(0.6)
            await chrome.shot(out / "2b-voice-notes.png")
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
            check(await chrome.js(f"document.getElementById('fact-{amount['id']}').classList.contains('superseded')"), "the old amount shows as replaced")
            check(len(json.loads(await chrome.js(OWED))) == 3, "paid and owed shown on the amount, the advance and the balance")
            rows = json.loads(await chrome.js(CHECKLIST))
            check((rows["amount"]["state"], rows["amount"]["value"]) == ("Changed", "26,000 rupees, with the balcony"), f"the checklist shows the change: {rows['amount']}")
            await asyncio.sleep(0.5)
            await chrome.shot(out / "3-payments-and-change.png")
            await reload_check("payments and change")

            # ---------- 4. a past fact altered inside memory: the chain must say where ----------
            print("4. the chain, with link 5 altered after it was written")
            versions = app.state.memory.book.deal(deal).versions
            versions[4] = versions[4].model_copy(update={"value": "99,000 rupees"})
            await chrome.reload()
            await chrome.wait_for(LOADED)
            await chrome.wait_for("document.getElementById('chain').textContent.includes('broken')")
            text = await chrome.js("document.getElementById('chain').textContent")
            check(text == "Witness chain broken at link 5 (Work, call 1 line 5)", f"chain: {text!r}")
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
    print(f"events published: {sent}; real rooms 0, messages 0")
    print("FAILED:\n  " + "\n  ".join(failures) if failures else "all checks passed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=8021)
    parser.add_argument("--out", type=Path, default=Path("fixtures/dashboard-shots/visual"))
    args = parser.parse_args()
    asyncio.run(main(args.port, args.out))
