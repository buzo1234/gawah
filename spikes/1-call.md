# Spike 1: the deal call on LiveKit

```
1. call: YES (machine-checked; the phone-from-WhatsApp check is still to do)
What I ran: Two headless Chrome browsers, each playing the user's Hinglish recordings as a fake microphone, joined one LiveKit room from our call page. Our agent joined the same room with the low-level Python client (no AgentSession), and a third listen-only bot recorded the room.
What happened: Both browsers received each other's audio (1,585 and 1,799 Opus packets in 64 s, audio energy above zero on both pages). The agent got two separate audio tracks, each labelled with the right person; gpt-transcribe of each track's recording matched what that person's fake microphone was playing. Tracks arrived 1.6 s after the browsers were launched.
Catch: A person who drops without saying goodbye is only reported gone after 22 s; until then their track delivers silence. Rejoining gives a new participant id and a new track id under the same identity, so the bridge must key on identity. Not yet checked: a real phone, the WhatsApp in-app browser, real microphones.
Decision: Use LiveKit with the low-level client. Run the human check (`spikes/1-call/HUMAN-CHECK.md`) before the bridge stream relies on the WhatsApp link.
```

All numbers are from one run of `./py.sh autotest.py phase1` on 21 Nov, saved in `1-call/results/phase1.json`.

## Measurements

### Do both people join and hear each other?

Stats are from each page's own `RTCPeerConnection` (`inbound-rtp`), read 64 s after joining.

| Page | Hears | Packets received | Lost | Total audio energy | Codec |
|---|---|---|---|---|---|
| sunita | ramesh | 1,585 | 4 | 0.74 | Opus |
| sunita | gawah | 304 | 0 | 0.00 (silent, as it should be) | Opus |
| ramesh | sunita | 1,799 | 18 | 1.40 | Opus |
| ramesh | gawah | 301 | 3 | 0.00 | Opus |

- Both pages reported `connected`, microphone on, no microphone error.
- In the barge-in run, when Gawah did speak, both pages received it: 2,130 packets, energy 1.98 (`results/phase3.json`).

### Does the agent get two tracks, each tied to the right person?

Yes. `track_subscribed` fires once per person with the participant attached. The agent wrote each track to its own file and I sent the first 40 s of each to `gpt-transcribe`.

| Track's identity | That fake microphone was playing | gpt-transcribe of the agent's recording |
|---|---|---|
| sunita | Hello, Ramesh ji bol rahe hain? Main Sunita bol rahi hoon, Sharma ji ne aapka number diya tha. Mujhe apna flat paint karwana hai. Two BHK hai, Indirapuram mein, third floor pe. Andar ka poora, dono bedroom, hall aur kitchen. Balcony ki grill bhi kar dena. | हेलो, रमेश जी बोल रहे हैं। मैं सुनील बोल रहा हूँ। शर्मा जी ने आपका नंबर दिया। मुझे अपना फ्लैट पेंट करना है, टू बीएचके, एक तरफ पूरा... थर्ड फ्लोर है। अंदर का पूरा, दो बेडरूम, हॉल और किचन, बालकनी की ग्रिल भी कर देनी है। |
| ramesh | Haan ji madam, namaste. Boliye, kya kaam hai? Theek hai madam. Sirf andar ka kaam hai ya balcony ki grill bhi karni hai? Paint kaun sa lagwana hai? Asian Paints ka Royale loge ya normal Tractor Emulsion? | हाँ जी मैडम, नमस्ते। बोलिए, क्या काम है? ठीक है मैडम, सर अंदर का काम है, अभी करेंगी, ग्रे भी करेंगे। पेंट कौन सा लगवाना है? … का … लोगे या नॉर्मल … |

- Each track holds only its own person's lines. There is no bleed between the two.
- The transcripts are not clean: "Sunita" became "Sunil", "Indirapuram" was lost, and the paint brand names came back as "…". This audio went through Chrome's fake microphone, its noise suppression and Opus, with no language hint. It is a warning for the ears stream, not a measure of it.

### Audio the agent receives

| | Sample rate | Channels | Frame | Format |
|---|---|---|---|---|
| `rtc.AudioStream(track)` with SDK defaults | 48,000 Hz | 1 | 10 ms (480 samples) | 16-bit signed PCM |
| `rtc.AudioStream(track, sample_rate=24000, num_channels=1, frame_size_ms=20)` | 24,000 Hz | 1 | 20 ms (480 samples) | 16-bit signed PCM |

- The SDK resamples for you. Ask for the rate the next step wants.
- `bytes(event.frame.data)` is raw little-endian PCM with no header. For a file upload to `gpt-transcribe`, wrap it with the standard `wave` module; that is all I did.
- 24 kHz mono 16-bit is also what OpenAI's realtime endpoint takes as `audio/pcm`, so the same frames can be sent there without conversion. I sent them to the realtime voice model this way for 65 s (see spike 3). I did not test a realtime transcription session.

### Join, subscribe, leave, drop, rejoin

Times are seconds on the agent's clock. Full log: `results/phase1.json` under `events`.

Join (the agent was already in the room):

```
6.05  participant_connected  ramesh  PA_qCRo…
6.24  track_published        ramesh  TR_AMyQ…  audio
6.28  track_subscribed       ramesh  TR_AMyQ…
6.29  first audio frame      ramesh
```

- The agent's own `room.connect` took 0.4-0.75 s.
- `participant_connected` does not fire for people already in the room when the agent joins; read `room.remote_participants` after connecting. `track_subscribed` does fire for their tracks.

Hard drop (browser killed, no goodbye), then rejoin:

```
71.5  (ramesh's browser killed)
93.31 track_unsubscribed       ramesh  TR_AMyQ…
93.33 track_unpublished        ramesh  TR_AMyQ…
93.33 participant_disconnected ramesh  PA_qCRo…  reason=CONNECTION_TIMEOUT
94.25 participant_connected    ramesh  PA_quLW…   (new participant id)
94.45 track_published          ramesh  TR_AMps…   (new track id)
94.48 track_subscribed         ramesh  TR_AMps…
```

- The drop was noticed 21.8 s after the kill. During those 22 s the old track kept delivering frames of silence, so the recording has a silent tail and nothing tells the agent the person is gone.
- After a rejoin, audio was flowing again 1.15 s after the browser was relaunched.

Same person opens the link a second time while still connected (a page reload, or a second tab):

```
101.568 track_unsubscribed       sunita  TR_AMg4…
101.569 track_unpublished        sunita  TR_AMg4…
101.571 participant_disconnected sunita  PA_QtoC…  reason=None
101.572 participant_connected    sunita  PA_qwzF…
101.85  track_published          sunita  TR_AMac…
101.88  track_subscribed         sunita  TR_AMac…
```

- LiveKit removes the old connection and admits the new one in the same millisecond. No 22 s wait.

Clean leave (the page calls `room.disconnect()`): `track_unsubscribed`, `track_unpublished`, `participant_disconnected reason=CLIENT_INITIATED`, all within 10 ms.

### Usage

- 22.5 LiveKit participant-minutes for both spikes, counted from connect and disconnect times (`results/usage.jsonl`). If LiveKit bills each connection by the started minute, the ceiling is 31.
- 7 rooms opened, one at a time, all closed: 4 measured runs, 2 lost to rig problems (see below), 1 short test of the human-check command. `list_rooms` returned an empty list at the end.
- 15 `gpt-transcribe` calls (2 here, 13 in spike 3).

## For the bridge stream

### Packages

- `livekit` 1.3.0 - the low-level client (`from livekit import rtc`). Pulls in `numpy`, `protobuf`, `aiofiles`.
- `livekit-api` 2.0.1 - tokens and room admin (`from livekit import api`). Pulls in `aiohttp`, `pyjwt`, `livekit-protocol`.
- Browser: `livekit-client` 2.25.0. The spike loads it from `https://cdn.jsdelivr.net/npm/livekit-client@2.25.0/dist/livekit-client.umd.min.js` (global `LivekitClient`). The real build should serve that file itself.
- Not used: `livekit-agents`.

### The calling pattern that worked

All of this is in `1-call/agent.py` (`Agent`), `1-call/lk.py` and `1-call/page.html`. It runs inside one asyncio loop next to a uvicorn server, the way the real agent will.

```python
room = rtc.Room()

@room.on("track_subscribed")                      # handlers must be plain functions, not async
def on_track(track, publication, participant):
    if track.kind == rtc.TrackKind.KIND_AUDIO and participant.identity != "gawah":
        asyncio.create_task(listen(participant.identity, track))

await room.connect(LIVEKIT_URL, token)            # auto-subscribe is on by default

async def listen(identity, track):
    stream = rtc.AudioStream(track, sample_rate=24000, num_channels=1, frame_size_ms=20)
    async for event in stream:
        pcm = bytes(event.frame.data)             # 960 bytes = 20 ms, 16-bit mono
        ...                                       # write to file, send to transcription
    await stream.aclose()
```

Room and tokens:

```python
lk = api.LiveKitAPI(url, key, secret)             # create it inside the running loop; it opens an aiohttp session
await lk.room.create_room(api.CreateRoomRequest(name=name, empty_timeout=30, departure_timeout=15, max_participants=6))
await lk.room.delete_room(api.DeleteRoomRequest(room=name))
await lk.aclose()

jwt = (api.AccessToken(key, secret).with_identity(identity).with_ttl(timedelta(minutes=15))
       .with_grants(api.VideoGrants(room_join=True, room=name)).to_jwt())
```

Page: `new LivekitClient.Room()`, `room.connect(url, token)`, `room.startAudio()`, `room.localParticipant.setMicrophoneEnabled(true)`, and on `TrackSubscribed` append `track.attach()` to the page. Do all of it inside the join button's tap, so the phone allows the microphone and the sound.

### Settings and rules to carry over

- Key everything on `participant.identity`. The participant id and the track id both change on every rejoin.
- One recording file per (identity, track). A rejoin starts a new file; keep each file's start time so they can be put on one timeline.
- There is no maximum-length setting on a room. `CreateRoomRequest` has only `empty_timeout`, `departure_timeout` and `max_participants`. The 10-minute cap has to be a timer in our code that calls `delete_room`; `human.py` does this.
- Close the room with `delete_room` when the call ends. It disconnects everyone.
- A dropped person looks like a silent person for 22 s. If the Judge must not ask a question to someone who has gone, the bridge needs its own signal. The page's `Reconnecting` event, or no packets on the track, are candidates; I did not test either.
- `logging.getLogger("livekit").setLevel(logging.ERROR)`: the SDK passes libwebrtc's warnings through at WARNING level, dozens of lines per connection.
- The agent counts as a participant for LiveKit's minutes. A 10-minute call with two people is 30 participant-minutes.

### What went wrong on the way

- `uv run --with livekit` could not reach PyPI from this machine (connect timeouts, while `curl` and Python's own `urllib` reached it at once). I downloaded the wheels with `pip download` into `1-call/.wheels/` (ignored by git) and `py.sh` uses them with `uv run --offline --find-links`. Still failing when I finished. Whoever adds these packages to `pyproject.toml` may hit the same thing.
- Chrome's fake microphone sent silence until I added `--disable-features=AudioServiceSandbox`. Chrome 157 on macOS runs audio in a sandboxed process that cannot read the wav file. The first room was wasted on this (2.6 participant-minutes).
- Port 8765 was already in use on this machine. uvicorn's failure exits the process from inside a task, which skipped my room cleanup. Nobody had joined, and the room was gone (30-second empty timeout) when I checked. The rig now picks a free port.
- `list_rooms` still shows a room with 0 participants for a few seconds after `delete_room`. Wait before deciding a room is stuck.
- A `cloudflared` quick tunnel prints its address before it is reachable. Asking for the address too early made macOS remember "no such host" for a while, so the link failed on the laptop that started it. `human.py` now waits for cloudflared's "Registered tunnel connection" line and checks the page through DNS-over-HTTPS.

## Not verified

- A real phone, the WhatsApp in-app browser, and real microphones. That is the human check.
- Bad networks. Both browsers ran on the laptop on one connection.
- More than one run. Every number here is from a single run.
- Echo cancellation and background noise: the fake microphone is digitally silent between lines.
- Whether LiveKit rounds each connection up to a whole minute when it counts usage.
- Uploading recordings to S3.

## Files

- `1-call/py.sh <script>` - runs a spike script with the two extra packages.
- `1-call/autotest.py`, `1-call/autotest_mouth.py` - the automated checks: `prep`, `phase1`, `phase2`, `phase2b`, `phase3`, `rooms`.
- `1-call/agent.py` - the agent and the listen-only recorder bot. `1-call/mouth.py` - the voice (spike 3).
- `1-call/server.py`, `1-call/page.html` - the token server and the call page.
- `1-call/human.py`, `1-call/start.sh`, `1-call/HUMAN-CHECK.md` - the human check.
- `1-call/closeall.py` - closes any spike room left open.
- `1-call/results/` - every number above. `1-call/out/` holds recordings of the user's voice and is ignored by git.
