import pytest

from app.config import Settings
from app.contracts import NO_DEAL, Backing, DealStatus, Direction, Role
from app.log import deal_log, mask_phone
from app.store import S3, Store
from fakes import RAMESH, SUNITA
from fakes.call import end_call, say, start_call
from fakes.replayer import replay
from fakes.whatsapp import (
    ask_to_confirm, confirm_record, reply_timed_out, request_deal, send_record, whatsapp_message,
)


@pytest.fixture
async def store(bus, settings):
    store = Store(settings.database_path)
    await store.open()
    bus.subscribe_all(store.record_event)
    yield store
    await store.close()


async def test_store_is_filled_from_events(bus, store):
    deal_id = request_deal(bus).deal_id
    await bus.drain()
    deal = await store.deal(deal_id)
    assert deal.status is DealStatus.REQUESTED
    assert deal.person(Role.HIRER) == SUNITA
    assert deal.person(Role.WORKER).phone == RAMESH.phone and deal.person(Role.WORKER).name is None

    start_call(bus, deal_id)
    say(bus, deal_id, Role.HIRER, "Hello Ramesh ji", 0.5, 2.0, line_no=1)
    say(bus, deal_id, Role.WORKER, "Namaste madam", 2.4, 3.6, line_no=2)
    await bus.drain()
    deal = await store.deal(deal_id)
    assert deal.status is DealStatus.IN_CALL and deal.person(Role.WORKER) == RAMESH
    end_call(bus, deal_id)
    await bus.drain()
    assert (await store.deal(deal_id)).status is DealStatus.CALL_ENDED
    assert [(line.speaker, line.text) for line in await store.transcript(deal_id)] == [
        (Role.HIRER, "Hello Ramesh ji"), (Role.WORKER, "Namaste madam"),
    ]
    assert await store.deal("no-such-deal") is None


async def test_records_and_the_fake_whatsapp_flow(bus, store):
    deal_id = request_deal(bus).deal_id
    backed = send_record(bus, deal_id, Role.HIRER, "Advance", backing=Backing.BACKED, amount=8000, transaction_id="T1").record
    cash = send_record(bus, deal_id, Role.HIRER, "2,000 cash diya", amount=2000).record
    asked = ask_to_confirm(bus, deal_id, cash)
    assert asked.confirm_by is Role.WORKER
    reply_timed_out(bus, deal_id, Role.WORKER, "Kya 2,000 cash mila?", record_id=cash.id)
    confirm_record(bus, deal_id, cash.id, Role.WORKER)
    await bus.drain()

    records = await store.records(deal_id)
    assert [(r.id, r.backing, r.confirmed) for r in records] == [
        (backed.id, Backing.BACKED, None), (cash.id, Backing.UNBACKED, True),
    ]
    names = [e.name for e in await store.events(deal_id)]
    assert names == [
        "deal.requested", "record.received", "record.received", "record.confirm_requested",
        "reply.timeout", "record.confirmed",
    ]
    assert len(await store.events(deal_id, "record.received")) == 2


async def test_whatsapp_messages_are_logged_before_and_after_the_deal_exists(bus, store, settings):
    first = whatsapp_message(
        bus, NO_DEAL, Direction.IN, SUNITA.phone, "Ramesh painter se deal karni hai", provider_id="SM1"
    )
    deal_id = request_deal(bus).deal_id
    link = whatsapp_message(
        bus, deal_id, Direction.OUT, RAMESH.phone, "Call ka link", role=Role.WORKER, simulated=True
    )
    proof = whatsapp_message(
        bus, deal_id, Direction.IN, SUNITA.phone, role=Role.HIRER, provider_id="SM2",
        media_url="https://example.invalid/screenshot.jpg", media_type="image/jpeg",
    )
    await bus.drain()

    assert await store.events(NO_DEAL) == [first]
    assert await store.deal(NO_DEAL) is None
    assert await store.events(deal_id, "whatsapp.message") == [link, proof]
    assert (first.role, first.simulated, link.simulated, link.provider_id) == (None, False, True, None)

    await store.close()
    reopened = Store(settings.database_path)
    await reopened.open()
    assert await reopened.events(name="whatsapp.message") == [first, link, proof]
    await reopened.close()


async def test_a_replayed_call_lands_in_the_log_and_survives_reopening(bus, store, settings):
    deal_id = await replay(bus, "fixtures/call_two_amounts.json", speed=0)
    await bus.drain()
    await store.close()
    reopened = Store(settings.database_path)
    await reopened.open()
    assert len(await reopened.transcript(deal_id)) == 33
    assert [e.name for e in await reopened.events(deal_id)][-1] == "call.ended"
    await reopened.close()


def test_logs_carry_the_deal_id_and_mask_phones(caplog):
    with caplog.at_level("INFO"):
        deal_log("gawah.test", "d7").info("sent link to %s", mask_phone("+919812345678"))
    assert "deal=d7 sent link to ***5678" in caplog.text
    assert "98123" not in caplog.text


async def test_a_signed_link_points_at_the_buckets_regional_address():
    """Signing is done locally, so this needs no network and no real keys."""
    s3 = S3(Settings(
        _env_file=None, aws_access_key_id="AKIAEXAMPLE", aws_secret_access_key="not-a-real-secret",
        aws_session_token="not-a-real-token", aws_default_region="us-west-2", s3_bucket="gawah-test",
    ))
    url = await s3.signed_url("contracts/d7.pdf")
    # The global host (gawah-test.s3.amazonaws.com) answers a new bucket with a redirect.
    assert url.startswith("https://gawah-test.s3.us-west-2.amazonaws.com/contracts/d7.pdf?")
