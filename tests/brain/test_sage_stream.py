"""The live Sage2 client, against a stand-in socket on this machine that speaks the
frames the spike saw (spikes/5-sage2.md). The real service is never called here."""

import json

import pytest
from websockets.asyncio.server import serve

from app.brain import sage, tuning


class FakeSage:
    def __init__(self) -> None:
        self.starts: list[dict] = []
        self.appends: list[dict] = []
        self.auth: list[str | None] = []
        self.silent_on: set[int] = set()
        self.hang_up_on: set[int] = set()

    async def handle(self, ws) -> None:
        self.auth.append(ws.request.headers.get("Authorization"))
        async for raw in ws:
            frame = json.loads(raw)
            if frame["type"] == "start":
                self.starts.append(frame)
                await ws.send(json.dumps({"type": "ready", "limits": {}}))
                await self.decide(ws, None, {"work_agreed": ("no", 0.1)})
            elif frame["type"] == "append":
                self.appends.append(frame)
                seq = frame["seq"]
                if seq in self.hang_up_on:
                    self.hang_up_on.discard(seq)
                    await ws.close()
                    return
                if seq not in self.silent_on:
                    await self.decide(ws, seq, {"work_agreed": ("yes", 0.97), "amount_agreed": (None, 0.5), "late_terms": ("no", 0.02)})

    async def decide(self, ws, seq, answers) -> None:
        body = {q: {"result": {"answer": a, "probability": p}} for q, (a, p) in answers.items()}
        await ws.send(json.dumps({"type": "decision", "seq": seq, "answers": body, "changed": []}))
        await ws.send(json.dumps({"type": "sig", "sig": "abc"}))


@pytest.fixture
async def fake_sage(monkeypatch):
    fake = FakeSage()
    async with serve(fake.handle, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        monkeypatch.setattr(sage, "WS_URL", f"ws://127.0.0.1:{port}")
        yield fake


async def test_stream_sends_the_questions_and_reads_the_answers(fake_sage):
    stream = sage.SageStream("test-key")
    first = await stream.open("Preamble.\n\n")
    assert first == {"work_agreed": 0.1}

    answers = await stream.append(1, "Sunita: namaste\n")
    assert answers == {"work_agreed": 0.97, "amount_agreed": None, "late_terms": 0.02}
    assert sage.yes(answers, "work_agreed")
    assert not sage.yes(answers, "amount_agreed"), "a null answer is no"
    assert not sage.yes(answers, "late_terms") and not sage.yes(answers, "not_asked")
    await stream.close()

    start = fake_sage.starts[0]
    assert fake_sage.auth == ["Bearer test-key"]
    assert start["content"] == "Preamble.\n\n" and start["emit"] == "all"
    assert [q["id"] for q in start["questions"]] == list(sage.QUESTIONS)
    assert all(q["kind"] == "yesno" for q in start["questions"])
    assert fake_sage.appends == [{"type": "append", "text": "Sunita: namaste\n", "seq": 1}]
    assert stream.updates == 2


async def test_no_answer_in_time_gives_none_and_the_next_line_still_works(fake_sage, monkeypatch):
    monkeypatch.setattr(tuning, "SAGE_TIMEOUT_S", 0.2)
    fake_sage.silent_on = {1}
    stream = sage.SageStream("k")
    await stream.open("P\n")
    assert await stream.append(1, "a\n") is None
    assert (await stream.append(2, "b\n"))["work_agreed"] == 0.97
    await stream.close()


async def test_dropped_stream_reopens_once_with_the_whole_call(fake_sage):
    fake_sage.hang_up_on = {2}
    stream = sage.SageStream("k")
    await stream.open("P\n")
    await stream.append(1, "a\n")
    assert await stream.append(2, "b\n") == {"work_agreed": 0.1}, "the answers of the reopened stream"
    assert fake_sage.starts[1]["content"] == "P\na\nb\n"
    assert (await stream.append(3, "c\n"))["work_agreed"] == 0.97
    assert stream.updates == 5  # two starts and three appends: the lost line 2 was sent, so it counts
    await stream.close()


async def test_no_service_means_no_answers_not_a_crash(monkeypatch):
    monkeypatch.setattr(sage, "WS_URL", "ws://127.0.0.1:9")
    monkeypatch.setattr(tuning, "SAGE_OPEN_TIMEOUT_S", 0.5)
    stream = sage.SageStream("k")
    assert await stream.open("P\n") is None
    await stream.close()


def test_preamble_names_both_people_and_the_date():
    from datetime import datetime

    from fakes import RAMESH, SUNITA

    text = sage.preamble([SUNITA, RAMESH], datetime(2026, 11, 21))
    assert "Sunita (the hirer" in text and "Ramesh (the worker" in text
    assert "Today is Saturday 21 November 2026." in text
    assert sage.line_text("Sunita", "haan  theek\nhai") == "Sunita: haan theek hai\n"
