"""The Sentinel on fakes: records checked against the deal (FakeMemory), reminders on a fake
clock, and second calls. Both phones are simulated."""

from datetime import date

import pytest
from whatsapp_world import BASE, RAMESH, SCREENSHOT, SUNITA, World

from app.config import Settings
from app.contracts import (
    CallEnded, CallOpened, Fact, FactKind, FactRecorded, FactSource, FactStatus, ItemKey, RecordConfirmed, Role,
    call_path, callback_path, clip_path,
)
from app.records import tuning
from app.records.reader import Reading
from app.store import Store
from fakes.memory import FakeMemory, silent_wav, two_amounts_facts

PAID_ADVANCE = "Advance ₹3,000 mil gaya. Baaki ₹10,000 kaam ke baad."


def deal_facts(deal_id: str) -> list[Fact]:
    """The practice call's terms (13,000 in all, 3,000 advance), nothing paid yet, and the
    balance due once the work is done."""
    balance = Fact(
        id="f-balance", deal_id=deal_id, text="The balance is paid after the work is done.", item=ItemKey.BALANCE,
        kind=FactKind.TERM, value="remaining payment after completion", said_by=Role.WORKER,
        agreed_by=[Role.HIRER], status=FactStatus.AGREED, quote="Baaki kaam ke baad.", call_no=1, line_no=18,
    )
    return [*[f for f in two_amounts_facts(deal_id) if f.id != "f-paid"], balance]


@pytest.fixture
async def watched(bus, tmp_path):
    settings = Settings(
        _env_file=None, database_path=str(tmp_path / "test.db"), public_base_url=BASE, reply_timeout_seconds=120,
    )
    store = Store(settings.database_path)
    await store.open()
    world = World(bus, store, settings, memory=FakeMemory([], clips={"f-advance": silent_wav()}))
    world.reader.readings.update({
        world.reader.IMAGE: Reading(kind="advance", amount=3000, transaction_id="T3000", payment_screenshot=True),
        "5000 advance diya": Reading(kind="advance", amount=5000),
        "3000 advance diya": Reading(kind="advance", amount=3000),
        "20000 de diya": Reading(kind="payment", amount=20000),
    })
    yield world
    await world.bot.stop()
    await bus.drain()
    await store.close()


async def deal(world: World) -> str:
    deal_id = await world.start_deal()
    world.memory.facts.extend(deal_facts(deal_id))
    return deal_id


def notes(world: World) -> list[str]:
    return [e.text for e in world.named("agent.note") if e.agent == "sentinel"]


async def test_a_payment_screenshot_tells_both_what_is_still_owed(watched):
    await deal(watched)
    await watched.say(SUNITA, "", media=SCREENSHOT)
    assert watched.texts_to(SUNITA)[-2:] == ["Record mein likh liya: ₹3,000 advance, transaction id T3000.", PAID_ADVANCE]
    assert watched.texts_to(RAMESH)[-1] == PAID_ADVANCE
    assert notes(watched) == ["advance of ₹3,000 stands: ₹10,000 still owed"]


async def test_a_cash_advance_is_said_back_once_the_other_person_says_yes(watched):
    await deal(watched)
    await watched.say(SUNITA, "3000 advance diya", name="Sunita")
    assert PAID_ADVANCE not in watched.texts_to(SUNITA)  # one person's word: not yet
    await watched.say(RAMESH, "haan", name="Ramesh")
    assert watched.texts_to(SUNITA)[-1] == watched.texts_to(RAMESH)[-1] == PAID_ADVANCE


async def test_a_larger_advance_than_agreed_gets_what_was_agreed_and_the_clip_then_the_question(watched):
    deal_id = await deal(watched)
    await watched.say(SUNITA, "5000 advance diya", name="Sunita")
    agreed = f"Deal mein advance ₹3,000 tay hua tha (21 Nov ki call mein). Wo pal yahan suniye: {BASE}{clip_path('f-advance')}"
    assert watched.texts_to(RAMESH)[-2:] == [
        agreed, 'Sunita ji ne likha hai: "5000 advance diya". Kya yeh sahi hai? Haan ya nahi likhiye.',
    ]
    assert watched.texts_to(SUNITA)[-2:] == [agreed, "Likh liya. Kaam karne wale se confirm kar raha hoon."]
    [asked] = watched.named("record.confirm_requested")
    assert asked.deal_id == deal_id and asked.confirm_by is Role.WORKER
    [note] = [e for e in watched.named("agent.note") if e.agent == "sentinel"]
    assert note.fact_ids == ["f-advance"] and "worker asked to confirm" in note.text

    await watched.say(RAMESH, "nahi")
    assert watched.texts_to(SUNITA)[-1].startswith("Kaam karne wale ne nahi kaha")
    assert not any("mil gaya" in t for t in watched.texts_to(SUNITA) + watched.texts_to(RAMESH))


async def test_the_same_advance_twice_is_more_than_is_owed(watched):
    await deal(watched)
    await watched.say(SUNITA, "", media=SCREENSHOT)
    watched.memory.facts.append(paid(watched, 3000, "f-advance"))  # memory now counts the screenshot
    await watched.say(SUNITA, "3000 advance diya")
    assert watched.texts_to(RAMESH)[-2].startswith(
        "Deal mein advance ₹3,000 tay hua tha (21 Nov ki call mein). ₹3,000 pehle se record mein hai."
    )


async def test_a_payment_larger_than_what_is_owed_gets_the_whole_deal(watched):
    await deal(watched)
    await watched.say(SUNITA, "20000 de diya")
    assert watched.texts_to(RAMESH)[-2] == "Deal mein kul paisa ₹13,000 tay hua tha (21 Nov ki call mein)."
    await watched.say(RAMESH, "haan")
    assert watched.texts_to(SUNITA)[-1] == "₹20,000 mil gaya. Deal se ₹7,000 zyada record mein hai."


async def test_work_confirmed_done_with_money_owed_reminds_the_hirer_once_after_the_delay(watched):
    await deal(watched)
    await watched.say(RAMESH, "kaam poora ho gaya")
    await watched.say(SUNITA, "haan", name="Sunita")
    done = "Kaam poora ho gaya, dono ne confirm kiya. Deal ke hisaab se baaki ₹13,000."
    assert watched.texts_to(SUNITA)[-1] == watched.texts_to(RAMESH)[-1] == done

    await watched.clock.advance(tuning.BALANCE_REMINDER_SECONDS - 1)
    await watched.settle()
    assert watched.texts_to(SUNITA)[-1] == done
    await watched.clock.advance(1)
    await watched.settle()
    assert watched.texts_to(SUNITA)[-1] == (
        "Yaad dila raha hoon: kaam poora ho chuka hai, dono ne confirm kiya tha. Deal ke hisaab se ₹13,000 baaki hai."
    )
    assert watched.texts_to(RAMESH)[-1] == "Gawah ne Kaam dene wale ko ₹13,000 baaki ki yaad dila di hai."

    # The work is confirmed again (say, on a call-back): no second reminder for the balance.
    sent = len(watched.texts_to(SUNITA))
    [confirmed] = watched.named("record.confirmed")
    watched.bus.publish(confirmed.model_copy(update={"event_id": "again"}))
    await watched.clock.advance(tuning.BALANCE_REMINDER_SECONDS * 2)
    await watched.settle()
    assert len(watched.texts_to(SUNITA)) == sent + 1  # the "kaam poora" line again, no reminder


async def test_no_reminder_when_the_money_is_paid_before_it_is_due(watched):
    await deal(watched)
    await watched.say(RAMESH, "kaam poora ho gaya")
    await watched.say(SUNITA, "haan")
    watched.memory.facts.append(paid(watched, 13000, "f-amount"))
    await watched.clock.advance(tuning.BALANCE_REMINDER_SECONDS)
    await watched.settle()
    assert not any(t.startswith("Yaad dila") for t in watched.texts_to(SUNITA))
    assert notes(watched)[-1] == "balance reminder due, nothing owed: not sent"


async def test_a_waiting_reminder_survives_a_restart(watched):
    await deal(watched)
    await watched.say(RAMESH, "kaam poora ho gaya")
    await watched.say(SUNITA, "haan")
    await watched.clock.advance(30)
    await watched.bot.stop()  # the server stops half way through the wait

    watched.bot = watched.wire()
    watched.bot.sentinel.reminders.load()
    await watched.clock.advance(30)
    await watched.settle()
    assert watched.texts_to(SUNITA)[-1].startswith("Yaad dila raha hoon: kaam poora")

    watched.bot = watched.wire()  # and after another restart it is not sent again
    watched.bot.sentinel.reminders.load()
    await watched.clock.advance(1000)
    await watched.settle()
    assert sum(t.startswith("Yaad dila") for t in watched.texts_to(SUNITA)) == 1


async def test_a_date_the_deal_names_passing_with_money_owed_reminds_the_hirer(watched):
    deal_id = await deal(watched)
    advance = next(f for f in watched.memory.facts if f.id == "f-advance")
    assert advance.value_date == date(2026, 11, 22)  # "kal subah": the day after the call
    watched.bus.publish(FactRecorded(deal_id=deal_id, fact=advance))
    await watched.settle()
    # The 22nd is over at midnight in India; the reminder goes 9 hours later: 23 hours from 10 am.
    await watched.clock.advance(23 * 3600 - 1)
    await watched.settle()
    assert not any(t.startswith("Yaad dila") for t in watched.texts_to(SUNITA))
    await watched.clock.advance(1)
    await watched.settle()
    assert watched.texts_to(SUNITA)[-1] == "Yaad dila raha hoon: deal mein advance 22 Nov tak dena tay hua tha. Abhi ₹3,000 baaki hai."
    assert watched.texts_to(RAMESH)[-1] == "Gawah ne Kaam dene wale ko ₹3,000 baaki ki yaad dila di hai."


async def test_a_second_call_opened_by_one_person_is_told_to_the_other_with_their_link(watched):
    deal_id = await deal(watched)
    opened = CallOpened(deal_id=deal_id, call_no=2, opened_by=Role.WORKER, room=f"deal-{deal_id}-2")
    watched.bus.publish(opened)
    watched.bus.publish(opened.model_copy(update={"event_id": "again"}))
    await watched.settle()
    assert watched.texts_to(SUNITA)[-1] == (
        f"Kaam karne wale aapse deal par phir se baat karna chahte hain. Call ke liye yeh link kholiye: "
        f"{BASE}{call_path(deal_id, Role.HIRER)}"
    )
    assert len(watched.texts_to(RAMESH)) == 1 and len(watched.texts_to(SUNITA)) == 2  # once, and not to him


async def test_after_a_second_call_the_call_back_only_for_a_term_it_changed(watched):
    deal_id = await deal(watched)
    before = {p: len(watched.texts_to(p)) for p in (SUNITA, RAMESH)}
    watched.bus.publish(CallEnded(deal_id=deal_id, call_no=2))
    await watched.settle()
    assert {p: len(watched.texts_to(p)) for p in (SUNITA, RAMESH)} == before
    assert notes(watched)[-1] == "call 2: no term changed, no call-back links"

    # Call 3 settles the balance date, and only the worker has confirmed it so far.
    watched.memory.facts.append(Fact(
        deal_id=deal_id, text="The balance is paid on 30 November.", item=ItemKey.BALANCE, kind=FactKind.TERM,
        value="30 November", value_date=date(2026, 11, 30), said_by=Role.HIRER, agreed_by=[Role.WORKER],
        confirmed_by=[Role.WORKER], status=FactStatus.CONFIRMED, source=FactSource.CALL, call_no=3, line_no=4,
    ))
    watched.bus.publish(CallEnded(deal_id=deal_id, call_no=3))
    await watched.settle()
    assert callback_path(deal_id, Role.HIRER) in watched.texts_to(SUNITA)[-1]
    assert len(watched.texts_to(RAMESH)) == before[RAMESH]
    assert notes(watched)[-1] == "call 3 changed balance: call-back links sent"


def paid(world: World, rupees: int, towards: str) -> Fact:
    deal_id = world.named("deal.requested")[-1].deal_id
    return Fact(
        deal_id=deal_id, text=f"Paid {rupees}.", item=ItemKey.ADVANCE, kind=FactKind.PAYMENT, value_rupees=rupees,
        said_by=Role.HIRER, status=FactStatus.CONFIRMED, source=FactSource.TEXT, counts_towards=towards,
    )
