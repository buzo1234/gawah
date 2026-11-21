# Gawah - Build Plan

How we scaffold, split the work across parallel worktrees and AI agents, and get to a demo in 2 days.

Read `idea.md` for what we are building and `tech-feasibility.md` for why each piece was chosen.

## The approach in one paragraph

Scaffold a thin skeleton on `main` first, with the shared event types frozen and a fake for every seam. Run the risky tests ("spikes") in parallel while that happens. Then split into six streams, each in its own worktree with its own agent, each owning one folder and talking to the others only through events. Merge small and often. Get an ugly end-to-end call working by the end of day 1, and spend day 2 on the records flow, tuning the Judge's timing, and rehearsing.

## Stack

- Python 3.12 through `uv`. The machine's default Python is 3.15, which is too new for some packages, so pin 3.12.
- FastAPI + uvicorn for the app. The LiveKit agent runs alongside it on the same machine.
- LiveKit for the call: a room per deal, a one-button call page in the browser, and an agent that joins as Gawah.
- Twilio only for the WhatsApp sandbox.
- An in-process event bus (asyncio). No queue service.
- SQLite for deals and records. S3 for recordings, clips, and PDFs.
- `cloudflared` for the public https address (already installed, as is `ffmpeg`).
- A plain HTML dashboard fed by a websocket. No frontend framework.

## Use the free plans with care

LiveKit and Twilio are on free plans. The rules are in `tech-feasibility.md` and `AGENTS.md`. In short: build against the fakes, open a real room or send a real message only for a spike, a manual check, or a demo run, and always close the room after. Sage2's free usage is the tightest of all - about a dozen full-length calls a month - so the brain is built against saved results and goes live only to tune and to demo.

## Folder layout

```
app/
  main.py          # FastAPI app, routes, websocket endpoints
  contracts.py     # shared event and data types - frozen after scaffold
  bus.py           # in-process event bus
  config.py        # reads .env
  log.py           # deal id on every log line, masked phone numbers
  dev.py           # development-only route that puts an event on the bus
  store/           # SQLite + S3
  call/            # stream: bridge - rooms, join links, the call page
  ears/            # stream: bridge - per-person transcription
  brain/           # stream: brain
  mouth/           # stream: mouth
  whatsapp/        # stream: whatsapp
  records/         # stream: whatsapp
  contract/        # stream: contract
  dashboard/       # stream: dashboard
fakes/             # transcript replayer, event tail, fake call, fake WhatsApp, sample events
fixtures/          # practice-call transcripts, sample screenshots
spikes/            # throwaway test scripts
tests/
```

## The events (the only way streams talk to each other)

| Event | Sent by | Carries |
|---|---|---|
| `deal.requested` | whatsapp | who asked, the other person's number |
| `call.started` / `call.ended` | bridge | deal, the two people in the room, the call number within the deal |
| `transcript.line` | bridge | deal, speaker, text, start and end time |
| `checklist.updated` | brain | each contract item: pending or agreed, value, confidence |
| `judge.speak` | brain | what to ask, whom to ask, why |
| `judge.spoke` | mouth | what was actually said |
| `terms.confirmed` / `terms.disputed` | mouth | deal, person, which term |
| `contract.ready` | contract | PDF link, voice summary link |
| `record.received` | whatsapp | deal, sender, type, backed or unbacked, extracted fields |
| `record.confirm_requested` / `record.confirmed` | whatsapp | deal, record, who must confirm |
| `reply.timeout` | whatsapp | deal, person to follow up with, what to ask |
| `whatsapp.message` | whatsapp | every WhatsApp message in or out: direction, phone, text or media, simulated or really sent. Deal is `NO_DEAL` before one exists |
| `fact.recorded` | memory | a new fact, or a new version of one: the sentence, item, value (also as rupees or a date), who said, agreed and confirmed it, status, where it came from (call and line with start and end, or record and media), what it replaces or counts towards, its witness-chain hash |
| `fact.conflict` | memory | what was just said, the agreed or confirmed facts it contradicts, one-sentence explanation, how sure |
| `fact.changed` | mouth | an amendment step (proposed, confirmed by one, by both, withdrawn): change id, the fact it changes, the new value |
| `agent.note` | any stream | one line of what a crew agent just did, for the dashboard's lanes; nothing depends on it |

Changing `contracts.py` after the scaffold needs one named person to approve it on `main`. Everyone else then rebases.

## Step 0 - Things only a human can do

Done:

- OpenAI key, AWS keys, LiveKit keys, Twilio account keys, Sage2 key, and our phone number are in `.env`.
- S3 bucket is created and its name is in `.env`.
- Our phone has joined the Twilio WhatsApp sandbox (number `+17372508034`, in `.env`). Membership lapses after three days, on 24 Nov - rejoin with the same join code if messages stop.

Still to do:

- Write two practice-call transcripts in Hinglish, 2-3 minutes each, playing Sunita and Ramesh, with speaker and rough timings. In one, leave out the balance date. In the other, say two different amounts. These go in `fixtures/` and are what the brain is built and tuned against.
- Watch for the AWS keys expiring. They are temporary. Replace all three together when they do.

### Working with one phone

We have one real phone. The build still works:

- Calls: one person joins from the phone's browser, the other from the laptop's browser. Each is their own audio track, so who-said-what still works. Wear earphones on the laptop to avoid echo.
- WhatsApp: one phone means one WhatsApp account. The second party's messages come from a "second phone" panel on the dashboard that sends the same events a real message would.
- For the final demo, borrow a second phone if possible. Its owner needs one minute: send the WhatsApp sandbox join message to our sandbox number. Keep the laptop version as the fallback.

## Step 1 - Scaffold (one agent, on `main`, about 45 minutes)

Builds the skeleton and nothing else.

- Folder layout, `contracts.py`, `bus.py`, `config.py`, the store, an empty module per stream.
- `fakes/replayer`: plays a fixture transcript onto the bus at real speed.
- A dashboard stub that prints every event live.
- One command to run the server, one to run the tests, one to run the replayer.

Done when: starting the server and running the replayer shows a practice call scrolling on the dashboard.

## Step 2 - Spikes (parallel, finish by hour 3)

Throwaway scripts in `spikes/`. Each answers one question from `tech-feasibility.md`.

| Spike | Question | If it fails |
|---|---|---|
| 1. Call | Can the phone (from a WhatsApp link) and the laptop join one LiveKit room, hear each other, and reach the agent as two separate tracks? | Real phone calls through a Twilio trial number |
| 2. Ears | Is Hinglish transcription on each track good enough? | Amazon Transcribe |
| 3. Mouth | Can the realtime voice model speak into the room, stay silent until triggered, and be cut off? | Generate speech from text and play that in |
| 4. WhatsApp | Can the sandbox receive a text and an image and reply? | Meta test number |
| 5. Sage2 | Does it answer our questions correctly on a Hinglish transcript, fast? | A small OpenAI text model for the same questions |

Hour 3 is the decision point. Write the five answers at the bottom of this file and move on.

## Step 3 - Streams (parallel worktrees, one agent each)

| Stream | Owns | Builds | Done when |
|---|---|---|---|
| `bridge` | `app/call`, `app/ears` | Creates the room, makes the join links, serves the call page, joins as the agent, plays the recording notice, transcribes each person's track, saves the audio | A real call between the phone and the laptop shows speaker-labelled lines on the dashboard |
| `brain` | `app/brain` | Sage2 stream client, the contract checklist, the rules for when to speak | Replaying both practice calls produces the right question at the right moment, as a repeatable test |
| `mouth` | `app/mouth` | The voice model speaking into the room on `judge.speak`; the one-to-one call-back that confirms terms | A `judge.speak` event is heard in the room within about a second and a half; a call-back ends in `terms.confirmed` |
| `whatsapp` | `app/whatsapp`, `app/records` | Bot webhook, starting a deal, sending links, record intake, backed or unbacked, asking the other side, the no-reply timer | A payment screenshot is logged directly; "paid in cash" asks the other person; no reply in 2 minutes raises `reply.timeout` |
| `contract` | `app/contract` | Confirmed terms to contract text, PDF, a spoken summary, sent to both | From fixture terms, a PDF and a voice note arrive on WhatsApp |
| `dashboard` | `app/dashboard` | Live view: transcript by speaker, checklist ticking, why the Judge spoke, the records ledger, the "second phone" panel | Readable on a projector |

What each stream needs from the others:

- `brain`, `whatsapp`, `contract`, and `dashboard` need nothing but the scaffold and the fakes. Start them immediately.
- `bridge` needs spike 1 and 2 answered.
- `mouth` needs spike 3 answered, and `bridge` merged before it can be tested on a two-person call. Until then it tests in a one-to-one room.

## Worktrees and agents

One worktree per stream, created with `workmux`. Each gets its own branch, its own tmux session, and its own agent:

```
workmux add bridge    -b -P <brief file>
workmux add brain     -b -P <brief file>
workmux add mouth     -b -P <brief file>
workmux add whatsapp  -b -P <brief file>
workmux add contract  -b -P <brief file>
workmux add dashboard -b -P <brief file>
```

`.workmux.yaml` does the setup: it branches from `main`, copies `.env` into the new worktree, installs dependencies, and runs the tests before any merge. Worktrees live in `.worktrees/<stream>`.

One orchestrator session writes the briefs, starts the agents, watches them, reviews each stream's work, and opens a pull request for it. The user reviews and merges each pull request. The orchestrator does not write code.

The full rules for agents are in `AGENTS.md`, and the working routines (briefing a stream, running a spike, merging, handing off, checking the demo) are skills in `.claude/skills/`.

Rules every agent is given:

- Touch only the folders your stream owns, plus your own tests.
- Talk to other streams only through the events in `contracts.py`. Never import another stream's code.
- Do not edit `contracts.py`, `bus.py`, or `main.py`. If you need a change, stop and ask.
- Build against the fakes first. Your stream must run and pass its tests with no other stream present.
- Rebase on `main` before asking for a merge. Tests pass before merge.
- Never commit keys.

The brief for each agent is five lines: the goal, the folders it owns, the events it listens to and sends, the "done when" from the table above, and the rules. The orchestrator reviews every stream and opens a pull request; the user merges it. Keep merges small - several a day per stream, not one big one at the end.

## Checkpoints

| When | What must be true |
|---|---|
| Scaffold done | A practice call replays onto the dashboard |
| Hour 3 | All five spikes answered |
| End of day 1 | Walking skeleton on a real call: both people join from their links, the transcript shows live, the Judge asks one question, a contract lands on WhatsApp. Ugly is fine. |
| Day 2, midday | Records flow works end to end; call-back confirms terms; the no-reply follow-up arrives |
| Day 2, 3-4 hours before the deadline | Feature freeze. Only fixes after this. |
| Before presenting | Three full rehearsals, and a recorded backup video of a clean run |

Day 2 afternoon is for tuning when the Judge speaks, on the practice calls and on live calls. That tuning is what makes the demo feel real, so protect the time.

## The demo we are building toward

1. Sunita messages Gawah with Ramesh's number.
2. Both get a call link on WhatsApp and tap it. Gawah says the call is being recorded; both agree.
3. They agree the work and the amount, and move on without saying when the balance is paid. Gawah waits for a pause and asks.
4. Gawah reads the full terms back. They hang up.
5. Gawah sends Ramesh a link to confirm alone. He disputes one term; Gawah plays him the clip. (Stretch.)
6. The contract arrives on both phones.
7. Sunita sends a payment screenshot - logged straight away.
8. Ramesh texts that the work is done. Gawah asks Sunita. She ignores it. Gawah follows up with a call link. (Stretch: her phone rings.)

The dashboard is on the big screen throughout, showing the transcript, the checklist filling in, and why the Judge chose to speak.

## If we run short

Cut in this order: clip replay, the second call-back, the voice summary of the contract, the dashboard polish. Never cut: the deal call, the Judge speaking at the right moment, the contract on WhatsApp, one backed and one unbacked record.

Keep the safety switch from `tech-feasibility.md`: one setting that makes the Judge speak only at wrap-up.

## Spike answers

Fill in at hour 3.

1. Call: YES, machine-checked. The human check with a real phone is still to do. Use LiveKit with its low-level Python client (`livekit`, `livekit-api`), not the agent framework's session.
   - Measured: two headless Chrome browsers, each playing our Hinglish recordings as its microphone, heard each other. The agent got each person as a separate track tied to the right identity, checked by transcribing each track. Audio arrives as 16-bit mono PCM at the rate we ask for.
   - Catches: a person who drops without leaving is only reported gone after 22 seconds, and their track is silence until then. A rejoin gives a new participant id and a new track id. A room has no maximum-length setting.
   - For the bridge stream: key everything on the participant's identity, start a new recording file on each rejoin, and close the room with our own 10-minute timer. The pattern, settings and event order are in `spikes/1-call.md`.
   - Still to do: a real phone, the link opened inside WhatsApp, real microphones. The checklist is `spikes/1-call/HUMAN-CHECK.md`.
2. Ears: PARTLY. Use OpenAI `gpt-transcribe`; Amazon Transcribe is not needed.
   - Use `gpt-transcribe` with a short prompt (the speakers' names, the kind of words to expect) and Hindi plus English language hints, one stream per person. Our own end-of-speech detection decides when a line ends. Send each line as a file upload; the text is back in about 0.9 seconds.
   - Right: 36 to 40 of the 42 amounts, dates, names and brands in 24 recorded Hinglish lines, against 30 to 34 without the prompt. "Haan theek hai" and "pakka" came back right every time. Text is always Devanagari. The contract values `gpt-5.4-mini` pulled from the transcript matched the ones from the script.
   - Wrong: "seventeen thousand" came back as "seventy thousand" in 42 of 43 runs and was never right. "Bees mein" came back as "please". With OpenAI's own end-of-speech detection, a "haan" or "Hindi" that nobody said was added to 5 of 24 lines.
   - For the build: an amount said only once cannot be trusted. The brain checks figures against each other, and the read-back and the separate confirmation are what protect the contract. The bridge does not use OpenAI's end-of-speech detection. Tests must not expect exact transcript text; it changes from run to run.
   - For the bridge stream: the calling pattern, what to expect to go wrong, and every transcript are in `spikes/2-ears.md` and `spikes/2-results/`.
3. Mouth: YES, machine-checked. The human check is still to do: nobody has listened to it on a real call. Use `gpt-realtime-2.1`, not the mini, on one connection held open for the whole call.
   - Measured: silent for 65 seconds while two people talked. On a trigger, heard in the room after 1.1-1.9 seconds (median 1.3), asking only what the instruction said, in Hindi, 13 times of 13. Talked over, it went silent in the room 139-158 ms after the person's first sound, 5 times of 5.
   - Catches: the mini is 0.1-0.2 seconds quicker but added words in 4 of 9 questions and once suggested a term. Talking-over is detected by loudness, tested only against a silent fake microphone. Playback ran dry for 130-275 ms early in half the timed runs. A cut-off reply is paid for in full.
   - For the mouth stream: automatic replies off, never send the model the room's audio, one reply per text instruction with the persona in it, and stop by dropping our buffer and clearing the LiveKit audio source. The pattern and settings are in `spikes/3-mouth.md`; samples to listen to are in `spikes/1-call/samples/`.
   - Still to do: how it sounds to a person, real room noise, and whether Gawah's own voice coming out of a loudspeaker cuts it off (echo). Same checklist as item 1.
4. WhatsApp:
5. Sage2: PARTLY. Use it for the live yes/no decisions; do not use its extract call.
   - Decisions were right on 286 of 286 answers on a 30-line Hinglish call, 285 of 286 in Devanagari, and 147 of 150 on a second, unseen call. About half a second per update from India.
   - Extract found the right words but wrong values ("42 hazaar" came back as 42). Get values from a small OpenAI text model instead; `gpt-5.4-mini` got all five right in about 2 seconds.
   - Catch: about a dozen full-length calls fit in the free $1 a month. The spike used about $0.11.
   - For the brain stream: the question wording that worked, the harness notes, and saved results are in `spikes/5-sage2.md` and `spikes/5-results/`.
