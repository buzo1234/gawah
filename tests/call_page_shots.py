"""Screenshots of the deal call page and the call-back page in every state, at phone sizes.
Not collected by pytest. Reaches nothing outside: it serves the offline app (tests/offline.py)
and swaps the LiveKit browser client for a stand-in that the script drives, so the pages'
own join, speaking, mute and leave code runs; no room is opened.

    PYTHONPATH=. uv run python tests/call_page_shots.py

Saves fixtures/call-page-shots/ios/<width>x<height>/<page>-<n>-<state>.png and checks what each
state says, including the two the scripts cannot reach in a real room: a phone that refuses to play
sound until it is tapped (the call must stay up), and an AI playing this person (app/actor), from a
stand-in for /actor/status. A real room is proved by tests/bridge_live.py.
"""

import asyncio
import json
from urllib.parse import quote
import tempfile
from pathlib import Path

import httpx
import uvicorn
from browser import Chrome

from app.contracts import DealRequested, Person, Role, call_path, callback_path
from fakes import RAMESH, SUNITA
from tests.offline import offline_app

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "fixtures" / "call-page-shots" / "ios"
SIZES = [(390, 844), (360, 640)]
ACTOR = {"active": True, "kind": "deal", "state": "on", "seconds": 83, "room": "deal-shots-1"}

# Stands in for window.LivekitClient. The real bundle still loads, but its global is ignored.
FAKE_LIVEKIT = """
(() => {
  const RoomEvent = { TrackSubscribed: 'trackSubscribed', TrackUnsubscribed: 'trackUnsubscribed',
    ParticipantConnected: 'participantConnected', ParticipantDisconnected: 'participantDisconnected',
    ActiveSpeakersChanged: 'activeSpeakersChanged', Reconnecting: 'reconnecting', Reconnected: 'reconnected',
    TrackMuted: 'trackMuted', TrackUnmuted: 'trackUnmuted', Disconnected: 'disconnected',
    AudioPlaybackStatusChanged: 'audioPlaybackChanged' };
  const DisconnectReason = { CLIENT_INITIATED: 1, DUPLICATE_IDENTITY: 2, ROOM_DELETED: 5 };
  const refused = () => new DOMException('Permission denied', 'NotAllowedError');
  // An actor's status for /actor/status, kept across a reload, as the page asks for it as it loads.
  const actor = JSON.parse(localStorage.getItem('fakeActor') || 'null');
  if (actor) window.__watchActor = true;
  const fake = window.__fake = { micRefused: false, audioRefused: false, fakeJoin: false, hold: null, room: null, calls: [],
    arrive(id) { const p = { identity: id }; this.room.remoteParticipants.set(id, p); this.room.emit('participantConnected', p); },
    speak(...ids) { this.room.emit('activeSpeakersChanged', ids.map((identity) => ({ identity }))); },
    end() { this.room.state = 'disconnected'; this.room.emit('disconnected', DisconnectReason.ROOM_DELETED); } };
  class Room {
    constructor(options) {
      this.options = options; this.handlers = {}; this.remoteParticipants = new Map(); this.state = 'disconnected';
      this.canPlaybackAudio = true; fake.room = this;
      this.localParticipant = { identity: 'me',
        publishTrack: async () => fake.calls.push('publishTrack'),
        setMicrophoneEnabled: async (on, opts) => { fake.calls.push(['setMicrophoneEnabled', on, opts]); if (fake.micRefused) throw refused(); } };
    }
    on(e, f) { (this.handlers[e] ||= []).push(f); return this; }
    emit(e, ...a) { (this.handlers[e] || []).forEach((f) => f(...a)); }
    async connect() { if (fake.hold) await fake.hold; this.state = 'connected'; }
    async startAudio() {
      fake.calls.push('startAudio');
      const before = this.canPlaybackAudio;
      this.canPlaybackAudio = !fake.audioRefused;
      if (before !== this.canPlaybackAudio) this.emit('audioPlaybackChanged', this.canPlaybackAudio);
      if (fake.audioRefused) throw refused();
    }
    async disconnect() { this.state = 'disconnected'; this.emit('disconnected', DisconnectReason.CLIENT_INITIATED); }
  }
  const client = { Room, RoomEvent, DisconnectReason,
    createLocalAudioTrack: async (opts) => {
      fake.calls.push(['createLocalAudioTrack', opts]);
      if (fake.micRefused) throw refused();
      return { mediaStreamTrack: new EventTarget(), stop() {}, mute: async () => fake.calls.push('mute'), unmute: async () => fake.calls.push('unmute') };
    } };
  Object.defineProperty(window, 'LivekitClient', { get: () => client, set() {} });
  const realFetch = window.fetch.bind(window);
  window.fetch = (url, init) => {
    if (actor && String(url).includes('/actor/status')) return Promise.resolve(new Response(JSON.stringify(actor), { status: 200 }));
    return fake.fakeJoin && String(url).endsWith('/join')
      ? Promise.resolve(new Response(JSON.stringify({ url: 'wss://fake.invalid', token: 't' }), { status: 200 }))
      : realFetch(url, init);
  };
})();
"""

VIEW = """JSON.stringify({state: document.body.dataset.state, title: document.getElementById('title').textContent,
  status: document.getElementById('status').textContent, join: document.getElementById('join').hidden ? null : document.getElementById('join').textContent,
  leave: !document.getElementById('leave').hidden, gawah: document.getElementById('gawah-line').textContent,
  talking: [...document.querySelectorAll('.talking')].map((e) => e.id)})"""


async def main(port: int = 8771) -> None:
    home = Path(tempfile.mkdtemp(prefix="gawah-call-shots-"))
    app = offline_app(home / "gawah.db")
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    serving = asyncio.create_task(server.serve())
    url = f"http://127.0.0.1:{port}"
    failures: list[str] = []

    def check(ok: bool, what: str) -> None:
        print(f"  {'ok  ' if ok else 'FAIL'} {what}")
        if not ok:
            failures.append(what)

    while not server.started:
        await asyncio.sleep(0.05)
    async with httpx.AsyncClient(base_url=url, timeout=10) as http:
        nameless = Person(role=Role.WORKER, phone=RAMESH.phone)  # the worker's name is not known yet
        for deal in (DealRequested(deal_id="shots", requested_by=SUNITA, other=RAMESH),
                     DealRequested(deal_id="noname", requested_by=SUNITA, other=nameless)):
            (await http.post("/dev/publish", content=deal.model_dump_json())).raise_for_status()
        await asyncio.sleep(0.3)

    for width, height in SIZES:
        folder = OUT / f"{width}x{height}"
        print(f"{width}x{height}")
        async with Chrome(port=9341, width=width, height=height) as chrome:
            await chrome.send("Emulation.setDeviceMetricsOverride", width=width, height=height, deviceScaleFactor=2, mobile=True)
            await chrome.send("Page.addScriptToEvaluateOnNewDocument", source=FAKE_LIVEKIT)

            async def at(state: str):
                await chrome.wait_for(f"document.body.dataset.state === '{state}'")
                await asyncio.sleep(0.6)  # let the rings reach the middle of their pulse
                return json.loads(await chrome.js(VIEW))

            async def shot(name: str) -> None:
                await chrome.shot(folder / f"{name}.png")

            async def actor(status: dict | None) -> None:
                await chrome.js(f"localStorage.setItem('fakeActor', {json.dumps(json.dumps(status))})")
                await chrome.reload()

            async def tapped() -> list:
                return await chrome.js("[document.body.dataset.state, !document.getElementById('tap-audio').hidden]")

            # The deal call, as Sunita: Ramesh is the other person. Before joining: the incoming call.
            await chrome.goto(url + call_path("shots", Role.HIRER))
            await actor(None)
            v = await at("idle")
            check(v["title"] == "Ramesh" and v["join"] == "Join" and not v["leave"]
                  and v["status"] == "Gawah will witness this call. It will be recorded.", f"deal idle: {v}")
            await shot("deal-1-incoming")
            await chrome.js("document.getElementById('join').click()")
            v = await at("waiting")
            check(v["status"] == "Waiting for Ramesh..." and v["leave"] and v["join"] is None, f"deal waiting: {v}")
            asked = await chrome.js("JSON.stringify(__fake.calls.slice(0, 2))")
            check(asked.startswith('["startAudio",["createLocalAudioTrack"') and '"echoCancellation":true' in asked
                  and '"noiseSuppression":true' in asked, f"sound unlocked and microphone asked inside the tap: {asked}")
            await shot("deal-2-waiting")
            await chrome.js("__fake.arrive('worker'); __fake.arrive('gawah'); __fake.speak('gawah'); startedAt = Date.now() - 154000")
            await asyncio.sleep(1.1)
            v = await at("on")
            timer = await chrome.js("document.getElementById('timer').textContent")
            check(v["talking"] == ["gawah"] and v["gawah"] == "Gawah is speaking" and timer.startswith("02:3"), f"deal on, Gawah speaking: {v} timer {timer}")
            await shot("deal-3-on-gawah-speaking")
            await chrome.js("__fake.speak('worker'); document.getElementById('mute').click()")
            await asyncio.sleep(0.6)
            v = await at("on")
            muted = await chrome.js("[document.getElementById('mute').getAttribute('aria-pressed'), __fake.calls.includes('mute'), document.getElementById('mic-quiet').hidden]")
            check(v["talking"] == ["them"] and v["gawah"] == "Gawah is listening" and muted == ["true", True, True],
                  f"deal on, Ramesh speaking, muted by hand (no notice): {v} {muted}")
            await shot("deal-4-on-muted")
            await chrome.js("document.getElementById('mute').click(); __fake.speak(); mic.mediaStreamTrack.dispatchEvent(new Event('mute'))")
            await asyncio.sleep(0.6)
            notice = await chrome.js("document.getElementById('mic-quiet').hidden ? null : document.getElementById('mic-quiet').textContent")
            check(bool(notice) and notice.startswith("Your microphone went off"), f"phone muted the microphone: {notice!r}")
            await shot("deal-5-on-phone-muted-mic")
            await chrome.js("__fake.end()")
            v = await at("ended")
            length = await chrome.js("document.getElementById('length').textContent")
            check(v["title"] == "Ramesh" and v["status"] == "Call ended" and v["join"] == "Call again" and length.startswith("2 min"),
                  f"deal ended: {v} {length!r}")
            await shot("deal-6-ended")
            await chrome.reload()
            await chrome.js("__fake.micRefused = true; document.getElementById('join').click()")
            v = await at("mic")
            check(v["title"] == "Microphone blocked" and v["join"] == "Rejoin", f"deal mic refused: {v}")
            await shot("deal-7-mic-blocked")
            # The phone will not play sound outside a tap: the call stays up and asks for a tap.
            await chrome.reload()
            await chrome.js("__fake.audioRefused = true; document.getElementById('join').click()")
            await at("waiting")
            await chrome.js("__fake.arrive('worker'); __fake.arrive('gawah')")
            await asyncio.sleep(0.6)
            check(await tapped() == ["on", True], f"deal: sound refused, still on the call, asks for a tap: {await tapped()}")
            await shot("deal-8-tap-to-hear")
            await chrome.js("__fake.audioRefused = false; document.body.click()")
            await asyncio.sleep(0.3)
            check(await tapped() == ["on", False], f"deal: a tap starts the sound: {await tapped()}")
            await chrome.js("__fake.end()")
            # An AI plays Sunita (app/actor): the page shows the call instead of joining it.
            await actor({**ACTOR, "role": "hirer"})
            v = await at("actor")
            timer = await chrome.js("document.getElementById('timer').textContent")
            check(v["join"] is None and v["gawah"] == "AI is playing Sunita" and timer == "01:23", f"deal, AI playing Sunita: {v} {timer}")
            await shot("deal-9-ai-playing")
            await actor(None)

            await chrome.goto(url + call_path("noname", Role.HIRER))
            v = await at("idle")
            check(v["title"] == "The worker", f"deal idle, the worker's name not known: {v}")
            await shot("deal-10-incoming-no-name")

            # The call-back, as Ramesh.
            await chrome.goto(url + callback_path("shots", Role.WORKER))
            v = await at("idle")
            check(v["join"] == "Join" and not v["leave"], f"call-back idle: {v}")
            await shot("callback-1-incoming")
            await chrome.js("__fake.fakeJoin = true; let go; __fake.hold = new Promise((r) => { go = r; }); window.go = go;"
                            " document.getElementById('join').click()")
            v = await at("connecting")
            check(v["join"] == "Connecting...", f"call-back connecting (waiting for Gawah): {v}")
            await shot("callback-2-connecting")
            first = await chrome.js("JSON.stringify(__fake.calls.slice(0, 2))")
            check(first.startswith('["startAudio",["createLocalAudioTrack"') and '"echoCancellation":true' in first,
                  f"call-back: sound and microphone asked for inside the tap, before anything is awaited: {first}")
            await chrome.js("go()")
            v = await at("on")
            await chrome.js("__fake.arrive('gawah'); __fake.speak('gawah'); startedAt = Date.now() - 48000")
            await asyncio.sleep(1.1)
            v = await at("on")
            check(v["talking"] == ["gawah"] and v["leave"] and v["gawah"] == "Gawah is speaking", f"call-back on, Gawah speaking: {v}")
            await shot("callback-3-on-gawah-speaking")
            await chrome.js("__fake.end()")
            v = await at("ended")
            check(v["title"] == "Gawah" and v["status"] == "Call ended" and v["join"] == "Call again", f"call-back ended: {v}")
            await shot("callback-4-ended")
            await chrome.reload()
            await chrome.js("__fake.fakeJoin = true; __fake.micRefused = true; document.getElementById('join').click()")
            v = await at("mic")
            check(v["title"] == "Microphone blocked", f"call-back mic refused: {v}")
            await shot("callback-5-mic-blocked")
            # The live bug: WhatsApp's browser refused the sound after the awaits, and the page dropped the call.
            await chrome.reload()
            await chrome.js("__fake.fakeJoin = true; __fake.audioRefused = true; document.getElementById('join').click()")
            await at("on")
            await chrome.js("__fake.arrive('gawah')")
            await asyncio.sleep(0.6)
            check(await tapped() == ["on", True] and await chrome.js("room !== null"),
                  f"call-back: sound refused, still on the call, asks for a tap: {await tapped()}")
            await shot("callback-6-tap-to-hear")
            await chrome.js("__fake.audioRefused = false; document.body.click()")
            await asyncio.sleep(0.3)
            check(await tapped() == ["on", False], f"call-back: a tap starts the sound: {await tapped()}")
            await chrome.js("__fake.end()")
            await chrome.reload()
            await chrome.js("document.getElementById('join').click()")  # the real route: nothing to confirm yet
            v = await at("error")
            check(v["status"] == "There is nothing to confirm with you yet.", f"call-back with nothing to ask (real route): {v}")
            await shot("callback-7-nothing-to-confirm")
            await actor({**ACTOR, "kind": "callback", "role": "worker", "name": "Ramesh"})
            v = await at("actor")
            check(v["join"] is None and v["gawah"] == "AI is playing Ramesh", f"call-back, AI playing Ramesh: {v}")
            await shot("callback-8-ai-playing")
            await actor(None)
            errors = [e for e in chrome.errors if not e.endswith("/callback/shots/worker/join")]  # the 404 just above
            check(not errors, f"no page errors: {errors}")
            if width == 390:
                frame = ('<body style="margin:0;background:#e5e5ea;display:grid;place-items:center;height:100vh">'
                         f'<iframe src="{call_path("shots", Role.WORKER)}" allow="microphone; autoplay" '
                         'style="width:300px;height:650px;border:10px solid #111;border-radius:44px"></iframe></body>')
                await chrome.goto(url + "/health")  # any page of the app, so the frame is the same origin
                await chrome.js(f"document.open(); document.write({json.dumps(frame)}); document.close()")
                await asyncio.sleep(1.5)
                framed = await chrome.js("(() => { const d = document.querySelector('iframe').contentDocument;"
                                         " return [d.body.dataset.state, d.getElementById('title').textContent]; })()")
                check(framed == ["idle", "Sunita"], f"the page works inside the dashboard's phone frame: {framed}")
                await shot("framed-deal-incoming")

    server.should_exit = True
    await serving
    print(f"saved to {OUT.relative_to(ROOT)}; {'all checks passed' if not failures else f'{len(failures)} FAILED'}")
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
