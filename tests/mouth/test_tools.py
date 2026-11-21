"""Gawah's tools against the fake memory, with the facts of fixtures/call_two_amounts.json."""

import logging

from app.contracts import AgentNote, ChangeStatus, FactChanged, Role, TranscriptLine
from app.mouth import tuning
from app.mouth.moments import Names, addresses_gawah
from app.mouth.tools import Tools
from fakes import RAMESH, SUNITA
from fakes.memory import FakeMemory, two_amounts_facts
from tests.mouth.test_agent import wav

FACTS = two_amounts_facts("d1")


def tools(memory=None, lines=None) -> Tools:
    memory = memory or FakeMemory(FACTS, clips={"f-amount": wav(2.0, rate=48000)})
    facts = {f.id: f for f in FACTS}
    return Tools("d1", lambda: memory, facts, Names([SUNITA, RAMESH]), lines if lines is not None else [], logging.LoggerAdapter(logging.getLogger("t")))


async def test_get_term_gives_the_agreed_value_and_the_offer_it_replaced():
    result = await tools().run("get_term", {"item": "amount"})
    now, history = result.output.split(" History, oldest first: ")
    assert now.startswith("the total amount: now [f-amount] confirmed:") and "13,000 rupees" in now
    assert "confirmed by Sunita, Ramesh" in now
    assert "[f-offer] superseded" in history and "15,000" in history and "Said by Ramesh" in history
    assert "No longer holds" in history and "call 1, 0 min 38 s in" in history
    assert isinstance(result.effects[0], AgentNote) and result.effects[0].fact_ids == ["f-offer", "f-amount", "f-offer", "f-amount"]


async def test_nothing_on_record_is_said_plainly():
    result = await tools().run("get_term", {"item": "dates"})
    assert result.output == tuning.NOT_ON_RECORD.format(what="the dates")


async def test_owed_is_worked_out_in_code():
    result = await tools().run("owed", {})
    assert "the advance: agreed 3,000, paid 3,000, still owed 0 rupees (payment facts: f-paid)" in result.output
    assert "the total amount: agreed 13,000, paid 0" in result.output
    assert "the balance: no figure agreed" in result.output


async def test_search_finds_the_facts_with_who_and_when():
    result = await tools().run("search_facts", {"query": "material labour"})
    assert result.output.startswith("[f-amount] confirmed") and "Words: 'Theek hai, 13 hazaar." in result.output


async def test_a_clip_comes_back_at_the_rooms_rate_with_a_little_silence_round_it():
    result = await tools().run("play_clip", {"fact_id": "f-amount"})
    pad = tuning.RATE * tuning.CLIP_PAD_MS // 1000 * 2
    assert len(result.clip) == 2 * pad + tuning.RATE * 2 * 2  # 2 s at 48 kHz, now 24 kHz
    assert result.clip_fact_id == "f-amount" and "now playing" in result.output
    assert (await tools().run("play_clip", {"fact_id": "f-advance"})).output == tuning.NO_CLIP.format(fact="f-advance")


async def test_a_long_clip_is_cut():
    memory = FakeMemory(FACTS, clips={"f-amount": wav(30.0)})
    result = await tools(memory).run("play_clip", {"fact_id": "f-amount"})
    assert len(result.clip) <= (tuning.CLIP_MAX_S + 2 * tuning.CLIP_PAD_MS / 1000) * tuning.RATE * 2


async def test_a_change_needs_a_real_fact_and_a_yes_from_each_person_said_after_it():
    lines: list[TranscriptLine] = [TranscriptLine(deal_id="d1", speaker=Role.WORKER, text="14 kar do", start=0, end=1, line_no=5)]
    t = tools(lines=lines)
    assert (await t.run("propose_change", {"fact_id": "f-nope", "new_value": "1", "proposed_by": "worker"})).output.startswith("There is no fact")
    proposed = await t.run("propose_change", {"fact_id": "f-amount", "new_value": "14,000", "proposed_by": "worker", "said": "14 kar do"})
    change = proposed.effects[0]
    assert isinstance(change, FactChanged) and change.status is ChangeStatus.PROPOSED and "13,000 rupees, labour only" in proposed.output
    yes = {"change_id": change.change_id, "agrees": True, "said": "haan"}
    assert "no line from Sunita" in (await t.run("confirm_change", {**yes, "person": "hirer"})).output
    lines.append(TranscriptLine(deal_id="d1", speaker=Role.HIRER, text="haan", start=2, end=3, line_no=6))
    one = (await t.run("confirm_change", {**yes, "person": "hirer"})).effects[0]
    assert one.status is ChangeStatus.CONFIRMED_ONE and one.confirmed_by == [Role.HIRER]
    lines.append(TranscriptLine(deal_id="d1", speaker=Role.WORKER, text="haan ji", start=4, end=5, line_no=7))
    both = await t.run("confirm_change", {**yes, "person": "worker"})
    assert both.effects[0].status is ChangeStatus.CONFIRMED_BOTH and both.effects[0].confirmed_by == [Role.HIRER, Role.WORKER]
    assert (await t.run("confirm_change", {**yes, "person": "worker"})).output.startswith("There is no open change")


async def test_a_no_withdraws_the_change():
    lines = [TranscriptLine(deal_id="d1", speaker=Role.HIRER, text="nahi", start=0, end=1, line_no=9)]
    t = tools(lines=lines)
    lines.clear()
    proposed = await t.run("propose_change", {"fact_id": "f-amount", "new_value": "14,000", "proposed_by": "worker"})
    lines.append(TranscriptLine(deal_id="d1", speaker=Role.HIRER, text="nahi, 13 hi", start=0, end=1, line_no=10))
    no = await t.run("confirm_change", {"change_id": proposed.effects[0].change_id, "person": "hirer", "agrees": False, "said": "nahi"})
    assert no.effects[0].status is ChangeStatus.WITHDRAWN and "stays \"13,000 rupees, labour only\"" in no.output


async def test_a_bad_tool_call_is_answered_not_raised():
    assert (await tools().run("get_term", {"item": "price"})).output.startswith("No such tool call")
    assert (await tools().run("delete_everything", {})).output.startswith("No such tool call")


def test_what_counts_as_speaking_to_gawah():
    for text in ["Gawah ji, advance kitna tha?", "गवाह जी, बताइए", "Haan gawaah, sahi hai?", "gavah, sun rahe ho", "Gawahji?"]:
        assert addresses_gawah(text), text
    for text in ["Gawaahi nahi chahiye", "Lagwa denge", "Haan theek hai", "गवाही दो", "gawahi dena"]:
        assert not addresses_gawah(text), text
