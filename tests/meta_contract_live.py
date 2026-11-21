"""Manual check, not a test: send the sample contract to both people of a deal through the
running server, as the contract stream's contract.ready would, so a real phone on Meta gets
the PDF with its caption and the voice note. Costs 2 S3 uploads and, per real phone, 2
WhatsApp messages. Needs a deal made in this run (the newest one is used) and .env's S3 keys.

    uv run python -m tests.meta_contract_live [--deal-id <id>] [--url http://localhost:8000]
"""

import argparse
import asyncio

import httpx

from app.config import Settings
from app.contracts import ContractReady
from app.store import S3

SAMPLE = "fixtures/contract-sample"


async def main(url: str, deal_id: str | None) -> None:
    async with httpx.AsyncClient(base_url=url, timeout=30) as server:
        if deal_id is None:
            deals = (await server.get("/dashboard/state")).json()["deals"]
            if not deals:
                raise SystemExit("No deal in this run yet: start one on WhatsApp first.")
            deal_id = deals[0]["id"]
        s3 = S3(Settings())
        pdf, voice = f"contracts/{deal_id}-v1.pdf", f"contracts/{deal_id}-v1.ogg"
        await s3.upload(f"{SAMPLE}/contract.pdf", pdf, "application/pdf")
        await s3.upload(f"{SAMPLE}/summary.ogg", voice, "audio/ogg")
        ready = ContractReady(deal_id=deal_id, pdf_key=pdf, voice_summary_key=voice, text="sample contract")
        response = await server.post("/dev/publish", content=ready.model_dump_json())
        response.raise_for_status()
        print(f"contract.ready published for deal {deal_id}: 2 S3 uploads. Watch the phone and the server log.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--deal-id")
    parser.add_argument("--url", default="http://localhost:8000")
    args = parser.parse_args()
    asyncio.run(main(args.url, args.deal_id))
