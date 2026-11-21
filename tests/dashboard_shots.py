"""Proof run for the dashboard, in a real browser at 1920 by 1080. Not collected by pytest.

It replays a practice call into a running server, publishes what the other streams would
(checklist, Judge, records, WhatsApp) through /dev/publish, takes the three screenshots in
fixtures/dashboard-shots/, and checks that a reload shows exactly what the live page did.
Start the server on a throwaway database first, because the events stay in it:

    DATABASE_PATH=/tmp/shots.db uv run uvicorn app.main:app --port 8000
    PYTHONPATH=. uv run python tests/dashboard_shots.py
"""

import argparse
import asyncio
import json
import tempfile
from pathlib import Path

import httpx
from browser import Chrome

from app.contracts import (
    NO_DEAL, Audience, Backing, ChecklistItem, ChecklistUpdated, ContractReady, DealRequested, Direction,
    ItemKey, ItemState, JudgeSpeak, JudgeSpoke, Person, Record, RecordConfirmed, RecordConfirmRequested,
    RecordKind, RecordReceived, ReplyTimeout, Role, SpeakReason, TermsConfirmed, TermsDisputed,
    WhatsAppMessage, call_path, callback_path, empty_checklist, new_id,
)
from fakes import RAMESH, SUNITA
from fakes.replayer import load, play

PANELS = ["top", "flow", "items", "decisions", "records", "second-chat", "real-chat"]
SNAPSHOT = "JSON.stringify(Object.fromEntries(%r.map((id) => [id, document.getElementById(id).innerText])))" % PANELS
LOADED = "document.getElementById('conn').textContent === 'live' && !!document.querySelector('#deal-picker option')"


async def main(url: str, out: Path, deal: str) -> None:
    items = {i.key: i for i in empty_checklist()}
    sent = 0

    async with httpx.AsyncClient(base_url=url, timeout=5) as http, Chrome() as chrome:

        async def publish(*events) -> None:
            nonlocal sent
            for e in events:
                (await http.post("/dev/publish", content=e.model_dump_json())).raise_for_status()
                sent += 1

        async def agree(key: ItemKey, value: str, line_no: int, source: str, note: str | None = None, state=ItemState.AGREED) -> None:
            items[key] = ChecklistItem(key=key, state=state, value=value, confidence=0.9, source_text=source, line_no=line_no, note=note)
            await publish(ChecklistUpdated(deal_id=deal, items=list(items.values()), changed=[key]))

        async def reload_check(label: str) -> None:
            await asyncio.sleep(0.5)
            before = await chrome.js(SNAPSHOT)
            await chrome.reload()
            await chrome.wait_for(LOADED)
            await asyncio.sleep(0.5)
            after = await chrome.js(SNAPSHOT)
            print(f"reload check ({label}): {'SAME' if before == after else 'DIFFERENT'} - {len(before)} characters of panel text compared")
            if before != after:
                b, a = json.loads(before), json.loads(after)
                for k in b:
                    if b[k] != a[k]:
                        print(f"  {k} before: {b[k][-300:]!r}\n  {k} after:  {a[k][-300:]!r}")

        # A stand-in payment screenshot, stored through the dashboard's own upload route.
        receipt = Path(tempfile.mkdtemp()) / "payment.png"
        await chrome.send("Emulation.setDeviceMetricsOverride", width=420, height=560, deviceScaleFactor=1, mobile=False)
        await chrome.goto("data:text/html,<body style='font:28px system-ui;margin:0;padding:40px;background:%23f4f6fb'><div style='font-size:22px'>Payment successful</div><div style='font-size:64px;font-weight:800;margin:30px 0'>&%238377;8,000</div><div>To: Ramesh</div><div>23 Nov 2026, 9:02 am</div><div style='margin-top:30px;font-size:20px'>Transaction ID<br>T2611230001</div></body>")
        await chrome.shot(receipt)
        await chrome.send("Emulation.setDeviceMetricsOverride", width=1920, height=1080, deviceScaleFactor=1, mobile=False)
        stored = (await http.post("/dashboard/media", content=receipt.read_bytes(), headers={"content-type": "image/png"})).json()
        shot_url = stored["url"]

        await chrome.goto(f"{url}/dashboard")
        await chrome.wait_for(LOADED)

        # Step 1 and 2 of the demo: Sunita asks, both get a link.
        base = url
        await publish(
            WhatsAppMessage(deal_id=NO_DEAL, direction=Direction.IN, phone=SUNITA.phone, text="Ramesh painter se deal pakki karni hai. Number +910000000002", provider_id="SM1"),
            DealRequested(deal_id=deal, requested_by=SUNITA, other=Person(role=Role.WORKER, phone=RAMESH.phone), text="Ramesh painter se deal pakki karni hai"),
            WhatsAppMessage(deal_id=deal, direction=Direction.OUT, phone=SUNITA.phone, role=Role.HIRER, text=f"Namaste Sunita ji. Call ke liye yeh link dabaiye: {base}{call_path(deal, Role.HIRER)}"),
            WhatsAppMessage(deal_id=deal, direction=Direction.OUT, phone=RAMESH.phone, role=Role.WORKER, simulated=True, text=f"Namaste. Sunita ji aapse kaam ki baat pakki karna chahti hain. Call ke liye yeh link dabaiye: {base}{call_path(deal, Role.WORKER)}"),
        )

        speak = None

        async def emit(e) -> None:
            nonlocal speak
            await publish(e)
            n = getattr(e, "line_no", None)
            if n == 6:
                await agree(ItemKey.WORK, "Paint the whole 2BHK flat: both bedrooms, hall, kitchen, ceilings, balcony grill. Putty on the damp wall.", 6, "Seelan wali wall pe pehle putty aur primer, phir do coat.")
            if n == 14:
                await agree(ItemKey.AMOUNT, "24,000 rupees, labour and material", 14, "Theek hai ji, 24 hazaar final. Labour, material, putty, sab ismein.")
            if n == 16:
                await asyncio.sleep(1.0)
                await chrome.shot(out / "1-mid-call.png")
                await reload_check("mid-call")
            if n == 18:
                await agree(ItemKey.ADVANCE, "8,000 rupees by GPay, on the morning work starts", 17, "jis din kaam shuru karoge us din subah GPay kar dungi")
            if n == 24:
                await agree(ItemKey.DATES, "Monday start, finished by Friday evening", 22, "Monday shuru, Friday shaam tak poora finish.")
                await asyncio.sleep(0.6)
                speak = JudgeSpeak(deal_id=deal, instruction="Ask when the balance will be paid.", to=Audience.HIRER, reason=SpeakReason.TERM_UNCLEAR, item=ItemKey.BALANCE, after_line=24)
                await publish(speak)
                await asyncio.sleep(0.9)
                await publish(JudgeSpoke(deal_id=deal, text="Sunita ji, ek baat reh gayi - baaki paise kab diye jayenge?", speak_id=speak.event_id, to=Audience.HIRER, reason=SpeakReason.TERM_UNCLEAR, item=ItemKey.BALANCE, start=121.0, end=124.5))
                await asyncio.sleep(0.8)
                await chrome.shot(out / "2-gawah-speaks.png")
            if n == 27:
                await agree(ItemKey.LATE_OR_UNFINISHED, "500 rupees cut for each day it is late", 26, "agar late hua to har din ka 500 rupaye kaat lena aap")
            if n == 30:
                wrap = JudgeSpeak(deal_id=deal, instruction="The balance is still open. Ask once more before they hang up.", to=Audience.BOTH, reason=SpeakReason.WRAPPING_UP, item=ItemKey.BALANCE, after_line=30)
                await publish(wrap, JudgeSpoke(deal_id=deal, text="Rakhne se pehle - baaki paise kab aur kaise diye jayenge?", speak_id=wrap.event_id, to=Audience.BOTH, reason=SpeakReason.WRAPPING_UP, item=ItemKey.BALANCE, start=149.0, end=152.0, interrupted=True))

        await play(load("fixtures/call_missing_balance.json"), emit, speed=12, deal_id=deal)

        # After the call: call-back answers, the contract, then records.
        advance = Record(sender=Role.HIRER, kind=RecordKind.ADVANCE, backing=Backing.BACKED, text="Advance bhej diya", media_url=shot_url, amount=8000, date="23 Nov 2026", transaction_id="T2611230001")
        cash = Record(sender=Role.HIRER, kind=RecordKind.PAYMENT, text="2,000 cash diya", amount=2000)
        day = Record(sender=Role.WORKER, kind=RecordKind.WORK_DAY, text="Aaj dono bedroom ho gaye")
        done = Record(sender=Role.WORKER, kind=RecordKind.WORK_DONE, text="Madam kaam poora ho gaya")
        await publish(
            TermsConfirmed(deal_id=deal, person=Role.HIRER, said="haan, sab sahi hai"),
            TermsConfirmed(deal_id=deal, person=Role.WORKER, item=ItemKey.AMOUNT, value="24,000 rupees", said="haan sahi hai"),
            TermsDisputed(deal_id=deal, person=Role.WORKER, item=ItemKey.DATES, value="Monday to Friday", said="nahi, Saturday tak bola tha"),
            ContractReady(deal_id=deal, pdf_key=f"contracts/{deal}.pdf", text="Kaam: 2BHK flat ki painting, ceiling aur balcony grill ke saath.\nRakam: 24,000 rupaye, labour aur material.\nAdvance: 8,000 rupaye, kaam shuru hone ki subah.\nTareekh: Monday se Friday shaam tak.\nDer hone par: har din 500 rupaye katenge.", items=list(items.values())),
            WhatsAppMessage(deal_id=deal, direction=Direction.OUT, phone=SUNITA.phone, role=Role.HIRER, text="Sunita ji, yeh aapka contract hai.", media_url="https://example.invalid/contract.pdf", media_type="application/pdf"),
            WhatsAppMessage(deal_id=deal, direction=Direction.OUT, phone=RAMESH.phone, role=Role.WORKER, simulated=True, text="Ramesh ji, yeh aapka contract hai.", media_url="https://example.invalid/contract.pdf", media_type="application/pdf"),
            WhatsAppMessage(deal_id=deal, direction=Direction.IN, phone=SUNITA.phone, role=Role.HIRER, text="Advance bhej diya", media_url=shot_url, media_type="image/png", provider_id="MM2"),
            RecordReceived(deal_id=deal, record=advance),
            WhatsAppMessage(deal_id=deal, direction=Direction.OUT, phone=SUNITA.phone, role=Role.HIRER, text="8,000 rupaye ka advance darj ho gaya."),
            WhatsAppMessage(deal_id=deal, direction=Direction.IN, phone=SUNITA.phone, role=Role.HIRER, text="2,000 cash diya", provider_id="SM3"),
            RecordReceived(deal_id=deal, record=cash),
            RecordConfirmRequested(deal_id=deal, record_id=cash.id, record=cash, confirm_by=Role.WORKER, question="Sunita ji keh rahi hain 2,000 cash diya. Sahi hai?"),
            WhatsAppMessage(deal_id=deal, direction=Direction.OUT, phone=RAMESH.phone, role=Role.WORKER, simulated=True, text="Sunita ji keh rahi hain 2,000 cash diya. Sahi hai?"),
            WhatsAppMessage(deal_id=deal, direction=Direction.IN, phone=RAMESH.phone, role=Role.WORKER, simulated=True, text="Haan mil gaya"),
            RecordConfirmed(deal_id=deal, record_id=cash.id, confirmed_by=Role.WORKER),
            WhatsAppMessage(deal_id=deal, direction=Direction.IN, phone=RAMESH.phone, role=Role.WORKER, simulated=True, text="Aaj dono bedroom ho gaye"),
            RecordReceived(deal_id=deal, record=day),
            RecordConfirmRequested(deal_id=deal, record_id=day.id, record=day, confirm_by=Role.HIRER),
            RecordConfirmed(deal_id=deal, record_id=day.id, confirmed_by=Role.HIRER, confirmed=False),
            WhatsAppMessage(deal_id=deal, direction=Direction.IN, phone=RAMESH.phone, role=Role.WORKER, simulated=True, text="Madam kaam poora ho gaya"),
            RecordReceived(deal_id=deal, record=done),
            RecordConfirmRequested(deal_id=deal, record_id=done.id, record=done, confirm_by=Role.HIRER, question="Ramesh ji keh rahe hain kaam poora ho gaya. Sahi hai?"),
            WhatsAppMessage(deal_id=deal, direction=Direction.OUT, phone=SUNITA.phone, role=Role.HIRER, text="Ramesh ji keh rahe hain kaam poora ho gaya. Sahi hai?"),
            ReplyTimeout(deal_id=deal, person=Role.HIRER, ask="Kya kaam poora ho gaya?", record_id=done.id, waited_seconds=120),
            WhatsAppMessage(deal_id=deal, direction=Direction.OUT, phone=SUNITA.phone, role=Role.HIRER, text=f"Sunita ji, jawab nahi aaya. Is link par ek minute baat kar lijiye: {base}{callback_path(deal, Role.HIRER)}"),
        )
        await asyncio.sleep(1.0)
        await chrome.shot(out / "3-after-call-records.png")
        await reload_check("after the call")

        overflow = await chrome.js("""JSON.stringify([...document.querySelectorAll('main *, #top *')].filter((el) =>
            el.scrollWidth > el.clientWidth + 1 && getComputedStyle(el).overflowX !== 'visible' && !el.classList.contains('scroll') && el.tagName !== 'SELECT' && el.tagName !== 'INPUT')
            .map((el) => el.tagName + '#' + el.id + '.' + el.className))""")
        print("clipped sideways:", overflow)
        print("smallest text:", await chrome.js("""Math.min(...[...document.querySelectorAll('body *')].filter((el) => el.offsetParent && el.childNodes.length && [...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim())).map((el) => parseFloat(getComputedStyle(el).fontSize)))"""), "px")
        print("page scrolls:", await chrome.js("document.documentElement.scrollHeight > innerHeight || document.documentElement.scrollWidth > innerWidth"))
        print("call links that are real links, second phone / real phone:", await chrome.js("[...['second-chat','real-chat']].map((id) => document.querySelectorAll('#' + id + ' a[href*=\"/call\"]').length).join(' / ')"))
        print("images shown in the chats:", await chrome.js("[...document.querySelectorAll('.chat img')].filter((i) => i.naturalWidth > 0).length"))
        print(f"events published: {sent}")
        print("browser errors:", chrome.errors or "none")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument("--out", default="fixtures/dashboard-shots")
    parser.add_argument("--deal", default=None, help="deal id; a new one each run by default")
    args = parser.parse_args()
    asyncio.run(main(args.url.rstrip("/"), Path(args.out), args.deal or f"shots-{new_id()[:4]}"))
