import pytest
from whatsapp_world import BASE, GEETA, MOHAN, RAMESH, SCREENSHOT, SUNITA, world  # noqa: F401

from app.contracts import Backing, RecordKind, Role, callback_path
from app.records import words as record_words
from app.records.intake import yes_or_no
from app.whatsapp import words
from fakes import whatsapp as fake_whatsapp


async def test_a_payment_screenshot_with_a_transaction_id_is_logged_and_nobody_is_asked(world):
    deal_id = await world.start_deal()
    await world.say(SUNITA, "", media=SCREENSHOT)

    [received] = world.named("record.received")
    record = received.record
    assert received.deal_id == deal_id
    assert (record.sender, record.kind, record.backing) == (Role.HIRER, RecordKind.ADVANCE, Backing.BACKED)
    assert (record.amount, record.date, record.transaction_id) == (8000, "21 Nov 2026", "632514789023")
    assert record.media_url == SCREENSHOT and world.twilio.fetched == [SCREENSHOT]
    assert world.texts_to(SUNITA)[-1] == "Record mein likh liya: ₹8,000 advance, transaction id 632514789023, 21 Nov 2026."
    assert world.named("record.confirm_requested") == []
    assert len(world.sent_to(RAMESH)) == 1  # only the call link from the start of the deal

    await world.clock.advance(1000)
    await world.settle()
    assert world.named("reply.timeout") == []
    assert await world.store.records(deal_id) == [record]


async def test_cash_is_one_persons_word_so_the_other_is_asked_and_says_yes(world):
    deal_id = await world.start_deal()
    await world.say(SUNITA, "2000 cash diya", name="Sunita")

    [received], [asked] = world.named("record.received"), world.named("record.confirm_requested")
    record = received.record
    assert (record.kind, record.backing, record.amount, record.text) == (RecordKind.PAYMENT, Backing.UNBACKED, 2000, "2000 cash diya")
    assert (asked.deal_id, asked.record_id, asked.confirm_by) == (deal_id, record.id, Role.WORKER)
    assert asked.question == 'Sunita ji ne likha hai: "2000 cash diya". Kya yeh sahi hai? Haan ya nahi likhiye.'
    assert world.texts_to(RAMESH)[-1] == asked.question
    assert world.texts_to(SUNITA)[-1] == "Likh liya. Kaam karne wale se confirm kar raha hoon."

    await world.say(RAMESH, "Haan, sahi hai", name="Ramesh")
    [confirmed] = world.named("record.confirmed")
    assert (confirmed.deal_id, confirmed.record_id, confirmed.confirmed_by, confirmed.confirmed) == (deal_id, record.id, Role.WORKER, True)
    assert world.texts_to(SUNITA)[-1] == 'Ramesh ji ne haan kaha. "2000 cash diya" record mein confirm ho gaya.'
    assert world.texts_to(RAMESH)[-1] == record_words.ANSWER_NOTED
    assert [r.confirmed for r in await world.store.records(deal_id)] == [True]
    assert world.reader.calls == [("2000 cash diya", False)]  # the yes was not sent to the model

    await world.clock.advance(1000)
    await world.settle()
    assert world.named("reply.timeout") == []


async def test_the_other_person_can_say_no(world):
    deal_id = await world.start_deal()
    await world.say(RAMESH, "kaam poora ho gaya")
    [asked] = world.named("record.confirm_requested")
    assert asked.confirm_by is Role.HIRER and asked.record.kind is RecordKind.WORK_DONE

    await world.say(SUNITA, "nahi")
    [confirmed] = world.named("record.confirmed")
    assert (confirmed.confirmed, confirmed.confirmed_by) == (False, Role.HIRER)
    assert world.texts_to(RAMESH)[-1] == 'Kaam dene wale ne nahi kaha. "kaam poora ho gaya" record mein bina confirm ke likha hai.'
    assert [r.confirmed for r in await world.store.records(deal_id)] == [False]


async def test_no_answer_in_time_raises_reply_timeout_and_sends_one_follow_up(world):
    deal_id = await world.start_deal()
    await world.say(RAMESH, "kaam poora ho gaya")
    record = world.named("record.received")[0].record
    before = len(world.sent_to(SUNITA))

    await world.clock.advance(119)
    await world.settle()
    assert world.named("reply.timeout") == []

    await world.clock.advance(1)
    await world.settle()
    [timeout] = world.named("reply.timeout")
    assert (timeout.deal_id, timeout.person, timeout.record_id, timeout.waited_seconds) == (deal_id, Role.HIRER, record.id, 120)
    assert timeout.ask == world.named("record.confirm_requested")[0].question
    assert world.texts_to(SUNITA)[before:] == [words.follow_up(BASE + callback_path(deal_id, Role.HIRER))]

    # Time passing, or the same timeout raised again, sends nothing more.
    await world.clock.advance(1000)
    fake_whatsapp.reply_timed_out(world.bus, deal_id, Role.HIRER, timeout.ask, record_id=record.id)
    await world.settle()
    assert len(world.named("reply.timeout")) == 2 and len(world.sent_to(SUNITA)) == before + 1

    await world.say(SUNITA, "theek hai")  # a late answer still counts
    assert [e.confirmed for e in world.named("record.confirmed")] == [True]


async def test_a_typed_transaction_id_without_a_screenshot_is_still_unbacked(world):
    await world.start_deal()
    await world.say(SUNITA, "8000 bheja, UPI ref 632514789023")
    [received] = world.named("record.received")
    assert (received.record.backing, received.record.transaction_id) == (Backing.UNBACKED, "632514789023")
    assert len(world.named("record.confirm_requested")) == 1


async def test_a_message_that_is_not_a_record_gets_help_and_an_unreadable_one_says_so(world):
    await world.start_deal()
    await world.say(SUNITA, "aur kya haal hai")
    assert world.texts_to(SUNITA)[-1] == words.HELP
    await world.say(SUNITA, "haan")  # nothing was asked, so this is not an answer
    assert world.texts_to(SUNITA)[-1] == words.HELP

    world.reader.fail = True
    await world.say(SUNITA, "2000 cash diya")
    assert world.texts_to(SUNITA)[-1] == words.READ_FAILED
    assert world.named("record.received") == []


async def test_two_deals_at_once_keep_their_records_and_answers_apart(world):
    first = await world.start_deal(SUNITA, RAMESH)
    second = await world.start_deal(GEETA, MOHAN)

    await world.say(RAMESH, "kaam poora ho gaya")
    await world.say(GEETA, "2000 cash diya")
    assert [(e.deal_id, e.record.sender) for e in world.named("record.received")] == [(first, Role.WORKER), (second, Role.HIRER)]
    assert [(e.deal_id, e.confirm_by) for e in world.named("record.confirm_requested")] == [(first, Role.HIRER), (second, Role.WORKER)]

    await world.say(MOHAN, "nahi mila")
    await world.say(SUNITA, "ji haan")
    assert [(e.deal_id, e.confirmed) for e in world.named("record.confirmed")] == [(second, False), (first, True)]
    assert [r.confirmed for r in await world.store.records(first)] == [True]
    assert [r.confirmed for r in await world.store.records(second)] == [False]
    assert all(e.deal_id == first for e in world.sent_to(SUNITA) + world.sent_to(RAMESH))
    assert all(e.deal_id == second for e in world.sent_to(GEETA) + world.sent_to(MOHAN))

    # A person in two deals: their messages belong to the most recent one.
    third = await world.start_deal(SUNITA, MOHAN)
    await world.say(SUNITA, "2000 cash diya")
    assert world.named("record.received")[-1].deal_id == third
    assert world.named("record.confirm_requested")[-1].confirm_by is Role.WORKER
    assert "2000 cash diya" in world.texts_to(MOHAN)[-1]


@pytest.mark.parametrize(
    ("text", "answer"),
    [
        ("haan", True), ("Ha", True), ("Ji haan", True), ("sahi hai", True), ("theek hai.", True),
        ("YES", True), ("haan mil gaya", True), ("हाँ", True),
        ("nahi", False), ("Nahi!", False), ("galat hai", False), ("no", False), ("sahi nahi hai", False),
        ("nahi mila", False), ("नहीं", False),
        ("2000 cash diya", None), ("kal dekhta hoon", None), ("", None),
        ("nahi bhai usne abhi tak kuch nahi diya hai", None),  # too long to be a plain yes or no
    ],
)
def test_yes_and_no_in_the_common_hinglish_forms(text, answer):
    assert yes_or_no(text) is answer
