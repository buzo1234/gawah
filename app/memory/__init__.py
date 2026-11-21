"""Stream: memory. The Scribe and the Memory in Gawah's crew.

- scribe.py     each transcript line to facts (a small OpenAI model, or saved replies)
- status.py     status moved forward by checklist, call-back, record and change events
- book.py       the fact store: every version in order, the lines, the calls
- chain.py      the witness chain over every fact version
- memory.py     MemoryQueries (get_term, owed, search, clip), conflicts, agent notes
- vectors.py    embeddings, cached on disk under memory-cache/
- clips.py      a fact's seconds of audio from the call recordings
- normalise.py  rupees (number words in number_words.py) and lines with nothing to extract
- dates.py      days, and whether each is the start or the finish

Set on app.state.memory (MEMORY_STATE). The clip is served at clip_path(fact_id), the chain
check at /memory/chain/<deal_id>; for the dashboard and checks by hand, /memory/term/<deal_id>/<item>,
/memory/search/<deal_id>?q=..., and /memory/state?deal=<deal_id> (facts, conflicts, owed, timings).
A replayed or fake call (room replay-... or fake-...) gets the Scribe's saved replies in
tests/memory/recorded/; MEMORY_LIVE_REPLAYS=1 in the shell sends it to the live model.
"""

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Response

from app.bus import Bus
from app.config import ROOT
from app.contracts import MEMORY_STATE, ItemKey, clip_path
from app.memory import chain
from app.memory.extract import LiveExtractor, RecordedExtractor, Routed
from app.memory.memory import Memory
from app.memory.openai_client import EMBED_MODEL, OpenAIClient
from app.memory.vectors import WordHashEmbedder

__all__ = ["Memory", "register"]


def register(app: FastAPI, bus: Bus) -> None:
    settings = app.state.settings
    client = OpenAIClient(settings) if settings.openai_api_key else None
    extractor = Routed(
        LiveExtractor(client) if client else None, RecordedExtractor(),
        live_replays=os.environ.get("MEMORY_LIVE_REPLAYS") == "1",
    )
    memory = Memory(
        bus, extractor, client or WordHashEmbedder(), root=ROOT,
        cache_dir=Path(settings.database_path).parent / "memory-cache",
        embed_model=EMBED_MODEL if client else "word-hash",
    )
    memory.attach(bus)
    setattr(app.state, MEMORY_STATE, memory)
    app.state.memory_client = client

    async def start() -> None:
        calls = getattr(app.state, "calls", None)  # the bridge's recordings folder, if it has one
        if calls is not None and getattr(calls, "folder", None):
            memory.root = Path(calls.folder).parent
        memory.rebuild(await app.state.store.events())

    async def stop() -> None:
        await memory.close()
        if client:
            await client.close()

    app.state.on_startup.append(start)
    app.state.on_shutdown.append(stop)

    @app.get(clip_path("{fact_id}"))
    async def clip(fact_id: str) -> Response:
        wav = await memory.clip(fact_id)
        if wav is None:
            raise HTTPException(404, "no recording for this fact")
        return Response(wav, media_type="audio/wav")

    @app.get("/memory/chain/{deal_id}")
    async def chain_check(deal_id: str) -> dict:
        """The witness chain checked end to end; the formula is in app/memory/chain.py."""
        return chain.report(memory.book.deal(deal_id).versions)

    @app.get("/memory/term/{deal_id}/{item}")
    async def term(deal_id: str, item: ItemKey) -> dict:
        return (await memory.get_term(deal_id, item)).model_dump(mode="json")

    @app.get("/memory/search/{deal_id}")
    async def search(deal_id: str, q: str, k: int = 5) -> list[dict]:
        return [f.model_dump(mode="json") for f in await memory.search(deal_id, q, k)]

    @app.get("/memory/state")
    async def state(deal: str) -> dict:
        """The deal's facts as they stand, every version, the conflicts, and whether the chain holds."""
        book = memory.book.deal(deal)
        return {
            "deal_id": deal,
            "facts": [f.model_dump(mode="json") for f in book.standing()],
            "versions": len(book.versions),
            "chain_ok": memory.chain_break(deal) is None,
            "fingerprint": book.versions[-1].hash if book.versions else None,
            "conflicts": [c.model_dump(mode="json") for c in memory.conflicts if c.deal_id == deal],
            "owed": [r.model_dump(mode="json") for r in await memory.owed(deal)],
            "latency_s": memory.latency_summary(),
            "openai_calls": dict(client.calls) if client else {},
        }
