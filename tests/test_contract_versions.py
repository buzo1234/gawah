"""The contract written from memory's facts: a change both confirmed on a second call makes
version 2, with the change history, both calls, and the witness chain."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from contract_fakes import FakeFiles, FakeSpeaker, FakeWriter, checklist, fake_fingerprint, fake_render_pdf

from app.contract.stream import ContractStream
from app.contracts import (
    AgentNote, CallEnded, CallStarted, ChangeStatus, ContractReady, CrewAgent, Fact, FactChanged, FactKind, ItemState,
    FactRecorded, FactSource, FactStatus, ItemKey, Role, TermsConfirmed,
)
from app.memory import Memory, chain
from app.memory.extract import RecordedExtractor, Routed
from app.memory.vectors import WordHashEmbedder
from app.store import Store
from fakes.memory import FakeMemory, two_amounts_facts
from fakes.replayer import replay

CALL = "fixtures/call_two_amounts.json"
DEAL = "d-ver"
PROPOSED = "Balcony ki deewar bhi karni hai, uske 2,000 extra."


class Rig:
    """The contract stream on a real bus and store, with memory standing in as given."""

    def __init__(self, bus, store, memory=None):
        self.bus, self.files, self.memory = bus, FakeFiles(), memory
        self.stream = ContractStream(
            bus, store, FakeWriter(), FakeSpeaker(), self.files, fake_render_pdf, fake_fingerprint,
            memory=lambda: self.memory,
        )
        self.ready: list[ContractReady] = []
        self.notes: list[AgentNote] = []
        bus.subscribe_all(self.stream.on_event)
        bus.subscribe(ContractReady, self._collect)
        bus.subscribe(AgentNote, self._collect)

    async def _collect(self, event):
        (self.ready if isinstance(event, ContractReady) else self.notes).append(event)

    def record(self, *facts: Fact) -> list[Fact]:
        """Chain each version the way memory does, hand it to the fake memory, and publish it."""
        linked = []
        for fact in facts:
            previous = self.memory.facts[-1].hash if self.memory.facts else chain.GENESIS
            fact = chain.link(fact, previous)
            self.memory.facts.append(fact)
            self.bus.publish(FactRecorded(deal_id=fact.deal_id, fact=fact))
            linked.append(fact)
        return linked

    async def first_contract(self, deal_id=DEAL) -> ContractReady:
        await replay(self.bus, CALL, speed=0, deal_id=deal_id)
        self.bus.publish(checklist(deal_id))
        for role in Role:
            self.bus.publish(TermsConfirmed(deal_id=deal_id, person=role))
        [ready] = await self.settle()
        return ready

    def second_call(self, deal_id=DEAL) -> datetime:
        started = datetime.now(UTC)
        self.bus.publish(CallStarted(deal_id=deal_id, call_no=2, room=f"replay-{deal_id}-2", ts=started))
        return started

    def end_second_call(self, started: datetime, deal_id=DEAL) -> None:
        self.bus.publish(CallEnded(
            deal_id=deal_id, call_no=2, duration=120.0, ts=started + timedelta(seconds=120),
            recording_keys={"hirer": f"recordings/{deal_id}/2/hirer.wav", "worker": f"recordings/{deal_id}/2/worker.wav"},
        ))

    def change(self, fact_id: str, new_value: str, deal_id=DEAL) -> None:
        steps = [
            (ChangeStatus.PROPOSED, [], PROPOSED),
            (ChangeStatus.CONFIRMED_ONE, [Role.HIRER], "haan"),
            (ChangeStatus.CONFIRMED_BOTH, [Role.HIRER, Role.WORKER], "ji theek hai"),
        ]
        for status, confirmed, said in steps:
            self.bus.publish(FactChanged(
                deal_id=deal_id, change_id="c-balcony", fact_id=fact_id, new_value=new_value, status=status,
                item=ItemKey.AMOUNT, proposed_by=Role.HIRER, confirmed_by=confirmed, said=said,
            ))

    async def settle(self) -> list[ContractReady]:
        await self.bus.drain()
        await self.stream.idle()
        await self.bus.drain()
        return self.ready


@pytest.fixture
async def store(bus, settings):
    store = Store(settings.database_path)
    await store.open()
    bus.subscribe_all(store.record_event)
    yield store
    await store.close()


def paint_brand(deal_id=DEAL, **changes) -> Fact:
    fact = Fact(
        id="f-paint", deal_id=deal_id, text="Sunita buys the paint, Asian Paints Apcolite.", kind=FactKind.OTHER,
        said_by=Role.HIRER, agreed_by=[Role.WORKER], status=FactStatus.AGREED,
        quote="Paint main khud le aaungi, Asian Paints ka.", call_no=1, line_no=6, start=32.5, end=37.0,
    )
    return fact.model_copy(update=changes)


async def test_a_change_both_confirmed_on_a_second_call_makes_version_2(bus, store):
    rig = Rig(bus, store, FakeMemory([]))
    rig.record(*two_amounts_facts(DEAL), paint_brand())
    v1 = await rig.first_contract()
    assert v1.pdf_key == f"contracts/{DEAL}-v1.pdf"
    assert "CHANGES" not in v1.text and "Version 1" in v1.text
    assert "Witness chain: 7 कड़ियाँ / links" in v1.text

    started = rig.second_call()
    rig.change("f-amount", "15,000 rupees, labour only, with the balcony wall")
    assert len(await rig.settle()) == 1  # both said yes, but memory has not recorded the new fact yet

    old = next(f for f in reversed(rig.memory.facts) if f.id == "f-amount")
    new, _ = rig.record(
        Fact(
            id="f-amount-2", deal_id=DEAL, text="The amount is now 15,000 rupees, labour only, with the balcony wall.",
            item=ItemKey.AMOUNT, kind=FactKind.TERM, value="15,000 rupees, labour only, with the balcony wall",
            value_rupees=15000, said_by=Role.HIRER, agreed_by=[Role.WORKER], confirmed_by=[Role.HIRER, Role.WORKER],
            status=FactStatus.CONFIRMED, quote=PROPOSED, call_no=2, valid_from=started + timedelta(seconds=65),
            replaces="f-amount",
        ),
        old.model_copy(update={"status": FactStatus.SUPERSEDED, "superseded_at": started + timedelta(seconds=65)}),
    )
    assert len(await rig.settle()) == 1  # the call is still going on: its length and recordings are not known yet
    rig.end_second_call(started)
    _, v2 = await rig.settle()
    text = v2.text

    assert (v2.pdf_key, v2.voice_summary_key) == (f"contracts/{DEAL}-v2.pdf", f"contracts/{DEAL}-v2.ogg")
    assert "संस्करण / Version: संस्करण 2 (संस्करण 1 की जगह) / Version 2 (replaces version 1)" in text
    # the changed term, with its new value and when it was agreed: call 2, 1:05 in
    assert ("2. कीमत और उसमें क्या शामिल है / The price and what it covers (बदला गया / changed)  [कॉल / call 2, 1:05]\n"
            "तय हुआ: 15,000 rupees, labour only, with the balcony wall") in text
    assert "13,000" not in text.split("CHANGES")[0]  # the old figure is only in the change history
    assert ("बदलाव / CHANGES\n" in text and
            "1. कीमत और उसमें क्या शामिल है / The price and what it covers  [कॉल / call 2, 1:05]\n"
            "  पहले / Before: तय हुआ: 13,000 rupees, labour only / 13,000 rupees, labour only\n"
            "  अब / Now: तय हुआ: 15,000 rupees, labour only, with the balcony wall / 15,000 rupees, labour only, with the balcony wall\n"
            "  दोनों ने कॉल पर बोलकर पक्का किया / Confirmed by both by voice on the call: ") in text
    assert f"कहा / Said: “{PROPOSED}”" in text
    # both calls, each with its own recordings, and "the calls", not "the call"
    assert "Call 1 started on " in text and "Call 2 started on " in text and "lasted 2 min 0 sec." in text
    assert "Call 2 · First party's audio: " in text and "Call 2 · Second party's audio: " in text  # the replay kept none
    assert "The two parties agreed the following on the calls." in text and "It was on the calls, and recorded them" in text
    # the chain over every fact version, as memory chained them
    assert f"Witness chain: 9 कड़ियाँ / links, आख़िरी पहचान / head fingerprint {rig.memory.facts[-1].hash}" in text
    assert "Any later change to a recorded fact would break this chain" in text
    # also agreed, quoting what was said
    assert ("6. और जो तय हुआ / Also agreed\n- तय हुआ: Sunita buys the paint, Asian Paints Apcolite.  [कॉल / call 1, 0:32]\n"
            "  Sunita buys the paint, Asian Paints Apcolite.\n  कहा / Said: “Paint main khud le aaungi, Asian Paints ka.”") in text
    assert "7. जो बातें तय नहीं हुईं / What was not agreed" in text
    html = rig.files.uploaded[v2.pdf_key][0].decode()
    assert "Version 2" in html and "class=changes" in html and "बदला गया" in html
    assert [i.value for i in v2.items if i.key is ItemKey.AMOUNT] == ["15,000 rupees, labour only, with the balcony wall"]

    clerk = [n for n in rig.notes if n.agent is CrewAgent.CLERK]
    assert [n.text for n in clerk] == [
        "contract v1 written: 6 terms, chain 7 links",
        "contract v2 written: 6 terms, amount now 15,000 rupees, labour only, with the balcony wall, chain 9 links",
    ]
    assert clerk[1].fact_ids == [new.id]


async def test_memory_figure_wins_over_a_checklist_that_read_an_offer(bus, store):
    rig = Rig(bus, store, FakeMemory([]))
    rig.record(*two_amounts_facts(DEAL))
    await replay(bus, CALL, speed=0, deal_id=DEAL)
    items = checklist(DEAL).items
    items[1] = items[1].model_copy(update={"value": "14,000 rupees, labour only"})  # line 19's slip
    bus.publish(checklist(DEAL).model_copy(update={"items": items}))
    for role in Role:
        bus.publish(TermsConfirmed(deal_id=DEAL, person=role))
    [ready] = await rig.settle()
    assert "14,000" not in ready.text
    assert "[कॉल / call 1, 0:59]\nतय हुआ: 13,000 rupees, labour only\n" in ready.text  # memory's agreed fact and its moment


async def test_only_facts_both_agreed_on_a_call_are_also_agreed(bus, store):
    rig = Rig(bus, store, FakeMemory([]))
    rig.record(
        paint_brand(id="f-said", text="Ramesh will bring a ladder.", status=FactStatus.SAID, agreed_by=[]),
        paint_brand(id="f-term", text="The walls get 2 coats.", item=ItemKey.WORK),
        paint_brand(id="f-text", text="Sunita sent a photo of the wall.", source=FactSource.TEXT),
        paint_brand(id="f-disputed", text="Work stops on Sunday.", status=FactStatus.DISPUTED),
        paint_brand(),
    )
    ready = await rig.first_contract()
    assert "Asian Paints" in ready.text
    for absent in ("ladder", "2 coats.", "photo", "Sunday"):
        assert absent not in ready.text, absent


async def test_a_chain_that_does_not_hold_is_left_off(bus, store, caplog):
    rig = Rig(bus, store, FakeMemory([]))
    [fact] = rig.record(paint_brand())
    bus.publish(FactRecorded(deal_id=DEAL, fact=fact.model_copy(update={"text": "Sunita buys Berger paint."})))
    ready = await rig.first_contract()
    assert "Witness chain" not in ready.text
    assert f"deal={DEAL} the witness chain over 2 fact versions does not hold" in caplog.text


async def test_without_memory_the_checklist_both_confirmed_is_written(bus, store):
    rig = Rig(bus, store, memory=None)
    ready = await rig.first_contract()
    assert "13,000 rupees, labour only; the hirer brings the paint" in ready.text and "Witness chain" not in ready.text


async def test_version_2_from_the_real_memory(bus, store, tmp_path):
    """The real memory stream, on the Scribe's saved replies: the change reaches its facts,
    and the contract follows it with the head memory itself reports."""
    memory = Memory(bus, Routed(None, RecordedExtractor()), WordHashEmbedder(), root=Path(tmp_path))
    memory.attach(bus)
    rig = Rig(bus, store, memory)
    deal_id = "replay-d-ver"
    await replay(bus, CALL, speed=0, deal_id=deal_id)
    await memory.settle()
    bus.publish(checklist(deal_id))
    await bus.drain()
    await memory.settle()
    for role in Role:
        bus.publish(TermsConfirmed(deal_id=deal_id, person=role))
    [v1] = await rig.settle()
    await memory.settle()

    started = rig.second_call(deal_id)
    amount = (await memory.get_term(deal_id, ItemKey.AMOUNT)).current
    assert amount.value_rupees == 13000
    rig.change(amount.id, "15,000 rupees, labour only, with the balcony wall", deal_id)
    rig.end_second_call(started, deal_id)
    await rig.settle()
    await memory.settle()
    _, v2 = await rig.settle()

    assert "Version 2 (replaces version 1)" in v2.text and "(बदला गया / changed)  [कॉल / call 2, " in v2.text
    assert "  पहले / Before: तय हुआ: 13,000 rupees" in v2.text
    report = chain.report(memory.book.deal(deal_id).versions)
    assert report["verified"]
    assert f"Witness chain: {report['links']} कड़ियाँ / links, आख़िरी पहचान / head fingerprint {report['head']}" in v2.text


def balance_said(deal_id=DEAL, **changes) -> Fact:
    """The user's real call: the hirer said when the balance is paid; nobody was heard agreeing."""
    fact = Fact(
        id="f-balance", deal_id=deal_id, text="The hirer will pay the rest after the work is done.", item=ItemKey.BALANCE,
        kind=FactKind.TERM, value="rest after completion", said_by=Role.HIRER, status=FactStatus.SAID,
        quote="बाकी का पैसा काम पूरे होने के बाद दूँगा।", call_no=1, line_no=12, start=68.0, end=71.0,
    )
    return fact.model_copy(update=changes)


async def test_a_term_said_but_not_agreed_is_written_as_not_agreed_with_what_was_said(bus, store):
    rig = Rig(bus, store, FakeMemory([]))
    rig.record(balance_said())
    await replay(bus, CALL, speed=0, deal_id=DEAL)
    bus.publish(checklist(DEAL, pending=(ItemKey.BALANCE,)))
    for role in Role:
        bus.publish(TermsConfirmed(deal_id=DEAL, person=role))
    [ready] = await rig.settle()
    assert "बाकी पैसा: तय नहीं हुआ। कॉल पर सुनीता ने कहा: “बाकी का पैसा काम पूरे होने के बाद दूँगा।”  [कॉल / call 1, 1:08]" in ready.text
    assert "Balance: not agreed. On the call, Sunita said: “बाकी का पैसा काम पूरे होने के बाद दूँगा।” (rest after completion)." in ready.text
    assert "when the balance is paid and against what" in ready.text  # and among what was not agreed
    assert next(i for i in ready.items if i.key is ItemKey.BALANCE).state is ItemState.PENDING


async def test_a_term_said_on_the_call_and_confirmed_by_both_on_their_call_backs_is_written(bus, store):
    rig = Rig(bus, store, FakeMemory([]))
    rig.record(balance_said())
    await replay(bus, CALL, speed=0, deal_id=DEAL)
    bus.publish(checklist(DEAL, pending=(ItemKey.BALANCE,)))
    for role in Role:
        bus.publish(TermsConfirmed(deal_id=DEAL, person=role, item=ItemKey.BALANCE, value="rest after completion", said="haan"))
        if role is Role.HIRER:
            await rig.settle()
            assert not rig.ready, "not before the second person has answered"
        bus.publish(TermsConfirmed(deal_id=DEAL, person=role, said="haan"))
    [ready] = await rig.settle()
    balance = next(i for i in ready.items if i.key is ItemKey.BALANCE)
    assert (balance.state, balance.value) == (ItemState.AGREED, "rest after completion")
    assert "तय हुआ: rest after completion" in ready.text and "Balance: not agreed" not in ready.text
    assert "All six were agreed" in ready.text
