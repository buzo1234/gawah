import asyncio

from fastapi.testclient import TestClient

from app.config import Settings
from app.contracts import parse_event
from app.main import STREAMS, create_app
from fakes.samples import sample_events


def test_app_starts_and_health_answers(settings):
    with TestClient(create_app(settings)) as client:
        assert client.get("/health").json() == {"status": "ok"}
        assert "Gawah" in client.get("/dashboard").text


def test_every_stream_folder_is_registered():
    names = {s.__name__ for s in STREAMS}
    assert {f"app.{n}" for n in ("call", "ears", "brain", "mouth", "whatsapp", "records", "contract", "dashboard")} <= names
    assert all(callable(s.register) for s in STREAMS)


def test_published_event_reaches_the_dashboard_socket_and_the_event_log(settings):
    app = create_app(settings)
    events = sample_events("d-app")
    with TestClient(app) as client, client.websocket_connect("/dashboard/ws") as ws:
        for event in events:
            response = client.post("/dev/publish", content=event.model_dump_json())
            assert response.status_code == 200, response.text
        # Streams answer some of these events with events of their own, so look only at ours.
        received = []
        while len(received) < len(events):
            event = parse_event(ws.receive_text())
            if event in events:
                received.append(event)
        assert received == events
        # The socket and the event log are separate subscriptions: the socket having
        # the last event does not mean the log has written it yet.
        client.portal.call(app.state.bus.drain)
        logged = client.portal.call(app.state.store.events, "d-app")
        assert [e for e in logged if e in events] == events


def test_dev_publish_rejects_bad_events_and_tunnel_traffic(settings):
    line = sample_events()[2].model_dump_json()
    with TestClient(create_app(settings)) as client:
        assert client.post("/dev/publish", content='{"name": "no.such.event"}').status_code == 422
        assert client.post("/dev/publish", content=line, headers={"cf-connecting-ip": "1.2.3.4"}).status_code == 403
    off = Settings(_env_file=None, database_path=settings.database_path, dev_routes=False)
    with TestClient(create_app(off)) as client:
        assert client.post("/dev/publish", content=line).status_code == 404


def test_a_stream_can_add_routes_subscriptions_and_startup_and_shutdown_work(settings):
    app = create_app(settings)
    bus, calls = app.state.bus, []

    def register(app, bus):
        async def on_line(event):
            calls.append(event.text)

        async def startup():
            calls.append("startup")

        async def shutdown():
            calls.append("shutdown")

        bus.subscribe("transcript.line", on_line)
        app.state.on_startup.append(startup)
        app.state.on_shutdown.append(shutdown)

        @app.get("/stream/ping")
        async def ping():
            return {"pong": True}

    register(app, bus)
    line = sample_events()[2]
    with TestClient(app) as client:
        assert client.get("/stream/ping").json() == {"pong": True}
        client.post("/dev/publish", content=line.model_dump_json())
        client.portal.call(bus.drain)
    assert calls == ["startup", line.text, "shutdown"]


def test_missing_keys_do_not_stop_startup_and_are_never_shown(settings):
    assert settings.openai_api_key is None
    try:
        settings.require("openai_api_key")
    except RuntimeError as e:
        assert "OPENAI_API_KEY" in str(e)
    else:
        raise AssertionError("require should fail on a missing key")
    filled = Settings(_env_file=None, openai_api_key="sk-secret", verified_numbers="+911111111111, +912222222222")
    assert "sk-secret" not in repr(filled) and "1111" not in repr(filled)
    assert filled.require("openai_api_key") == "sk-secret"
    assert filled.verified_number_list == ["+911111111111", "+912222222222"]
