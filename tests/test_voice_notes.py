"""Voice notes on fakes: the practice call (13,000 in all, 3,000 advance) replayed into the
real memory from its saved replies, then voice notes from fixtures/voice-notes/ through the
bot. The transcription is faked (the words the recordings say), the Scribe answers from its
saved replies (tests/memory/recorded/voice_notes.json), and ffmpeg is the laptop's own."""

import io
import shutil
import wave
from pathlib import Path

import pytest
from meta_fakes import FakeGraph
from meta_world import MetaWorld, message, meta_settings, webhook
from whatsapp_world import BASE, GEETA, RAMESH, SUNITA, VOICE_NOTES, World, note_seconds, note_words

from app.config import Settings
from app.contracts import (
    ChangeStatus, Direction, FactChanged, FactConflict, FactKind, FactSource, FactStatus, ItemKey, VoiceNote, clip_path,
)
from app.memory import Memory
from app.memory.extract import RecordedExtractor, Routed
from app.memory.vectors import WordHashEmbedder
from app.records import words
from app.records.reader import Reading
from app.store import Store
from app.whatsapp import words as bot_words
from app.whatsapp.hearing import seconds_of, to_wav
from app.whatsapp.inbound import parse_inbound
from app.whatsapp.voice import key_for
from fakes.replayer import replay

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")

PAID = "Maine aaj teen hazaar advance GPay kar diya."
AGREE, CHANGE, MORE_ADVANCE = "paint-05.ogg", "paint-08.ogg", "paint-14.ogg"


def make_memory(bus, root: Path) -> Memory:
    memory = Memory(bus, Routed(None, RecordedExtractor()), WordHashEmbedder(), root=root, embed_model="hash")
    memory.attach(bus)
    return memory


def silent_call(root: Path, deal_id: str, seconds: int = 150) -> None:
    """The practice call's two recordings, silent, where the bridge would leave them."""
    for role in ("hirer", "worker"):
        path = root / "recordings" / deal_id / "1" / f"{role}.wav"
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


async def after_the_call(world: World) -> str:
    deal_id = await world.start_deal()
    await replay(world.bus, "fixtures/call_two_amounts.json", speed=0, deal_id=deal_id)
    silent_call(world.root, deal_id)
    await settled(world)
    assert (await world.memory.get_term(deal_id, ItemKey.AMOUNT)).current.value_rupees == 13000
    return deal_id


def whatsapp_conflicts(world: World) -> list[FactConflict]:
    return [e for e in world.named("fact.conflict") if e.call_no is None]


def voice_facts(world: World, deal_id: str) -> list:
    return [f for f in world.memory.book.deal(deal_id).standing() if f.source is FactSource.VOICE_NOTE]


@pytest.fixture
async def heard(bus, tmp_path):
    settings = Settings(
        _env_file=None, database_path=str(tmp_path / "test.db"), public_base_url=BASE, reply_timeout_seconds=120,
    )
    store = Store(settings.database_path)
    await store.open()
    world = World(bus, store, settings, memory=make_memory(bus, tmp_path))
    world.reader.readings[PAID] = Reading(kind="advance", amount=3000)
    yield world
    await world.bot.stop()
    await bus.drain()
    await store.close()


# ---------- hearing ----------

async def test_an_ogg_opus_voice_note_becomes_16_khz_wav_of_its_length():
    wav = await to_wav((VOICE_NOTES / AGREE).read_bytes())
    with wave.open(io.BytesIO(wav), "rb") as audio:
        assert (audio.getframerate(), audio.getnchannels(), audio.getsampwidth()) == (16000, 1, 2)
    assert round(seconds_of(wav), 1) == note_seconds(AGREE)


def test_a_voice_note_is_kept_beside_the_calls_recordings():
    assert key_for("d1", "wamid.HBg=/x", "audio/ogg; codecs=opus") == "recordings/d1/voice/wamid.HBg__x.ogg"
    assert key_for("d1", "MM1", "audio/amr") == "recordings/d1/voice/MM1.amr"


# ---------- facts from a voice note ----------

async def test_a_voice_note_through_twilios_form_becomes_facts_whose_clip_is_the_note(heard):
    deal_id = await after_the_call(heard)
    form = {
        "From": f"whatsapp:{SUNITA}", "Body": "", "NumMedia": "1", "MessageSid": "MMagree",
        "MediaUrl0": f"https://api.twilio.com/2010-04-01/Accounts/AC0/Messages/MMagree/Media/{AGREE}",
        "MediaContentType0": "audio/ogg",
    }
    await heard.bot.on_message(parse_inbound(form))
    await settled(heard)

    [note] = heard.named("whatsapp.voice_note")
    key = f"recordings/{deal_id}/voice/MMagree.ogg"
    assert (note.speaker, note.text, note.media_key, note.record_id) == ("hirer", note_words(AGREE), key, None)
    assert (heard.root / key).read_bytes() == (VOICE_NOTES / AGREE).read_bytes()
    [fact] = voice_facts(heard, deal_id)
    assert (fact.item, fact.said_by, fact.media_url, fact.call_no, fact.start) == (ItemKey.WORK, "hirer", key, None, 0.0)
    clip = await heard.memory.clip(fact.id)
    with wave.open(io.BytesIO(clip), "rb") as audio:
        assert audio.getframerate() == 24000 and round(audio.getnframes() / 24000, 1) == note_seconds(AGREE)
    assert heard.texts_to(SUNITA)[-1] == words.voice_kept(note_words(AGREE))
    assert not whatsapp_conflicts(heard) and not heard.named("record.received")


async def test_a_voice_note_through_metas_json_is_heard_the_same_way(bus, tmp_path):
    settings = meta_settings(tmp_path)
    store = Store(settings.database_path)
    await store.open()
    world = MetaWorld(bus, store, settings, memory=make_memory(bus, tmp_path))
    try:
        world.graph.media["MEDIA-VOICE"] = ((VOICE_NOTES / AGREE).read_bytes(), "audio/ogg")
        deal_id = await after_the_call(world)
        await world.post(webhook(message(SUNITA, "audio", {"id": "MEDIA-VOICE", "mime_type": "audio/ogg; codecs=opus", "voice": True})))
        await settled(world)
        [note] = world.named("whatsapp.voice_note")
        assert note.text == note_words(AGREE) and note.media_type == "audio/ogg; codecs=opus"
        assert [f.item for f in voice_facts(world, deal_id)] == [ItemKey.WORK]
        assert world.texts_to(SUNITA)[-1] == words.voice_kept(note_words(AGREE))
    finally:
        await world.bot.stop()
        await bus.drain()
        await store.close()


# ---------- a contradiction ----------

async def test_a_voice_note_that_contradicts_the_advance_is_answered_with_what_was_agreed_and_the_clip(heard):
    deal_id = await after_the_call(heard)
    await heard.voice_note(SUNITA, MORE_ADVANCE)
    await settled(heard)

    [conflict] = whatsapp_conflicts(heard)
    advance = (await heard.memory.get_term(deal_id, ItemKey.ADVANCE)).current
    assert (conflict.call_no, conflict.line_no, conflict.speaker, conflict.fact_ids) == (None, None, "hirer", [advance.id])
    assert "5,000" in conflict.explanation and "offer" not in conflict.explanation
    said = [f for f in voice_facts(heard, deal_id) if f.item == ItemKey.ADVANCE]
    assert [(f.value_rupees, f.status) for f in said] == [(5000, FactStatus.SAID)]
    clip = BASE + clip_path(advance.id)
    line = heard.texts_to(SUNITA)[-1]
    assert line == heard.texts_to(RAMESH)[-1]
    assert line.startswith(f'Sunita ji ne voice note mein kaha: "{note_words(MORE_ADVANCE)}". Deal mein advance ₹3,000 tay hua tha')
    assert line.endswith(f"Wo pal yahan suniye: {clip}")
    assert heard.reader.calls[-1] == (note_words(MORE_ADVANCE), False)  # a promise to pay: no record
    assert not heard.named("record.received")


# ---------- a payment ----------

async def test_a_payment_voice_note_is_a_record_the_other_person_confirms_and_one_payment_fact(heard):
    deal_id = await after_the_call(heard)
    heard.transcriber.heard[note_seconds(AGREE)] = PAID
    await heard.voice_note(SUNITA, AGREE, sid="MMpaid")
    await settled(heard)

    [record] = [e.record for e in heard.named("record.received")]
    key = f"recordings/{deal_id}/voice/MMpaid.ogg"
    assert (record.kind, record.amount, record.backing, record.text, record.media_url) == ("advance", 3000, "unbacked", PAID, key)
    assert heard.named("whatsapp.voice_note")[-1].record_id == record.id
    assert heard.texts_to(RAMESH)[-1] == f'Sunita ji ne voice note mein kaha: "{PAID}". Kya yeh sahi hai? Haan ya nahi likhiye.'
    assert heard.texts_to(SUNITA)[-1] == f'Aapka voice note suna: "{PAID}". Ramesh ji se confirm kar raha hoon.'

    await heard.say(RAMESH, "haan")
    await settled(heard)
    payments = {f.id: f for f in heard.memory.book.deal(deal_id).standing() if f.kind is FactKind.PAYMENT}
    [payment] = payments.values()  # the record's, and only that: the Scribe did not read the note
    assert (payment.status, payment.source, payment.media_url, payment.value_rupees) == (FactStatus.CONFIRMED, FactSource.VOICE_NOTE, key, 3000)
    assert await heard.memory.clip(payment.id)
    assert heard.texts_to(SUNITA)[-1] == "Advance ₹3,000 mil gaya. Baaki ₹10,000 kaam ke baad."


# ---------- a change ----------

async def change_asked(heard) -> tuple[str, FactChanged]:
    deal_id = await after_the_call(heard)
    await heard.voice_note(RAMESH, CHANGE)
    await settled(heard)
    [asked] = heard.named("fact.changed")
    return deal_id, asked


async def test_a_change_asked_by_voice_note_holds_only_once_the_other_person_says_yes(heard):
    deal_id, asked = await change_asked(heard)
    amount = (await heard.memory.get_term(deal_id, ItemKey.AMOUNT)).current
    assert (asked.status, asked.fact_id, asked.new_value, asked.proposed_by, asked.confirmed_by) == (
        ChangeStatus.CONFIRMED_ONE, amount.id, "25,000 rupees", "worker", ["worker"])
    assert heard.texts_to(SUNITA)[-1] == (
        f'Ramesh ji ne voice note mein kaha: "{note_words(CHANGE)}". Isse deal mein kul paisa ₹13,000 se badal kar '
        "₹25,000 ho jayega. Kya aap maante hain? Haan ya nahi likhiye.")
    assert heard.texts_to(RAMESH)[-1] == "Yeh badlav tabhi hoga jab Sunita ji bhi haan kahenge. Unse pooch raha hoon."
    assert amount.value_rupees == 13000  # nothing changes on one person's word

    await heard.say(SUNITA, "haan")
    await settled(heard)
    held = heard.named("fact.changed")[-1]
    assert (held.change_id, held.status, held.confirmed_by) == (asked.change_id, ChangeStatus.CONFIRMED_BOTH, ["hirer", "worker"])
    now = (await heard.memory.get_term(deal_id, ItemKey.AMOUNT)).current
    assert (now.value_rupees, now.status, now.replaces, now.source) == (25000, FactStatus.CONFIRMED, amount.id, FactSource.VOICE_NOTE)
    assert heard.memory.book.deal(deal_id).latest[amount.id].status is FactStatus.SUPERSEDED
    assert heard.texts_to(RAMESH)[-1] == "Sunita ji ne haan kaha. Deal mein kul paisa ab 25,000 rupees hai."


async def test_a_no_to_a_voice_note_change_leaves_the_term_as_it_was(heard):
    deal_id, asked = await change_asked(heard)
    await heard.say(SUNITA, "nahi")
    await settled(heard)
    assert heard.named("fact.changed")[-1].status is ChangeStatus.WITHDRAWN
    assert (await heard.memory.get_term(deal_id, ItemKey.AMOUNT)).current.value_rupees == 13000
    [change] = [f for f in voice_facts(heard, deal_id) if f.kind is FactKind.CHANGE]
    assert change.status is FactStatus.DISPUTED
    assert heard.texts_to(RAMESH)[-1] == "Sunita ji ne nahi kaha. Deal mein kul paisa pehle jaisa hi hai."


# ---------- no deal, and a voice note that cannot be heard ----------

async def test_a_voice_note_with_no_deal_gets_the_same_answer_as_a_text(heard):
    await heard.voice_note(GEETA, AGREE)
    assert heard.texts_to(GEETA) == [bot_words.HELP_NO_DEAL]
    assert heard.transcriber.calls == [] and not heard.named("whatsapp.voice_note")


async def test_a_voice_note_that_cannot_be_heard_says_so(heard):
    await heard.start_deal()
    heard.transcriber.fail = True
    await heard.voice_note(SUNITA, AGREE)
    assert heard.texts_to(SUNITA)[-1] == words.VOICE_FAILED
    heard.transcriber.fail = False
    heard.transcriber.heard[note_seconds(AGREE)] = ""
    await heard.voice_note(SUNITA, AGREE)
    assert heard.texts_to(SUNITA)[-1] == words.VOICE_EMPTY
    assert not heard.named("whatsapp.voice_note")
    inbound = [e for e in heard.named("whatsapp.message") if e.direction is Direction.IN]
    assert inbound[-1].media_type == "audio/ogg"
