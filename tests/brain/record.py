"""Record what the real services say about a practice call, for the brain's tests.

    uv run python -m tests.brain.record sage fixtures/call_missing_balance.json
    uv run python -m tests.brain.record values fixtures/call_missing_balance.json
    uv run python -m tests.brain.record values-missing fixtures/call_missing_balance.json

`sage` costs one Sage2 update per line plus one. Sage2's free allowance is small: run it
once per fixture, and again only if the questions in app/brain/sage.py change.
`values` replays the saved Sage2 answers through the brain with the real OpenAI model
and saves what it returned. It uses no Sage2. `values-missing` keeps every reply already
saved and asks the model only for lookups the brain now makes that are not saved yet.
"""

import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from app.brain import Brain, sage, tuning
from app.brain.values import OpenAIValues, key
from app.bus import Bus
from app.config import get_settings
from app.contracts import Event, Person, Role
from fakes.replayer import load
from tests.brain.replaying import play

OUT = Path(__file__).parent / "recorded"


async def record_sage(fixture_path: str, extra_questions: dict[str, str]) -> None:
    fixture = load(fixture_path)
    people = [Person(**p) for p in fixture["people"]]
    questions = sage.QUESTIONS | extra_questions
    tuning.SAGE_TIMEOUT_S = 20.0  # a recording must not have holes
    stream = sage.SageStream(get_settings().require("sage_api_key"), questions)
    preamble = sage.preamble(people)
    answers, lines = {"0": await stream.open(preamble)}, {}
    for line in fixture["lines"]:
        name = sage.speaker_name(people, Role(line["speaker"]))
        text = lines[str(line["line_no"])] = sage.line_text(name, line["text"])
        got = await stream.append(line["line_no"], text)
        answers[str(line["line_no"])] = got
        print(line["line_no"], "".join("-" if got is None or got.get(q) is None else "Y" if sage.yes(got, q) else "n" for q in questions), flush=True)
    await stream.close()
    if any(a is None for a in answers.values()):
        raise SystemExit(f"holes in the recording, not saved. updates sent: {stream.updates}")
    out = OUT / f"{fixture['id']}.sage.json"
    out.write_text(json.dumps({
        "fixture": fixture["id"], "recorded_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "preamble": preamble, "questions": questions, "updates": stream.updates, "lines": lines, "answers": answers,
    }, ensure_ascii=False, indent=1) + "\n")
    print(f"saved {out}; sage2 updates sent: {stream.updates}")


class _Saving:
    def __init__(self, inner: OpenAIValues, saved: dict | None = None) -> None:
        self.inner, self.replies, self.saved = inner, {}, saved or {}

    async def lookup(self, kind, item, transcript, at_line):
        if key(kind, item, at_line) in self.saved:
            reply = self.replies[key(kind, item, at_line)] = self.saved[key(kind, item, at_line)]
            return reply
        reply = await self.inner.lookup(kind, item, transcript, at_line)
        self.replies[key(kind, item, at_line)] = reply
        print(" ", key(kind, item, at_line), json.dumps(reply, ensure_ascii=False), flush=True)
        return reply


async def record_values(fixture_path: str, keep: bool = False) -> None:
    fixture = load(fixture_path)
    out = OUT / f"{fixture['id']}.values.json"
    tuning.LOOKUP_WAIT_S = 30.0
    silence_s, tuning.CLOSING_SILENCE_S = tuning.CLOSING_SILENCE_S, 3600.0  # play() passes silences, in call seconds
    openai = OpenAIValues(get_settings().require("openai_api_key"))
    saving = _Saving(openai, json.loads(out.read_text())["replies"] if keep and out.exists() else None)
    bus = Bus()
    bus.start()
    brain = Brain(bus, "live", lambda started: (sage.RecordedDecisions(OUT / f"{fixture['id']}.sage.json"), saving))

    async def emit(event: Event | None) -> None:
        # One event at a time, and wait for its values: the tests replay with replies
        # that are there at once, so the recording has to settle between lines too.
        if event:
            bus.publish(event)
        await bus.drain(60)
        await brain.idle()
        await bus.drain(60)

    await play(fixture, brain, emit, fixture["id"], silence_s)
    await bus.stop()
    await openai.close()
    out.write_text(json.dumps({
        "fixture": fixture["id"], "recorded_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "model": tuning.VALUES_MODEL, "replies": saving.saved | saving.replies,
    }, ensure_ascii=False, indent=1) + "\n")
    print(f"saved {out}; openai calls: {openai.calls}")


if __name__ == "__main__":
    command, fixture_path = sys.argv[1], sys.argv[2]
    if command == "sage":
        extra = json.loads(Path(sys.argv[3]).read_text()) if len(sys.argv) > 3 else {}
        asyncio.run(record_sage(fixture_path, extra))
    elif command in ("values", "values-missing"):
        asyncio.run(record_values(fixture_path, keep=command == "values-missing"))
    else:
        raise SystemExit(__doc__)
