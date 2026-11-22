"""A claim the other person says no to, on fakes: the practice call (13,000 in all, 3,000
advance, the balance once the work is done) replayed into the real memory from its saved
replies, then WhatsApp messages through the bot from two simulated phones."""

import wave
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from meta_world import MetaWorld, meta_settings
from whatsapp_world import BASE, RAMESH, SCREENSHOT, SUNITA, World

from app.config import Settings
from app.contracts import Fact, FactKind, FactSource, FactStatus, ItemKey, Role, clip_path
from app.memory import Memory
from app.memory.extract import RecordedExtractor, Routed
from app.memory.vectors import WordHashEmbedder
from app.records import tuning, words
from app.records.dispute import IST
from app.records.reader import Reading
from app.store import Store
from fakes.memory import FakeMemory, two_amounts_facts
from fakes.replayer import replay

CASH = "2000 cash diya"
PROMISE = "Baaki ke 2000 kal GPay kar dungi."


def silent_calls(root: Path, deal_id: str, calls=(1, 2), seconds: int = 150) -> None:
    for call_no in calls:
        for role in ("hirer", "worker"):
            path = root / "recordings" / deal_id / str(call_no) / f"{role}.wav"
            path.parent.mkdir(parents=True, exist_ok=True)
            with wave.open(str(path), "wb") as out:
                out.setnchannels(1)
                out.setsampwidth(2)
                out.setframerate(8000)
                out.writeframes(bytes(seconds * 8000 * 2))


async def settled(world: World) -> None:
    for _ in range(4):
        await world.settle()
        await world.memory.settle()
    await world.settle()


@pytest.fixture
async def world(bus, tmp_path):
    settings = Settings(
        _env_file=None, database_path=str(tmp_path / "test.db"), public_base_url=BASE, reply_timeout_seconds=120,
    )
    store = Store(settings.database_path)
    await store.open()
    memory = Memory(bus, Routed(None, RecordedExtractor()), WordHashEmbedder(), root=tmp_path, embed_model="hash")
    memory.attach(bus)
    world = World(bus, store, settings, memory=memory)
    world.reader.readings[CASH] = Reading(kind="payment", amount=2000)
    yield world
    await world.bot.stop()
    await bus.drain()
    await store.close()


async def after_the_call(world: World) -> str:
    deal_id = await world.start_deal()
    await replay(world.bus, "fixtures/call_two_amounts.json", speed=0, deal_id=deal_id)
    silent_calls(world.root, deal_id)
    await settled(world)
    return deal_id


def screenshot(world: World, rupees: int, transaction_id: str | None, kind: str = "payment") -> None:
    world.reader.readings[world.reader.IMAGE] = Reading(
        kind=kind, amount=rupees, transaction_id=transaction_id, payment_screenshot=True,
    )


def today() -> str:
    return words.day(datetime.now(IST).date())


async def with_a_promise_and_an_advance(world: World) -> str:
    """After the call: Sunita promised 2,000 of the balance on a second call, and paid the 3,000
    advance with a screenshot. Then she says she paid 2,000 cash, and Ramesh says no."""
    deal_id = await after_the_call(world)
    world.memory.record(Fact(
        deal_id=deal_id, text="Sunita says she will pay 2,000 of the balance by GPay tomorrow.", item=ItemKey.BALANCE,
        kind=FactKind.OTHER, said_by=Role.HIRER, status=FactStatus.SAID, source=FactSource.CALL, quote=PROMISE,
        call_no=2, line_no=3, start=10.0, end=13.0, valid_from=datetime.now(UTC) + timedelta(minutes=5),
    ))
    screenshot(world, 3000, "T3000", "advance")
    await world.say(SUNITA, "", media=SCREENSHOT)
    await world.say(SUNITA, CASH)
    await settled(world)
    await world.say(RAMESH, "nahi")
    await settled(world)
    return deal_id


def notes(world: World) -> list[str]:
    return [e.text for e in world.named("agent.note") if e.agent == "sentinel"]


def claim_fact(world: World, deal_id: str) -> Fact:
    return next(f for f in world.memory.book.deal(deal_id).standing() if f.kind is FactKind.PAYMENT and f.value_rupees == 2000)


async def owed(world: World, deal_id: str) -> dict[ItemKey, int | None]:
    return {r.item: r.owed_rupees for r in await world.memory.owed(deal_id)}


DENIED = ("Ramesh ji ne mana kiya. Yeh ₹2,000 hisaab mein nahi juda. Record ke hisaab se ab tak ₹3,000 mila hai "
          "(advance, {day}, screenshot se pakka). Baaki ₹10,000 kaam ke baad.")
PROOF_ASK = "₹2,000 ke payment ka screenshot ya UPI reference bhejiye. Milne par Ramesh ji se ek baar phir poochunga."


async def test_a_cash_claim_denied_tells_both_the_numbers_quotes_the_record_and_asks_once_for_proof(world):
    deal_id = await with_a_promise_and_an_advance(world)
    denied = DENIED.format(day=today())
    memory = world.memory.book.deal(deal_id)
    promise = next(f for f in memory.standing() if f.quote == PROMISE)
    balance, amount = memory.current(ItemKey.BALANCE), memory.current(ItemKey.AMOUNT)
    quoted = (
        "Is payment ke baare mein record mein yeh hai:\n"
        f'1. 23 Nov ki call mein: Sunita ji ne vaada kiya tha: "Baaki ke 2000 kal GPay kar dungi". '
        f"Suniye: {BASE}{clip_path(promise.id)}\n"
        f"2. {today()} ki call mein: baaki paisa tay hua tha. Sunita ji ne kaha: \"Baaki kaam poora hone ke baad, jis din "
        "finish karoge usi din. Pehle main kaam dekhungi, phir payment\", Ramesh ji ne maana. "
        f"Suniye: {BASE}{clip_path(balance.id)}\n"
        f"3. {today()} ki call mein: kul paisa ₹13,000 tay hua tha. Ramesh ji ne kaha: \"12 mein nahi padta madam... "
        f"13 hazaar, last. Isse neeche nahi\", Sunita ji ne maana. Suniye: {BASE}{clip_path(amount.id)}"
    ).replace("23 Nov", words.day(promise.valid_from.astimezone(IST).date()))
    assert world.texts_to(RAMESH)[-2:] == [denied, quoted]
    assert world.texts_to(SUNITA)[-3:] == [denied, quoted, PROOF_ASK]
    assert claim_fact(world, deal_id).status is FactStatus.DISPUTED
    assert await owed(world, deal_id) == {ItemKey.AMOUNT: 10000, ItemKey.ADVANCE: 0, ItemKey.BALANCE: 10000}
    assert notes(world)[-4:] == [
        "claim from the hirer: ₹2,000 payment, one person's word: the worker is asked to confirm",
        "the worker said no to the hirer's ₹2,000 payment claim: not counted, ₹10,000 owed",
        "quoted the record to both: a promise, the agreed balance, the agreed amount",
        "asked the hirer once for proof of the hirer's ₹2,000 payment claim",
    ]
    [quote_note] = [e for e in world.named("agent.note") if e.text.startswith("quoted the record")]
    assert quote_note.fact_ids == [promise.id, balance.id, amount.id]


async def test_a_matching_screenshot_backs_it_puts_it_again_with_the_image_and_a_yes_counts_it(world):
    deal_id = await with_a_promise_and_an_advance(world)
    screenshot(world, 2000, "T2000")
    await world.say(SUNITA, "", media=SCREENSHOT)
    await settled(world)
    assert world.texts_to(RAMESH)[-2:] == [
        f"Sunita ji ka bheja hua screenshot yahan dekhiye: {SCREENSHOT}",  # no S3 here: the link as it came
        'Sunita ji ne ₹2,000 ke payment ka screenshot bheja (transaction id T2000). Kya yeh payment aapko mila? '
        "Haan ya nahi likhiye.",
    ]
    assert world.texts_to(SUNITA)[-1] == "Proof record mein rakh liya. Ramesh ji se ek baar phir pooch raha hoon."
    asked = world.named("record.confirm_requested")[-1]
    assert asked.record.backing == "backed" and asked.record.transaction_id == "T2000"
    assert (world.root / "recordings" / deal_id / "proof" / f"{asked.record_id}.png").read_bytes() == b"png bytes"
    assert claim_fact(world, deal_id).status is FactStatus.DISPUTED  # not counted before the yes
    assert notes(world)[-1] == "screenshot T2000 sent for the disputed hirer's ₹2,000 payment claim: it matches, the worker is asked again"

    await world.say(RAMESH, "haan")
    await settled(world)
    fact = claim_fact(world, deal_id)
    assert fact.status is FactStatus.CONFIRMED and fact.media_url == SCREENSHOT
    assert await owed(world, deal_id) == {ItemKey.AMOUNT: 8000, ItemKey.ADVANCE: 0, ItemKey.BALANCE: 8000}
    assert world.texts_to(SUNITA)[-1] == world.texts_to(RAMESH)[-1] == "₹2,000 mil gaya. Baaki ₹8,000 kaam ke baad."
    assert notes(world)[-2] == "the hirer's ₹2,000 payment claim disputed before is confirmed by the worker: it counts now"


async def test_a_screenshot_that_does_not_match_leaves_it_disputed(world):
    deal_id = await with_a_promise_and_an_advance(world)
    asks = len(world.named("record.confirm_requested"))
    screenshot(world, 2000, None)  # the same amount, no transaction id
    await world.say(SUNITA, "", media=SCREENSHOT)
    await settled(world)
    assert world.texts_to(SUNITA)[-1] == (
        "Is screenshot mein transaction id nahi dikhi, ₹2,000 wale payment se mel nahi khata. "
        "Woh payment abhi bhi disputed hai, hisaab mein nahi."
    )
    assert len(world.named("record.confirm_requested")) == asks  # nobody is asked again, no new claim
    assert claim_fact(world, deal_id).status is FactStatus.DISPUTED
    assert await owed(world, deal_id) == {ItemKey.AMOUNT: 10000, ItemKey.ADVANCE: 0, ItemKey.BALANCE: 10000}


async def test_a_upi_reference_puts_it_again_and_a_second_no_keeps_it_disputed_with_nothing_more_asked(world):
    deal_id = await with_a_promise_and_an_advance(world)
    world.reader.readings["UPI ref 412345678901"] = Reading(kind="payment", transaction_id="412345678901")
    await world.say(SUNITA, "UPI ref 412345678901")
    assert world.texts_to(RAMESH)[-1].startswith(
        "Sunita ji ne ₹2,000 ke payment ka UPI reference bheja: 412345678901. Kya yeh payment aapko mila?")
    sent = len(world.texts_to(SUNITA))
    await world.say(RAMESH, "nahi")
    await settled(world)
    again = ("Ramesh ji ne phir mana kiya. ₹2,000 ka payment disputed hai, hisaab mein nahi. UPI reference record mein "
             "rakha hai. Baaki ₹10,000 kaam ke baad.")
    assert world.texts_to(SUNITA)[sent:] == [again] and world.texts_to(RAMESH)[-1] == again
    assert claim_fact(world, deal_id).status is FactStatus.DISPUTED


@pytest.mark.parametrize("said, utr", [
    ("UTR 9198 7654 3210", "919876543210"),  # 12 digits starting 91: read alone, +91 98765 43210
    ("9876543210", "9876543210"),  # 10 digits starting 9: an Indian mobile's shape
])
async def test_a_utr_shaped_like_a_phone_number_is_proof_never_a_new_deal(world, said, utr):
    deal_id = await with_a_promise_and_an_advance(world)
    deals = len(world.named("deal.requested"))
    await world.say(SUNITA, said)
    assert len(world.named("deal.requested")) == deals
    assert world.texts_to(RAMESH)[-1].startswith(
        f"Sunita ji ne ₹2,000 ke payment ka UPI reference bheja: {utr}. Kya yeh payment aapko mila?")
    assert world.named("record.confirm_requested")[-1].record.transaction_id == utr
    assert claim_fact(world, deal_id).status is FactStatus.DISPUTED


async def test_with_no_proof_asked_a_number_still_starts_a_deal(world):
    await after_the_call(world)
    deals = len(world.named("deal.requested"))
    await world.say(SUNITA, "9876543210")
    assert len(world.named("deal.requested")) == deals + 1


async def test_later_owed_messages_and_reminders_name_the_disputed_amount(world):
    await with_a_promise_and_an_advance(world)
    await world.say(RAMESH, "kaam poora ho gaya")
    await world.say(SUNITA, "haan")
    await settled(world)
    disputed = " ₹2,000 ka payment disputed hai, isme shaamil nahi."
    done = "Kaam poora ho gaya, dono ne confirm kiya. Deal ke hisaab se baaki ₹10,000." + disputed
    assert world.texts_to(SUNITA)[-1] == world.texts_to(RAMESH)[-1] == done
    await world.clock.advance(tuning.BALANCE_REMINDER_SECONDS)
    await settled(world)
    assert world.texts_to(SUNITA)[-1] == (
        "Yaad dila raha hoon: kaam poora ho chuka hai, dono ne confirm kiya tha. Deal ke hisaab se ₹10,000 baaki hai." + disputed
    )
    assert world.texts_to(RAMESH)[-1] == "Gawah ne Sunita ji ko ₹10,000 baaki ki yaad dila di hai." + disputed


async def test_a_work_done_claim_denied_quotes_the_work_and_stays_visible(world):
    deal_id = await after_the_call(world)
    await world.say(RAMESH, "kaam poora ho gaya")
    await world.say(SUNITA, "nahi")
    await settled(world)
    denied = "Sunita ji ne mana kiya ki kaam poora ho gaya. Record mein kaam poora hona disputed hai, pakka nahi. Baaki ₹13,000 kaam ke baad."
    assert world.texts_to(SUNITA)[-2] == world.texts_to(RAMESH)[-2] == denied
    quoted = world.texts_to(RAMESH)[-1]
    assert quoted.startswith("Kaam ke baare mein record mein yeh hai:\n1. ")
    assert "kaam ki tareekh tay hua tha" in quoted and "kaam tay hua tha" in quoted and quoted.count("Suniye: ") == 2
    assert not any("screenshot ya UPI" in t for t in world.texts_to(RAMESH))  # no money: no proof to ask for
    work = next(f for f in world.memory.book.deal(deal_id).standing() if f.kind is FactKind.WORK and f.record_id)
    assert work.status is FactStatus.DISPUTED
    assert notes(world)[-2:] == [
        "the hirer said no to the worker's work-done claim: not counted, ₹13,000 owed",
        "quoted the record to both: the agreed dates, the agreed work",
    ]

    screenshot(world, 3000, "T3000", "advance")  # a later owed message names it
    await world.say(SUNITA, "", media=SCREENSHOT)
    assert world.texts_to(RAMESH)[-1] == "Advance ₹3,000 mil gaya. Baaki ₹10,000 kaam ke baad. Kaam poora hone ki baat disputed hai."


@pytest.fixture
async def on_meta(bus, tmp_path):
    settings = meta_settings(tmp_path)
    store = Store(settings.database_path)
    await store.open()
    world = MetaWorld(bus, store, settings, memory=FakeMemory([]))
    world.reader.readings[CASH] = Reading(kind="payment", amount=2000)
    yield world
    await world.bot.stop()
    await bus.drain()
    await store.close()


async def test_on_meta_the_proof_reaches_the_other_person_as_an_image_above_the_question(on_meta):
    world = on_meta
    deal_id = await world.start_deal()
    world.memory.facts.extend(two_amounts_facts(deal_id))
    await world.say(SUNITA, CASH)
    await world.say(RAMESH, "nahi")
    screenshot(world, 2000, "T2000")
    await world.say(SUNITA, "", media=SCREENSHOT)
    await world.flush()
    to_ramesh = [m for m in world.graph.messages if m["to"] == RAMESH.lstrip("+")]
    image, question = to_ramesh[-2:]
    assert image["type"] == "image" and image["image"] == {"link": SCREENSHOT, "caption": "Kaam dene wale ka bheja hua screenshot."}
    assert question["type"] == "interactive" and question["interactive"]["type"] == "button"
    assert question["interactive"]["body"]["text"].startswith("Kaam dene wale ne ₹2,000 ke payment ka screenshot bheja")


def test_the_agreement_lists_a_claim_still_disputed_and_drops_it_once_confirmed():
    from app.contract.document import disputed
    from app.contract.terms import Bi

    paid = Fact(
        id="p1", deal_id="d", text="Sunita paid 2,000.", item=ItemKey.BALANCE, kind=FactKind.PAYMENT, value_rupees=2000,
        said_by=Role.HIRER, status=FactStatus.DISPUTED, source=FactSource.TEXT, quote=CASH, record_id="r1",
        valid_from=datetime(2026, 11, 23, 6, 0, tzinfo=UTC),
    )
    [note] = disputed({"p1": paid}, {Role.HIRER: Bi("सुनीता", "Sunita"), Role.WORKER: None})
    assert note.text.en == "Disputed: Sunita reported a payment of ₹2,000 (23 November 2026); the worker said no. It is not counted."
    assert note.text.hi.startswith("विवादित: सुनीता ने ₹2,000 का भुगतान बताया") and note.said == CASH
    assert disputed({"p1": paid.model_copy(update={"status": FactStatus.CONFIRMED})}, {}) == []
