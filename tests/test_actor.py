"""The actor (app/actor) on fakes: its routes, one actor at a time, and that it always leaves."""

import time

import jwt
import pytest
from bridge_world import LIVEKIT_SETTINGS, FakeLiveKit
from fastapi.testclient import TestClient

from app import actor as actor_stream
from app.actor import actor as actor_module
from app.actor import persona
from app.actor import ActorSettings
from app.contracts import CallEnded, CallKind, DealRequested, Person, Role
from app.main import create_app
from fakes import RAMESH, SUNITA


class FakeSeat:
    def __init__(self, log) -> None:
        self.joined, self.left, self.people, self.room = None, False, set(), None
        self.on_heard = lambda pcm: None
        self.on_closed = lambda: None
        self.spoken = bytearray()
        self.given_ms = 0.0

    async def join(self, url, token):
        self.joined = (url, token)

    def present(self):
        return self.people

    def say(self, pcm):
        self.spoken += pcm

    def speaking(self):
        return bool(self.spoken)

    def heard_ms(self):
        return 120.0

    def clear(self):
        self.spoken.clear()

    async def leave(self):
        self.left = True


class FakeLink:
    def __init__(self, config, on_event, log) -> None:
        self.config, self.on_event, self.sent, self.opened, self.closed = config, on_event, [], False, False

    async def open(self):
        self.opened = True

    async def send(self, event):
        self.sent.append(event)

    async def close(self):
        self.closed = True


@pytest.fixture
def world(tmp_path, request):
    settings = ActorSettings(
        _env_file=None, database_path=str(tmp_path / "test.db"), actor_routes=True,
        access_key=getattr(request, "param", None),
        **{k: getattr(LIVEKIT_SETTINGS, k) for k in ("livekit_url", "livekit_api_key", "livekit_api_secret")},
    )
    app = create_app(settings)
    livekit = app.state.calls.livekit = FakeLiveKit()
    seats, links = [], []
    app.state.actor_seat = lambda log: seats.append(FakeSeat(log)) or seats[-1]
    app.state.actor_link = lambda config, on_event, log: links.append(FakeLink(config, on_event, log)) or links[-1]
    with TestClient(app) as client:

        def publish(event) -> None:
            sent = client.post("/dev/publish", content=event.model_dump_json(), headers={"x-access-key": settings.access_key.get_secret_value()} if settings.access_key else {})
            assert sent.status_code == 200
            client.portal.call(app.state.bus.drain)

        publish(DealRequested(deal_id="d1", requested_by=SUNITA, other=Person(role=Role.WORKER, phone=RAMESH.phone)))
        yield client, app, livekit, seats, links, publish


def wait_until(check, seconds: float = 3.0) -> None:
    end = time.monotonic() + seconds
    while not check():
        assert time.monotonic() < end, "timed out"
        time.sleep(0.05)


def test_the_routes_are_off_unless_asked_for(settings, monkeypatch):
    monkeypatch.setenv("ACTOR_ROUTES", "false")
    with TestClient(create_app(settings)) as client:
        assert client.get("/actor/status", params={"deal_id": "d1"}).status_code == 404
        assert client.post("/actor/start", json={"deal_id": "d1", "role": "worker", "kind": "deal"}).status_code == 404


def test_the_tunnel_is_refused(world):
    client, *_ = world
    assert client.get("/actor/status", params={"deal_id": "d1"}, headers={"cf-connecting-ip": "1.2.3.4"}).status_code == 403
    started = client.post("/actor/start", json={"deal_id": "d1", "role": "worker", "kind": "deal"}, headers={"x-forwarded-for": "1.2.3.4"})
    assert started.status_code == 403


@pytest.mark.parametrize("world", ["test-access-key"], indirect=True)
def test_on_a_server_with_the_access_key_the_routes_work_through_the_proxy_with_the_cookie(world):
    """Behind Caddy every request has x-forwarded-for. The dashboard's toggle and the framed
    call page's status poll send the board's cookie; a person's own phone has none, gets 401,
    and its page stops asking."""
    client, *_ = world
    proxy = {"x-forwarded-for": "203.0.113.9"}
    assert client.get("/actor/status", params={"deal_id": "d1"}, headers=proxy).status_code == 401
    assert client.post("/actor/start", json={"deal_id": "d1", "role": "worker", "kind": "deal"}, headers=proxy).status_code == 401
    assert client.post("/access", data={"key": "test-access-key", "next": "/dashboard"}).status_code == 200
    assert client.get("/actor/status", params={"deal_id": "d1"}, headers=proxy).json()["active"] is False
    started = client.post("/actor/start", json={"deal_id": "d1", "role": "worker", "kind": "deal"}, headers=proxy)
    assert started.status_code == 200 and started.json()["active"] is True
    assert client.get("/actor/status", params={"deal_id": "d1"}, headers=proxy).json()["role"] == "worker"
    assert client.post("/actor/stop", json={"deal_id": "d1", "role": "worker"}, headers=proxy).status_code == 200


def test_it_takes_the_workers_seat_through_the_pages_own_join(world):
    client, app, livekit, seats, links, _ = world
    assert client.get("/actor/status", params={"deal_id": "d1"}).json() == {"active": False, "role": None, "kind": None}
    started = client.post("/actor/start", json={"deal_id": "d1", "role": "worker", "kind": "deal"})
    assert started.status_code == 200, started.text
    assert started.json() | {"seconds": None} == {
        "active": True, "role": "worker", "kind": "deal", "state": "waiting", "seconds": None, "name": None, "room": "deal-d1-1",
    }
    # The bridge opened the room as for a page, and the token is the worker's own.
    assert livekit.created == ["deal-d1-1"]
    url, token = seats[0].joined
    claims = jwt.decode(token, LIVEKIT_SETTINGS.require("livekit_api_secret"), algorithms=["HS256"])
    assert url == LIVEKIT_SETTINGS.livekit_url and claims["sub"] == "worker" and claims["video"]["room"] == "deal-d1-1"
    # It plays Ramesh from the demo story, with a man's voice and the wait tool.
    config = links[0].config
    assert links[0].opened and config["audio"]["output"]["voice"] == "ash" and config["tools"] == [persona.WAIT_TOOL]
    said = config["instructions"]
    assert "You are Ramesh" in said and "You: Do coat aur putty ka touch-up" in said and "Sunita: Pachees hazaar bahut zyada" in said
    assert "[After the line above, Gawah asks Sunita when the balance will be paid.]" in said
    # The hirer arrives: the call is on.
    seats[0].people = {"hirer", "gawah", "gawah-ears"}
    wait_until(lambda: client.get("/actor/status", params={"deal_id": "d1"}).json()["state"] == "on")
    assert client.get("/actor/status", params={"deal_id": "other"}).json()["active"] is False


def test_one_actor_at_a_time(world):
    client, *_ = world
    body = {"deal_id": "d1", "role": "worker", "kind": "deal"}
    assert client.post("/actor/start", json=body).status_code == 200
    assert client.post("/actor/start", json=body).status_code == 200  # asked again: the same actor
    busy = client.post("/actor/start", json={**body, "role": "hirer"})
    assert busy.status_code == 409 and busy.json()["detail"]["role"] == "worker"


def test_it_leaves_when_the_call_ends(world):
    client, app, livekit, seats, links, publish = world
    client.post("/actor/start", json={"deal_id": "d1", "role": "worker", "kind": "deal"})
    publish(CallEnded(deal_id="d1", people=[SUNITA, RAMESH], room="deal-d1-1", duration=60, kind=CallKind.DEAL))
    wait_until(lambda: seats[0].left and links[0].closed)
    assert app.state.actor.reason == "the call ended"
    assert client.get("/actor/status", params={"deal_id": "d1"}).json()["active"] is False
    # A call-back's end is not the deal call's.
    client.post("/actor/start", json={"deal_id": "d1", "role": "worker", "kind": "deal"})
    publish(CallEnded(deal_id="d1", people=[RAMESH], room="callback-x", duration=60, kind=CallKind.CALLBACK))
    assert client.get("/actor/status", params={"deal_id": "d1"}).json()["active"] is True


def test_it_leaves_when_stopped_or_when_the_room_closes(world):
    client, app, livekit, seats, links, _ = world
    client.post("/actor/start", json={"deal_id": "d1", "role": "worker", "kind": "deal"})
    assert client.post("/actor/stop", json={"deal_id": "d1", "role": "worker"}).json()["active"] is False
    assert seats[0].left and links[0].closed and app.state.actor.reason == "stopped from the dashboard"
    client.post("/actor/start", json={"deal_id": "d1", "role": "worker", "kind": "deal"})
    client.portal.call(lambda: _call(seats[1].on_closed))
    wait_until(lambda: seats[1].left)
    assert app.state.actor.reason == "the room closed"


async def _call(f):
    f()


@pytest.mark.parametrize("limit, reason, people", [("ALONE_S", "nobody else came", set()), ("MAX_S", "time limit", {"hirer"})])
def test_it_never_sits_in_a_room(world, monkeypatch, limit, reason, people):
    client, app, livekit, seats, links, _ = world
    monkeypatch.setattr(actor_module, limit, 0.2 if limit == "ALONE_S" else {"deal": 0.2, "callback": 0.2})
    client.post("/actor/start", json={"deal_id": "d1", "role": "worker", "kind": "deal"})
    seats[0].people = people
    wait_until(lambda: seats[0].left)
    assert app.state.actor.reason == reason


def test_a_call_back_with_nothing_to_confirm_is_refused(world):
    client, *_ = world
    refused = client.post("/actor/start", json={"deal_id": "d1", "role": "worker", "kind": "callback"})
    assert refused.status_code == 409


def test_it_speaks_stops_when_talked_over_and_answers_wait_with_silence(world):
    client, app, livekit, seats, links, _ = world
    client.post("/actor/start", json={"deal_id": "d1", "role": "worker", "kind": "deal"})
    link, seat = links[0], seats[0]
    on = lambda event: client.portal.call(link.on_event, event)  # noqa: E731
    on({"type": "response.output_audio.delta", "response_id": "r1", "item_id": "i1", "delta": "AAAA"})
    assert bytes(seat.spoken) == b"\0\0\0"
    on({"type": "input_audio_buffer.speech_started"})
    assert not seat.spoken and link.sent[-1] == {
        "type": "conversation.item.truncate", "item_id": "i1", "content_index": 0, "audio_end_ms": 120,
    }
    on({"type": "response.output_audio.delta", "response_id": "r1", "item_id": "i1", "delta": "AAAA"})
    assert not seat.spoken  # the rest of the reply that was talked over is dropped
    on({"type": "response.done", "response": {"output": [{"type": "function_call", "status": "completed", "call_id": "c1", "name": "wait"}]}})
    assert link.sent[-1]["item"] == {"type": "function_call_output", "call_id": "c1", "output": '{"ok": true}'}
    assert not any(e["type"] == "response.create" for e in link.sent)
    on({"type": "response.output_audio_transcript.done", "transcript": "Haan  theek hai."})
    assert app.state.actor.said == ["Haan theek hai."]


def test_what_it_hears_goes_to_the_model_in_100_ms_pieces(world):
    client, app, livekit, seats, links, _ = world
    client.post("/actor/start", json={"deal_id": "d1", "role": "worker", "kind": "deal"})
    frame = bytes(960)
    for _ in range(5):
        client.portal.call(lambda: _call(lambda: seats[0].on_heard(frame)))
    wait_until(lambda: any(e["type"] == "input_audio_buffer.append" for e in links[0].sent))


def test_the_callback_persona_says_yes_to_each_term():
    said = persona.instructions(Role.HIRER, "callback", 1, {Role.HIRER: "Sunita", Role.WORKER: None})
    assert "You are Sunita" in said and "Haan, sahi hai" in said and "Ramesh" in said


def test_call_two_has_the_wrong_total_and_the_balcony():
    said = persona.instructions(Role.WORKER, "deal", 2, {Role.HIRER: "Sunita", Role.WORKER: "Ramesh"})
    assert "Total pachees hazaar tay hua tha na?" in said and "Uske do hazaar extra lagenge" in said
    assert persona.instructions(Role.WORKER, "deal", 3, {}) == persona.instructions(Role.WORKER, "deal", 2, {})


def test_the_script_uses_the_deals_names_and_no_gendered_address():
    for call_no in (1, 2):
        said = persona.instructions(Role.WORKER, "deal", call_no, {Role.HIRER: "Karan", Role.WORKER: "Namesh"})
        assert "Main Namesh" in said and "Karan ji" in said and "de dunga" in said
        assert not any(w in said for w in ("Ramesh", "Sunita", "madam", "Madam", "sir", "her flat"))
    as_hirer = persona.instructions(Role.HIRER, "deal", 1, {Role.HIRER: "Karan", Role.WORKER: "Namesh"})
    assert "Main Karan hoon" in as_hirer and "Dhanyavaad Namesh ji" in as_hirer and "Sunita" not in as_hirer


def test_with_no_names_the_story_names_are_kept():
    said = persona.instructions(Role.WORKER, "deal", 1, {})
    assert "Main Ramesh, painter" in said and "Dhanyavaad Ramesh ji" in said and "Sunita ji" in said
    assert "madam" not in said.lower()


def test_register_is_a_stream():
    assert callable(actor_stream.register)


def test_the_status_learns_the_name_the_call_told(world):
    client, app, livekit, seats, links, publish = world
    client.post("/actor/start", json={"deal_id": "d1", "role": "worker", "kind": "deal"})
    assert client.get("/actor/status", params={"deal_id": "d1"}).json()["name"] is None
    from app.contracts import CallStarted
    publish(CallStarted(deal_id="d1", people=[SUNITA, RAMESH], room="deal-d1-1", call_no=1))
    assert client.get("/actor/status", params={"deal_id": "d1"}).json()["name"] == "Ramesh"
