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

LiveKit and Twilio are on free plans. The rules are in `tech-feasibility.md` and `AGENTS.md`. In short: build against the fakes, open a real room or send a real message only for a spike, a manual check, or a demo run, and always close the room after.

## Folder layout

```
app/
  main.py          # FastAPI app, routes, websocket endpoints
  contracts.py     # shared event and data types - frozen after scaffold
  bus.py           # in-process event bus
  config.py        # reads .env
  store/           # SQLite + S3
  call/            # stream: bridge - rooms, join links, the call page
  ears/            # stream: bridge - per-person transcription
  brain/           # stream: brain
  mouth/           # stream: mouth
  whatsapp/        # stream: whatsapp
  records/         # stream: whatsapp
  contract/        # stream: contract
  dashboard/       # stream: dashboard
fakes/             # transcript replayer, fake call, fake WhatsApp
fixtures/          # practice-call transcripts, sample screenshots
spikes/            # throwaway test scripts
tests/
```

## The events (the only way streams talk to each other)

| Event | Sent by | Carries |
|---|---|---|
| `deal.requested` | whatsapp | who asked, the other person's number |
| `call.started` / `call.ended` | bridge | deal, the two people in the room |
| `transcript.line` | bridge | deal, speaker, text, start and end time |
| `checklist.updated` | brain | each contract item: pending or agreed, value, confidence |
| `judge.speak` | brain | what to ask, whom to ask, why |
| `judge.spoke` | mouth | what was actually said |
| `terms.confirmed` / `terms.disputed` | mouth | deal, person, which term |
| `contract.ready` | contract | PDF link, voice summary link |
| `record.received` | whatsapp | deal, sender, type, backed or unbacked, extracted fields |
| `record.confirm_requested` / `record.confirmed` | whatsapp | deal, record, who must confirm |
| `reply.timeout` | whatsapp | deal, person to follow up with, what to ask |

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

One worktree per stream, next to the main folder:

```
git worktree add ../gawah-bridge    -b bridge
git worktree add ../gawah-brain     -b brain
git worktree add ../gawah-mouth     -b mouth
git worktree add ../gawah-whatsapp  -b whatsapp
git worktree add ../gawah-contract  -b contract
git worktree add ../gawah-dashboard -b dashboard
```

Each worktree gets its own copy of `.env`.

The full rules for agents are in `AGENTS.md`, and the working routines (briefing a stream, running a spike, merging, handing off, checking the demo) are skills in `.claude/skills/`.

Rules every agent is given:

- Touch only the folders your stream owns, plus your own tests.
- Talk to other streams only through the events in `contracts.py`. Never import another stream's code.
- Do not edit `contracts.py`, `bus.py`, or `main.py`. If you need a change, stop and ask.
- Build against the fakes first. Your stream must run and pass its tests with no other stream present.
- Rebase on `main` before asking for a merge. Tests pass before merge.
- Never commit keys.

The brief for each agent is five lines: the goal, the folders it owns, the events it listens to and sends, the "done when" from the table above, and the rules. A human reviews every merge into `main`. Keep merges small - several a day per stream, not one big one at the end.

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

1. Call:
2. Ears:
3. Mouth:
4. WhatsApp:
5. Sage2:
