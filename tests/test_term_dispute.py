"""A term disputed on a call-back, through the whole offline app (tests/offline.py): the
practice call (13,000 in all, 3,000 advance) replayed into the real brain and memory from their
saved answers, call-backs as mouth sends them, then the two simulated phones on WhatsApp.

The user's deal e5841b469c0f is the first case: the worker said a bare "ना" to the amount and
the advance on the call-back, the hirer confirmed everything."""

import asyncio
import json
import wave
from pathlib import Path

import httpx
import pytest

from app.contracts import (
    MEMORY_STATE, WHATSAPP_WEBHOOK_PATH, CallEnded, DealRequested, CallKind, CallStarted, ChangeStatus, ChecklistUpdated, ContractReady,
    Direction, DisputeStep, Event, FactChanged, FactStatus, ItemKey, ItemState, Person, Role, TermDispute,
    TermsConfirmed, TermsDisputed, TranscriptLine, WhatsAppMessage, call_path, clip_path,
)
from app.records import tuning
from app.whatsapp.inbound import Inbound
from fakes.replayer import load
from tests.offline import offline_app
from tests.whatsapp_world import FakeClock, note_words

HIRER, WORKER = "+919000000001", "+919000000002"  # not verified: simulated phones
PHONE = {Role.HIRER: HIRER, Role.WORKER: WORKER}
CALL = "fixtures/call_two_amounts.json"
NA = "ना"


class Deal:
    def __init__(self, app, client: httpx.AsyncClient, clock: FakeClock, root: Path) -> None:
        self.app, self.client, self.clock, self.root = app, client, clock, root
        self.bus, self.memory = app.state.bus, getattr(app.state, MEMORY_STATE)
        self.bot = app.state.whatsapp
        self.events: list[Event] = []
        self.bus.subscribe_all(self._keep)
        self.id = ""

    async def _keep(self, event: Event) -> None:
        self.events.append(event)

    async def settle(self) -> None:
        for _ in range(3):
            await self.bot.idle()
            await self.memory.settle()
            await self.bus.drain()
            await self.app.state.contract.idle()
        await self.bot.outbox.drain()

    def of(self, kind: type[Event], **match) -> list:
        return [e for e in self.events if isinstance(e, kind) and all(getattr(e, k) == v for k, v in match.items())]

    def media(self, role: Role) -> list[str | None]:
        return [m.media_url for m in self.of(WhatsAppMessage, direction=Direction.OUT, phone=PHONE[role])]

    def texts(self, role: Role) -> list[str]:
        return [m.text or m.media_url or "" for m in self.of(WhatsAppMessage, direction=Direction.OUT, phone=PHONE[role])]

    async def send(self, role: Role, text: str = "", button: str | None = None, **more) -> None:
        await self.bot.on_message(Inbound(phone=PHONE[role], text=text, button=button, kind="button" if button else "text", **more))
        await self.settle()

    async def start(self) -> None:
        form = {"From": f"whatsapp:{HIRER}", "Body": WORKER.removeprefix("+91"), "ProfileName": "Sunita", "NumMedia": "0"}
        assert (await self.client.post(WHATSAPP_WEBHOOK_PATH, data=form)).status_code == 200
        await self.settle()
        [requested] = self.of(DealRequested)
        self.id = requested.deal_id
        fixture = load(CALL)
        people = [Person(role=p["role"], name=p["name"]) for p in fixture["people"]]
        room = f"replay-{self.id}"
        self.bus.publish(CallStarted(deal_id=self.id, people=people, room=room))
        for line in fixture["lines"]:
            self.bus.publish(TranscriptLine(deal_id=self.id, **line))
            await self.settle()
        silent_recordings(self.root, self.id, seconds=int(fixture["lines"][-1]["end"]) + 5)
        self.bus.publish(CallEnded(deal_id=self.id, people=people, room=room, duration=fixture["lines"][-1]["end"]))
        await self.settle()

    def checklist(self) -> dict[ItemKey, str]:
        return {i.key: i.value for i in self.of(ChecklistUpdated)[-1].items if i.state is ItemState.AGREED}

    async def call_back(self, role: Role, disputes: dict[ItemKey, str] = (), reason: str = "done") -> None:
        """What mouth sends for one call-back: a no to each disputed term, or a yes to all."""
        person = [Person(role=role, phone=PHONE[role])]
        room = f"callback-{self.id}-{role.value}"
        self.bus.publish(CallStarted(deal_id=self.id, people=person, kind=CallKind.CALLBACK, room=room))
        for item, said in dict(disputes).items():
            self.bus.publish(TermsDisputed(deal_id=self.id, person=role, item=item, value=self.checklist()[item], said=said))
        if not disputes and reason == "done":
            self.bus.publish(TermsConfirmed(deal_id=self.id, person=role, said="haan ji"))
        await self.settle()
        self.bus.publish(CallEnded(deal_id=self.id, people=person, kind=CallKind.CALLBACK, room=room, reason=reason))
        await self.settle()

    def disputes(self) -> list[TermDispute]:
        return self.of(TermDispute)

    def button(self, step_text: str, choice: str) -> str:
        """The id a reply button was sent with, from the dispute it names."""
        [opened] = [d for d in self.disputes() if d.step is DisputeStep.OPENED and d.item.value == step_text]
        return f"term-{choice}:{opened.dispute_id}"


def silent_recordings(root: Path, deal_id: str, seconds: int) -> None:
    for role in Role:
        path = root / "recordings" / deal_id / "1" / f"{role.value}.wav"
        path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(path), "wb") as out:
            out.setnchannels(1)
            out.setsampwidth(2)
            out.setframerate(8000)
            out.writeframes(bytes(seconds * 8000 * 2))


class Opened:
    """The offline app, opened and closed around a test; open it again on the same database for a restart."""

    def __init__(self, tmp_path: Path, whatsapp: str) -> None:
        self.tmp_path, self.whatsapp = tmp_path, whatsapp
        self._stack: list = []

    async def open(self) -> Deal:
        clock = FakeClock()
        app = offline_app(self.tmp_path / "test.db", clock, whatsapp=self.whatsapp)
        transport = httpx.ASGITransport(app=app)
        life, client = app.router.lifespan_context(app), httpx.AsyncClient(transport=transport, base_url="http://gawah.test")
        await life.__aenter__()
        await client.__aenter__()
        self._stack.append((life, client))
        return Deal(app, client, clock, self.tmp_path)

    async def close(self) -> None:
        while self._stack:
            life, client = self._stack.pop()
            await client.__aexit__(None, None, None)
            await life.__aexit__(None, None, None)


async def _deal(tmp_path, monkeypatch, whatsapp: str):
    monkeypatch.setattr(tuning, "DISPUTE_REMINDER_SECONDS", 3600)
    opened = Opened(tmp_path, whatsapp)
    deal = await opened.open()
    deal.opened = opened
    await deal.start()
    return deal


@pytest.fixture
async def meta_deal(tmp_path, monkeypatch):
    deal = await _deal(tmp_path, monkeypatch, "meta")
    yield deal
    await deal.opened.close()


@pytest.fixture
async def twilio_deal(tmp_path, monkeypatch):
    deal = await _deal(tmp_path, monkeypatch, "twilio")
    yield deal
    await deal.opened.close()


def dump(deal: Deal) -> None:
    for role in Role:
        print(f"--- {role.value}")
        for text in deal.texts(role):
            print(json.dumps(text, ensure_ascii=False))


BASE = "http://localhost:8000"


def told(deal: Deal) -> str:
    """The message both get once the worker's call-back is over, with the clips of call 1."""
    amount, advance = (deal.memory.book.deal(deal.id).record(i) for i in (ItemKey.AMOUNT, ItemKey.ADVANCE))
    return (
        'Ramesh ji ne kul paisa ₹13,000 aur advance ₹3,000 par "nahi" kaha. Baaki sab dono ne confirm kar diya hai. '
        "Agreement tab tak ruka hai jab tak yeh tay nahi hota.\n"
        "Kul paisa aur advance ke baare mein record mein yeh hai:\n"
        '1. Call 1 mein (0:55): kul paisa ₹13,000 tay hua tha. Ramesh ji ne kaha: "12 mein nahi padta madam... 13 hazaar, '
        f'last. Isse neeche nahi", Sunita ji ne maana. Suniye: {BASE}{clip_path(amount.id)}\n'
        '2. Call 1 mein (1:06): advance ₹3,000 tay hua tha. Ramesh ji ne kaha: "3 hazaar de dijiye madam, ladkon ko dena '
        f'padta hai", Sunita ji ne maana. Suniye: {BASE}{clip_path(advance.id)}'
    )


def choose(term: str, numbered: bool = False) -> str:
    line = f'Aapne {term} par "nahi" kaha. Upar record mein woh pal suniye. Kya recording sahi hai, ya kuch aur tay hua tha?'
    return line + ("\n1 likhiye: Recording sahi hai\n2 likhiye: Kuch aur tay hua tha" if numbered
                   else "\n[Recording sahi hai]  [Kuch aur tay hua tha]")


async def disputed_by_the_worker(deal: Deal) -> None:
    """The user's deal e5841b469c0f: the hirer confirms all, the worker says a bare "ना" to the amount and the advance."""
    await deal.call_back(Role.HIRER)
    await deal.call_back(Role.WORKER, {ItemKey.AMOUNT: NA, ItemKey.ADVANCE: NA})


async def test_the_users_deal_both_are_told_with_the_moment_and_the_agreement_is_held(meta_deal):
    deal = meta_deal
    await disputed_by_the_worker(deal)
    assert deal.texts(Role.HIRER)[-1] == told(deal)
    assert deal.texts(Role.WORKER)[-3:] == [told(deal), choose("kul paisa ₹13,000"), choose("advance ₹3,000")]
    book = deal.memory.book.deal(deal.id)
    assert [book.record(i).status for i in (ItemKey.AMOUNT, ItemKey.ADVANCE)] == [FactStatus.DISPUTED] * 2
    assert [(d.item, d.person, d.step) for d in deal.disputes()] == [
        (ItemKey.AMOUNT, Role.WORKER, DisputeStep.OPENED), (ItemKey.ADVANCE, Role.WORKER, DisputeStep.OPENED)]
    assert deal.disputes()[0].fact_id == book.record(ItemKey.AMOUNT).id
    assert not deal.of(ContractReady)  # held while anything is in dispute
    clip = await deal.client.get(clip_path(book.record(ItemKey.AMOUNT).id))
    assert clip.status_code == 200 and clip.content.startswith(b"RIFF")  # the clip link plays the moment


async def test_recording_sahi_hai_confirms_tells_the_other_and_the_last_one_writes_the_agreement(meta_deal):
    deal = meta_deal
    await disputed_by_the_worker(deal)
    await deal.send(Role.WORKER, "Recording sahi hai", button=deal.button("amount", "ok"))
    assert deal.of(TermsConfirmed, person=Role.WORKER)[-1].item is ItemKey.AMOUNT  # only this one: the advance is still open
    assert deal.texts(Role.WORKER)[-1] == "Likh liya: kul paisa ₹13,000 aapki taraf se bhi pakka hai."
    assert deal.texts(Role.HIRER)[-1] == "Ramesh ji ne maana ki recording sahi hai: kul paisa ₹13,000 ab dono ki taraf se pakka hai."
    book = deal.memory.book.deal(deal.id)
    assert book.record(ItemKey.AMOUNT).status is FactStatus.CONFIRMED
    assert set(book.record(ItemKey.AMOUNT).confirmed_by) == set(Role)
    assert book.record(ItemKey.ADVANCE).status is FactStatus.DISPUTED
    assert not deal.of(ContractReady)

    await deal.send(Role.WORKER, "Recording sahi hai", button=deal.button("advance", "ok"))
    *_, advance, rest = deal.of(TermsConfirmed, person=Role.WORKER)
    assert (advance.item, rest.item) == (ItemKey.ADVANCE, None)  # the last one: then their call-back's yes to everything else
    done = " Ab sab tay hai: agreement thodi der mein yahin aayega."
    assert deal.texts(Role.HIRER)[-3] == "Ramesh ji ne maana ki recording sahi hai: advance ₹3,000 ab dono ki taraf se pakka hai." + done
    [ready] = deal.of(ContractReady)
    for role in Role:
        assert deal.media(role)[-2:] == [ready.pdf_url, ready.voice_summary_url]  # the agreement, to both
    assert [d.how for d in deal.disputes() if d.step is DisputeStep.SETTLED] == ["recording", "recording"]
    assert book.record(ItemKey.ADVANCE).status is FactStatus.CONFIRMED

    await deal.send(Role.WORKER, "Recording sahi hai", button=deal.button("advance", "ok"))  # tapped again
    assert deal.texts(Role.WORKER)[-1] == "Is sawaal ka jawab pehle hi likh liya hai."


async def test_kuch_aur_tay_hua_tha_asks_records_their_version_beside_the_record_and_sends_both(meta_deal):
    deal = meta_deal
    await disputed_by_the_worker(deal)
    await deal.send(Role.WORKER, "Kuch aur tay hua tha", button=deal.button("amount", "other"))
    assert deal.texts(Role.WORKER)[-1] == "Aapke hisaab se kul paisa mein kya tay hua tha? Likh kar ya voice note mein bhejiye."
    await deal.send(Role.WORKER, "15 hazaar tay hua tha, saath mein paint bhi")
    [version] = deal.of(TermDispute, step=DisputeStep.VERSION)
    book = deal.memory.book.deal(deal.id)
    fact = book.latest[version.version_fact_id]
    assert (fact.kind.value, fact.status, fact.said_by, fact.value_rupees, fact.source.value, fact.item) == (
        "term", FactStatus.SAID, Role.WORKER, 15000, "text", ItemKey.AMOUNT)
    record = book.record(ItemKey.AMOUNT)
    assert (record.value_rupees, record.status) == (13000, FactStatus.DISPUTED)  # never in place of the record
    for role in Role:
        assert deal.texts(role)[-1] == (
            "Kul paisa par do baatein hain:\n"
            '1. Call 1 mein (0:55): kul paisa ₹13,000 tay hua tha. Ramesh ji ne kaha: "12 mein nahi padta madam... 13 hazaar, '
            f'last. Isse neeche nahi", Sunita ji ne maana. Suniye: {BASE}{clip_path(record.id)}\n'
            '2. Ramesh ji ke hisaab se: "15 hazaar tay hua tha, saath mein paint bhi".\n'
            "Dono saath call par baat karke tay kar lijiye; call mein Gawah dono baatein saamne rakhega. "
            f"Call ke liye yeh link kholiye: {BASE}{call_path(deal.id, role)}"
        )
    assert not deal.of(ContractReady)
    await deal.send(Role.WORKER, "kal aaunga")  # once given, anything else goes the usual way
    assert len(deal.of(TermDispute, step=DisputeStep.VERSION)) == 1


async def test_a_voice_note_is_their_version_once_asked(twilio_deal):
    deal = twilio_deal
    await disputed_by_the_worker(deal)
    await deal.send(Role.WORKER, "1")
    await deal.send(Role.WORKER, "Kuch aur tay hua tha")
    note = "paint-05.ogg"
    await deal.send(Role.WORKER, media_url=f"https://example.invalid/media/{note}", media_type="audio/ogg", sid="wamid.V1")
    [version] = deal.of(TermDispute, step=DisputeStep.VERSION)
    assert version.version == note_words(note) and version.media_key.endswith("wamid.V1.ogg")
    fact = deal.memory.book.deal(deal.id).latest[version.version_fact_id]
    assert (fact.source.value, fact.media_url, fact.start) == ("voice_note", version.media_key, 0.0)
    assert not [e for e in deal.events if e.name == "whatsapp.voice_note"]  # the version, nothing else made of it
    assert deal.texts(Role.HIRER)[-1].startswith("Advance par do baatein hain:")


async def test_on_twilio_the_choices_are_numbered_and_typed(twilio_deal):
    deal = twilio_deal
    await disputed_by_the_worker(deal)
    assert deal.texts(Role.WORKER)[-2:] == [choose("kul paisa ₹13,000", True), choose("advance ₹3,000", True)]
    await deal.send(Role.WORKER, "1")  # the oldest question first
    assert deal.of(TermsConfirmed, person=Role.WORKER)[-1].item is ItemKey.AMOUNT
    await deal.send(Role.WORKER, "2")
    assert deal.texts(Role.WORKER)[-1].startswith("Aapke hisaab se advance mein")
    await deal.send(Role.WORKER, "5000")
    assert deal.of(TermDispute, step=DisputeStep.VERSION)[-1].version == "5000"


async def test_one_reminder_to_both_with_the_choices_again_never_repeated(meta_deal):
    deal = meta_deal
    await disputed_by_the_worker(deal)
    await deal.send(Role.WORKER, "Recording sahi hai", button=deal.button("amount", "ok"))
    sent = {role: len(deal.texts(role)) for role in Role}
    await deal.clock.advance(3600)
    await deal.settle()
    remind = 'Yaad dila raha hoon: advance ₹3,000 par baat abhi baaki hai (Ramesh ji ne "nahi" kaha tha). Agreement tab tak ruka hai.'
    assert deal.texts(Role.HIRER)[sent[Role.HIRER]:] == [remind]
    assert deal.texts(Role.WORKER)[sent[Role.WORKER]:] == [remind, choose("advance ₹3,000")]
    assert [d.item for d in deal.disputes() if d.step is DisputeStep.REMINDED] == [ItemKey.ADVANCE]  # the settled amount: none
    await deal.clock.advance(3 * 3600)
    await deal.settle()
    assert len(deal.texts(Role.HIRER)) == sent[Role.HIRER] + 1


async def test_a_restart_rebuilds_the_open_disputes_and_the_wait_for_a_version(meta_deal):
    deal = meta_deal
    await disputed_by_the_worker(deal)
    await deal.send(Role.WORKER, "Kuch aur tay hua tha", button=deal.button("amount", "other"))
    await deal.opened.close()

    again = await deal.opened.open()
    again.id = deal.id
    await again.send(Role.WORKER, "14 hazaar")  # still the version asked for before the restart
    [version] = again.of(TermDispute, step=DisputeStep.VERSION)
    assert version.item is ItemKey.AMOUNT and version.version == "14 hazaar"
    await again.send(Role.WORKER, "Recording sahi hai", button=deal.button("advance", "ok"))
    assert again.of(TermsConfirmed, person=Role.WORKER)[-1].item is ItemKey.ADVANCE  # the amount is still open
    await again.clock.advance(3600)  # the reminder is still due after the restart
    await again.settle()
    assert again.texts(Role.HIRER)[-1].startswith("Yaad dila raha hoon: kul paisa ₹13,000 par baat abhi baaki hai")
    assert not again.of(ContractReady)


async def test_a_change_both_confirm_settles_it_and_writes_the_agreement(meta_deal):
    deal = meta_deal
    await disputed_by_the_worker(deal)
    await deal.send(Role.WORKER, "Recording sahi hai", button=deal.button("advance", "ok"))
    amount = deal.memory.book.deal(deal.id).record(ItemKey.AMOUNT)
    deal.bus.publish(FactChanged(
        deal_id=deal.id, fact_id=amount.id, new_value="14,000 rupees", item=ItemKey.AMOUNT, proposed_by=Role.WORKER,
        confirmed_by=list(Role), status=ChangeStatus.CONFIRMED_BOTH, said="Chaudah hazaar theek hai.",
    ))
    await deal.settle()
    assert deal.disputes()[-1].how == "changed"
    assert deal.memory.book.deal(deal.id).current(ItemKey.AMOUNT).value_rupees == 14000
    assert deal.texts(Role.HIRER)[-3] == ("Kul paisa ab ₹14,000 hai, dono ne confirm kiya. Is par ab koi vivaad nahi. "
                                          "Ab sab tay hai: agreement thodi der mein yahin aayega.")
    assert deal.of(ContractReady)


async def test_owed_messages_use_the_figure_on_record_and_say_it_is_in_dispute(meta_deal):
    deal = meta_deal
    await disputed_by_the_worker(deal)
    await deal.send(Role.HIRER, "2000 cash diya")
    await deal.send(Role.WORKER, "haan")
    paid = deal.texts(Role.HIRER)[-1]
    assert paid == "₹2,000 mil gaya. Baaki ₹11,000 kaam ke baad. Kul paisa aur advance par vivaad hai."


async def test_a_call_back_cut_short_says_nothing_of_the_rest_and_a_withdrawal_confirms_only_that_term(meta_deal):
    deal = meta_deal
    await deal.call_back(Role.HIRER)
    await deal.call_back(Role.WORKER, {ItemKey.AMOUNT: NA}, reason="the person left")
    assert deal.texts(Role.HIRER)[-1].startswith(
        'Ramesh ji ne kul paisa ₹13,000 par "nahi" kaha. Agreement tab tak ruka hai jab tak yeh tay nahi hota.')
    await deal.send(Role.WORKER, "Recording sahi hai", button=deal.button("amount", "ok"))
    assert deal.of(TermsConfirmed, person=Role.WORKER)[-1].item is ItemKey.AMOUNT
    assert not deal.of(ContractReady)  # the rest was never read to them
