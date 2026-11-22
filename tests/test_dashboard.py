import asyncio
import json
from urllib.parse import parse_qsl, urlsplit

import pytest
import uvicorn
from fastapi.testclient import TestClient
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route

from app.config import Settings
from app.contracts import NO_DEAL, WHATSAPP_WEBHOOK_PATH, Direction, WhatsAppMessage
from app.dashboard import phone
from app.main import create_app
from fakes import RAMESH, SUNITA
from fakes.replayer import load, play
from fakes.samples import sample_events
from fakes.tail import tail

PNG = b"\x89PNG\r\n\x1a\n" + b"not really a picture"


def publish(client: TestClient, *events) -> None:
    for event in events:
        assert client.post("/dev/publish", content=event.model_dump_json()).status_code == 200
    client.portal.call(client.app.state.bus.drain)


def as_json(events) -> list[dict]:
    return [e.model_dump(mode="json") for e in events]


def only(published, listed: list[dict]) -> list[dict]:
    """Streams answer some events with events of their own (the brain's checklist, the
    call-back links), so keep only the ones this test published."""
    ids = {e.event_id for e in published}
    return [e for e in listed if e["event_id"] in ids]


def capture_webhook(app) -> list[tuple[dict, dict]]:
    """Stand in for the whatsapp stream's intake: keep each request's headers and form.
    Put first, so it still catches the post once the real route exists."""
    got: list[tuple[dict, dict]] = []

    async def webhook(request: Request) -> Response:
        form = dict(parse_qsl((await request.body()).decode(), keep_blank_values=True))
        got.append((dict(request.headers), form))
        return Response("<Response/>", media_type="text/xml")

    app.router.routes.insert(0, Route(WHATSAPP_WEBHOOK_PATH, webhook, methods=["POST"]))
    return got


def test_the_page_and_its_files_are_served(settings):
    with TestClient(create_app(settings)) as client:
        page = client.get("/dashboard")
        assert page.status_code == 200 and "Gawah" in page.text
        assert "/dashboard/static/style.css" in page.text and "/dashboard/static/app.js" in page.text
        assert 'id="phone-frame"' in page.text and 'allow="microphone *; autoplay *"' in page.text
        phone_page = client.get("/dashboard/phone")
        assert phone_page.status_code == 200 and "/dashboard/static/phone.js" in phone_page.text
        for name in ("base.css", "style.css", "phone.css", "app.js", "state.js", "render.js", "dom.js", "phone.js", "crew-state.js", "board.js", "lanes.js", "moments.js", "graph.js", "timeline.js", "detail.js", "wave.js", "chain.js", "clips.js", "logo.png", "fonts/public-sans-latin-600-normal.woff2", "fonts/ibm-plex-mono-latin-400-normal.woff2"):
            assert client.get(f"/dashboard/static/{name}").status_code == 200, name
        for text in (page.text, phone_page.text):
            assert "http://" not in text and "https://" not in text  # nothing from outside
        assert client.get("/dashboard/state").json() == {"deal_id": None, "deals": [], "events": []}


def test_a_fresh_page_load_gets_every_event_published_so_far(settings):
    fixture = load("fixtures/call_missing_balance.json")
    played = []

    async def keep(event):
        played.append(event)

    asyncio.run(play(fixture, keep, speed=0, deal_id="d-call"))
    half = len(played) // 2
    early = WhatsAppMessage(deal_id=NO_DEAL, direction=Direction.IN, phone=SUNITA.phone, text="Deal karni hai")
    samples = sample_events("d-next")
    ours = [early, *played, *samples]
    with TestClient(create_app(settings)) as client:
        publish(client, early, *played[:half])
        state = client.get("/dashboard/state").json()
        assert state["deal_id"] == "d-call"
        assert only(ours, state["events"]) == as_json([early, *played[:half]])  # mid-call: nothing lost, in order

        publish(client, *played[half:])
        assert only(ours, client.get("/dashboard/state").json()["events"]) == as_json([early, *played])

        # A second deal becomes the one shown; the first can still be picked.
        publish(client, *samples)
        state = client.get("/dashboard/state").json()
        assert state["deal_id"] == "d-next"
        assert [d["id"] for d in state["deals"]] == ["d-next", "d-call"]
        assert state["deals"][0]["names"] == {"hirer": "Sunita", "worker": "Ramesh"}
        # Chats are per phone, not per deal, so the message from before any deal comes too.
        assert only(ours, state["events"]) == as_json([early, *samples])
        picked = client.get("/dashboard/state", params={"deal": "d-call"}).json()
        assert picked["deal_id"] == "d-call"
        assert only(ours, picked["events"]) == as_json([early, *played, samples[-1]])
        assert client.get("/dashboard/state", params={"deal": "no-such"}).json()["deal_id"] == "d-next"


async def test_the_socket_still_feeds_the_tail(settings, capsys):
    app = create_app(settings)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning"))
    serving = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.01)
    port = server.servers[0].sockets[0].getsockname()[1]
    tailing = asyncio.create_task(tail(f"http://127.0.0.1:{port}"))
    try:
        # Events sent before the tail has connected are not for it, so knock until one lands.
        printed = ""
        async with asyncio.timeout(5):
            while not printed:
                app.state.bus.publish(sample_events("knock")[2])
                await asyncio.sleep(0.05)
                printed = capsys.readouterr().out
        await app.state.bus.drain()
        await asyncio.sleep(0.1)
        capsys.readouterr()

        events = sample_events("d-tail")
        for event in events:
            app.state.bus.publish(event)
        # Streams answer some of these with events of their own, which the tail prints too.
        sent = [e.model_dump_json() for e in events]
        printed = ""
        async with asyncio.timeout(5):
            while sent[-1] not in printed.splitlines():
                await asyncio.sleep(0.02)
                printed += capsys.readouterr().out
        assert [line for line in printed.splitlines() if line in sent] == sent
    finally:
        tailing.cancel()
        await asyncio.gather(tailing, return_exceptions=True)
        server.should_exit = True
        await serving


def test_a_second_phone_message_reaches_the_webhook_in_the_provider_shape(settings, tmp_path, monkeypatch):
    monkeypatch.setattr(phone, "MEDIA_DIR", tmp_path / "media")
    app = create_app(settings)
    got = capture_webhook(app)
    with TestClient(app) as client:
        sent = client.post("/dashboard/phone/send", json={"phone": "+91 00000 00002", "text": "Kaam ho gaya", "profile_name": "Ramesh"})
        assert sent.status_code == 200 and sent.json()["status"] == 200
        headers, form = got[0]
        assert headers["content-type"] == "application/x-www-form-urlencoded"
        assert form["From"] == "whatsapp:+910000000002" and form["WaId"] == "910000000002"
        assert form["To"].startswith("whatsapp:+")
        assert form["Body"] == "Kaam ho gaya" and form["NumMedia"] == "0" and form["ProfileName"] == "Ramesh"
        assert form["MessageSid"].startswith("SM") and len(form["MessageSid"]) == 34
        assert form["MessageSid"] == form["SmsSid"] == form["SmsMessageSid"]
        assert form["AccountSid"].startswith("AC") and len(form["AccountSid"]) == 34
        assert "MediaUrl0" not in form and "x-twilio-signature" not in headers
        assert sent.json()["form"] == form

        # With an image: it is stored, has an address, and the address goes in the form.
        stored = client.post("/dashboard/media", content=PNG, headers={"content-type": "image/png"}).json()
        assert client.get(urlsplit(stored["url"]).path).content == PNG
        sent = client.post("/dashboard/phone/send", json={"phone": RAMESH.phone, "media_url": stored["url"], "media_type": stored["content_type"]})
        assert sent.status_code == 200
        _, form = got[1]
        assert form["NumMedia"] == "1" and form["Body"] == ""
        assert form["MediaUrl0"] == stored["url"] and form["MediaContentType0"] == "image/png"
        assert form["MessageSid"].startswith("MM")

        # It publishes nothing itself: the whatsapp stream does that.
        client.portal.call(app.state.bus.drain)
        assert client.portal.call(app.state.store.events) == []


def test_the_second_phone_refuses_what_it_should(settings, tmp_path, monkeypatch):
    monkeypatch.setattr(phone, "MEDIA_DIR", tmp_path / "media")
    app = create_app(settings)

    async def webhook_down(request: Request) -> Response:
        return Response(status_code=503)

    app.router.routes.insert(0, Route(WHATSAPP_WEBHOOK_PATH, webhook_down, methods=["POST"]))
    with TestClient(app) as client:
        # The webhook's own answer is passed back, not hidden.
        assert client.post("/dashboard/phone/send", json={"phone": RAMESH.phone, "text": "hello"}).json()["status"] == 503
        assert client.post("/dashboard/phone/send", json={"phone": RAMESH.phone, "text": "  "}).status_code == 422
        assert client.post("/dashboard/phone/send", json={"phone": "none", "text": "hello"}).status_code == 422
        tunnel = {"cf-connecting-ip": "1.2.3.4"}
        assert client.post("/dashboard/phone/send", json={"phone": RAMESH.phone, "text": "hi"}, headers=tunnel).status_code == 403
        assert client.post("/dashboard/media", content=PNG, headers={"content-type": "image/png", **tunnel}).status_code == 403
        assert client.post("/dashboard/media", content=b"<html>", headers={"content-type": "text/html"}).status_code == 415
        assert client.get("/dashboard/media/..%2f..%2fetc%2fpasswd").status_code == 404
        assert client.get("/dashboard/media/" + "0" * 32 + ".png").status_code == 404


def test_the_second_phone_signs_as_the_provider_does_when_it_has_the_token(tmp_path):
    # Twilio's own worked example (also the test vector in its Python library).
    form = {"CallSid": "CA1234567890ABCDE", "Caller": "+12349013030", "Digits": "1234", "From": "+12349013030", "To": "+18005551212"}
    assert phone.signature("https://mycompany.com/myapp.php?foo=1&bar=2", form, "12345") == "0/KCTR6DLpKmkAf8muzZqo1nDgQ="

    settings = Settings(
        _env_file=None, database_path=str(tmp_path / "test.db"),
        twilio_auth_token="token", public_base_url="https://gawah.example",
    )
    app = create_app(settings)
    got = capture_webhook(app)
    with TestClient(app) as client:
        client.post("/dashboard/phone/send", json={"phone": RAMESH.phone, "text": "hello"})
    headers, form = got[0]
    assert headers["x-twilio-signature"] == phone.signature("https://gawah.example" + WHATSAPP_WEBHOOK_PATH, form, "token")


def test_a_reply_button_tapped_on_the_second_phone_reaches_the_webhook_as_meta_sends_a_tap(tmp_path):
    """Only Meta shows reply buttons, so a tap is posted in Meta's shape, with the button's
    id (which names the question it answers), and signed as Meta signs when the app secret is set."""
    settings = phone.PhoneSettings(_env_file=None, database_path=str(tmp_path / "test.db"), meta_app_secret="secret")
    app = create_app(settings)
    got: list[tuple[dict, bytes]] = []

    async def webhook(request: Request) -> Response:
        got.append((dict(request.headers), await request.body()))
        return Response(status_code=200)

    app.router.routes.insert(0, Route(WHATSAPP_WEBHOOK_PATH, webhook, methods=["POST"]))
    with TestClient(app) as client:
        tap = {"id": "yes:9d50609bb11b", "title": "Haan, sahi hai"}
        sent = client.post("/dashboard/phone/send", json={"phone": SUNITA.phone, "text": tap["title"], "button": tap, "profile_name": "Sunita"})
        assert sent.status_code == 200 and sent.json()["status"] == 200
    headers, body = got[0]
    assert headers["content-type"] == "application/json"
    assert headers["x-hub-signature-256"] == phone.meta_signature("secret", body)
    payload = json.loads(body)
    value = payload["entry"][0]["changes"][0]["value"]
    message = value["messages"][0]
    digits = SUNITA.phone.lstrip("+")
    assert payload["object"] == "whatsapp_business_account" and value["contacts"] == [{"wa_id": digits, "profile": {"name": "Sunita"}}]
    assert message["from"] == digits and message["type"] == "interactive"
    assert message["interactive"] == {"type": "button_reply", "button_reply": tap}
    # Read the way the whatsapp stream reads Meta's posts: a button, carrying its id.
    from app.whatsapp.meta_inbound import parse_meta
    (read,), _, _ = parse_meta(payload, lambda media_id: media_id)
    assert (read.kind, read.button, read.text, read.phone) == ("button", tap["id"], tap["title"], SUNITA.phone)
