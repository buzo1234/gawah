"""Manual proof for the contract stream. Not a test: it uses the real model, speech and S3.

Start the server, then:

    uv run python -m tests.contract_proof --url http://localhost:8000

It replays a practice call, publishes a checklist with all six terms agreed and both
confirmations through /dev/publish, waits for contract.ready on the dashboard socket,
and saves the PDF and the audio from their signed links into fixtures/contract-sample/.
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from websockets.asyncio.client import connect

sys.path.insert(0, str(Path(__file__).parent))
from contract_fakes import agreed_items  # noqa: E402

from app.contracts import ChecklistUpdated, ContractReady, Event, Role, TermsConfirmed, new_id, parse_event  # noqa: E402
from fakes.replayer import load, play  # noqa: E402
from fakes.tail import socket_url  # noqa: E402

CALL = "fixtures/call_two_amounts.json"
OUT = Path("fixtures/contract-sample")


def _no_query(url: str) -> str:
    """A signed link without its signature, safe to print."""
    return urlsplit(url)._replace(query="<signature>").geturl()


async def main(url: str) -> None:
    fixture = load(CALL)
    said = {line["line_no"]: line["text"] for line in fixture["lines"]}
    items = [i.model_copy(update={"source_text": said[i.line_no]}) for i in agreed_items()]
    deal_id = f"contract-proof-{new_id()[:4]}"

    async with httpx.AsyncClient(base_url=url, timeout=10) as server, connect(socket_url(url)) as watcher:

        async def publish(event: Event) -> None:
            response = await server.post("/dev/publish", content=event.model_dump_json())
            response.raise_for_status()

        await play(fixture, publish, speed=0, deal_id=deal_id)
        await publish(ChecklistUpdated(deal_id=deal_id, items=items))
        await publish(TermsConfirmed(deal_id=deal_id, person=Role.HIRER, said="haan sab sahi hai"))
        await publish(TermsConfirmed(deal_id=deal_id, person=Role.WORKER, said="ji theek hai"))
        print(f"deal={deal_id}: call replayed, checklist and both confirmations published; waiting for contract.ready")

        async def wait_for_ready() -> ContractReady:
            async for message in watcher:
                event = parse_event(message)
                if isinstance(event, ContractReady) and event.deal_id == deal_id:
                    return event

        ready = await asyncio.wait_for(wait_for_ready(), 180)

    shown = ready.model_dump(mode="json")
    shown["pdf_url"], shown["voice_summary_url"] = _no_query(ready.pdf_url), _no_query(ready.voice_summary_url)
    print(json.dumps(shown, ensure_ascii=False, indent=1))

    OUT.mkdir(parents=True, exist_ok=True)
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as web:
        for link, name in ((ready.pdf_url, "contract.pdf"), (ready.voice_summary_url, "summary.ogg")):
            response = await web.get(link)
            response.raise_for_status()
            (OUT / name).write_bytes(response.content)
            print(f"downloaded {OUT / name}: {len(response.content)} bytes, {response.headers['content-type']}")
    (OUT / "contract.txt").write_text(ready.text + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run one complete deal through a running server.")
    parser.add_argument("--url", default="http://localhost:8000")
    asyncio.run(main(parser.parse_args().url))
