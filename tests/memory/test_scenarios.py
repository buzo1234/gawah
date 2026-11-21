"""Scenarios 1 to 7 of the fact layer (.plans/gawah-crew.md), on fakes: the Scribe's model is
scripted, embeddings are word hashes, recordings are tones."""

import io
import wave
from datetime import timedelta

from app.contracts import (
    Backing, ChangeStatus, FactChanged, FactKind, FactSource, FactStatus, ItemKey, MemoryQueries, Record,
    RecordConfirmed, RecordKind, RecordReceived, Role, TermsConfirmed,
)
from app.memory.chain import first_break
from tests.memory.world import DAY1, DEAL, World, claim

H, W = Role.HIRER, Role.WORKER


def wav_seconds(data: bytes) -> float:
    with wave.open(io.BytesIO(data)) as wav:
        assert (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) == (24000, 1, 2)
        return wav.getnframes() / 24000


AMOUNT_CALL = [
    (W, "Pura kaam 25 hazaar ka hoga madam."),
    (H, "25 bahut zyada hai, 20 mein karo."),
    (W, "22 hazaar last, isse kam nahi."),
    (H, "Theek hai, 22 hazaar pakka."),
]
AMOUNT_SCRIPT = {
    AMOUNT_CALL[0][1]: [claim("amount", "offer", 25000, "Pura kaam 25 hazaar ka hoga")],
    AMOUNT_CALL[1][1]: [claim("amount", "offer", 20000, "20 mein karo")],
    AMOUNT_CALL[2][1]: [claim("amount", "offer", 22000, "22 hazaar last")],
    AMOUNT_CALL[3][1]: [claim("amount", "accept", 22000, "Theek hai, 22 hazaar pakka", accepts_line=3)],
}


async def test_scenario_1_the_agreed_advance_with_who_said_it_and_the_clip(bus, tmp_path):
    lines = [
        (H, "Advance kitna loge?"),
        (W, "5 hazaar pehle de dijiye."),
        (H, "Nahi, 3 hazaar dungi, kal subah."),
        (W, "Theek hai."),
        (H, "Gawah, advance kitna tay hua tha?"),
    ]
    world = World(bus, tmp_path, {
        lines[1][1]: [claim("advance", "offer", 5000, "5 hazaar pehle de dijiye")],
        lines[2][1]: [claim("advance", "offer", 3000, "3 hazaar dungi, kal subah", date="2026-11-22")],
    })
    memory: MemoryQueries = world.memory
    assert isinstance(memory, MemoryQueries)
    await world.call(lines)
    assert "Theek hai." not in world.extractor.asked  # a plain yes is read in code, not by the model

    term = await memory.get_term(DEAL, ItemKey.ADVANCE)
    current = term.current
    assert (current.value_rupees, current.status, current.said_by, current.agreed_by) == (3000, FactStatus.AGREED, H, [W])
    assert current.quote == "3 hazaar dungi, kal subah" and current.line_no == 3
    assert str(current.value_date) == "2026-11-22"
    assert (current.start, current.end) == (9.0, 16.0)  # the offer and its "theek hai", in one clip
    assert [(f.value_rupees, f.status) for f in term.history] == [
        (5000, FactStatus.SAID), (3000, FactStatus.SAID), (3000, FactStatus.AGREED),
    ]
    assert 7.5 < wav_seconds(await memory.clip(current.id)) < 7.7

    found = await memory.search(DEAL, "advance kitna tay hua tha")
    assert found[0].id == current.id  # agreed ranks above the 5,000 that was turned down


async def test_scenario_2_aapne_25_bola_tha_on_a_second_call(bus, tmp_path):
    later = "Madam, aapne 25 hazaar bola tha."
    world = World(bus, tmp_path, AMOUNT_SCRIPT | {later: [claim("amount", "recall", 25000, "aapne 25 hazaar bola tha")]})
    await world.call(AMOUNT_CALL)
    agreed = world.fact_from_line(1, 3)
    assert world.conflicts == []  # bargaining is not a contradiction

    await world.call([(W, later)], call_no=2, at=DAY1 + timedelta(days=4))

    [conflict] = world.conflicts
    assert conflict.fact_ids == [agreed.id]
    assert (conflict.speaker, conflict.call_no, conflict.line_no, conflict.said) == (W, 2, 1, later)
    assert conflict.explanation == (
        "Says 25,000 rupees; the amount was agreed at 22,000 rupees by both on 21 November (call 1, line 3). "
        "25,000 rupees was Ramesh's offer on call 1."
    )

    term = await world.memory.get_term(DEAL, ItemKey.AMOUNT)
    assert term.current.id == agreed.id
    assert (term.current.value_rupees, term.current.said_by, term.current.agreed_by) == (22000, W, [H])
    assert term.current.valid_from == DAY1 + timedelta(seconds=9)
    offers = [(f.value_rupees, f.said_by, f.call_no, f.status) for f in term.history if f.status == FactStatus.SAID]
    assert offers == [(25000, W, 1, FactStatus.SAID), (20000, H, 1, FactStatus.SAID), (22000, W, 1, FactStatus.SAID),
                      (25000, W, 2, FactStatus.SAID)]
    assert await world.memory.clip(agreed.id) is not None


async def test_scenario_3_an_amendment_replaces_the_term_and_keeps_its_history(bus, tmp_path):
    extra = "Balcony ke 2,000 extra lagenge."
    world = World(bus, tmp_path, AMOUNT_SCRIPT | {
        extra: [claim("amount", "offer", 2000, "Balcony ke 2,000 extra", kind="change")],
    })
    await world.call(AMOUNT_CALL)
    old = world.fact_from_line(1, 3)
    await world.send(TermsConfirmed(deal_id=DEAL, person=H, item=ItemKey.AMOUNT),
                     TermsConfirmed(deal_id=DEAL, person=W, item=ItemKey.AMOUNT))
    assert (await world.memory.get_term(DEAL, ItemKey.AMOUNT)).current.confirmed_by == [H, W]

    await world.call([(W, extra)], call_no=2, at=DAY1 + timedelta(days=2))
    for status, by in ((ChangeStatus.PROPOSED, []), (ChangeStatus.CONFIRMED_ONE, [H]), (ChangeStatus.CONFIRMED_BOTH, [H, W])):
        await world.send(FactChanged(
            deal_id=DEAL, change_id="c1", fact_id=old.id, new_value="24,000 rupees, with the balcony",
            status=status, item=ItemKey.AMOUNT, proposed_by=W, confirmed_by=by, said="Haan, 24 hazaar balcony ke saath.",
        ))
    assert world.conflicts == []  # a proposed change is not a contradiction

    term = await world.memory.get_term(DEAL, ItemKey.AMOUNT)
    new = term.current
    assert (new.value_rupees, new.status, new.replaces, new.confirmed_by) == (24000, FactStatus.CONFIRMED, old.id, [H, W])
    replaced = world.memory.book.fact(old.id)
    assert replaced.status == FactStatus.SUPERSEDED and replaced.superseded_at is not None
    assert [f.kind for f in term.history].count(FactKind.CHANGE) == 1
    assert [f.status for f in term.history if f.id == old.id][-2:] == [FactStatus.CONFIRMED, FactStatus.SUPERSEDED]

    versions = world.memory.book.deal(DEAL).versions
    assert versions == world.versions and first_break(versions) is None
    tampered = list(versions)
    tampered[2] = tampered[2].model_copy(update={"value_rupees": 2000})
    assert first_break(tampered) == 2


async def test_scenario_4_a_payment_counts_towards_its_term_and_owed_is_arithmetic(bus, tmp_path):
    lines = [
        (W, "13 hazaar lagega, sirf labour."), (H, "Theek hai."),
        (W, "Advance 3 hazaar chahiye."), (H, "Haan ji."),
    ]
    world = World(bus, tmp_path, {
        lines[0][1]: [claim("amount", "offer", 13000, "13 hazaar lagega, sirf labour")],
        lines[2][1]: [claim("advance", "offer", 3000, "Advance 3 hazaar chahiye")],
        "Aaj 5 hazaar aur diye.": [claim("balance", "state", 5000, "Aaj 5 hazaar aur diye", kind="payment")],
    })
    await world.call(lines)
    advance = world.fact_from_line(1, 3)
    record = Record(id="r1", sender=H, kind=RecordKind.ADVANCE, amount=3000.0, text="3000 cash diya")
    await world.send(RecordReceived(deal_id=DEAL, record=record, ts=DAY1 + timedelta(days=1)))
    paid = world.memory.book.deal(DEAL).by_record("r1")
    assert (paid.kind, paid.status, paid.counts_towards, paid.value_rupees) == (FactKind.PAYMENT, FactStatus.SAID, advance.id, 3000)
    await world.send(RecordConfirmed(deal_id=DEAL, record_id="r1", confirmed_by=W))
    assert world.memory.book.fact(paid.id).status == FactStatus.CONFIRMED

    rows = {r.item: r for r in await world.memory.owed(DEAL)}
    assert [(r.agreed_rupees, r.paid_rupees, r.owed_rupees) for r in rows.values()] == [
        (13000, 3000, 10000), (3000, 3000, 0), (10000, 0, 10000),
    ]

    await world.call([(H, "Aaj 5 hazaar aur diye.")], call_no=2, at=DAY1 + timedelta(days=3))
    denied = Record(id="r2", sender=H, kind=RecordKind.PAYMENT, amount=2000.0, text="2000 aur diye")
    await world.send(RecordReceived(deal_id=DEAL, record=denied), RecordConfirmed(deal_id=DEAL, record_id="r2", confirmed_by=W, confirmed=False))
    rows = {r.item: r for r in await world.memory.owed(DEAL)}
    assert [(r.agreed_rupees, r.paid_rupees, r.owed_rupees) for r in rows.values()] == [
        (13000, 8000, 5000), (3000, 3000, 0), (10000, 5000, 5000),
    ]
    assert len(rows[ItemKey.BALANCE].payment_fact_ids) == 1  # the denied 2,000 is not counted


async def test_scenario_5_open_recall_of_details_that_are_not_terms(bus, tmp_path):
    lines = [
        (H, "Paint main khud le aaungi, mere bhai ki dukaan hai."),
        (W, "Asian Paints ka Tractor Emulsion lena, white colour."),
        (H, "Bhai ki dukaan se paint sasta milta hai."),
        (W, "Walls pe do coat lagenge."),
    ]
    world = World(bus, tmp_path, {
        lines[0][1]: [claim("work", "state", None, "Paint main khud le aaungi", text="The hirer will buy the paint herself.", value="hirer buys the paint")],
        lines[1][1]: [claim(None, "state", None, "Asian Paints ka Tractor Emulsion lena, white colour", kind="other",
                            text="The paint is Asian Paints Tractor Emulsion, white.", value="Asian Paints Tractor Emulsion, white")],
        lines[3][1]: [claim("work", "state", None, "Walls pe do coat lagenge", text="Two coats on the walls.", value="two coats on walls")],
    })
    await world.call(lines)

    found = await world.memory.search(DEAL, "Paint ke baare mein kya baat hui thi?", k=3)
    assert {f.line_no for f in found} == {1, 2, 3}
    line = next(f for f in found if f.line_no == 3)  # no fact covers it: the line comes back as a said fact
    assert (line.quote, line.said_by, line.call_no, line.status) == (lines[2][1], H, 1, FactStatus.SAID)
    assert all(f.quote and f.said_by and f.valid_from for f in found)
    assert await world.memory.clip(line.id) is not None
    assert await world.memory.search("another-deal", "paint") == []


async def test_scenario_6_a_screenshot_record_is_evidence_for_its_term(bus, tmp_path):
    world = World(bus, tmp_path, {"Kaam 13 hazaar ka.": [claim("amount", "offer", 13000, "Kaam 13 hazaar ka")]})
    await world.call([(W, "Kaam 13 hazaar ka."), (H, "Theek hai.")])
    amount = world.fact_from_line(1, 1)
    shot = Record(id="r-shot", sender=H, kind=RecordKind.PAYMENT, backing=Backing.BACKED, amount=5000.0,
                  media_url="https://example.invalid/shot.jpg", transaction_id="UPI123")
    await world.send(RecordReceived(deal_id=DEAL, record=shot))

    fact = world.memory.book.deal(DEAL).by_record("r-shot")
    assert (fact.status, fact.source, fact.media_url, fact.counts_towards) == (
        FactStatus.CONFIRMED, FactSource.SCREENSHOT, shot.media_url, amount.id,
    )
    assert (await world.memory.search(DEAL, "Maine screenshot bheja tha na?"))[0].id == fact.id
    assert (await world.memory.owed(DEAL))[0].paid_rupees == 5000


async def test_scenario_7_work_done_days_ago_and_the_balance_still_owed(bus, tmp_path):
    lines = [
        (W, "Do kamre paint karne hain."), (H, "Haan ji."),
        (W, "12 hazaar total."), (H, "Theek hai."),
        (W, "2 hazaar advance."), (H, "Theek hai."),
        (H, "Baaki kaam khatam hone ke din dungi."), (W, "Theek hai madam."),
    ]
    world = World(bus, tmp_path, {
        lines[0][1]: [claim("work", "offer", None, "Do kamre paint karne hain", value="paint two rooms")],
        lines[2][1]: [claim("amount", "offer", 12000, "12 hazaar total")],
        lines[4][1]: [claim("advance", "offer", 2000, "2 hazaar advance")],
        lines[6][1]: [claim("balance", "offer", None, "Baaki kaam khatam hone ke din dungi", value="on the day the work is finished")],
    })
    await world.call(lines)
    work = world.fact_from_line(1, 1)
    done_at = DAY1 + timedelta(days=4)
    record = Record(id="r-done", sender=W, kind=RecordKind.WORK_DONE, text="Kaam poora ho gaya madam")
    await world.send(RecordReceived(deal_id=DEAL, record=record, ts=done_at),
                     RecordConfirmed(deal_id=DEAL, record_id="r-done", confirmed_by=H))

    done = world.memory.book.deal(DEAL).by_record("r-done")
    assert (done.kind, done.status, done.counts_towards, done.valid_from) == (FactKind.WORK, FactStatus.CONFIRMED, work.id, done_at)
    balance = (await world.memory.get_term(DEAL, ItemKey.BALANCE)).current
    assert balance.value == "on the day the work is finished" and balance.status == FactStatus.AGREED
    rows = {r.item: r for r in await world.memory.owed(DEAL)}
    assert (rows[ItemKey.BALANCE].owed_rupees, rows[ItemKey.BALANCE].payment_fact_ids) == (10000, [])


async def test_a_filler_theek_hai_agrees_to_nothing_and_no_advance_is_settled(bus, tmp_path):
    lines = [
        (H, "Kaam kab se shuru karoge?"), (W, "Theek hai."),
        (W, "Advance nahi chahiye madam, kaam ke baad sab dena."), (H, "Theek hai."),
    ]
    world = World(bus, tmp_path, {
        lines[2][1]: [claim("advance", "state", 0, "Advance nahi chahiye madam", value="no advance")],
    })
    await world.call(lines)
    advance = (await world.memory.get_term(DEAL, ItemKey.ADVANCE)).current
    assert (advance.value_rupees, advance.status, advance.agreed_by) == (0, FactStatus.AGREED, [H])
    assert [f.line_no for f in world.versions] == [3, 3]  # the first "theek hai" followed a question


async def test_a_contradiction_code_cannot_compare_goes_to_one_short_check(bus, tmp_path):
    lines = [(H, "Material aap laoge."), (W, "Haan ji.")]
    later = [(W, "Material to aap laogi na madam?"), (W, "Paint aapka, putty main lunga.")]
    world = World(bus, tmp_path, {
        lines[0][1]: [claim("work", "state", None, "Material aap laoge", value="worker brings the material")],
        later[0][1]: [claim("work", "recall", None, "Material to aap laogi na", value="hirer brings the material", contradicts="work@1.1")],
        later[1][1]: [claim("work", "state", None, "putty main lunga", value="worker brings putty", contradicts="work@1.1")],
    })
    world.extractor.checks = {
        "Material to aap laogi na": {"contradicts": True, "reason": "Agreed: the worker brings the material; now says the hirer does."},
        "putty main lunga": {"contradicts": False, "reason": "Putty is part of the material the worker brings."},
    }
    await world.call(lines)
    await world.call(later, call_no=2, at=DAY1 + timedelta(days=1))
    [conflict] = world.conflicts
    assert (conflict.line_no, conflict.call_no, conflict.confidence) == (1, 2, 0.7)
    assert conflict.explanation.startswith("Agreed: the worker brings the material")
    assert conflict.fact_ids == [world.fact_from_line(1, 1).id]


async def test_asking_what_was_agreed_puts_the_agreed_figure_above_a_restated_one(bus, tmp_path):
    lines = [(W, "13 hazaar lagega."), (H, "Theek hai."), (W, "To total 14 hazaar.")]
    world = World(bus, tmp_path, {lines[0][1]: [claim("amount", "offer", 13000, "13 hazaar lagega")]})
    await world.call(lines)
    assert [c.line_no for c in world.conflicts] == [3]  # caught in code: no model reply for that line
    found = await world.memory.search(DEAL, "Gawah, total kitna tay hua tha?", k=2)
    assert [(f.value_rupees, f.status) for f in found] == [(13000, FactStatus.AGREED), (14000, FactStatus.SAID)]
