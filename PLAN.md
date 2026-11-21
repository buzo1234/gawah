# Gawah - Build Plan

How we scaffold, split the work across parallel worktrees and AI agents, and get to a demo in 2 days.

Read `idea.md` for what we are building and `tech-feasibility.md` for why each piece was chosen.

## The approach in one paragraph

Scaffold a thin skeleton on `main` first, with the shared event types frozen and a fake for every seam. Run the risky tests ("spikes") in parallel while that happens. Then split into six streams, each in its own worktree with its own agent, each owning one folder and talking to the others only through events. Merge small and often. Get an ugly end-to-end call working by the end of day 1, and spend day 2 on the records flow, tuning the Judge's timing, and rehearsing.

## Stack

- Python 3.12 through `uv`. The machine's default Python is 3.15, which is too new for some packages, so pin 3.12.
- FastAPI + uvicorn, one process. Audio streaming needs long-lived connections.
- An in-process event bus (asyncio). No queue service.
- SQLite for deals and records. S3 for recordings, clips, and PDFs.
- `cloudflared` for the public address during development (already installed, as are `ffmpeg` and `ngrok`).
- A plain HTML dashboard fed by a websocket. No frontend framework.

## Folder layout

```
app/
  main.py          # FastAPI app, routes, websocket endpoints
  contracts.py     # shared event and data types - frozen after scaffold
  bus.py           # in-process event bus
  config.py        # reads .env
  store/           # SQLite + S3
  telephony/       # stream: bridge
  ears/            # stream: bridge
  brain/           # stream: brain
  mouth/           # stream: mouth
  whatsapp/        # stream: whatsapp
  records/         # stream: whatsapp
  contract/        # stream: contract
  dashboard/       # stream: dashboard
fakes/             # transcript replayer, fake phone bridge, fake WhatsApp
fixtures/          # recorded practice calls, transcripts, sample screenshots
spikes/            # throwaway test scripts
tests/
```

## The events (the only way streams talk to each other)

| Event | Sent by | Carries |
|---|---|---|
| `deal.requested` | whatsapp | who asked, the other person's number |
| `call.started` / `call.ended` | bridge | deal, the two phone legs |
| `transcript.line` | bridge | deal, speaker, text, start and end time |
| `checklist.updated` | brain | each contract item: pending or agreed, value, confidence |
| `judge.speak` | brain | what to ask, whom to ask, why |
| `judge.spoke` | mouth | what was actually said |
| `terms.confirmed` / `terms.disputed` | mouth | deal, person, which term |
| `contract.ready` | contract | PDF link, voice summary link |
| `record.received` | whatsapp | deal, sender, type, backed or unbacked, extracted fields |
| `record.confirm_requested` / `record.confirmed` | whatsapp | deal, record, who must confirm |
| `reply.timeout` | whatsapp | deal, person to call, what to ask |

Changing `contracts.py` after the scaffold needs one named person to approve it on `main`. Everyone else then rebases.

## Step 0 - Things only a human can do (start now, about 45 minutes)

Do these while the scaffold is being built.

- Twilio: sign up with an Indian mobile number, verify every team phone we will demo with.
- OpenAI: API key with access to the transcription and realtime voice models.
- Levanto: Sage2 API key (free plan).
- AWS: an S3 bucket, and access keys for it.
- Meta: WhatsApp Cloud API test number, as the backup to Twilio's sandbox.
- Put all keys in a local `.env`. Never commit it.
- Record two practice calls on our own phones, 2-3 minutes each, in Hinglish, playing Sunita and Ramesh. In one, leave out the balance date. In the other, say two different amounts. Type out both transcripts with speaker and rough timings. These go in `fixtures/` and are what the brain is built and tuned against.

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
| 1. Phone | Can the Twilio trial call two Indian mobiles and join them? | Plan B: browser call from a WhatsApp link |
| 2. Ears | Is Hinglish transcription on phone audio good enough? | Amazon Transcribe |
| 3. Mouth | Can the realtime voice model sit in the call, stay silent until triggered, and stop when talked over? | Play generated speech into the call instead |
| 4. WhatsApp | Can the sandbox receive a text and an image and reply? | Meta test number |
| 5. Sage2 | Does it answer our questions correctly on a Hinglish transcript, fast? | A small OpenAI text model for the same questions |

Hour 3 is the decision point. Write the five answers at the bottom of this file and move on. Do not spend day 1 fighting telephony.

## Step 3 - Streams (parallel worktrees, one agent each)

| Stream | Owns | Builds | Done when |
|---|---|---|---|
| `bridge` | `app/telephony`, `app/ears` | Places both calls, joins them, plays the recording notice, streams each leg to transcription, saves the recording | A real call between two phones shows speaker-labelled lines on the dashboard |
| `brain` | `app/brain` | Sage2 stream client, the contract checklist, the rules for when to speak | Replaying both practice calls produces the right question at the right moment, as a repeatable test |
| `mouth` | `app/mouth` | The voice model in the call, speaking on `judge.speak`; the one-to-one call-back that confirms terms | A `judge.speak` event is heard on the call within about a second and a half; a call-back ends in `terms.confirmed` |
| `whatsapp` | `app/whatsapp`, `app/records` | Bot webhook, starting a deal, record intake, backed or unbacked, asking the other side, the no-reply timer | A payment screenshot is logged directly; "paid in cash" asks the other person; no reply in 2 minutes raises `reply.timeout` |
| `contract` | `app/contract` | Confirmed terms to contract text, PDF, a spoken summary, sent to both | From fixture terms, a PDF and a voice note arrive on WhatsApp |
| `dashboard` | `app/dashboard` | Live view: transcript by speaker, checklist ticking, why the Judge spoke, the records ledger | Readable on a projector |

What each stream needs from the others:

- `brain`, `whatsapp`, `contract`, and `dashboard` need nothing but the scaffold and the fakes. Start them immediately.
- `bridge` needs spike 1 and 2 answered.
- `mouth` needs spike 3 answered, and `bridge` merged before it can be tested on a real call. Until then it tests against a single plain phone call.

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
| Hour 3 | All five spikes answered; Plan A or B chosen |
| End of day 1 | Walking skeleton on real phones: Gawah calls two people, the transcript shows live, the Judge asks one question, a contract lands on WhatsApp. Ugly is fine. |
| Day 2, midday | Records flow works end to end; call-back confirms terms; the no-reply call rings |
| Day 2, 3-4 hours before the deadline | Feature freeze. Only fixes after this. |
| Before presenting | Three full rehearsals, and a recorded backup video of a clean run |

Day 2 afternoon is for tuning when the Judge speaks, on the practice calls and on live calls. That tuning is what makes the demo feel real, so protect the time.

## The demo we are building toward

1. Sunita messages Gawah with Ramesh's number.
2. Both phones ring. Gawah says the call is being recorded; both agree.
3. They agree the work and the amount, and move on without saying when the balance is paid. Gawah waits for a pause and asks.
4. Gawah reads the full terms back. They hang up.
5. Gawah rings Ramesh alone to confirm. He disputes one term; Gawah plays him the clip. (Stretch.)
6. The contract arrives on both phones.
7. Sunita sends a payment screenshot - logged straight away.
8. Ramesh texts that the work is done. Gawah asks Sunita. She ignores it. Her phone rings.

The dashboard is on the big screen throughout, showing the transcript, the checklist filling in, and why the Judge chose to speak.

## If we run short

Cut in this order: clip replay, the second call-back, the voice summary of the contract, the dashboard polish. Never cut: the bridge call, the Judge speaking at the right moment, the contract on WhatsApp, one backed and one unbacked record.

Keep the safety switch from `tech-feasibility.md`: one setting that makes the Judge speak only at wrap-up.

## Spike answers

Fill in at hour 3.

1. Phone:
2. Ears:
3. Mouth:
4. WhatsApp:
5. Sage2:
