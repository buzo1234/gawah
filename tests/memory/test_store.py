"""The store rebuilt from the event log, the witness chain, the routes, and the cache."""

import hashlib
import json

from fastapi.testclient import TestClient

from app import memory as memory_stream
from app.contracts import MEMORY_STATE, FactRecorded, ItemKey, MemoryQueries, clip_path
from app.main import STREAMS, create_app
from app.memory import Memory
from app.memory.chain import GENESIS
from app.memory.vectors import WordHashEmbedder
from tests.memory.test_scenarios import AMOUNT_CALL, AMOUNT_SCRIPT
from tests.memory.world import DEAL, ScriptedExtractor, World


async def test_a_restart_rebuilds_the_same_facts_and_does_not_re_embed(bus, tmp_path):
    world = World(bus, tmp_path, AMOUNT_SCRIPT)
    await world.call(AMOUNT_CALL)
    first = await world.memory.search(DEAL, "amount kitna tay hua")
    calls_before = world.embedder.calls

    embedder = WordHashEmbedder()
    again = Memory(bus, ScriptedExtractor({}), embedder, root=tmp_path, cache_dir=tmp_path / "cache", embed_model="hash")
    again.rebuild(world.events)
    assert again.book.deal(DEAL).versions == world.memory.book.deal(DEAL).versions
    assert await again.get_term(DEAL, ItemKey.AMOUNT) == await world.memory.get_term(DEAL, ItemKey.AMOUNT)
    assert await again.search(DEAL, "amount kitna tay hua") == first
    assert embedder.calls == 0 and calls_before >= 1  # every vector came from the disk cache
    assert await again.clip(first[0].id) == await world.memory.clip(first[0].id)


async def test_the_chain_formula_in_the_docstring_checks_out_by_hand(bus, tmp_path):
    world = World(bus, tmp_path, AMOUNT_SCRIPT)
    await world.call(AMOUNT_CALL)
    previous = GENESIS
    for event in (e for e in world.events if isinstance(e, FactRecorded)):
        data = json.loads(event.model_dump_json())["fact"]
        stored = data.pop("hash")
        content = json.dumps(data, sort_keys=True, ensure_ascii=False)
        assert hashlib.sha256(f"{previous}\n{content}".encode()).hexdigest() == stored
        previous = stored


def test_the_app_registers_memory_and_serves_its_clip_chain_and_state(settings, tmp_path):
    app = create_app(settings)
    assert memory_stream in STREAMS
    with TestClient(app) as client:
        memory = getattr(app.state, MEMORY_STATE)
        assert isinstance(memory, MemoryQueries)
        memory.extractor = ScriptedExtractor(AMOUNT_SCRIPT)
        memory.root = tmp_path
        world = World.__new__(World)
        world.bus, world.tmp, world.memory, world.events = app.state.bus, tmp_path, memory, []
        client.portal.call(world.call, AMOUNT_CALL)
        agreed = memory.book.deal(DEAL).current(ItemKey.AMOUNT)

        wav = client.get(clip_path(agreed.id))
        assert wav.status_code == 200 and wav.headers["content-type"] == "audio/wav"
        assert client.get(clip_path("no-such-fact")).status_code == 404

        chain = client.get(f"/memory/chain/{DEAL}").json()
        assert chain["verified"] and chain["links"] == 4 and chain["first_broken"] is None
        assert chain["head"] == memory.book.deal(DEAL).versions[-1].hash
        state = client.get("/memory/state", params={"deal": DEAL}).json()
        assert state["chain_ok"] and len(state["facts"]) == 3

        versions = memory.book.deal(DEAL).versions
        versions[1] = versions[1].model_copy(update={"value_rupees": 2000})
        broken = client.get(f"/memory/chain/{DEAL}").json()
        assert not broken["verified"] and broken["first_broken"]["index"] == 1
