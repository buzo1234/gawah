"""The user's real call (deal 28f0f514ab54): the hirer said when the balance is paid, nobody
was heard accepting it, and the contract went out without it. The lines that decided it are in
tests/memory/calls/real_balance_gap.json, with Gawah's two turns.

Two ways the balance should have been agreed, each tested on its own: the worker's "ji Karan ji,
theek hai" opening the next line, and both people's yes to Gawah's question naming the value.
The scripted Scribe gives what the live Scribe gave on that call (the balance said at 12 and
again at 20, the start date at 13, nothing from 22 or 23); the last test uses the replies the
live model gave with Gawah's words in its context (tests/memory/recorded/real_balance_gap.json).
"""

import json
import logging
from pathlib import Path

import pytest

from app.brain import Brain, _Saved
from app.bus import Bus
from app.contracts import (
    CallStarted, ChecklistUpdated, FactKind, FactRecorded, FactStatus, ItemKey, ItemState, JudgeSpeak, JudgeSpoke,
    Person, Role, SpeakReason, Audience, TranscriptLine,
)
from app.memory import Memory, scribe
from app.memory.extract import RecordedExtractor
from app.memory.vectors import WordHashEmbedder
from tests.memory.world import ScriptedExtractor, claim

CALL = json.loads((Path(__file__).parent / "calls" / "real_balance_gap.json").read_text())
DEAL = "d-balance-gap"
LINES = {line["line_no"]: line for line in CALL["lines"]}
TURNS = {turn["after_line"]: turn for turn in CALL["gawah"]}
REST = "rest after completion"

# What the live Scribe made of these lines on the user's call, on main.
AS_ON_THE_CALL = {
    LINES[12]["text"]: [claim("balance", "state", value=REST, quote=LINES[12]["text"])],
    LINES[13]["text"]: [claim("dates", "state", value="start next Monday", date="2026-11-23", quote=LINES[13]["text"])],
    LINES[20]["text"]: [claim("balance", "state", value=REST, quote=LINES[20]["text"])],
}


class Call:
    def __init__(self, bus: Bus, extractor, tmp_path: Path) -> None:
        self.bus = bus
        self.memory = Memory(self.bus, extractor, WordHashEmbedder(), root=tmp_path, embed_model="hash")
        self.memory.attach(self.bus)
        quiet = _Saved([], logging.LoggerAdapter(logging.getLogger("test"), {}))
        self.brain = Brain(self.bus, "live", lambda started: (quiet, quiet), self.memory)
        self.events = []

        async def keep(event) -> None:
            self.events.append(event)

        self.bus.subscribe_all(keep)

    async def settle(self) -> None:
        for _ in range(3):
            await self.bus.drain()
            await self.memory.settle()
            await self.brain.idle()

    async def send(self, event) -> None:
        self.bus.publish(event)
        await self.settle()

    async def start(self) -> None:
        people = [Person(**p) for p in CALL["people"]]
        await self.send(CallStarted(deal_id=DEAL, people=people, call_no=1, room="fake-balance-gap"))

    async def line(self, n: int, gawah: bool = True) -> None:
        await self.send(TranscriptLine(deal_id=DEAL, call_no=1, **LINES[n]))
        if gawah and n in TURNS:
            await self.gawah(TURNS[n])

    async def gawah(self, turn: dict) -> None:
        """Gawah's turn as the brain and the mouth send it: judge.speak naming what the brain
        would ask both to confirm, then judge.spoke with the words said on the call."""
        item = ItemKey(turn["item"])
        proposal = self.brain.sessions[DEAL]._proposals().get(item) if turn["reason"] == "wrapping_up" else None
        speak = JudgeSpeak(
            deal_id=DEAL, instruction="(as on the call)", to=Audience.BOTH, reason=SpeakReason(turn["reason"]), item=item,
            after_line=turn["after_line"], fact_ids=list(proposal.fact_ids) if proposal else [],
        )
        await self.send(speak)
        await self.send(JudgeSpoke(deal_id=DEAL, text=turn["text"], speak_id=speak.event_id, reason=speak.reason, item=item))

    def balance(self) -> list:
        book = self.memory.book.deal(DEAL)
        return [f for f in book.standing() if f.item == ItemKey.BALANCE and f.kind == FactKind.TERM]

    def checklist(self, key: ItemKey):
        last = [e for e in self.events if isinstance(e, ChecklistUpdated)][-1]
        return next(i for i in last.items if i.key == key)


@pytest.mark.asyncio
async def test_both_saying_yes_to_gawahs_question_agrees_the_balance(bus, tmp_path, monkeypatch):
    # The leading "ji, theek hai" at line 13 is taken away, as it was on main, so only Gawah's question can agree it.
    monkeypatch.setattr(scribe, "opens_with_yes", lambda text, names=frozenset(): False)
    call = Call(bus, ScriptedExtractor(AS_ON_THE_CALL), tmp_path)
    await call.start()
    for n in (11, 12, 13, 20):
        await call.line(n)
    assert {f.status for f in call.balance()} == {FactStatus.SAID}
    assert call.checklist(ItemKey.BALANCE).state is ItemState.PENDING
    asked = [e for e in call.events if isinstance(e, JudgeSpeak)][-1]
    assert asked.fact_ids == [f.id for f in call.balance()]  # lines 12 and 20: the brain names every fact of its proposal

    await call.line(22)  # the hirer's yes to his own words agrees nothing yet
    assert {f.status for f in call.balance()} == {FactStatus.SAID}

    await call.line(23)
    facts = call.balance()
    assert {f.status for f in facts} == {FactStatus.AGREED}
    assert all(f.said_by is Role.HIRER and f.agreed_by == [Role.WORKER] and f.value == REST for f in facts)
    item = call.checklist(ItemKey.BALANCE)
    assert item.state is ItemState.AGREED and item.value == REST
    assert not [e for e in call.events if isinstance(e, FactRecorded) and e.fact.line_no in (22, 23)
                and e.fact.item != ItemKey.BALANCE]  # Gawah's words are no fact


@pytest.mark.asyncio
async def test_a_yes_opening_the_next_line_accepts_the_balance(bus, tmp_path):
    call = Call(bus, ScriptedExtractor(AS_ON_THE_CALL), tmp_path)
    await call.start()
    for n in (11, 12, 13):
        await call.line(n)
    [balance] = call.balance()
    assert balance.status is FactStatus.AGREED and balance.agreed_by == [Role.WORKER] and balance.line_no == 12
    assert call.checklist(ItemKey.BALANCE).state is ItemState.AGREED
    dates = [f for f in call.memory.book.deal(DEAL).standing() if f.item == ItemKey.DATES]
    assert [(f.status, f.said_by) for f in dates] == [(FactStatus.SAID, Role.WORKER)]  # the rest of the line is its own clause


@pytest.mark.asyncio
async def test_a_yes_to_a_question_that_names_no_value_agrees_nothing(bus, tmp_path, monkeypatch):
    monkeypatch.setattr(scribe, "opens_with_yes", lambda text, names=frozenset(): False)
    call = Call(bus, ScriptedExtractor(AS_ON_THE_CALL), tmp_path)
    await call.start()
    for n in (11, 12, 13, 20):
        await call.line(n, gawah=n != 20)
    await call.gawah({"after_line": 20, "reason": "term_unclear", "item": "balance", "text": "Karan ji, balance kab denge?"})
    for n in (22, 23):
        await call.line(n)
    assert {f.status for f in call.balance()} == {FactStatus.SAID}


@pytest.mark.asyncio
@pytest.mark.parametrize("leading_yes", [True, False], ids=["both-ways", "gawahs-question-only"])
async def test_the_live_scribes_replies_with_gawahs_words_end_with_the_balance_agreed(bus, tmp_path, monkeypatch, leading_yes):
    if not leading_yes:
        monkeypatch.setattr(scribe, "opens_with_yes", lambda text, names=frozenset(): False)
    call = Call(bus, RecordedExtractor(), tmp_path)
    await call.start()
    agreed_after = None
    for n in LINES:
        await call.line(n)
        if agreed_after is None and call.checklist(ItemKey.BALANCE).state is ItemState.AGREED:
            agreed_after = n
    assert agreed_after == (13 if leading_yes else 23)
    held = [f for f in call.balance() if f.status in (FactStatus.AGREED, FactStatus.CONFIRMED)]
    assert held and all(f.said_by is Role.HIRER and Role.WORKER in f.agreed_by for f in held)
    changes = [f for f in call.memory.book.deal(DEAL).standing() if f.kind == FactKind.CHANGE]
    assert not changes, [(f.line_no, f.item, f.status, f.value) for f in changes]


@pytest.mark.asyncio
@pytest.mark.parametrize("said", ["हाँ जी, लेकिन बाकी का पैसा तो आधा पहले चाहिए।", "नहीं जी, ऐसा तय नहीं हुआ था।", "हाँ? कौन सा बैलेंस?"])
async def test_a_hedged_or_doubting_answer_to_gawah_agrees_nothing(bus, tmp_path, monkeypatch, said):
    monkeypatch.setattr(scribe, "opens_with_yes", lambda text, names=frozenset(): False)
    call = Call(bus, ScriptedExtractor(AS_ON_THE_CALL), tmp_path)
    await call.start()
    for n in (11, 12, 13, 20, 22):
        await call.line(n)
    await call.send(TranscriptLine(deal_id=DEAL, call_no=1, **{**LINES[23], "text": said}))
    assert {f.status for f in call.balance()} == {FactStatus.SAID}
