import pytest
from contract_fakes import (
    FakeFiles, FakeSpeaker, FakeWriter, agreed_items, checklist, fake_fingerprint, fake_render_pdf,
)

from app.contract.stream import ContractStream
from app.contracts import CallEnded, ContractReady, ItemKey, Role, TermsConfirmed, TermsDisputed
from app.store import Store
from fakes.replayer import replay

CALL = "fixtures/call_two_amounts.json"


class Rig:
    """The contract stream on a real bus and store, with everything outside it faked."""

    def __init__(self, bus, store, files=None):
        self.bus, self.files, self.speaker = bus, files or FakeFiles(), FakeSpeaker()
        self.stream = ContractStream(
            bus, store, FakeWriter(), self.speaker, self.files, fake_render_pdf, fake_fingerprint
        )
        self.ready: list[ContractReady] = []
        self.off = bus.subscribe_all(self.stream.on_event)
        bus.subscribe(ContractReady, self._collect)

    async def _collect(self, event):
        self.ready.append(event)

    async def call(self, deal_id=None) -> str:
        deal_id = await replay(self.bus, CALL, speed=0, deal_id=deal_id)
        self.bus.publish(checklist(deal_id))
        await self.bus.drain()  # the call is in the store long before anyone confirms
        return deal_id

    def confirm(self, deal_id, role, item=None, said=None):
        self.bus.publish(TermsConfirmed(deal_id=deal_id, person=role, item=item, said=said))

    def dispute(self, deal_id, role, item=None):
        self.bus.publish(TermsDisputed(deal_id=deal_id, person=role, item=item))

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


@pytest.fixture
async def rig(bus, store):
    return Rig(bus, store)


async def test_both_confirm_and_the_contract_is_written_uploaded_and_announced(rig):
    deal_id = await rig.call()
    rig.confirm(deal_id, Role.HIRER)
    rig.confirm(deal_id, Role.WORKER)
    [ready] = await rig.settle()

    assert ready.deal_id == deal_id
    assert (ready.pdf_key, ready.voice_summary_key) == (f"contracts/{deal_id}.pdf", f"contracts/{deal_id}.ogg")
    assert ready.pdf_url == f"https://signed.invalid/{ready.pdf_key}"
    assert ready.voice_summary_url == f"https://signed.invalid/{ready.voice_summary_key}"
    assert rig.files.uploaded[ready.pdf_key][1] == "application/pdf"
    assert rig.files.uploaded[ready.voice_summary_key][1] == "audio/ogg"
    assert ready.items == agreed_items()
    assert "13,000 rupees" in ready.text and "सुनीता (Sunita), फ़ोन / phone +910000000001" in ready.text
    # the amount, line 12, starts at 59.8s
    assert "2. कीमत और उसमें क्या शामिल है / The price and what it covers  [कॉल / call 0:59]" in ready.text
    assert "कहा / Said" not in ready.text and "SHA-256" not in ready.text  # nothing to print, so no line
    assert len(rig.speaker.spoken) == 1


async def test_the_words_each_person_said_and_the_recordings_fingerprints_are_printed(rig, caplog):
    deal_id = await rig.call()
    recordings = {"hirer": f"recordings/{deal_id}/hirer.wav", "worker": f"recordings/{deal_id}/missing.wav"}
    rig.bus.publish(CallEnded(deal_id=deal_id, duration=145.0, recording_keys=recordings))
    rig.confirm(deal_id, Role.HIRER, said="haan sab sahi hai")
    rig.confirm(deal_id, Role.WORKER)
    [ready] = await rig.settle()

    assert "कहा / Said: “haan sab sahi hai”" in ready.text and ready.text.count("कहा / Said") == 1
    assert "and lasted 2 min 25 sec." in ready.text
    hirer_print = await fake_fingerprint(f"https://signed.invalid/{recordings['hirer']}")
    assert f"First party's audio: {hirer_print}" in ready.text
    assert "Second party's audio" not in ready.text  # that recording could not be read: no line, not a blank
    assert f"deal={deal_id} could not read the worker recording (RuntimeError)" in caplog.text
    assert "signed.invalid" not in caplog.text  # a signed link never goes to the log


async def test_one_person_confirming_is_not_enough(rig):
    deal_id = await rig.call()
    rig.confirm(deal_id, Role.HIRER)
    rig.confirm(deal_id, Role.HIRER)
    assert await rig.settle() == []


async def test_a_dispute_cancels_that_persons_confirmation_until_they_confirm_again(rig):
    deal_id = await rig.call()
    rig.confirm(deal_id, Role.HIRER)
    rig.dispute(deal_id, Role.HIRER, ItemKey.AMOUNT)
    rig.confirm(deal_id, Role.WORKER)
    assert await rig.settle() == []

    rig.confirm(deal_id, Role.HIRER, ItemKey.AMOUNT)
    assert len(await rig.settle()) == 1


async def test_it_is_written_once_and_again_only_after_a_dispute_is_settled(rig):
    deal_id = await rig.call()
    rig.confirm(deal_id, Role.HIRER)
    rig.confirm(deal_id, Role.WORKER)
    rig.confirm(deal_id, Role.WORKER)
    rig.bus.publish(checklist(deal_id))
    assert len(await rig.settle()) == 1

    rig.dispute(deal_id, Role.WORKER)
    assert len(await rig.settle()) == 1
    rig.confirm(deal_id, Role.WORKER)
    first, second = await rig.settle()
    assert second.pdf_key == first.pdf_key  # the new one replaces the old


async def test_confirming_every_agreed_term_one_by_one_counts_as_all(rig):
    deal_id = await replay(rig.bus, CALL, speed=0)
    rig.bus.publish(checklist(deal_id, pending=(ItemKey.BALANCE,)))
    rig.confirm(deal_id, Role.HIRER)
    for key in ItemKey:
        if key is not ItemKey.BALANCE:
            assert await rig.settle() == []
            rig.confirm(deal_id, Role.WORKER, key)
    [ready] = await rig.settle()
    assert "These were not agreed on the call: when the balance is paid and against what." in ready.text


async def test_two_deals_at_the_same_time_do_not_mix(rig):
    a, b = await rig.call("deal-a"), await rig.call("deal-b")
    rig.confirm(a, Role.HIRER)
    rig.confirm(b, Role.WORKER)
    rig.confirm(a, Role.WORKER)
    assert [r.deal_id for r in await rig.settle()] == [a]

    rig.confirm(b, Role.HIRER)
    assert [r.deal_id for r in await rig.settle()] == [a, b]
    assert "Reference no.: GW-DEAL-B" in rig.ready[1].text


async def test_no_agreed_terms_means_nothing_to_write(rig):
    rig.confirm("no-checklist", Role.HIRER)
    rig.confirm("no-checklist", Role.WORKER)
    assert await rig.settle() == []


async def test_s3_down_fails_loudly_and_publishes_nothing(bus, store, caplog):
    rig = Rig(bus, store, FakeFiles(fail=True))
    deal_id = await rig.call()
    rig.confirm(deal_id, Role.HIRER)
    rig.confirm(deal_id, Role.WORKER)
    assert await rig.settle() == []
    assert f"deal={deal_id} CONTRACT NOT WRITTEN" in caplog.text and "ExpiredToken" in caplog.text

    rig.files.fail = False  # new keys in .env: the next confirmation writes it
    rig.confirm(deal_id, Role.WORKER)
    assert len(await rig.settle()) == 1


async def test_after_a_restart_it_catches_up_from_the_store(bus, store):
    before = Rig(bus, store)
    deal_id = await before.call()
    before.confirm(deal_id, Role.HIRER)
    await before.settle()

    before.off()
    after = Rig(bus, store)  # a new process knows nothing; the store has the earlier events
    after.confirm(deal_id, Role.WORKER)
    assert [r.deal_id for r in await after.settle()] == [deal_id]
