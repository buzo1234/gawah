import logging

import pytest
from fastapi.testclient import TestClient
from whatsapp_world import BASE, GEETA, RAMESH, REAL, SUNITA, world  # noqa: F401

from app.config import Settings
from app.contracts import (
    NO_DEAL, WHATSAPP_WEBHOOK_PATH, CallKind, ContractReady, Direction, Role, call_path, callback_path,
)
from app.main import create_app
from app.whatsapp import bot, phone, words
from app.whatsapp.twilio import TwilioError, signature
from fakes import call as fake_call


@pytest.mark.parametrize(
    ("text", "sender_role"),
    [
        ("9822200002", Role.HIRER),
        ("Ramesh painter se deal karni hai, number +91 98222 00002", Role.HIRER),
        ("098222-00002 se baat pakki karni hai", Role.HIRER),
        ("mere ghar mein kaam karwana hai 919822200002", Role.HIRER),
        ("main kaam karunga, malik ka number 9822200002 hai", Role.WORKER),
        ("I am the painter. Customer: 98222 00002", Role.WORKER),
        ("Ramesh ji kaam karenge, unka number 9822200002", Role.HIRER),  # someone else does the work
        ("mere customer ka number 9822200002", Role.WORKER),
    ],
)
async def test_a_phone_number_starts_a_deal_and_each_person_gets_their_own_call_link(world, text, sender_role):
    await world.say(SUNITA, text, name="Sunita")

    [deal] = world.named("deal.requested")
    assert (deal.requested_by.phone, deal.requested_by.role, deal.requested_by.name) == (SUNITA, sender_role, "Sunita")
    assert (deal.other.phone, deal.other.role) == (RAMESH, sender_role.other)
    assert deal.text == text

    [to_sender], [to_other] = world.sent_to(SUNITA), world.sent_to(RAMESH)
    assert BASE + call_path(deal.deal_id, sender_role) in to_sender.text
    assert BASE + call_path(deal.deal_id, sender_role.other) in to_other.text
    assert to_sender.deal_id == to_other.deal_id == deal.deal_id
    # The message that asked arrived before the deal existed.
    inbound = [e for e in world.named("whatsapp.message") if e.direction is Direction.IN]
    assert [(e.deal_id, e.phone, e.text, e.role) for e in inbound] == [(NO_DEAL, SUNITA, text, None)]
    assert (await world.store.deal(deal.deal_id)).person(sender_role).phone == SUNITA


def test_phone_numbers_are_normalised_to_full_indian_numbers():
    assert phone.find_numbers("9822200002") == [RAMESH]
    assert phone.find_numbers("+91-98222-00002 ya 09833300003") == [RAMESH, GEETA]
    assert phone.find_numbers("2000 cash diya") == []
    assert phone.find_numbers("UPI ref 412345678901") == []  # twelve digits, but not a mobile number
    assert phone.find_numbers("1234567890") == []


async def test_messages_it_cannot_use_get_one_line_of_help_and_start_nothing(world):
    await world.say(SUNITA, "hello")
    await world.say(SUNITA, SUNITA)  # their own number
    await world.say(SUNITA, "9822200002 ya 9833300003")  # which one? never guess
    assert world.texts_to(SUNITA) == [words.HELP_NO_DEAL, words.OWN_NUMBER, words.MANY_NUMBERS]
    assert world.named("deal.requested") == []
    assert world.reader.calls == []


async def test_a_simulated_number_never_reaches_twilio(world):
    await world.start_deal(SUNITA, RAMESH)
    await world.say(SUNITA, "2000 cash diya")
    await world.say(RAMESH, "haan")
    await world.clock.advance(60)

    sent = [e for e in world.named("whatsapp.message") if e.direction is Direction.OUT]
    assert len(sent) == 6 and all(e.simulated and e.provider_id is None for e in sent)
    assert world.twilio.sent == []


async def test_a_real_number_goes_through_twilio_and_is_published_once_twilio_accepts(world):
    await world.say(REAL, RAMESH)
    assert [(to, "call/" in text) for _, to, text, _ in world.twilio.sent] == [(REAL, True)]
    [real] = world.sent_to(REAL)
    assert (real.simulated, real.provider_id) == (False, "SM1")
    assert all(e.simulated for e in world.sent_to(RAMESH))

    world.twilio.fail = True
    await world.say(REAL, "hello")
    await world.clock.advance(10)
    await world.settle()
    assert len(world.sent_to(REAL)) == 1  # the refused message is not in the event log


async def test_the_send_queue_keeps_three_seconds_between_real_messages(world):
    for n in range(4):
        world.bot.outbox.send(NO_DEAL, REAL, None, f"message {n}")
    await world.clock.advance(1)
    assert len(world.twilio.sent) == 1
    await world.clock.advance(20)
    assert [(at, text) for at, _, text, _ in world.twilio.sent] == [
        (0.0, "message 0"), (3.0, "message 1"), (6.0, "message 2"), (9.0, "message 3"),
    ]
    world.bot.outbox.send(NO_DEAL, REAL, None, "much later")
    await world.clock.advance(0)
    assert world.twilio.sent[-1][0] == 21.0  # no wait when the last one is long gone


async def test_after_the_deal_call_each_person_gets_their_own_call_back_link(world):
    deal_id = await world.start_deal()
    fake_call.end_call(world.bus, deal_id, kind=CallKind.CALLBACK)
    await world.settle()
    assert len(world.sent_to(SUNITA)) == len(world.sent_to(RAMESH)) == 1  # only the call links so far

    fake_call.end_call(world.bus, deal_id)
    await world.settle()
    assert BASE + callback_path(deal_id, Role.HIRER) in world.texts_to(SUNITA)[-1]
    assert BASE + callback_path(deal_id, Role.WORKER) in world.texts_to(RAMESH)[-1]
    assert "akele" in world.texts_to(RAMESH)[-1]


async def test_the_contract_goes_to_both_people_as_a_line_a_pdf_and_a_voice_summary(world):
    deal_id = await world.start_deal()
    world.bus.publish(
        ContractReady(
            deal_id=deal_id, pdf_url="https://s3.example/c.pdf?sig=1", voice_summary_url="https://s3.example/c.ogg?sig=1"
        )
    )
    await world.settle()
    for person in (SUNITA, RAMESH):
        got = [(e.text, e.media_url, e.media_type) for e in world.sent_to(person)[1:]]
        assert got == [
            (words.CONTRACT, None, None),
            (None, "https://s3.example/c.pdf?sig=1", "application/pdf"),
            (None, "https://s3.example/c.ogg?sig=1", "audio/ogg"),
        ]


async def test_the_contract_line_names_only_the_files_really_attached(world):
    deal_id = await world.start_deal()
    world.bus.publish(ContractReady(deal_id=deal_id, pdf_key="contracts/x.pdf", voice_summary_url="https://s3.example/c.ogg?sig=1"))
    await world.settle()  # the key cannot be signed here: the test settings have no bucket
    assert [(e.text, e.media_url) for e in world.sent_to(SUNITA)[1:]] == [
        (words.CONTRACT_VOICE_ONLY, None), (None, "https://s3.example/c.ogg?sig=1"),
    ]
    world.bus.publish(ContractReady(deal_id=deal_id, text="contract"))
    await world.settle()
    assert world.texts_to(RAMESH)[-1] == words.CONTRACT_NO_FILE and "PDF" not in words.CONTRACT_NO_FILE


def _form(sender: str, body: str) -> dict[str, str]:
    return {"From": f"whatsapp:{sender}", "To": "whatsapp:+17370000000", "Body": body, "NumMedia": "0", "MessageSid": "SM1"}


def test_the_webhook_wants_a_twilio_signature_from_the_tunnel_but_not_from_this_machine(tmp_path):
    settings = Settings(
        _env_file=None, database_path=str(tmp_path / "t.db"), twilio_auth_token="token", public_base_url=BASE
    )
    app = create_app(settings)
    form = _form(SUNITA, "hello")
    tunnel = {"cf-connecting-ip": "1.2.3.4", "x-forwarded-for": "1.2.3.4"}
    good = signature("token", BASE + WHATSAPP_WEBHOOK_PATH, form)
    with TestClient(app) as client:
        post = lambda headers, data=form: client.post(WHATSAPP_WEBHOOK_PATH, data=data, headers=headers).status_code  # noqa: E731
        assert post(tunnel) == 403
        assert post({**tunnel, "x-twilio-signature": signature("wrong", BASE + WHATSAPP_WEBHOOK_PATH, form)}) == 403
        assert post({**tunnel, "x-twilio-signature": good}, {**form, "Body": "changed"}) == 403
        assert post({"x-forwarded-for": "1.2.3.4", "x-twilio-signature": "junk"}) == 403
        client.portal.call(app.state.whatsapp.idle)
        client.portal.call(app.state.bus.drain)
        assert client.portal.call(app.state.store.events, None, "whatsapp.message") == []

        assert post({**tunnel, "x-twilio-signature": good}) == 200
        assert post({}) == 200  # the dashboard's second phone, from this machine
        assert post({}, {"Body": "no sender"}) == 422
        client.portal.call(app.state.whatsapp.idle)
        client.portal.call(app.state.bus.drain)
        log = client.portal.call(app.state.store.events, None, "whatsapp.message")
    assert [(e.direction, e.phone, e.text, e.simulated) for e in log] == [
        (Direction.IN, SUNITA, "hello", True), (Direction.OUT, SUNITA, words.HELP_NO_DEAL, True),
    ] * 2


def test_the_signature_matches_the_worked_example_in_twilios_docs():
    # From "Validating requests are coming from Twilio", twilio.com/docs/usage/security.
    params = {
        "Digits": "1234", "To": "+18005551212", "From": "+14158675310", "Caller": "+14158675310",
        "CallSid": "CA1234567890ABCDE",
    }
    assert signature("12345", "https://example.com/myapp.php?foo=1&bar=2", params) == "L/OH5YylLD5NRKLltdqwSvS0BnU="


def test_a_twilio_error_keeps_its_reason_but_not_a_phone_number():
    error = TwilioError(400, 21211, "The 'To' number whatsapp:+919811100001 is not a valid phone number")
    assert str(error) == "twilio http 400 code 21211: The 'To' number whatsapp:***0001 is not a valid phone number"


@pytest.mark.parametrize(
    ("text", "asks"),
    [
        ("delete my data", True), ("Delete my data please", True), ("please remove my deal data", True),
        ("mera data delete karo", True), ("Mera data delete kar do", True), ("data hata do", True),
        ("mera saara data hatao", True), ("data mita do", True), ("मेरा डेटा हटा दो", True),
        ("2000 cash diya", False), ("data entry ka kaam hai", False), ("delete", False), ("haan", False),
    ],
)
def test_a_request_to_delete_data_is_recognised_in_english_and_hinglish(text, asks):
    assert bot.asks_to_delete(text) is asks


async def test_delete_my_data_is_answered_logged_and_noted_and_nothing_is_deleted(world, caplog):
    deal_id = await world.start_deal()
    await world.say(SUNITA, "2000 cash diya")
    with caplog.at_level(logging.WARNING, "gawah.whatsapp"):
        await world.say(RAMESH, "mera data delete karo")
    assert world.texts_to(RAMESH)[-1] == words.DELETE_RECEIVED
    [note] = [e for e in world.named("agent.note") if "deleted" in e.text]
    assert (note.deal_id, note.agent) == (deal_id, "sentinel")
    assert note.text.startswith("worker (***0002) asked for this deal's data to be deleted")
    [line] = [r.getMessage() for r in caplog.records if "DATA DELETION" in r.getMessage()]
    assert line == f"deal={deal_id} DATA DELETION ASKED by ***0002 (worker): remove by hand, see tools/DELETE-DATA.md"
    assert world.named("record.confirmed") == []  # not taken as an answer to the open question
    assert await world.store.deal(deal_id) and len(await world.store.records(deal_id)) == 1
    assert world.reader.calls == [("2000 cash diya", False)]  # never sent to the model

    await world.say(GEETA, "delete my data")  # no deal: still heard, still logged
    assert world.texts_to(GEETA) == [words.DELETE_RECEIVED]
    assert [e.deal_id for e in world.named("agent.note") if "deleted" in e.text][-1] == NO_DEAL
