"""The access key on a public server: what it guards, what stays public, the cookie, the
clip links sent on WhatsApp, and the refusals that only apply on the server."""

import re
import time
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from whatsapp_world import BASE, RAMESH, SUNITA, World

from app.access import COOKIE, sign_path
from app.config import Settings
from app.contracts import WHATSAPP_WEBHOOK_PATH, Role, call_path, callback_path, clip_path
from app.main import create_app
from app.records.reader import Reading
from app.store import Store
from app.whatsapp.settings import WhatsAppSettings
from fakes.samples import sample_events
from fakes.memory import FakeMemory, silent_wav
from test_sentinel import deal_facts

KEY = "open-sesame-test-key"
HTML = {"accept": "text/html"}
PROXY = {"x-forwarded-for": "203.0.113.9"}  # what Caddy adds to every request
GUARDED = [
    "/dashboard", "/dashboard/state", "/dashboard/phone", "/dashboard/static/app.js",
    "/actor/status", "/memory/chain/d1", "/memory/clip/f1", "/memory/state?deal=d1",
]


@pytest.fixture
def keyed(tmp_path):
    return Settings(_env_file=None, database_path=str(tmp_path / "t.db"), access_key=KEY, public_base_url=BASE)


@pytest.fixture
def client(keyed):
    with TestClient(create_app(keyed)) as c:
        yield c


@pytest.mark.parametrize("path", GUARDED)
def test_guarded_routes_ask_for_the_key(client, path):
    r = client.get(path)
    assert r.status_code == 401 and r.json() == {"detail": "access key needed"}


def test_a_browser_gets_the_form_and_the_right_key_sets_an_http_only_cookie(client):
    page = client.get("/dashboard?deal=d1", headers=HTML)
    assert page.status_code == 401 and 'name="key"' in page.text and 'value="/dashboard?deal=d1"' in page.text
    wrong = client.post("/access", data={"key": "nope", "next": "/dashboard"}, follow_redirects=False)
    assert wrong.status_code == 401 and "Galat key" in wrong.text and COOKIE not in client.cookies
    right = client.post("/access", data={"key": KEY, "next": "/dashboard?deal=d1"}, follow_redirects=False)
    assert right.status_code == 303 and right.headers["location"] == "/dashboard?deal=d1"
    cookie = right.headers["set-cookie"]
    assert "HttpOnly" in cookie and "samesite=lax" in cookie.lower() and KEY not in cookie
    for path in ["/dashboard", "/dashboard/state", "/dashboard/phone", "/dashboard/static/app.js"]:
        assert client.get(path).status_code == 200, path
    with client.websocket_connect("/dashboard/ws"):
        pass


def test_the_form_never_sends_anyone_off_the_site(client):
    r = client.post("/access", data={"key": KEY, "next": "//evil.example/x"}, follow_redirects=False)
    assert r.headers["location"] == "/dashboard"


def test_the_websocket_is_closed_without_the_key(client):
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/dashboard/ws") as ws:
            ws.receive_text()


def test_a_script_can_send_the_key_in_a_header_and_dev_publish_takes_it_through_the_proxy(client):
    line = sample_events()[2].model_dump_json()
    assert client.post("/dev/publish", content=line, headers=PROXY).status_code == 401
    ok = client.post("/dev/publish", content=line, headers={**PROXY, "x-access-key": KEY})
    assert ok.status_code == 200
    assert client.post("/dev/publish", content=line, headers={**PROXY, "x-access-key": "nope"}).status_code == 401


def test_public_routes_stay_public(client):
    assert client.get("/health").json() == {"status": "ok"}
    for path in [call_path("no-such-deal", Role.HIRER), callback_path("no-such-deal", Role.HIRER)]:
        assert client.get(path, headers=HTML).status_code in (200, 404), path  # not 401: the link decides
        assert client.post(path + "/join").status_code not in (401, 403), path
    assert client.get(WHATSAPP_WEBHOOK_PATH, params={"hub.mode": "subscribe"}).status_code == 403  # wrong token
    form = {"From": "whatsapp:+919800000001", "Body": "hello", "MessageSid": "SM1", "NumMedia": "0"}
    assert client.post(WHATSAPP_WEBHOOK_PATH, data=form).status_code == 200
    # An image the second phone attached is read by the model, which has no key: its name is the secret.
    assert client.get("/dashboard/media/" + "a" * 32 + ".jpg").status_code == 404
    assert client.post("/dashboard/media", content=b"x", headers={"content-type": "image/png"}).status_code == 401


def test_the_second_phone_works_through_the_proxy_once_the_key_is_given(client):
    client.post("/access", data={"key": KEY, "next": "/dashboard"})
    sent = client.post("/dashboard/phone/send", json={"phone": "+919800000002", "text": "namaste"}, headers=PROXY)
    assert sent.status_code == 200 and sent.json()["status"] == 200


def test_without_the_key_nothing_changes(settings):
    with TestClient(create_app(settings)) as c:
        assert c.get("/dashboard").status_code == 200
        assert c.get("/memory/chain/d1").status_code == 200
        assert c.get("/access").status_code == 404
        line = sample_events()[2].model_dump_json()
        assert c.post("/dev/publish", content=line, headers=PROXY).status_code == 403  # still local only
        assert c.post("/dashboard/phone/send", json={"phone": "+1", "text": "x"}, headers=PROXY).status_code == 403


def test_a_signed_clip_link_opens_until_it_expires(client):
    path = clip_path("f1")
    assert client.get(sign_path(KEY, path)).status_code == 404  # past the guard: memory has no such fact
    assert client.get(sign_path("another-key", path)).status_code == 401
    assert client.get(sign_path(KEY, clip_path("f2")).replace("f2", "f1")).status_code == 401
    assert client.get(sign_path(KEY, path, now=time.time() - 2 * 86400)).status_code == 401
    assert client.get(sign_path(KEY, "/memory/chain/d1")).status_code == 401  # only clips are signed


async def test_the_clip_link_the_sentinel_sends_on_whatsapp_opens_without_the_key(bus, tmp_path, keyed):
    store = Store(keyed.database_path)
    await store.open()
    world = World(bus, store, keyed, memory=FakeMemory([], clips={"f-advance": silent_wav()}))
    world.reader.readings["5000 advance diya"] = Reading(kind="advance", amount=5000)
    try:
        deal_id = await world.start_deal()
        world.memory.facts.extend(deal_facts(deal_id))
        await world.say(SUNITA, "5000 advance diya", name="Sunita")
        [line] = [t for t in world.texts_to(RAMESH) if t and "Wo pal yahan suniye" in t]
    finally:
        await world.bot.stop()
        await bus.drain()
        await store.close()
    link = urlsplit(re.search(r"https?://\S+", line).group(0))
    assert f"{link.scheme}://{link.netloc}" == BASE and link.path == clip_path("f-advance")
    assert "exp=" in link.query and "sig=" in link.query
    with TestClient(create_app(keyed.model_copy(update={"database_path": str(tmp_path / "other.db")}))) as c:
        assert c.get(f"{link.path}?{link.query}").status_code == 404  # through the guard; this app has no audio
        assert c.get(link.path).status_code == 401


def test_on_the_server_meta_without_its_app_secret_refuses_to_start(tmp_path):
    meta = dict(_env_file=None, database_path=str(tmp_path / "t.db"), whatsapp_provider="meta", meta_app_secret=None)
    with pytest.raises(RuntimeError, match="META_APP_SECRET"):
        create_app(WhatsAppSettings(**meta, access_key=KEY))
    create_app(WhatsAppSettings(**meta))  # the laptop still starts, with the warning


def test_on_the_server_an_unsigned_meta_post_is_refused(tmp_path):
    base = dict(_env_file=None, database_path=str(tmp_path / "t.db"), whatsapp_provider="twilio", meta_app_secret=None)
    body = {"object": "whatsapp_business_account", "entry": []}
    with TestClient(create_app(WhatsAppSettings(**base, access_key=KEY))) as c:
        assert c.post(WHATSAPP_WEBHOOK_PATH, json=body).status_code == 403
    with TestClient(create_app(WhatsAppSettings(**base))) as c:
        assert c.post(WHATSAPP_WEBHOOK_PATH, json=body).status_code == 200
