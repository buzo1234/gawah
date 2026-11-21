import asyncio
import time

import jwt
import pytest
from bridge_world import LIVEKIT_SETTINGS, FakeLiveKit
from fastapi.testclient import TestClient

from app.call.livekit import LISTENER, deal_of, room_name
from app.contracts import CallEnded, DealRequested, DealStatus, Person, Role, call_path
from app.main import create_app
from app.store import Store
from fakes import RAMESH, SUNITA


@pytest.fixture
def site(settings):
    """The whole app, with the bridge's LiveKit replaced. Yields (client, fake LiveKit, publish)."""
    app = create_app(settings)
    livekit = app.state.calls.livekit = FakeLiveKit()
    with TestClient(app) as client:

        def publish(event) -> None:
            assert client.post("/dev/publish", content=event.model_dump_json()).status_code == 200
            client.portal.call(app.state.bus.drain)

        publish(DealRequested(deal_id="d1", requested_by=SUNITA, other=Person(role=Role.WORKER, phone=RAMESH.phone)))
        yield client, livekit, publish


def claims(token: str) -> dict:
    return jwt.decode(token, LIVEKIT_SETTINGS.require("livekit_api_secret"), algorithms=["HS256"])


def test_call_page_for_a_valid_link(site):
    client, livekit, _ = site
    page = client.get(call_path("d1", Role.HIRER))
    assert page.status_code == 200
    assert "Judiye" in page.text and "Call chhodein" in page.text
    assert '"name": "Sunita"' in page.text and '"roleWords": "kaam dene wale"' in page.text
    # The other person's name is not known yet, and their phone number is never put on the page.
    worker = client.get(call_path("d1", Role.WORKER)).text
    assert '"name": null' in worker and '"otherName": "Sunita"' in worker and '"roleWords": "kaam karne wale"' in worker
    assert RAMESH.phone not in page.text and SUNITA.phone not in worker
    # What the page has to do: echo cancellation and friends, a way out of WhatsApp's browser, the three states.
    for needed in ("echoCancellation: true", "noiseSuppression: true", "autoGainControl: true",
                   "Open in Chrome", "ka intezaar", "Call chalu hai", "Call khatam ho gaya",
                   "yeh page khula rakhiye", "wakeLock.request('screen')", "Aapka microphone band ho gaya hai"):
        assert needed in page.text, needed
    # Opening the page (or WhatsApp fetching a preview of it) opens no room.
    assert livekit.created == []


def test_livekit_browser_client_is_served_by_us(site):
    client, _, _ = site
    page = client.get(call_path("d1", Role.HIRER)).text
    assert 'src="/call/static/livekit-client.umd.min.js"' in page
    assert "cdn." not in page and "https://" not in page  # nothing is fetched from a public address
    script = client.get("/call/static/livekit-client.umd.min.js")
    assert script.status_code == 200 and "LivekitClient" in script.text


@pytest.mark.parametrize("path", [
    "/call/no-such-deal/hirer", "/call/d1/judge", "/call/d1/gawah-ears", "/call/no-deal/worker",
])
def test_a_link_that_is_not_valid_gets_a_plain_page_and_no_room(site, path):
    client, livekit, _ = site
    page = client.get(path)
    assert page.status_code == 404 and "Yeh link sahi nahi hai" in page.text
    assert client.post(f"{path}/join").status_code == 404
    assert livekit.created == []


def test_a_name_cannot_break_out_of_the_page(site):
    client, _, publish = site
    nasty = Person(role=Role.HIRER, name="</script><script>alert(1)</script>", phone="+910000000009")
    publish(DealRequested(deal_id="d2", requested_by=nasty, other=RAMESH))
    assert "<script>alert(1)" not in client.get(call_path("d2", Role.HIRER)).text


def test_join_opens_one_room_and_gives_each_person_their_own_token(site):
    client, livekit, _ = site
    hirer = client.post(call_path("d1", Role.HIRER) + "/join").json()
    worker = client.post(call_path("d1", Role.WORKER) + "/join").json()
    assert livekit.created == ["deal-d1-1"] and list(livekit.open) == ["deal-d1-1"]
    assert hirer["url"] == worker["url"] == "wss://fake.livekit.invalid"

    mine, theirs = claims(hirer["token"]), claims(worker["token"])
    assert (mine["sub"], mine["name"]) == ("hirer", "Sunita")
    assert (theirs["sub"], theirs["name"]) == ("worker", "worker")  # no name known: the role stands in
    for token in (mine, theirs):
        grant = token["video"]
        assert grant["roomJoin"] is True and grant["room"] == "deal-d1-1" and deal_of(grant["room"]) == "d1"
        assert grant["canPublish"] is True and grant["canSubscribe"] is True and not grant.get("hidden")
        assert not grant.get("roomAdmin") and not grant.get("roomCreate")
        assert 0 < token["exp"] - time.time() <= 15 * 60


def test_the_listener_is_hidden_and_cannot_speak():
    token = claims(FakeLiveKit().token(room_name("d1", 1), LISTENER, listener=True))
    grant = token["video"]
    assert token["sub"] == "gawah-ears" and grant["room"] == "deal-d1-1"
    assert grant["hidden"] is True and grant["canPublish"] is False and grant["canSubscribe"] is True


def test_after_the_call_the_page_says_so_and_offers_a_new_one(site):
    client, livekit, publish = site
    publish(CallEnded(deal_id="d1", people=[SUNITA, RAMESH], room="deal-d1-1", duration=60))
    page = client.get(call_path("d1", Role.HIRER)).text
    assert '"ended": 1' in page and "Phir se baat karein" in page
    late = client.post(call_path("d1", Role.HIRER) + "/join?after=0")  # a page from before it ended
    assert (late.status_code, late.json()) == (410, {"error": "over", "ended": 1}) and livekit.created == []

    again = client.post(call_path("d1", Role.HIRER) + "/join?after=1").json()
    assert again["call_no"] == 2 and claims(again["token"])["video"]["room"] == "deal-d1-2"
    other = client.post(call_path("d1", Role.WORKER) + "/join?after=0").json()  # a call is open: join it
    assert other["call_no"] == 2 and livekit.created == ["deal-d1-2"]
    assert '"ended": 0' in client.get(call_path("d1", Role.WORKER)).text


def test_join_says_so_when_livekit_cannot_be_reached(site):
    client, livekit, _ = site

    async def down(name: str) -> None:
        raise TimeoutError

    livekit.create_room = down
    assert client.post(call_path("d1", Role.HIRER) + "/join").status_code == 503


def test_server_shutdown_ends_an_open_call_and_deletes_its_room(settings, tmp_path):
    app = create_app(settings)
    calls = app.state.calls
    livekit = calls.livekit = FakeLiveKit()
    calls.folder = tmp_path / "recordings"
    seen, uploaded = [], []

    async def note(event) -> None:
        seen.append(event)

    async def upload(path: str, key: str, content_type: str) -> str:
        uploaded.append(key)
        return key

    calls.upload = upload
    app.state.bus.subscribe("call.ended", note)
    with TestClient(app) as client:
        client.post("/dev/publish", content=DealRequested(deal_id="d1", requested_by=SUNITA, other=RAMESH).model_dump_json())
        client.portal.call(app.state.bus.drain)
        for role in Role:
            assert client.post(call_path("d1", role) + "/join").status_code == 200
            client.portal.call(lambda role=role: livekit.open["deal-d1-1"].joined(role.value))
        assert seen == [] and livekit.deleted == []
    [ended] = seen
    assert ended.reason == "shutdown" and sorted(uploaded) == ["recordings/d1/1/hirer.wav", "recordings/d1/1/worker.wav"]
    assert livekit.deleted == ["deal-d1-1"] and livekit.listeners[0].disconnected
    # The call.ended sent during shutdown is in the event log, so the deal is not left "in call".
    store = Store(settings.database_path)
    asyncio.run(store.open())
    assert [e.reason for e in asyncio.run(store.events("d1", "call.ended"))] == ["shutdown"]
    assert asyncio.run(store.deal("d1")).status is DealStatus.CALL_ENDED
    asyncio.run(store.close())
