"""Stream: memory. The Scribe and the Memory in Gawah's crew.

- scribe.py     each transcript line to facts (a small OpenAI model, or saved replies)
- status.py     status moved forward by checklist, call-back, record and change events
- book.py       the fact store: every version in order, the lines, the calls
- chain.py      the witness chain over every fact version
- memory.py     MemoryQueries (get_term, owed, search, clip), conflicts, agent notes
- vectors.py    embeddings, cached on disk under memory-cache/
- clips.py      a fact's seconds of audio from the call recordings
- normalise.py  rupees, dates, and lines with nothing to extract

Set on app.state.memory (MEMORY_STATE). The clip is served at clip_path(fact_id).
A replayed or fake call (room replay-... or fake-...) gets the Scribe's saved replies in
tests/memory/recorded/; MEMORY_LIVE_REPLAYS=1 in the shell sends it to the live model.
"""

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Response

from app.bus import Bus
from app.config import ROOT
from app.contracts import MEMORY_STATE, clip_path
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
        }
