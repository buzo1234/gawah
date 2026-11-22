"""A restart while the agreement is being written (deal 957df1d89287: the second yes at
06:32:09, a deploy at 06:32:24). The contract stream writes, on start, every agreement the
event log says is due and never got written, and nothing that was. The whole app on its
fakes (tests/offline.py), stopped mid-write and built again on the same database."""

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import httpx
import pytest
from contract_fakes import FakeFiles, FakeSpeaker, FakeWriter, checklist, fake_fingerprint, fake_render_pdf

from app.contract.stream import ContractStream
from app.contracts import (
    MEMORY_STATE, CallEnded, CallKind, CallStarted, ChangeStatus, ContractReady, DealRequested, FactChanged, ItemKey,
    Role, TermsConfirmed,
)
from app.store import Store
from fakes.replayer import replay
from tests.offline import offline_app
from tests.test_whole_flow import PHONE, Flow

CALL = "fixtures/call_missing_balance.json"


@asynccontextmanager
async def running(db):
    """The app on its fakes, from startup to shutdown, as uvicorn runs it."""
    app = offline_app(db)
    transport = httpx.ASGITransport(app=app)
    async with app.router.lifespan_context(app), httpx.AsyncClient(transport=transport, base_url="http://gawah.test") as client:
        yield Flow(app, client, None)


async def written(flow: Flow) -> list[ContractReady]:
    """Every contract.ready in the event log, once the stream has nothing left to do."""
    await flow.app.state.contract.idle()
    await flow.settle()
    return await flow.store.events(name="contract.ready")


def stall_the_pdf(flow: Flow):
    """Chrome never finishes: the write hangs until the server stops under it. Returns a
    wait for the write to be stuck there with every event before it in the log."""
    started = asyncio.Event()

    async def hang(html, out):
        started.set()
        await asyncio.Event().wait()

    async def stuck() -> None:
        await asyncio.wait_for(started.wait(), 5)
        await flow.settle()  # the store's own queue: on the server it was long written

    flow.app.state.contract._render_pdf = hang
    return stuck


async def deal_with_a_call(flow: Flow) -> str:
    await flow.whatsapp(Role.HIRER, PHONE[Role.WORKER].removeprefix("+91"), name="Sunita")
    [requested] = flow.of(DealRequested)
    return await replay(flow.bus, CALL, speed=0, deal_id=requested.deal_id)


async def both_confirm(flow: Flow, deal_id: str) -> None:
    """Each says yes to every term memory has agreed, term by term, as on their call-backs.
    (A replay at speed 0 outruns the brain, so its checklist stays pending; memory's terms do not.)"""
    memory = getattr(flow.app.state, MEMORY_STATE)
    await flow.settle()
    terms = {k: t.current for k in ItemKey if (t := await memory.get_term(deal_id, k)).current}
    assert terms
    for role in Role:
        for key, fact in terms.items():
            flow.bus.publish(TermsConfirmed(deal_id=deal_id, person=role, item=key, value=fact.value, said="haan ji"))


async def change_the_amount_on_call_2(flow: Flow, deal_id: str) -> None:
    """Both agree 26,000 on a second call and confirm it through Gawah."""
    amount = (await getattr(flow.app.state, MEMORY_STATE).get_term(deal_id, ItemKey.AMOUNT)).current
    flow.bus.publish(CallStarted(deal_id=deal_id, call_no=2, room=f"replay-{deal_id}-2", ts=datetime.now(UTC)))
    for status, confirmed in ((ChangeStatus.PROPOSED, []), (ChangeStatus.CONFIRMED_ONE, [Role.HIRER]),
                              (ChangeStatus.CONFIRMED_BOTH, list(Role))):
        flow.bus.publish(FactChanged(
            deal_id=deal_id, change_id="c-1", fact_id=amount.id, new_value="26,000", status=status,
            item=ItemKey.AMOUNT, proposed_by=Role.HIRER, confirmed_by=confirmed, said="haan ji",
        ))
    await flow.settle()
    flow.bus.publish(CallEnded(deal_id=deal_id, call_no=2, kind=CallKind.DEAL, room=f"replay-{deal_id}-2", duration=60.0))


async def test_both_confirmed_and_the_server_restarted_mid_write_so_v1_is_written_once_on_start(tmp_path, caplog):
    async with running(tmp_path / "gawah.db") as flow:
        stalled = stall_the_pdf(flow)
        deal_id = await deal_with_a_call(flow)
        await both_confirm(flow, deal_id)
        await stalled()
    # stopped mid-write: both confirmations in the log, no agreement
    async with running(tmp_path / "gawah.db") as flow:
        [ready] = await written(flow)
        assert ready.deal_id == deal_id and ready.pdf_key.endswith("-v1.pdf")
        for role in Role:  # and it went to both, as any agreement does
            assert ready.pdf_url in flow.sent_to(role) or ready.voice_summary_url in flow.sent_to(role)
    assert f"deal={deal_id} version 1 was due and never written" in caplog.text

    async with running(tmp_path / "gawah.db") as flow:  # and again: written, so nothing
        assert len(await written(flow)) == 1


async def test_a_deal_whose_agreement_was_written_gets_nothing_on_restart(tmp_path, caplog):
    async with running(tmp_path / "gawah.db") as flow:
        deal_id = await deal_with_a_call(flow)
        await both_confirm(flow, deal_id)
        await flow.until(ContractReady)
        assert len(await written(flow)) == 1
    caplog.clear()
    async with running(tmp_path / "gawah.db") as flow:
        assert len(await written(flow)) == 1
        assert flow.of(ContractReady) == []
    assert "was due and never written" not in caplog.text


async def test_a_change_both_confirmed_with_no_v2_gets_v2_on_restart(tmp_path):
    async with running(tmp_path / "gawah.db") as flow:
        deal_id = await deal_with_a_call(flow)
        await both_confirm(flow, deal_id)
        await flow.until(ContractReady)
        stalled = stall_the_pdf(flow)
        await change_the_amount_on_call_2(flow, deal_id)
        await stalled()
        assert len(await flow.store.events(name="contract.ready")) == 1
    async with running(tmp_path / "gawah.db") as flow:
        v1, v2 = await written(flow)
        assert v2.pdf_key.endswith("-v2.pdf") and "26,000" in v2.text and "26,000" not in v1.text
    async with running(tmp_path / "gawah.db") as flow:
        assert len(await written(flow)) == 2


async def test_with_callbacks_off_the_calls_confirmations_get_v1_on_restart(tmp_path, monkeypatch):
    monkeypatch.setenv("CALLBACKS_ENABLED", "false")
    async with running(tmp_path / "gawah.db") as flow:
        stalled = stall_the_pdf(flow)
        deal_id = await deal_with_a_call(flow)  # no call-back: the call's end confirms what both agreed
        await stalled()
        assert flow.of(TermsConfirmed) and await flow.store.events(name="contract.ready") == []
    async with running(tmp_path / "gawah.db") as flow:
        [ready] = await written(flow)
        assert ready.deal_id == deal_id and ready.pdf_key.endswith("-v1.pdf")
    async with running(tmp_path / "gawah.db") as flow:
        assert len(await written(flow)) == 1


async def test_with_callbacks_off_a_change_confirmed_on_call_2_gets_v2_on_restart(tmp_path, monkeypatch):
    monkeypatch.setenv("CALLBACKS_ENABLED", "false")
    async with running(tmp_path / "gawah.db") as flow:
        deal_id = await deal_with_a_call(flow)
        await flow.until(ContractReady)
        stalled = stall_the_pdf(flow)
        await change_the_amount_on_call_2(flow, deal_id)
        await stalled()
    async with running(tmp_path / "gawah.db") as flow:
        v1, v2 = await written(flow)
        assert v2.pdf_key.endswith("-v2.pdf") and "26,000" in v2.text


# The contract stream alone, on a real bus and store: what can race on start, and a failed write.

@pytest.fixture
async def store(bus, settings):
    store = Store(settings.database_path)
    await store.open()
    bus.subscribe_all(store.record_event)
    yield store
    await store.close()


def contract_stream(bus, store, files=None, render=fake_render_pdf) -> tuple[ContractStream, list[ContractReady]]:
    stream = ContractStream(bus, store, FakeWriter(), FakeSpeaker(), files or FakeFiles(), render, fake_fingerprint, retry_after=0)
    bus.subscribe_all(stream.on_event)
    ready: list[ContractReady] = []

    async def keep(event):
        ready.append(event)

    bus.subscribe(ContractReady, keep)
    return stream, ready


async def confirmed_deal_in_the_log(bus) -> str:
    """A deal both confirmed, published while no contract stream is listening: the log a
    restart starts from."""
    deal_id = await replay(bus, "fixtures/call_two_amounts.json", speed=0)
    bus.publish(checklist(deal_id))
    for role in Role:
        bus.publish(TermsConfirmed(deal_id=deal_id, person=role))
    await bus.drain()
    return deal_id


async def test_an_event_for_the_deal_during_the_startup_write_does_not_start_a_second(bus, store):
    deal_id = await confirmed_deal_in_the_log(bus)
    release, rendering = asyncio.Event(), asyncio.Event()

    async def slow_pdf(html, out):
        rendering.set()
        await release.wait()
        await fake_render_pdf(html, out)

    stream, ready = contract_stream(bus, store, render=slow_pdf)
    bus.publish(TermsConfirmed(deal_id=deal_id, person=Role.WORKER))  # arrives while the stream starts
    await stream.start()
    await asyncio.wait_for(rendering.wait(), 5)
    bus.publish(TermsConfirmed(deal_id=deal_id, person=Role.HIRER))  # and another while it writes
    bus.publish(checklist(deal_id))
    await bus.drain()
    release.set()
    await stream.idle()
    await bus.drain()
    assert [r.pdf_key for r in ready] == [f"contracts/{deal_id}-v1.pdf"]


class FailsOnce(FakeFiles):
    async def upload(self, path, key, content_type=None):
        if not self.uploaded and not self.fail:
            self.fail = True
            raise RuntimeError("Could not connect to the endpoint URL")
        self.fail = False
        return await super().upload(path, key, content_type)


async def test_a_failed_write_is_tried_once_more_and_then_written(bus, store, caplog):
    deal_id = await confirmed_deal_in_the_log(bus)
    stream, ready = contract_stream(bus, store, FailsOnce())
    await stream.start()
    await stream.idle()
    await bus.drain()
    assert [r.pdf_key for r in ready] == [f"contracts/{deal_id}-v1.pdf"]
    assert f"deal={deal_id} contract write failed; trying once more" in caplog.text
    assert "CONTRACT NOT WRITTEN" not in caplog.text


async def test_a_write_that_fails_twice_is_logged_loudly_and_publishes_nothing(bus, store, caplog):
    deal_id = await confirmed_deal_in_the_log(bus)
    files = FakeFiles(fail=True)
    stream, ready = contract_stream(bus, store, files)
    await stream.start()
    await stream.idle()
    await bus.drain()
    assert ready == []
    assert caplog.text.count(f"deal={deal_id} contract write failed; trying once more") == 1
    assert f"deal={deal_id} CONTRACT NOT WRITTEN after one retry" in caplog.text
