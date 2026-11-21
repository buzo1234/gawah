"""Manual proof for the contract stream. Not a test: it uses the real model, speech and S3.

Start the server, then:

    uv run python -m tests.contract_proof --url http://localhost:8000

Through /dev/publish it replays a practice call as call 1, publishes a checklist with all
six terms agreed and both confirmations, and waits for version 1 of the contract. Then a
short call 2 on the same deal: the hirer adds the balcony wall for 2,000 more and both
confirm the change by voice (fact.changed, as the mouth sends it), and they agree the paint
brand. Memory records the change, and the contract stream writes version 2.

Both versions' PDFs and texts, version 2's spoken summary, and an image of each page of
version 2 are saved in fixtures/contract-sample/v2/. Short clips from fixtures/audio/ are
uploaded to stand in for each call's recordings, so the agreement prints their SHA-256.

Usage: 4 S3 uploads of clips here, and from the server 2 contract writes (reasoning model),
2 speech calls and 4 S3 uploads; memory's Scribe sends call 2's 8 lines to its small model
(call 1 is answered from its saved replies).
"""

import argparse
import asyncio
import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from websockets.asyncio.client import connect

sys.path.insert(0, str(Path(__file__).parent))
from contract_fakes import agreed_items  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.contracts import (  # noqa: E402
    CallEnded, CallStarted, ChangeStatus, ChecklistUpdated, ContractReady, Event, FactChanged, ItemKey, Person, Role,
    TermsConfirmed, TranscriptLine, new_id, parse_event,
)
from app.store import S3  # noqa: E402
from fakes.replayer import load, play  # noqa: E402
from fakes.tail import socket_url  # noqa: E402

CALL = "fixtures/call_two_amounts.json"
OUT = Path("fixtures/contract-sample/v2")
RECORDINGS = {
    1: {Role.HIRER: Path("fixtures/audio/paint-01.wav"), Role.WORKER: Path("fixtures/audio/paint-02.wav")},
    2: {Role.HIRER: Path("fixtures/audio/paint-03.wav"), Role.WORKER: Path("fixtures/audio/paint-04.wav")},
}
# Call 2: (speaker, start, end, words). The change is confirmed after line 4.
CALL_2 = [
    (Role.HIRER, 1.0, 6.5, "Ramesh ji, ek baat aur. Balcony ki deewar bhi paint karni hai, railing ke saath."),
    (Role.WORKER, 7.0, 11.5, "Ho jayega madam. Deewar ke 2,000 extra lagenge."),
    (Role.HIRER, 12.0, 16.5, "Theek hai, 2,000 extra. To total 15 hazaar ho gaya."),
    (Role.WORKER, 17.0, 19.5, "Ji madam, 15 hazaar."),
    (Role.HIRER, 26.0, 32.0, "Aur paint Asian Paints ka hi lana hai, Apcolite. Wo main le aaungi."),
    (Role.WORKER, 32.5, 36.0, "Ji, Asian Paints Apcolite hi lagaunga."),
    (Role.HIRER, 36.5, 39.5, "Theek hai. Baaki sab waisa hi rahega."),
    (Role.WORKER, 40.0, 42.0, "Ji madam, namaste."),
]
NEW_AMOUNT = "15,000 rupees, labour only, including the balcony wall"


def _no_query(url: str) -> str:
    """A signed link without its signature, safe to print."""
    return urlsplit(url)._replace(query="<signature>").geturl()


async def main(url: str) -> None:
    fixture = load(CALL)
    said = {line["line_no"]: line["text"] for line in fixture["lines"]}
    items = [i.model_copy(update={"source_text": said[i.line_no]}) for i in agreed_items()]
    deal_id = f"contract-proof-{new_id()[:4]}"
    s3, keys = S3(get_settings()), {1: {}, 2: {}}
    for call_no, clips in RECORDINGS.items():
        for role, clip in clips.items():
            keys[call_no][role.value] = await s3.upload(str(clip), f"recordings/{deal_id}/{call_no}/{role.value}.wav", "audio/wav")
            print(f"uploaded {clip} as call {call_no}'s {role.value} recording, sha256 {hashlib.sha256(clip.read_bytes()).hexdigest()}")

    no_keepalive = httpx.Limits(max_keepalive_connections=0)  # call 2's pauses outlast uvicorn's idle timeout
    async with httpx.AsyncClient(base_url=url, timeout=10, limits=no_keepalive) as server, connect(socket_url(url), max_size=None) as watcher:
        ready: dict[int, ContractReady] = {}

        async def publish(event: Event) -> None:
            if isinstance(event, CallEnded):
                event = event.model_copy(update={"recording_keys": keys[event.call_no]})
            response = await server.post("/dev/publish", content=event.model_dump_json())
            response.raise_for_status()

        async def wait_for_version(n: int) -> ContractReady:
            async for message in watcher:
                event = parse_event(message)
                if isinstance(event, ContractReady) and event.deal_id == deal_id:
                    ready[len(ready) + 1] = event
                    if len(ready) == n:
                        return event

        await play(fixture, publish, speed=0, deal_id=deal_id)
        await publish(ChecklistUpdated(deal_id=deal_id, items=items))
        await publish(TermsConfirmed(deal_id=deal_id, person=Role.HIRER, said="haan sab sahi hai"))
        await publish(TermsConfirmed(deal_id=deal_id, person=Role.WORKER, said="ji theek hai"))
        print(f"deal={deal_id}: call 1 replayed, checklist and both confirmations published; waiting for version 1")
        await asyncio.wait_for(wait_for_version(1), 180)

        amount = (await server.get(f"/memory/term/{deal_id}/{ItemKey.AMOUNT.value}")).json()["current"]
        print(f"memory's amount: {amount['value']} ({amount['status']}), fact {amount['id']}")
        people = [Person(**p) for p in fixture["people"]]
        room = f"replay-{deal_id}-2"  # a replay room: the brain and the mouth stay out
        start = datetime.now(UTC)
        await publish(CallStarted(deal_id=deal_id, people=people, room=room, call_no=2, ts=start))
        change_id = new_id()
        steps = [
            (20.0, FactChanged(deal_id=deal_id, change_id=change_id, fact_id=amount["id"], new_value=NEW_AMOUNT,
                               status=ChangeStatus.PROPOSED, item=ItemKey.AMOUNT, proposed_by=Role.HIRER,
                               said=f"{CALL_2[1][3]} {CALL_2[2][3]}")),
            (22.5, FactChanged(deal_id=deal_id, change_id=change_id, fact_id=amount["id"], new_value=NEW_AMOUNT,
                               status=ChangeStatus.CONFIRMED_ONE, item=ItemKey.AMOUNT, proposed_by=Role.HIRER,
                               confirmed_by=[Role.HIRER], said="Haan, theek hai.")),
            (24.0, FactChanged(deal_id=deal_id, change_id=change_id, fact_id=amount["id"], new_value=NEW_AMOUNT,
                               status=ChangeStatus.CONFIRMED_BOTH, item=ItemKey.AMOUNT, proposed_by=Role.HIRER,
                               confirmed_by=[Role.HIRER, Role.WORKER], said="Ji, pakka.")),
        ]
        steps += [
            (end, TranscriptLine(deal_id=deal_id, speaker=speaker, text=text, start=begin, end=end, line_no=n, call_no=2))
            for n, (speaker, begin, end, text) in enumerate(CALL_2, 1)
        ]
        steps.append((43.0, CallEnded(deal_id=deal_id, people=people, room=room, call_no=2, duration=43.0, reason="replay")))
        print(f"deal={deal_id}: call 2 at real speed, about 45 seconds")
        for at, event in sorted(steps, key=lambda step: step[0]):  # at real speed, so every time is a real one
            await asyncio.sleep(max(0.0, (start + timedelta(seconds=at) - datetime.now(UTC)).total_seconds()))
            await publish(event.model_copy(update={"ts": datetime.now(UTC)}))
        print(f"deal={deal_id}: call 2 and the change published; waiting for version 2")
        await asyncio.wait_for(wait_for_version(2), 240)
        chain = (await server.get(f"/memory/chain/{deal_id}")).json()
        state = (await server.get("/memory/state", params={"deal": deal_id})).json()

    v2 = ready[2]
    shown = v2.model_dump(mode="json")
    shown["pdf_url"], shown["voice_summary_url"] = _no_query(v2.pdf_url), _no_query(v2.voice_summary_url)
    shown.pop("text")
    print(json.dumps(shown, ensure_ascii=False, indent=1))
    print(f"memory's chain now: verified={chain['verified']} links={chain['links']} head={chain['head']}")
    print(f"memory's OpenAI calls since the server started: {state['openai_calls']}")

    OUT.mkdir(parents=True, exist_ok=True)
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as web:
        for n, event in ready.items():
            files = [(event.pdf_url, f"contract-v{n}.pdf")] + ([(event.voice_summary_url, f"summary-v{n}.ogg")] if n == 2 else [])
            for link, name in files:
                response = await web.get(link)
                response.raise_for_status()
                (OUT / name).write_bytes(response.content)
                print(f"downloaded {OUT / name}: {len(response.content)} bytes, {response.headers['content-type']}")
            (OUT / f"contract-v{n}.txt").write_text(event.text + "\n", encoding="utf-8")
    for old in OUT.glob("contract-v2-page-*.png"):
        old.unlink()
    subprocess.run(["pdftoppm", "-r", "110", "-png", str(OUT / "contract-v2.pdf"), str(OUT / "contract-v2-page")], check=True)
    print("pages:", ", ".join(str(p) for p in sorted(OUT.glob("contract-v2-page-*.png"))))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run one deal with two calls and a confirmed change through a running server.")
    parser.add_argument("--url", default="http://localhost:8000")
    asyncio.run(main(parser.parse_args().url))
