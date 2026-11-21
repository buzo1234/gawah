"""Proof run for the dashboard's crew view, in a real browser at 1920 by 1080. Not collected
by pytest.

Plays a two-call deal into a running server: call 1 is the practice call with the facts,
agent notes and witness chain memory and the rest of the crew would send; between the
calls, a call-back confirmation and an advance paid on WhatsApp; call 2 has a
contradiction, Gawah playing the clip, and an amendment both people say yes to. Takes the
screenshots in fixtures/dashboard-shots/crew/ and checks a reload rebuilds the page.
Run it against the offline server, so nothing outside is reached:

    uv run python -m tests.offline --port 8000
    PYTHONPATH=. uv run python tests/dashboard_crew_shots.py
"""

import argparse
import asyncio
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
from browser import Chrome

from app.contracts import (
    AgentNote, Audience, CallEnded, CallKind, CallStarted, ChangeStatus, ContractReady, CrewAgent, DealRequested, Direction, Fact,
    FactChanged, FactConflict, FactKind, FactRecorded, FactSource, FactStatus, ItemKey, JudgeSpeak, JudgeSpoke,
    Person, Role, SpeakReason, TermsConfirmed, TranscriptLine, WhatsAppMessage, NO_DEAL, new_id,
)
from fakes import RAMESH, SUNITA
from fakes.replayer import load, play

H, W = Role.HIRER, Role.WORKER
PANELS = ["top", "flow", "items", "decisions", "graph", "lanes", "records", "second-chat", "real-chat"]
SNAPSHOT = """JSON.stringify({
  text: Object.fromEntries(%r.map((id) => [id, document.getElementById(id).textContent])),
  links: [...document.querySelectorAll('#graph path.link')].map((p) => p.getAttribute('class')).sort(),
  view: document.getElementById('graph-view').hidden ? 'phones' : 'graph',
})""" % PANELS
LOADED = "document.getElementById('conn').textContent === 'live' && !!document.querySelector('#deal-picker option')"

CALL2 = [
    (H, "Ramesh ji, balcony ka kaam reh gaya hai. Woh kab karoge?"),
    (W, "Madam balcony ke liye alag lagega. Aur total to 25 hazaar tay hua tha na, 24 nahi."),
    (W, "Achha haan ji, 24 hi tha. Par balcony ke 2,000 extra lagenge."),
    (H, "Theek hai, balcony ke 2,000 extra. Total 26 ho gaya."),
    (W, "Haan ji, 26 theek hai."),
    (H, "Haan, mujhe bhi manzoor hai."),
    (H, "Chalo theek hai. Kal se balcony shuru karo."),
]


async def main(url: str, out: Path, deal: str) -> None:
    sent = 0
    prev_hash = "0" * 64
    facts: dict[str, Fact] = {}

    async with httpx.AsyncClient(base_url=url, timeout=5) as http, Chrome() as chrome:

        async def publish(*events) -> None:
            nonlocal sent
            for e in events:
                (await http.post("/dev/publish", content=e.model_dump_json())).raise_for_status()
                sent += 1

        async def fact(key: str, **fields) -> Fact:
            """Record a fact or a new version of one, chained as memory would."""
            nonlocal prev_hash
            base = facts.get(key)
            f = (base.model_copy(update=fields) if base else Fact(deal_id=deal, valid_from=datetime.now(UTC), **fields))
            body = f.model_copy(update={"hash": None}).model_dump_json()
            f.hash = prev_hash = hashlib.sha256((prev_hash + body).encode()).hexdigest()
            facts[key] = f
            await publish(FactRecorded(deal_id=deal, fact=f))
            return f

        async def note(agent: CrewAgent, text: str, **kw) -> None:
            await publish(AgentNote(deal_id=deal, agent=agent, text=text, **kw))

        async def reload_check(label: str) -> None:
            await asyncio.sleep(0.6)
            before = json.loads(await chrome.js(SNAPSHOT))
            await chrome.reload()
            await chrome.wait_for(LOADED)
            await asyncio.sleep(0.8)
            after = json.loads(await chrome.js(SNAPSHOT))
            same = before == after
            print(f"reload check ({label}): {'SAME' if same else 'DIFFERENT'} - {sum(map(len, before['text'].values()))} characters, {len(before['links'])} links, view {before['view']}")
            if not same:
                for k in before["text"]:
                    if before["text"][k] != after["text"][k]:
                        print(f"  {k} before: {before['text'][k][-300:]!r}\n  {k} after:  {after['text'][k][-300:]!r}")
                if before["links"] != after["links"] or before["view"] != after["view"]:
                    print(f"  links/view before: {before['links']} {before['view']}\n  after: {after['links']} {after['view']}")

        await chrome.goto(f"{url}/dashboard?deal={deal}")
        await chrome.wait_for(LOADED)

        await publish(
            WhatsAppMessage(deal_id=NO_DEAL, direction=Direction.IN, phone=SUNITA.phone, text="Ramesh painter se deal pakki karni hai. Number +910000000002"),
            DealRequested(deal_id=deal, requested_by=SUNITA, other=Person(role=W, phone=RAMESH.phone), text="Ramesh painter se deal pakki karni hai"),
        )

        # ---------- call 1: the practice call, with what the crew would send ----------

        async def on_line(e) -> None:
            await publish(e)
            n = getattr(e, "line_no", None)
            if n is None:
                return
            if n % 3 == 0:
                await note(CrewAgent.EARS, f"line {n}: {'Sunita' if e.speaker == H else 'Ramesh'}, {e.end - e.start:.1f} s of speech", line_nos=[n])
            if n == 3:
                f = await fact("work1", item=ItemKey.WORK, kind=FactKind.TERM, text="Paint the whole 2BHK flat.", value="Whole 2BHK: both bedrooms, hall, kitchen, balcony grill", said_by=H, quote=e.text, call_no=1, line_no=3, start=e.start, end=e.end)
                await note(CrewAgent.SCRIBE, "wrote down the work: whole 2BHK", fact_ids=[f.id], line_nos=[3])
            if n == 6:
                old = facts["work1"]
                f = await fact("work2", item=ItemKey.WORK, kind=FactKind.TERM, text="Paint the 2BHK with ceilings; putty and primer on the damp wall.", value="Whole 2BHK with ceilings; putty and primer on the damp wall", said_by=W, agreed_by=[H], status=FactStatus.AGREED, replaces=old.id, quote=e.text, call_no=1, line_no=6, start=e.start, end=e.end)
                await fact("work1", status=FactStatus.SUPERSEDED, superseded_at=datetime.now(UTC))
                await note(CrewAgent.MEMORY, "work: new version replaces line 3", fact_ids=[f.id])
            if n == 10:
                f = await fact("amt28", item=ItemKey.AMOUNT, kind=FactKind.TERM, text="Ramesh offers 28,000 rupees.", value="28,000 rupees, labour and material", value_rupees=28000, said_by=W, quote=e.text, call_no=1, line_no=10, start=e.start, end=e.end)
                await note(CrewAgent.SCRIBE, "Ramesh's offer: 28,000 total", fact_ids=[f.id], line_nos=[10])
            if n == 12:
                f = await fact("amt25", item=ItemKey.AMOUNT, kind=FactKind.TERM, text="Ramesh offers 25,000 rupees.", value="25,000 rupees", value_rupees=25000, said_by=W, replaces=facts["amt28"].id, quote=e.text, call_no=1, line_no=12, start=e.start, end=e.end)
                await fact("amt28", status=FactStatus.SUPERSEDED, superseded_at=datetime.now(UTC))
                await note(CrewAgent.SCRIBE, "new offer: 25,000 replaces 28,000", fact_ids=[f.id], line_nos=[12])
                await note(CrewAgent.FLOOR, "they are bargaining: stay quiet")
            if n == 14:
                f = await fact("amt24", item=ItemKey.AMOUNT, kind=FactKind.TERM, text="The total is 24,000 rupees, labour and material.", value="24,000 rupees, labour, material, putty", value_rupees=24000, said_by=H, agreed_by=[W], status=FactStatus.AGREED, replaces=facts["amt25"].id, quote="Theek hai ji, 24 hazaar final. Labour, material, putty, sab ismein.", call_no=1, line_no=14, start=e.start, end=e.end)
                await fact("amt25", status=FactStatus.SUPERSEDED, superseded_at=datetime.now(UTC))
                await note(CrewAgent.SCRIBE, "agreed by both: total 24,000", fact_ids=[f.id], line_nos=[14])
                await note(CrewAgent.JUDGE, "amount settled; nothing to ask")
            if n == 16:
                f = await fact("adv", item=ItemKey.ADVANCE, kind=FactKind.TERM, text="The advance is 8,000 rupees before work starts.", value="8,000 rupees, before work starts", value_rupees=8000, said_by=W, quote=e.text, call_no=1, line_no=16, start=e.start, end=e.end)
                await note(CrewAgent.SCRIBE, "Ramesh asks 8,000 advance", fact_ids=[f.id], line_nos=[16])
            if n == 17:
                f = await fact("adv", status=FactStatus.AGREED, agreed_by=[H], value="8,000 rupees by GPay, the morning work starts")
                await note(CrewAgent.SCRIBE, "Sunita agreed the advance", fact_ids=[f.id], line_nos=[17])
                await asyncio.sleep(0.9)
                await chrome.shot(out / "1-mid-call-facts.png")
                await reload_check("mid-call")
            if n == 22:
                f = await fact("dates", item=ItemKey.DATES, kind=FactKind.TERM, text="Work starts Monday and finishes by Friday evening.", value="Monday start, finished by Friday evening", said_by=W, quote=e.text, call_no=1, line_no=22, start=e.start, end=e.end)
            if n == 24:
                await fact("dates", status=FactStatus.AGREED, agreed_by=[H])
                await note(CrewAgent.JUDGE, "balance never discussed: ask Sunita")
                await note(CrewAgent.FLOOR, "pause after line 24: Gawah may speak")
                await note(CrewAgent.GAWAH, "asked when the balance will be paid")
            if n == 27:
                f = await fact("late", item=ItemKey.LATE_OR_UNFINISHED, kind=FactKind.TERM, text="500 rupees are cut for each day late.", value="500 rupees cut per day late", value_rupees=500, said_by=W, agreed_by=[H], status=FactStatus.AGREED, quote="agar late hua to har din ka 500 rupaye kaat lena aap", call_no=1, line_no=26, start=e.start, end=e.end)
                await note(CrewAgent.SCRIBE, "agreed: 500 cut per day late", fact_ids=[f.id], line_nos=[26])
            if n == 29:
                f = await fact("paint", kind=FactKind.OTHER, text="Normal emulsion paint; Ramesh brings the material.", value="Normal emulsion; Ramesh brings material", said_by=H, agreed_by=[W], status=FactStatus.AGREED, quote="normal emulsion theek hai. Material aap laoge", call_no=1, line_no=7, start=38.0, end=43.0)

        await play(load("fixtures/call_missing_balance.json"), on_line, speed=10, deal_id=deal)
        await publish(ContractReady(deal_id=deal, pdf_key=f"contracts/{deal}.pdf", text="Kaam: 2BHK flat ki painting.\nRakam: 24,000 rupaye.\nAdvance: 8,000 rupaye."))
        await note(CrewAgent.CLERK, "contract written: 5 terms, balance open")

        # ---------- between the calls ----------
        await publish(TermsConfirmed(deal_id=deal, person=W, item=ItemKey.AMOUNT, value="24,000 rupees", said="haan sahi hai"))
        await fact("amt24", status=FactStatus.CONFIRMED, confirmed_by=[H, W])
        await note(CrewAgent.MEMORY, "total 24,000 confirmed by both")
        shot_url = f"{url}/dashboard/static/does-not-matter.png"
        await publish(WhatsAppMessage(deal_id=deal, direction=Direction.IN, phone=SUNITA.phone, role=H, text="Advance bhej diya, 8,000 GPay"))
        p = await fact("pay1", kind=FactKind.PAYMENT, text="Sunita paid the 8,000 rupee advance by GPay.", value="₹8,000 by GPay", value_rupees=8000, said_by=H, confirmed_by=[H], status=FactStatus.CONFIRMED, source=FactSource.SCREENSHOT, media_url=shot_url, counts_towards=facts["adv"].id, quote="Advance bhej diya, 8,000 GPay")
        await note(CrewAgent.SENTINEL, "₹8,000 matches the agreed advance", fact_ids=[p.id])

        # ---------- call 2: a contradiction, then an amendment ----------
        room = f"replay-{deal}-2"
        people = [SUNITA, RAMESH]
        await publish(CallStarted(deal_id=deal, people=people, room=room, call_no=2))
        await note(CrewAgent.MEMORY, "call 2: 9 facts from call 1 loaded")
        t = 2.0
        for i, (who, text) in enumerate(CALL2, start=1):
            line = TranscriptLine(deal_id=deal, speaker=who, text=text, start=t, end=t + 3.5, line_no=i, call_no=2, kind=CallKind.DEAL)
            t += 5.0
            await publish(line)
            await asyncio.sleep(0.4)
            if i == 2:
                amt = facts["amt24"]
                await note(CrewAgent.MEMORY, "25,000 was Ramesh's offer; 24,000 agreed", fact_ids=[amt.id, facts["amt25"].id])
                await publish(FactConflict(deal_id=deal, fact_ids=[amt.id], explanation="Says the total was 25,000; both agreed 24,000 on call 1, and confirmed it.", said=text, speaker=W, call_no=2, line_no=2, confidence=0.94))
                await note(CrewAgent.JUDGE, "contradicts the record: the total")
                await note(CrewAgent.FLOOR, "waiting for Ramesh to finish")
                speak = JudgeSpeak(deal_id=deal, instruction="Say what was agreed on the total in call 1 and offer to play it.", to=Audience.WORKER, reason=SpeakReason.CONTRADICTS_RECORD, item=ItemKey.AMOUNT, after_line=2, fact_ids=[amt.id])
                await publish(speak)
                await asyncio.sleep(0.5)
                await publish(JudgeSpoke(deal_id=deal, text="Ramesh ji, pehli call mein 24,000 tay hua tha. Sunaiye.", speak_id=speak.event_id, to=Audience.WORKER, reason=SpeakReason.CONTRADICTS_RECORD, item=ItemKey.AMOUNT, start=12.5, end=16.0, clip_fact_id=amt.id))
                await note(CrewAgent.GAWAH, "played the clip: call 1, line 14", fact_ids=[amt.id])
                await asyncio.sleep(1.2)
                await chrome.shot(out / "2-contradiction.png")
                await reload_check("contradiction")
            if i == 4:
                change = FactChanged(deal_id=deal, fact_id=facts["amt24"].id, new_value="26,000 rupees, with the balcony", item=ItemKey.AMOUNT, proposed_by=H, said=text)
                await publish(change)
                await note(CrewAgent.GAWAH, "proposed: total 26,000; asking both")
            if i == 5:
                await publish(change.model_copy(update={"status": ChangeStatus.CONFIRMED_ONE, "confirmed_by": [W], "said": text, "event_id": new_id(), "ts": datetime.now(UTC)}))
                await note(CrewAgent.GAWAH, "Ramesh said yes to 26,000")
                await asyncio.sleep(0.8)
                await chrome.shot(out / "3-amendment-one-yes.png")
            if i == 6:
                await publish(change.model_copy(update={"status": ChangeStatus.CONFIRMED_BOTH, "confirmed_by": [W, H], "said": text, "event_id": new_id(), "ts": datetime.now(UTC)}))
                old = facts["amt24"]
                f = await fact("amt26", item=ItemKey.AMOUNT, kind=FactKind.CHANGE, text="The total is 26,000 rupees, with the balcony.", value="26,000 rupees, with the balcony", value_rupees=26000, said_by=H, agreed_by=[W], confirmed_by=[H, W], status=FactStatus.CONFIRMED, replaces=old.id, quote=text, call_no=2, line_no=6, start=line.start, end=line.end)
                await fact("amt24", status=FactStatus.SUPERSEDED, superseded_at=datetime.now(UTC))
                await note(CrewAgent.MEMORY, "total: 26,000 replaces 24,000", fact_ids=[f.id])
                await note(CrewAgent.CLERK, "contract reissued with its change history")
        await publish(CallEnded(deal_id=deal, people=people, room=room, duration=t, call_no=2, reason="replay"))
        await asyncio.sleep(1.0)
        # The call is over, so WhatsApp brings the phones forward; show the crew for the shot.
        await chrome.js("document.getElementById('tab-graph').click()")
        await asyncio.sleep(0.6)
        await chrome.shot(out / "4-after-amendment.png")
        await chrome.js("document.getElementById('tab-phones').click()")
        await asyncio.sleep(0.4)
        await chrome.shot(out / "5-phones-tab.png")
        await chrome.js("document.getElementById('tab-graph').click()")

        overflow = await chrome.js("""JSON.stringify([...document.querySelectorAll('main *, #top *')].filter((el) =>
            el.offsetParent && el.scrollWidth > el.clientWidth + 1 && getComputedStyle(el).overflowX !== 'visible' && !el.closest('.scroll') && !['SELECT','INPUT','svg','path'].includes(el.tagName))
            .map((el) => el.tagName + '#' + el.id + '.' + el.className))""")
        print("clipped sideways:", overflow)
        print("smallest text:", await chrome.js("""Math.min(...[...document.querySelectorAll('body *')].filter((el) => el.offsetParent && [...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim())).map((el) => parseFloat(getComputedStyle(el).fontSize)))"""), "px")
        print("page scrolls:", await chrome.js("document.documentElement.scrollHeight > innerHeight || document.documentElement.scrollWidth > innerWidth"))
        print("graph scrolls:", await chrome.js("(() => { const g = document.getElementById('graph'); return g.scrollHeight > g.clientHeight })()"))
        print("links drawn:", await chrome.js("JSON.stringify([...document.querySelectorAll('#graph path.link')].map((p) => p.getAttribute('class')))"))
        print("clip buttons:", await chrome.js("document.querySelectorAll('#graph .play').length"))
        print(f"events published: {sent}")
        print("browser errors:", chrome.errors or "none")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument("--out", default="fixtures/dashboard-shots/crew")
    parser.add_argument("--deal", default=None, help="deal id; a new one each run by default")
    args = parser.parse_args()
    asyncio.run(main(args.url.rstrip("/"), Path(args.out), args.deal or f"crew-{new_id()[:4]}"))
