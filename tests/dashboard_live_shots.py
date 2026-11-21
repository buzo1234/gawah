"""Proof run for the dashboard on the real memory, in a real browser at 1920 by 1080. Not
collected by pytest. Reaches nothing outside: it serves the offline app (tests/offline.py,
with memory answering from its saved replies) in this process, so it knows where the call
recordings go.

    PYTHONPATH=. uv run python tests/dashboard_live_shots.py

1. call_missing_balance to line 17, then the shot: mid-call.
   The user's recorded lines (fixtures/audio) are laid out as the call's two recordings,
   at the times of the call's lines, so a clip button plays real audio from memory.
1b. The brain's own spike call to line 23, where Sunita asks Gawah: the page shows the
   question the brain sent in judge.speak, then Gawah's answer under it.
2. call_two_amounts to line 21: memory's contradiction on line 19, then the shot.
3. The first call finished, an advance paid on WhatsApp, and the amount changed by both:
   payments, what they count towards, and a superseded version, then the shot.

After each shot: the page is checked against memory's own answers (/memory/state, terms,
owed, /memory/chain), and a reload must rebuild exactly the same page. Last, one past
fact is altered inside memory, and the chain must name the link that broke.
"""

import argparse
import asyncio
import io
import json
import tempfile
import wave
from pathlib import Path

import httpx
import uvicorn
from browser import Chrome

from app.contracts import (
    Audience, CallEnded, CallStarted, ChangeStatus, FactChanged, ItemKey, JudgeSpoke, Person, Record,
    RecordKind, RecordReceived, Role, SpeakReason, TranscriptLine, new_id,
)
from fakes.replayer import load
from tests.offline import offline_app

PANELS = ["top", "flow", "items", "decisions", "graph", "chain", "lanes", "records"]
SNAPSHOT = """JSON.stringify({
  text: Object.fromEntries(%r.map((id) => [id, document.getElementById(id).textContent])),
  links: [...document.querySelectorAll('#graph path.link')].map((p) => p.getAttribute('class')).sort(),
})""" % PANELS
LOADED = "document.getElementById('conn').textContent === 'live' && !!document.querySelector('#deal-picker option')"
VERIFIED = "document.getElementById('chain').textContent.includes('Verified') && !document.getElementById('chain').textContent.includes('new')"
GRAPH = """JSON.stringify([...document.querySelectorAll('#graph .fact[id^="fact-"]')].map((el) => ({
  id: el.id.slice(5), status: [...el.classList].find((c) => ['said','agreed','confirmed','disputed','superseded'].includes(c)),
  stands: el.classList.contains('stands'), row: el.closest('.term-row').querySelector('.term-label').firstChild.textContent,
  below: !!el.closest('.track.below'),
})))"""
OWED = "JSON.stringify([...document.querySelectorAll('#graph .owed')].map((el) => [el.closest('.term-label').firstChild.textContent, el.textContent]))"
IN_VIEW = """(() => { const el = document.querySelector('%s'), g = document.getElementById('graph').getBoundingClientRect();
  const r = el.getBoundingClientRect(); return r.top >= g.top && r.bottom <= g.bottom; })()"""
AUDIO = Path("fixtures/audio")


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

        async def play(deal: str, fixture: dict, lines: range, start: bool = True, end: bool = False) -> None:
            people = [Person(**p) for p in fixture["people"]]
            if start:
                await publish(CallStarted(deal_id=deal, people=people, room=f"replay-{deal}"))
            for line in fixture["lines"]:
                if line["line_no"] in lines:
                    await publish(TranscriptLine(deal_id=deal, **line))
                    await asyncio.sleep(0.05)
            if end:
                await publish(CallEnded(deal_id=deal, people=people, room=f"replay-{deal}", duration=fixture["lines"][-1]["end"]))

        async with Chrome(port=port + 1000) as chrome:

            async def matches_memory(deal: str) -> None:
                """The graph, card by card, against what memory holds."""
                memory = await settle(deal)
                await chrome.wait_for(VERIFIED)
                shown = {c["id"]: c for c in json.loads(await chrome.js(GRAPH))}
                held = {f["id"]: f for f in memory["facts"]}
                check(shown.keys() == held.keys(), f"every fact memory holds is a card, and no other ({len(held)})")
                wrong = [i for i in held if i in shown and shown[i]["status"] != held[i]["status"]]
                check(not wrong, f"each card shows memory's latest status{f': wrong on {wrong}' if wrong else ''}")
                for item in ItemKey:
                    term = (await http.get(f"/memory/term/{deal}/{item.value}")).json()["current"]
                    stands = [i for i, c in shown.items() if c["stands"] and held[i]["item"] == item.value and held[i]["kind"] == "term"]
                    check(stands == ([term["id"]] if term else []), f"{item.value}: the card marked as standing is memory's current term")
                for i, f in held.items():
                    target = held.get(f.get("counts_towards") or "")
                    if target and target["item"] and i in shown:
                        check(shown[i]["below"], f"{f['kind']} {f['value']} sits under the {target['item']} term it counts towards")
                owed = {r["item"]: r for r in memory["owed"]}
                for label, text in json.loads(await chrome.js(OWED)):
                    r = owed[label.lower()]
                    want = f"Paid ₹{r['paid_rupees']}₹{r['owed_rupees']} left"
                    check(text.replace(",", "") == want, f"{label}: {text!r} is memory's owed ({r['paid_rupees']} paid, {r['owed_rupees']} owed)")
                chain = (await http.get(f"/memory/chain/{deal}")).json()
                text = await chrome.js("document.getElementById('chain').textContent")
                check(chain["verified"] and f"Verified, {chain['links']} links" in text and chain["head"][:8] in text, f"chain: {text!r}")

            async def reload_check(label: str) -> None:
                before = await chrome.js(SNAPSHOT)
                await chrome.reload()
                await chrome.wait_for(LOADED)
                await chrome.wait_for(VERIFIED)
                await asyncio.sleep(0.8)
                await chrome.js("document.getElementById('tab-graph').click()")
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

            # ---------- 1b. a question put to Gawah, asked of the real brain ----------
            print("1b. spike_painter_call to line 23: the brain's own question")
            sp = load("tests/brain/spike_painter_call.json")
            deal_sp = f"live-sp-{new_id()[:4]}"
            await chrome.goto(f"{url}/dashboard?deal={deal_sp}")
            await chrome.wait_for(LOADED)
            await play(deal_sp, sp, range(1, 24))
            await settle(deal_sp)
            events = (await http.get("/dashboard/state", params={"deal": deal_sp})).json()["events"]
            speak = next((e for e in events if e["name"] == "judge.speak" and e["reason"] == "addressed_directly"), None)
            check(speak is not None and speak["after_line"] == 23, f"the brain spoke to a question at line 23: {speak and speak['after_line']}")
            check(bool(speak and speak.get("question")), f"the brain filled judge.speak.question: {speak and speak.get('question')!r}")
            if speak and speak.get("question"):
                why = await chrome.js("document.querySelector('#decisions .decision').textContent")
                check(f"AskedSunita: “{speak['question']}”Answer" in why and "(not said yet)" in why, f"asked, before Gawah answers: {why[:140]!r}")
                await publish(JudgeSpoke(
                    deal_id=deal_sp, text="Haan Sunita ji, sab note kar liya hai.", speak_id=speak["event_id"],
                    to=Audience.HIRER, reason=SpeakReason.ADDRESSED_DIRECTLY, start=123.0, end=125.0,
                ))
                await asyncio.sleep(0.5)
                why = await chrome.js("document.querySelector('#decisions .decision').textContent")
                check(f"AskedSunita: “{speak['question']}”Answer“Haan Sunita ji, sab note kar liya hai.”" in why, f"asked and answered: {why[:140]!r}")
                await chrome.shot(out / "1b-asked-gawah.png")

            # ---------- 2. the contradiction on call_two_amounts ----------
            print("2. call_two_amounts, the contradiction")
            ta = load("fixtures/call_two_amounts.json")
            deal2 = f"live-ta-{new_id()[:4]}"
            await chrome.goto(f"{url}/dashboard?deal={deal2}")
            await chrome.wait_for(LOADED)
            await play(deal2, ta, range(1, 22))  # the contradiction is on line 19; two lines on, it is still in view
            await matches_memory(deal2)
            conflict = await chrome.js("document.querySelector('#graph div.conflict')?.textContent || ''")
            check("14,000" in conflict and "13,000" in conflict, f"contradiction card: {conflict[:140]!r}")
            check(await chrome.js("!!document.querySelector('#graph path.link.conflict')"), "the contradiction points at the agreed 13,000")
            check(await chrome.js(IN_VIEW % "#graph div.conflict"), "the contradiction is in view in the graph")
            await chrome.shot(out / "2-contradiction.png")
            await reload_check("contradiction")

            # ---------- 3. after call 1: a payment, and a change both agree to ----------
            print("3. call_missing_balance finished, an advance paid, the amount changed")
            await chrome.goto(f"{url}/dashboard?deal={deal}")
            await chrome.wait_for(LOADED)
            await play(deal, mb, range(18, 100), start=False, end=True)
            await settle(deal)
            await publish(RecordReceived(deal_id=deal, record=Record(sender=Role.HIRER, kind=RecordKind.ADVANCE, amount=8000, text="8000 advance GPay kar diya")))
            await publish(RecordReceived(deal_id=deal, record=Record(sender=Role.HIRER, kind=RecordKind.PAYMENT, amount=5000, text="5000 aur diye")))
            amount = (await http.get(f"/memory/term/{deal}/amount")).json()["current"]
            change = FactChanged(deal_id=deal, fact_id=amount["id"], new_value="26,000 rupees, with the balcony", item=ItemKey.AMOUNT,
                                 proposed_by=Role.HIRER, status=ChangeStatus.CONFIRMED_BOTH, confirmed_by=[Role.WORKER, Role.HIRER])
            await publish(change)
            await settle(deal)
            await chrome.js("document.getElementById('tab-graph').click()")
            await matches_memory(deal)
            check(await chrome.js(f"document.getElementById('fact-{amount['id']}').classList.contains('superseded')"), "the old amount shows as replaced")
            check(len(json.loads(await chrome.js(OWED))) == 3, "paid and owed shown on the amount, the advance and the balance")
            await chrome.js("document.querySelector('#graph .owed')?.closest('.term-row').scrollIntoView()")
            await asyncio.sleep(0.5)
            await chrome.shot(out / "3-payments-and-change.png")
            await reload_check("payments and change")

            # ---------- 4. a past fact altered inside memory: the chain must say where ----------
            print("4. the chain, with link 5 altered after it was written")
            versions = app.state.memory.book.deal(deal).versions
            versions[4] = versions[4].model_copy(update={"value": "99,000 rupees"})
            await chrome.reload()
            await chrome.wait_for(LOADED)
            await chrome.wait_for("document.getElementById('chain').textContent.includes('Broken')")
            text = await chrome.js("document.getElementById('chain').textContent")
            check(text == "Witness chainBroken at link 5 (Work, call 1 line 5)", f"chain: {text!r}")
            await chrome.shot(out / "4-chain-broken.png")
            check(not chrome.errors, f"no errors in the page: {chrome.errors}")

    server.should_exit = True
    await serving
    print(f"events published: {sent}; real rooms 0, messages 0")
    print("FAILED:\n  " + "\n  ".join(failures) if failures else "all checks passed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=8021)
    parser.add_argument("--out", type=Path, default=Path("fixtures/dashboard-shots/live"))
    args = parser.parse_args()
    asyncio.run(main(args.port, args.out))
