"""Record the Scribe's replies for the voice notes in fixtures/voice-notes/: the practice call
fixtures/call_two_amounts.json is replayed into memory first (from its saved replies), then
each note's words are read as a voice note from its speaker with the live model. Prints the
facts and conflicts each note makes; --save keeps the replies in
tests/memory/recorded/voice_notes.json, so tests answer without the model.

    uv run python -m tests.memory.record_voice [--save]

Costs one small-model call per note (four), and one more for each contradiction the model
cites that code cannot compare.
"""

import argparse
import asyncio
import json
import tempfile
from pathlib import Path

from app.bus import Bus
from app.config import get_settings
from app.contracts import FactConflict, FactRecorded, ItemKey, Role, VoiceNote
from app.memory import Memory, extract
from app.memory.openai_client import OpenAIClient
from app.memory.vectors import WordHashEmbedder
from fakes.replayer import replay
from tests.memory.record import Recorder

CALL = "fixtures/call_two_amounts.json"
NOTES = Path("fixtures/voice-notes/notes.json")
OUT = extract.RECORDED / "voice_notes.json"


async def run(save: bool) -> None:
    client = OpenAIClient(get_settings())
    recorder = Recorder(extract.LiveExtractor(client))
    extractor = extract.Routed(recorder, extract.RecordedExtractor())  # the call from its saved replies
    bus = Bus()
    memory = Memory(bus, extractor, WordHashEmbedder(), root=Path(tempfile.mkdtemp()), embed_model="hash")
    memory.attach(bus)
    seen: list = []

    async def keep(event):
        if isinstance(event, FactRecorded | FactConflict):
            seen.append(event)

    bus.subscribe_all(keep)
    bus.start()
    deal = await replay(bus, CALL, speed=0, deal_id="record-voice")
    await bus.drain()
    await memory.settle()
    terms = {k.value: (await memory.get_term(deal, k)).current for k in ItemKey}
    print("after the call:", json.dumps({k: v.value if v else None for k, v in terms.items()}, ensure_ascii=False))
    for name, note in json.loads(NOTES.read_text()).items():
        seen.clear()
        bus.publish(VoiceNote(
            deal_id=deal, speaker=Role(note["speaker"]), phone="+910000000000", text=note["said"],
            media_key=f"recordings/{deal}/voice/{name}", media_type="audio/ogg", message_id=name, seconds=note["seconds"],
        ))
        await bus.drain()
        await memory.settle()
        await bus.drain()
        print(f"\n{name} ({note['speaker']}): {note['said']}")
        for e in seen:
            if isinstance(e, FactRecorded):
                f = e.fact
                print(f"  fact {f.kind.value:<7} {f.item.value if f.item else '-':<10} {f.status.value:<9} "
                      f"{f.value_rupees if f.value_rupees is not None else '':>6} {f.source.value} {f.text}")
            else:
                print(f"  CONFLICT (call {e.call_no}): {e.explanation}")
    print("\nopenai calls:", dict(client.calls))
    if save:
        OUT.write_text(json.dumps(
            {"model": extract.MODEL, "effort": extract.EFFORT, "replies": recorder.replies, "checks": recorder.checks},
            indent=1, ensure_ascii=False,
        ) + "\n")
        print("saved", OUT)
    await client.close()
    await bus.stop()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--save", action="store_true")
    asyncio.run(run(p.parse_args().save))
