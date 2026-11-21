"""Gawah the agent's tools against the real memory (app/memory), not FakeMemory: memory's own
test world runs the Scribe on a scripted model and writes tone recordings, and Gawah is asked
on a second call about what was agreed on the first, then plays the clip from its recording."""

from app.contracts import ItemKey, Role, TranscriptLine
from app.mouth import tuning
from tests.memory.world import DEAL, claim
from tests.memory.world import World as MemoryWorld
from tests.mouth.world import World, until

H, W = Role.HIRER, Role.WORKER
CALL_1 = [
    (H, "Advance kitna loge?"),
    (W, "5 hazaar pehle de dijiye."),
    (H, "Nahi, 3 hazaar dungi, kal subah."),
    (W, "Theek hai."),
]


async def test_on_a_second_call_the_tools_answer_from_memory_and_play_the_first_calls_clip(bus, tmp_path, monkeypatch):
    monkeypatch.setattr(tuning, "CLIP_MAX_S", 1.0)  # the real clip is 7.6 s; a second of it is enough to hear
    memory = MemoryWorld(bus, tmp_path, {
        CALL_1[1][1]: [claim("advance", "offer", 5000, "5 hazaar pehle de dijiye")],
        CALL_1[2][1]: [claim("advance", "offer", 3000, "3 hazaar dungi, kal subah", date="2026-11-22")],
    })
    await memory.call(CALL_1)
    agreed = (await memory.memory.get_term(DEAL, ItemKey.ADVANCE)).current

    world = World(bus, mode="live", memory=memory.memory)
    seat, link = await world.call(deal_id=DEAL, room=f"deal-{DEAL}-2", call_no=2)
    link.replies = [
        {"calls": [("get_term", {"item": "advance"}), ("search_facts", {"query": "advance kitna tay hua tha"}), ("owed", {})]},
        {"text": "3,000 tay hua tha, kal subah. Suniye.", "ms": 300, "calls": [("play_clip", {"fact_id": agreed.id})]},
        {"text": "Yahi tay hua tha.", "ms": 200},
    ]
    world.bus.publish(TranscriptLine(deal_id=DEAL, speaker=W, text="Gawah ji, advance kitna tay hua tha?",
                                     start=1.0, end=3.0, line_no=1, call_no=2))
    call = world.mouth.calls[DEAL]
    await until(lambda: call.outcomes and call.outcomes[-1]["what"] == "addressed_directly", timeout=8)

    term, found, owed, clip = link.outputs()
    assert term.startswith(f"the advance: now [{agreed.id}] agreed:") and "3,000" in term and "call 1" in term
    assert "History, oldest first:" in term and "5,000" in term  # the offer that was turned down, kept apart
    assert found.startswith(f"[{agreed.id}]")  # the term as it stands comes first
    assert "the advance: agreed 3,000, paid 0, still owed 3,000 rupees" in owed
    assert clip.startswith(f"The clip of fact {agreed.id} is now playing")
    said = call.outcomes[-1]
    assert said["clip"] == agreed.id and said["tools"] == ["get_term", "search_facts", "owed", "play_clip"]
    pads = 2 * tuning.CLIP_PAD_MS
    assert said["speech_ms"] == 300 + 1000 + pads + 200 and not said["interrupted"]  # words, the clip, words
