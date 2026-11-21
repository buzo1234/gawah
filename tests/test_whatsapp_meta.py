"""The bot on Meta's Cloud API, against a fake Graph API: every message type in and out,
buttons, reactions, the contract as a document and a voice note, typing, pacing, and the
errors Meta gives. Sunita and Ramesh are real (verified) phones, Geeta a simulated one."""

import json
import logging

import pytest
from fastapi.testclient import TestClient
from meta_world import API, LOOKASIDE, MetaWorld, message, meta_settings, meta_world, tap, text, webhook  # noqa: F401
from test_sentinel import deal_facts
from whatsapp_world import BASE, GEETA, RAMESH, SUNITA, world  # noqa: F401

from app.config import Settings
from app.contracts import (
    NO_DEAL,
    WHATSAPP_WEBHOOK_PATH,
    CallKind,
    ContractReady,
    Direction,
    RecordKind,
    Role,
    call_path,
    callback_path,
    clip_path,
)
from app.main import create_app
from app.records import words as record_words
from app.records.reader import Reading
from app.store import Store
from app.whatsapp import words
from app.whatsapp.meta import Meta, payload, signature
from app.whatsapp.meta_inbound import parse_meta, report_failures
from app.whatsapp.outgoing import Button, Outgoing
from app.whatsapp.settings import WhatsAppSettings
from fakes import call as fake_call
from fakes.memory import FakeMemory, silent_wav

ASKED = 'Sunita ji ne likha hai: "2000 cash diya". Kya yeh sahi hai? Haan ya nahi likhiye.'


# ---------- the messages Gawah sends, in Graph's shape ----------

def test_each_kind_of_message_has_graphs_shape():
    to = {"messaging_product": "whatsapp", "recipient_type": "individual", "to": "919811100001"}
    assert payload(Outgoing(SUNITA, "Namaste")) == to | {"type": "text", "text": {"body": "Namaste", "preview_url": False}}
    assert payload(Outgoing(SUNITA, "Sahi hai?", buttons=(Button("yes:r1", "Haan, sahi hai"), Button("no:r1", "Nahi")))) == to | {
        "type": "interactive", "interactive": {"type": "button", "body": {"text": "Sahi hai?"}, "action": {"buttons": [
            {"type": "reply", "reply": {"id": "yes:r1", "title": "Haan, sahi hai"}},
            {"type": "reply", "reply": {"id": "no:r1", "title": "Nahi"}},
        ]}},
    }
    url = f"{BASE}/call/d1/hirer"
    assert payload(Outgoing(SUNITA, f"Call ke liye yeh link kholiye: {url}", link=url, link_label="Call kholiye")) == to | {
        "type": "interactive", "interactive": {
            "type": "cta_url", "body": {"text": "Call ke liye yeh link kholiye."},
            "action": {"name": "cta_url", "parameters": {"display_text": "Call kholiye", "url": url}},
        },
    }
    pdf = Outgoing(SUNITA, "Contract", media_url="https://s3/c.pdf", media_type="application/pdf", filename="c.pdf")
    assert payload(pdf) == to | {"type": "document", "document": {"link": "https://s3/c.pdf", "caption": "Contract", "filename": "c.pdf"}}
    assert payload(Outgoing(SUNITA, None, "https://s3/c.ogg", "audio/ogg")) == to | {
        "type": "audio", "audio": {"link": "https://s3/c.ogg", "voice": True},
    }
    assert payload(Outgoing(SUNITA, None, "https://s3/c.mp3", "audio/mpeg"))["audio"] == {"link": "https://s3/c.mp3"}
    assert payload(Outgoing(SUNITA, None, "https://s3/a.png", "image/png"))["image"] == {"link": "https://s3/a.png"}
    assert payload(Outgoing(SUNITA, "✅", react_to="wamid.IN1")) == to | {
        "type": "reaction", "reaction": {"message_id": "wamid.IN1", "emoji": "✅"},
    }


# ---------- the messages people send, read from Meta's webhook ----------

def test_every_kind_of_inbound_message_is_read():
    shot = message(SUNITA, "image", {"id": "M1", "mime_type": "image/jpeg", "sha256": "x", "caption": " advance "})
    payload = webhook(
        text(SUNITA, " 2000 cash diya "),
        shot,
        message(SUNITA, "document", {"id": "M2", "mime_type": "application/pdf", "filename": "bill.pdf"}),
        message(SUNITA, "audio", {"id": "M3", "mime_type": "audio/ogg; codecs=opus", "voice": True}),
        tap(RAMESH, "yes:r1", "Haan, sahi hai"),
        message(RAMESH, "button", {"payload": "no:r1", "text": "Nahi"}),
        message(RAMESH, "reaction", {"message_id": "wamid.OUT1", "emoji": "👍"}),
        message(RAMESH, "reaction", {"message_id": "wamid.OUT1"}),  # taken back: nothing to read
        message(SUNITA, "contacts", None, contacts=[{"name": {"formatted_name": "Ramesh Painter"},
                                                     "phones": [{"phone": "+91 98222 00002", "wa_id": "919822200002"}]}]),
        message(SUNITA, "sticker", {"id": "M4", "mime_type": "image/webp"}),
        message(SUNITA, "unsupported", {"type": "poll_creation"}),
        {"from_user_id": "IN.123", "id": "wamid.X", "type": "text", "text": {"body": "no phone number"}},
        names={SUNITA: "Sunita", RAMESH: "Ramesh"},
        statuses=[{"id": "wamid.OUT1", "status": "delivered", "recipient_id": "919822200002"}],
    )
    messages, statuses, skipped = parse_meta(payload, lambda media_id: f"{API}/{media_id}")
    got = [(m.phone, m.kind, m.text, m.media_url, m.media_type, m.button, m.other_name) for m in messages]
    assert got == [
        (SUNITA, "text", "2000 cash diya", None, None, None, None),
        (SUNITA, "image", "advance", f"{API}/M1", "image/jpeg", None, None),
        (SUNITA, "document", "", f"{API}/M2", "application/pdf", None, None),
        (SUNITA, "audio", "", f"{API}/M3", "audio/ogg; codecs=opus", None, None),
        (RAMESH, "button", "Haan, sahi hai", None, None, "yes:r1", None),
        (RAMESH, "button", "Nahi", None, None, "no:r1", None),
        (RAMESH, "reaction", "👍 (reaction)", None, None, None, None),
        (SUNITA, "contacts", "Ramesh Painter +919822200002", None, None, None, "Ramesh Painter"),
        (SUNITA, "other", "(sticker)", None, None, None, None),
        (SUNITA, "other", "(poll_creation)", None, None, None, None),
    ]
    assert {m.name for m in messages} == {"Sunita", "Ramesh"}
    assert messages[1].sid == shot["id"]
    assert [s["status"] for s in statuses] == ["delivered"] and skipped == 1


# ---------- the webhook: Meta's handshake and signature, beside Twilio's form ----------

def test_the_webhook_takes_metas_signed_json_and_still_takes_the_second_phones_form(tmp_path, monkeypatch):
    monkeypatch.setenv("WHATSAPP_PROVIDER", "meta")  # what .env says once the user switches
    settings = Settings(_env_file=None, database_path=str(tmp_path / "t.db"), meta_verify_token="verify-me")
    app = create_app(settings)
    assert isinstance(app.state.whatsapp.provider, Meta) and app.state.whatsapp.outbox.rich
    tunnel = {"cf-connecting-ip": "1.2.3.4", "x-forwarded-for": "1.2.3.4"}
    hello = json.dumps(webhook(text(SUNITA, "hello"), names={SUNITA: "Sunita"})).encode()
    tapped = json.dumps(webhook(tap(SUNITA, "yes:r1", "Haan, sahi hai"))).encode()
    thumbs = json.dumps(webhook(message(SUNITA, "reaction", {"message_id": "wamid.OUT1", "emoji": "👍"}))).encode()
    signed = lambda body: {**tunnel, "content-type": "application/json", "x-hub-signature-256": signature("test-app-secret", body)}  # noqa: E731

    with TestClient(app) as client:
        handshake = {"hub.mode": "subscribe", "hub.verify_token": "verify-me", "hub.challenge": "1158201444"}
        answer = client.get(WHATSAPP_WEBHOOK_PATH, params=handshake)
        assert (answer.status_code, answer.text, answer.headers["content-type"].split(";")[0]) == (200, "1158201444", "text/plain")
        assert client.get(WHATSAPP_WEBHOOK_PATH, params={**handshake, "hub.verify_token": "guess"}).status_code == 403
        assert client.get(WHATSAPP_WEBHOOK_PATH, params={**handshake, "hub.mode": "unsubscribe"}).status_code == 403

        post = lambda body, headers: client.post(WHATSAPP_WEBHOOK_PATH, content=body, headers=headers).status_code  # noqa: E731
        assert post(hello, {**tunnel, "content-type": "application/json"}) == 403  # no signature
        assert post(hello, {**signed(hello), "x-hub-signature-256": signature("wrong", hello)}) == 403
        assert post(hello.replace(b"hello", b"hallo"), signed(hello)) == 403  # the body was changed
        assert post(thumbs, {"content-type": "application/json"}) == 403  # from this machine too, with the secret set
        assert post(b"not json", signed(b"not json")) == 422
        client.portal.call(app.state.whatsapp.idle)
        client.portal.call(app.state.bus.drain)
        assert client.portal.call(app.state.store.events, None, "whatsapp.message") == []

        assert post(hello, signed(hello)) == 200
        assert post(tapped, signed(tapped)) == 200
        assert post(thumbs, signed(thumbs)) == 200
        status = json.dumps(webhook(statuses=[{"id": "wamid.OUT1", "status": "read", "recipient_id": "919811100001"}])).encode()
        assert post(status, signed(status)) == 200
        # The dashboard's second phone still posts Twilio's form, from this machine.
        form = {"From": f"whatsapp:{GEETA}", "Body": "hello", "NumMedia": "0", "MessageSid": "SM1", "ProfileName": "Geeta"}
        assert client.post(WHATSAPP_WEBHOOK_PATH, data=form).status_code == 200
        client.portal.call(app.state.whatsapp.idle)
        client.portal.call(app.state.bus.drain)
        log = client.portal.call(app.state.store.events, None, "whatsapp.message")
    assert [(e.direction, e.phone, e.text, e.simulated) for e in log] == [
        (Direction.IN, SUNITA, "hello", True), (Direction.OUT, SUNITA, words.HELP_NO_DEAL, True),
        (Direction.IN, SUNITA, "Haan, sahi hai", True), (Direction.OUT, SUNITA, record_words.ALREADY_ANSWERED, True),
        (Direction.IN, SUNITA, "👍 (reaction)", True),
        (Direction.IN, GEETA, "hello", True), (Direction.OUT, GEETA, words.HELP_NO_DEAL, True),
    ]
    assert log[0].provider_id.startswith("wamid.IN")


def test_with_no_app_secret_meta_posts_are_taken_unsigned_with_a_loud_warning(tmp_path, caplog):
    settings = WhatsAppSettings(
        _env_file=None, database_path=str(tmp_path / "t.db"), whatsapp_provider="meta", meta_app_secret=None,
    )
    app = create_app(settings)
    hello = json.dumps(webhook(text(SUNITA, "hello"))).encode()
    tunnel = {"cf-connecting-ip": "1.2.3.4", "content-type": "application/json"}
    with caplog.at_level(logging.WARNING, "gawah.whatsapp"), TestClient(app) as client:
        assert client.post(WHATSAPP_WEBHOOK_PATH, content=hello, headers=tunnel).status_code == 200
        client.portal.call(app.state.whatsapp.idle)
        client.portal.call(app.state.bus.drain)
        log = client.portal.call(app.state.store.events, None, "whatsapp.message")
    assert [e.text for e in log] == ["hello", words.HELP_NO_DEAL]
    warnings = [r.getMessage() for r in caplog.records if "META_APP_SECRET IS NOT SET" in r.getMessage()]
    assert len(warnings) == 2  # once at startup, once for the post
    assert all(w.startswith(f"deal={NO_DEAL} ") for w in warnings)


def test_metas_signature_is_hmac_sha256_of_the_raw_body_with_the_app_secret():
    # Worked by hand: printf '{"a":1}' | openssl dgst -sha256 -hmac secret
    assert signature("secret", b'{"a":1}') == "sha256=" + "aa9e2e3575f5d7098b6caccd790888c36d5fdb63342a73bada2d6a51747a8494"


# ---------- deals and links ----------

async def test_a_deal_starts_with_a_link_button_for_each_and_gawah_shows_it_is_typing(meta_world):
    [asked] = await meta_world.post(webhook(text(SUNITA, "9822200002"), names={SUNITA: "Sunita"}))
    deal_id = meta_world.named("deal.requested")[-1].deal_id

    assert meta_world.graph.typing == [{
        "messaging_product": "whatsapp", "status": "read", "message_id": asked, "typing_indicator": {"type": "text"},
    }]
    to_sunita, to_ramesh = meta_world.graph.messages
    for sent, phone, role in ((to_sunita, SUNITA, Role.HIRER), (to_ramesh, RAMESH, Role.WORKER)):
        url = BASE + call_path(deal_id, role)
        assert sent["to"] == phone.lstrip("+") and sent["type"] == "interactive"
        assert sent["interactive"]["type"] == "cta_url"
        assert sent["interactive"]["action"]["parameters"] == {"display_text": words.CALL_BUTTON, "url": url}
        assert url not in sent["interactive"]["body"]["text"]
        [logged] = meta_world.sent_to(phone)
        assert url in logged.text and not logged.simulated and logged.provider_id.startswith("wamid.OUT")
    assert "Sunita ji" in to_ramesh["interactive"]["body"]["text"]


async def test_a_shared_contact_card_starts_a_deal_with_the_other_persons_name(meta_world):
    card = [{"name": {"formatted_name": "Ramesh"}, "phones": [{"phone": "+91 98222 00002", "wa_id": "919822200002"}]}]
    await meta_world.post(webhook(message(SUNITA, "contacts", None, contacts=card), names={SUNITA: "Sunita"}))
    [deal] = meta_world.named("deal.requested")
    assert (deal.other.phone, deal.other.name, deal.requested_by.name) == (RAMESH, "Ramesh", "Sunita")
    assert len(meta_world.graph.messages) == 2


async def test_the_call_back_and_the_follow_up_links_are_buttons_too(meta_world):
    deal_id = await meta_world.start_deal()
    fake_call.end_call(meta_world.bus, deal_id)
    await meta_world.flush()
    [*_, to_sunita, to_ramesh] = meta_world.graph.messages
    assert to_sunita["interactive"]["action"]["parameters"] == {
        "display_text": words.CALLBACK_BUTTON, "url": BASE + callback_path(deal_id, Role.HIRER),
    }
    assert "akele" in to_ramesh["interactive"]["body"]["text"]

    await meta_world.say(SUNITA, "2000 cash diya", name="Sunita")
    await meta_world.clock.advance(120)
    await meta_world.flush()
    assert meta_world.graph.messages[-1]["interactive"]["action"]["parameters"]["url"] == BASE + callback_path(deal_id, Role.WORKER)
    assert "jawab nahi aaya" in meta_world.texts_to(RAMESH)[-1]


# ---------- records: buttons and reactions ----------

async def test_a_cash_record_is_asked_with_buttons_and_a_tapped_yes_confirms_it_with_a_thumbs_up(meta_world):
    deal_id = await meta_world.start_deal()
    [said] = await meta_world.post(webhook(text(SUNITA, "2000 cash diya"), names={SUNITA: "Sunita"}))
    [asked] = meta_world.named("record.confirm_requested")
    question = meta_world.graph.messages[-2]
    assert question["to"] == RAMESH.lstrip("+") and question["interactive"]["body"]["text"] == ASKED
    assert [b["reply"] for b in question["interactive"]["action"]["buttons"]] == [
        {"id": f"yes:{asked.record_id}", "title": "Haan, sahi hai"}, {"id": f"no:{asked.record_id}", "title": "Nahi"},
    ]
    assert meta_world.texts_to(RAMESH)[-1] == ASKED + "\n[Haan, sahi hai]  [Nahi]"  # the dashboard shows the buttons

    await meta_world.post(webhook(tap(RAMESH, f"yes:{asked.record_id}", "Haan, sahi hai"), names={RAMESH: "Ramesh"}))
    [confirmed] = meta_world.named("record.confirmed")
    assert (confirmed.deal_id, confirmed.confirmed, confirmed.confirmed_by) == (deal_id, True, Role.WORKER)
    inbound = [e for e in meta_world.named("whatsapp.message") if e.direction is Direction.IN]
    assert inbound[-1].text == "Haan, sahi hai"
    thumbs = [m for m in meta_world.graph.messages if m["type"] == "reaction"]
    assert thumbs == [{"messaging_product": "whatsapp", "recipient_type": "individual", "to": SUNITA.lstrip("+"),
                       "type": "reaction", "reaction": {"message_id": said, "emoji": "👍"}}]
    assert meta_world.texts_to(SUNITA)[-2:] == ["👍 (reaction)", 'Ramesh ji ne haan kaha. "2000 cash diya" record mein confirm ho gaya.']
    assert meta_world.texts_to(RAMESH)[-1] == record_words.ANSWER_NOTED
    assert meta_world.reader.calls == [("2000 cash diya", False)]

    await meta_world.post(webhook(tap(RAMESH, f"yes:{asked.record_id}", "Haan, sahi hai")))  # tapped twice
    assert meta_world.texts_to(RAMESH)[-1] == record_words.ALREADY_ANSWERED
    assert len(meta_world.named("record.confirmed")) == 1


async def test_a_tap_answers_its_own_question_even_when_an_older_one_is_open(meta_world):
    await meta_world.start_deal()
    await meta_world.say(SUNITA, "2000 cash diya")
    await meta_world.say(SUNITA, "kaam poora ho gaya")
    older, newer = meta_world.named("record.confirm_requested")
    await meta_world.post(webhook(tap(RAMESH, f"no:{newer.record_id}", "Nahi")))
    [answer] = meta_world.named("record.confirmed")
    assert (answer.record_id, answer.confirmed) == (newer.record_id, False)
    assert not [m for m in meta_world.graph.messages if m["type"] == "reaction"]  # no thumbs up for a no

    await meta_world.post(webhook(text(RAMESH, "haan")))  # typing still works, for the one left
    assert [(e.record_id, e.confirmed) for e in meta_world.named("record.confirmed")][-1] == (older.record_id, True)


async def test_a_payment_screenshot_is_downloaded_with_the_token_and_gets_a_tick(meta_world):
    deal_id = await meta_world.start_deal()
    shot = message(SUNITA, "image", {"id": "MEDIA-SHOT", "mime_type": "image/jpeg", "sha256": "x"})
    [shot_id] = await meta_world.post(webhook(shot))

    assert meta_world.graph.gets == [f"{API}/MEDIA-SHOT", f"{LOOKASIDE}?mid=MEDIA-SHOT"]
    [received] = meta_world.named("record.received")
    assert received.deal_id == deal_id and received.record.media_url == f"{API}/MEDIA-SHOT"
    tick, logged = meta_world.graph.messages[-2:]
    assert tick["reaction"] == {"message_id": shot_id, "emoji": "✅"} and tick["to"] == SUNITA.lstrip("+")
    assert logged["text"]["body"].startswith("Record mein likh liya: ₹8,000 advance")
    assert meta_world.named("record.confirm_requested") == []


async def test_a_reaction_a_voice_note_or_a_sticker_is_logged_and_never_read_as_a_record(meta_world):
    await meta_world.start_deal()
    sent = len(meta_world.graph.messages)
    await meta_world.post(webhook(message(RAMESH, "reaction", {"message_id": "wamid.OUT2", "emoji": "🙏"})))
    assert len(meta_world.graph.messages) == sent and meta_world.texts_to(RAMESH)[-1] != words.HELP
    inbound = [e for e in meta_world.named("whatsapp.message") if e.direction is Direction.IN]
    assert inbound[-1].text == "🙏 (reaction)"

    await meta_world.post(webhook(message(RAMESH, "audio", {"id": "MEDIA-SHOT", "mime_type": "audio/ogg"})))
    await meta_world.post(webhook(message(RAMESH, "sticker", {"id": "MEDIA-SHOT", "mime_type": "image/webp"})))
    assert meta_world.texts_to(RAMESH)[-2:] == [words.HELP, words.HELP]
    assert meta_world.reader.calls == [] and meta_world.graph.gets == []
    await meta_world.post(webhook(message(GEETA, "sticker", {"id": "M9", "mime_type": "image/webp"})))
    assert meta_world.texts_to(GEETA) == [words.HELP_NO_DEAL]


# ---------- the contract ----------

async def test_the_contract_is_a_pdf_with_a_caption_and_a_voice_note_for_each_person(meta_world):
    deal_id = await meta_world.start_deal()
    meta_world.bus.publish(ContractReady(
        deal_id=deal_id, pdf_key=f"contracts/{deal_id}-v2.pdf", pdf_url="https://s3.example/c-v2.pdf?sig=1",
        voice_summary_url="https://s3.example/c-v2.ogg?sig=1",
    ))
    await meta_world.flush()
    caption = "Aapki deal ka contract, version 2. Awaaz mein summary neeche hai."
    for phone in (SUNITA, RAMESH):
        pdf, voice = [m for m in meta_world.graph.messages if m["to"] == phone.lstrip("+")][-2:]
        assert pdf["document"] == {"link": "https://s3.example/c-v2.pdf?sig=1", "caption": caption, "filename": "Gawah-contract-v2.pdf"}
        assert voice["audio"] == {"link": "https://s3.example/c-v2.ogg?sig=1", "voice": True}
        assert [(e.text, e.media_type) for e in meta_world.sent_to(phone)[1:]] == [(caption, "application/pdf"), (None, "audio/ogg")]


async def test_a_contract_with_no_pdf_says_so_in_a_line_before_the_voice_note(meta_world):
    deal_id = await meta_world.start_deal()
    meta_world.bus.publish(ContractReady(deal_id=deal_id, voice_summary_url="https://s3.example/c.ogg?sig=1"))
    await meta_world.flush()
    assert [m["type"] for m in meta_world.graph.messages if m["to"] == SUNITA.lstrip("+")][-2:] == ["text", "audio"]
    assert meta_world.texts_to(SUNITA)[-2] == words.CONTRACT_VOICE_ONLY


# ---------- simulated phones, errors, pacing ----------

async def test_a_simulated_phone_gets_what_meta_would_send_as_text_and_nothing_reaches_meta(meta_world):
    await meta_world.say(SUNITA, GEETA.removeprefix("+91"))
    await meta_world.say(GEETA, "2000 cash diya")
    [asked] = meta_world.named("record.confirm_requested")
    await meta_world.say(SUNITA, "Haan, sahi hai")
    await meta_world.flush()
    assert {m["to"] for m in meta_world.graph.messages} == {SUNITA.lstrip("+")}
    assert meta_world.graph.typing == []  # say() carries no wamid
    to_geeta = meta_world.sent_to(GEETA)
    assert all(e.simulated and e.provider_id is None for e in to_geeta)
    assert meta_world.named("record.confirmed")[0].record_id == asked.record_id
    assert to_geeta[-1].text.startswith("Kaam dene wale ne haan kaha")


async def test_a_message_meta_refuses_is_logged_with_why_and_kept_out_of_the_event_log(meta_world, caplog):
    meta_world.graph.fail = (400, 131047)
    with caplog.at_level(logging.ERROR, "gawah.whatsapp"):
        await meta_world.say(SUNITA, "hello")
        await meta_world.flush()
    assert meta_world.sent_to(SUNITA) == []
    [line] = [r.getMessage() for r in caplog.records if "not sent" in r.getMessage()]
    assert line.startswith(f"deal={NO_DEAL} not sent to ***0001: meta http 400 code 131047")
    assert "must send a message first" in line and "9822200002" not in line


async def test_a_failed_delivery_report_is_logged_against_its_deal(meta_world, caplog):
    deal_id = await meta_world.start_deal()
    wamid = meta_world.sent_to(RAMESH)[-1].provider_id
    failed = {"id": wamid, "status": "failed", "recipient_id": RAMESH.lstrip("+"),
              "errors": [{"code": 131047, "title": "Re-engagement message"}]}
    with caplog.at_level(logging.ERROR, "gawah.whatsapp"):
        report_failures(webhook(statuses=[failed])["entry"][0]["changes"][0]["value"]["statuses"], meta_world.bot.outbox.deal_of)
    [line] = [r.getMessage() for r in caplog.records]
    assert line.startswith(f"deal={deal_id} not delivered to ***0002: code 131047 Re-engagement message")


async def test_real_messages_go_one_at_a_time_a_second_apart(meta_world):
    meta_world.meta.spacing_seconds = 1.0
    meta_world.bot.outbox.spacing = 1.0
    for n in range(3):
        meta_world.bot.outbox.send(NO_DEAL, SUNITA, None, f"message {n}")
    await meta_world.clock.advance(0.5)
    assert len(meta_world.graph.messages) == 1
    await meta_world.clock.advance(5)
    await meta_world.flush()
    assert [m["text"]["body"] for m in meta_world.graph.messages] == ["message 0", "message 1", "message 2"]
    assert [e.text for e in meta_world.sent_to(SUNITA)] == ["message 0", "message 1", "message 2"]


# ---------- the Sentinel's clip ----------

@pytest.fixture
async def watched_on_meta(bus, tmp_path):
    settings = meta_settings(tmp_path)
    store = Store(settings.database_path)
    await store.open()
    world = MetaWorld(bus, store, settings, memory=FakeMemory([], clips={"f-advance": silent_wav()}))
    world.reader.readings["5000 advance diya"] = Reading(kind="advance", amount=5000)
    yield world
    await world.bot.stop()
    await bus.drain()
    await store.close()


async def test_the_moment_a_term_was_agreed_is_a_button_to_the_clip(watched_on_meta):
    world = watched_on_meta
    deal_id = await world.start_deal()
    world.memory.facts.extend(deal_facts(deal_id))
    await world.say(SUNITA, "5000 advance diya", name="Sunita")
    await world.flush()
    agreed = [m for m in world.graph.messages if m["type"] == "interactive" and m["interactive"]["type"] == "cta_url"][-2:]
    assert sorted(m["to"] for m in agreed) == sorted(p.lstrip("+") for p in (SUNITA, RAMESH))
    for sent in agreed:
        assert sent["interactive"]["action"]["parameters"] == {"display_text": "Wo pal suniye", "url": BASE + clip_path("f-advance")}
        assert sent["interactive"]["body"]["text"] == "Deal mein advance ₹3,000 tay hua tha (21 Nov ki call mein). Wo pal yahan suniye."
    assert world.named("record.confirm_requested")[0].record.kind is RecordKind.ADVANCE


async def test_twilio_is_still_the_default_and_a_call_back_link_there_stays_plain(world):
    deal_id = await world.start_deal()
    fake_call.end_call(world.bus, deal_id, kind=CallKind.DEAL)
    await world.settle()
    assert BASE + callback_path(deal_id, Role.HIRER) in world.texts_to(SUNITA)[-1]
    assert world.bot.outbox.rich is False
