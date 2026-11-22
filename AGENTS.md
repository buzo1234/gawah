# Gawah: a guide for reviewers

Gawah (गवाह, "witness") is an AI witness for work deals made by voice. It joins the call between a household and a worker, keeps every term each person says, asks about the terms they skip, sends both a written agreement on WhatsApp, and then checks every payment claim against what was agreed.

**Live server:** https://44.253.37.59.sslip.io

- The board: https://44.253.37.59.sslip.io/dashboard
- Access key for the board and its phones: `REVIEWER_ACCESS_KEY_HERE` (asked for once per browser; scripts send it as the `X-Access-Key` header)
- Health check: https://44.253.37.59.sslip.io/health answers `{"status":"ok"}`

The live server runs on limited free allowances (LiveKit call minutes, the Sage2 decision model's monthly calls, OpenAI credits). If a live call fails or Gawah stays silent, use the offline mode below: it runs the whole product on your machine with no keys and no outside services.

This file is for people reviewing and running Gawah. The rules for this repository's own coding agents are in `docs/DEVELOPMENT.md`.

---

## Touch points

| Touch point | Who uses it | Where |
|---|---|---|
| WhatsApp | Both people: start a deal, get call links, the agreement, payment checks, voice notes | Real WhatsApp only for numbers Karan Dua has added (below); otherwise the simulated phones at `/dashboard/phone` |
| The call page | Both people, in a phone's browser, from the link Gawah sends | `/call/<deal id>/hirer` and `/call/<deal id>/worker` (no key needed) |
| The board | Anyone with the access key | `/dashboard`: every term, fact, contradiction and the witness chain, live; a simulated second phone in a drawer on the right (its tab or the P key shows and hides it) |
| The agreement | Both people, on WhatsApp | A PDF in Hindi and English, and a spoken summary (audio), sent once both have agreed |

**Real WhatsApp numbers.** Gawah's WhatsApp runs on Meta's Cloud API test number. Meta lets that number message only phones on its allowed list, so a real WhatsApp number works only after the code owner, Karan Dua, adds it to his Meta WhatsApp account (the test number's allowed recipients) and to `VERIFIED_NUMBERS` on the server. Without that, use the simulated phones on the board. They go through the same WhatsApp code path: a simulated phone posts to the same webhook in the provider's message format, and Gawah's replies to it are shown in its chat instead of being sent.

---

## Test logins and people

There are no user accounts. The roles are:

| Role | How to be them |
|---|---|
| Reviewer on the board | Open `/dashboard` and type the access key once. The browser keeps it in a cookie. The offline mode has no key. |
| The hirer (pays for the work) | A simulated phone: `/dashboard/phone?number=+919000001001` in its own tab |
| The worker (does the work) | Another simulated phone: `/dashboard/phone?number=+919000001002` in a second tab |

- Any number that is not in `VERIFIED_NUMBERS` is a simulated phone. Use `+91` and ten digits starting with 9.
- **Pick your own last four digits** (for example `+91900000` followed by four random digits) on the live server. Several reviewers share it, and a chat shows every message for its number across deals.
- **A deal starts** when one phone sends the other person's name and number, for example `Ramesh +919000001002`. The sender becomes the hirer. Both phones get a call link.
- **"AI plays this person"** is a switch at the top of a simulated phone. When it is on and a call link arrives on that phone, an AI joins the call as that person and talks. One reviewer can then make a whole call alone, speaking as the other person. Turn it on **before** the link arrives. Only one AI player runs on the server at a time; if it is busy the phone says so.
- The board shows the newest deal. Add `?deal=<deal id>` to pin yours; the deal id is in your call link (`/call/<deal id>/hirer`). Press D on the board to step through deals.

---

## Journeys

Spoken words and WhatsApp messages are in Hindi and Hinglish. The lines below are written out so you can read them aloud.

### (a) A deal from WhatsApp to the agreement (live server)

You need a laptop with a microphone and earphones, and about 10 minutes. You speak as the hirer, Sunita; the AI plays the worker, Ramesh.

1. Open `https://44.253.37.59.sslip.io/dashboard` and enter the access key.
2. Open the worker's phone in a new tab: `/dashboard/phone?number=+91900000XXXX` (your worker number). Switch on **AI plays this person**.
3. Open the hirer's phone in another tab: `/dashboard/phone?number=+91900000YYYY` (your hirer number). Send `hi`.
   **You should see:** "Namaste, main Gawah hoon. Deal shuru karne ke liye doosre vyakti ka mobile number bhejiye ..."
4. From the hirer's phone send `Ramesh +91900000XXXX`.
   **You should see:** the hirer gets "Namaste! Gawah aapki deal ka gawah rahega. Call ke liye yeh link kholiye" and a call link. The worker's phone gets "+91900000YYYY aapke saath kaam ki deal pakki karna chahte hain ..." and, with the switch on, starts the AI on its link. A simulated phone has no WhatsApp profile name, so Gawah learns each person's name when they say it on the call. On the board (add `?deal=<deal id>`) the deal appears with both people.
5. In the hirer's tab, open the call link, press the green **Join** button and allow the microphone. If the page says "Tap anywhere to hear", tap once.
   **You should see:** "On call". Within about 20 seconds Gawah says the call is recorded and asks each of you to say your name and that you agree.
6. Speak these lines as Sunita, one at a time. Leave a pause of a second or two after each, and **wait whenever Gawah speaks**: talking over Gawah stops it. The AI answers as Ramesh in its own words: it quotes 25,000, comes down to 22,000, asks for a 5,000 advance, and offers a 500-a-day cut if late.

   | # | Say (as Sunita) | Then |
   |---|---|---|
   | 1 | Main Sunita hoon. Main sehmat hoon. | The AI gives its name |
   | 2 | Mujhe apna flat paint karwana hai. Two BHK hai, Indirapuram mein, third floor pe. | It quotes a price |
   | 3 | Pachees hazaar bahut zyada hai. Mera budget twenty thousand ka hai. | It comes down |
   | 4 | Theek hai, twenty two thousand done. Lekin material aapka hoga, upar se koi extra charge nahi. | It asks for an advance |
   | 5 | Theek hai, paanch hazaar advance. | |
   | 6 | Chalo theek hai. Kaam kab se start karoge? | **Wait up to 25 s:** the balance was never settled, so Gawah asks Sunita about it |
   | 7 | Baaki paisa kaam poora hone ke din de dungi. | It gives the start date |
   | 8 | Aur khatam kab tak hoga? 15 tareekh ko mere ghar pe guests aa rahe hain. | It promises Friday, and a cut if late |
   | 9 | Theek hai, paanch sau kaat lena. | |
   | 10 | Chalo, sab tay ho gaya. Dhanyavaad Ramesh ji. | **Wait up to 45 s:** Gawah reads every term back and asks both to say haan |
   | 11 | Haan, sab sahi hai. | |

   You can also ask Gawah directly at any point, for example "Gawah ji, advance kitna tay hua tha?", and it answers from the record.
7. Press the red **End** button.
8. **You should see on the board, during the call:** the six terms on the left filling in (work, amount 22,000, advance 5,000, balance, dates, late or unfinished), each term's versions as chips (25,000 and 20,000 as offers, 22,000 agreed in both people's colours), every fact in the timeline with a play button for its clip, and the witness chain under the terms, "verified".
9. **After the call:** within about a minute both chats get the agreement: a line, a link to the PDF (version 1, Hindi and English), and a link to the spoken summary. The live server has the separate call-back step switched off, so what both agreed on the call is the confirmation.

No microphone (a headless browser, for example)? The call page uses the browser's normal microphone, so a browser that plays a WAV file as its microphone works the same way. Recordings of Sunita's lines are in `fixtures/audio/`; `fixtures/story/story_call_1.json` says which file is which line (its `audio` field).

### (b) A second call: a wrong figure and the original recording (live server)

On the same deal, after journey (a). Keep the worker's AI switch on.

1. In the hirer's tab, open the same call link again. The page says the call ended: press **Call again**, then **Join**.
   **You should see:** the worker's phone gets "Sunita ji aapse deal par phir se baat karna chahte hain ..." with a link, and the AI joins. Gawah greets you both by name. The board's header says call 2.
2. Say your name ("Main Sunita. Main bhi sehmat hoon."). The AI says half the work is done and asks whether the total was 25,000; it honestly remembers it wrong. If it does not, say it yourself: "Ramesh ji, total pachees hazaar tay hua tha na?"
3. **Wait up to 45 s.** **You should see and hear:** Gawah says the record holds 22,000, who said it and who agreed, on call 1, and asks "Kya main woh recording sunaun?" On the board: a red contradiction chip on the amount, a red edge back to the agreed 22,000, the amount marked "Contradicted", and a card with the original moment and a play button.
4. Say "Haan, sunaiye." Gawah plays that moment of call 1, in both people's voices. The AI accepts it.
5. Optional, a change by voice: "Ek kaam aur hai. Balcony ki deewar bhi paint kar dijiye." The AI asks 2,000 extra. Say "Theek hai, do hazaar extra. Total chaubees hazaar." **Wait:** Gawah says the record holds 22,000 and 24,000 was said, and asks both to say haan. Say "Haan, mujhe manzoor hai." Once both have, the amount reads 24,000, the old 22,000 is struck through, and version 2 of the agreement, with its change history, arrives in both chats after the call.
6. Say "Theek hai Ramesh ji, bye." and press **End**.

### (c) Payments on WhatsApp

After an agreement exists (journey a on the live server, or journey e offline).

1. From the hirer's phone send `2000 cash diya`.
   **You should see:** the hirer gets "Likh liya. Ramesh ji se confirm kar raha hoon." The worker is asked whether ₹2,000 was received, with **Haan, sahi hai** and **Nahi** under it (tap one, or type `haan` / `nahi`).
2. If the worker says **haan**: both are told the payment stands and what is still owed, worked out from the agreed terms (for example "₹2,000 mil gaya. Baaki ₹20,000.").
3. If the worker says **nahi**: both get "Ramesh ji ne mana kiya. Yeh ₹2,000 hisaab mein nahi juda. Record ke hisaab se ab tak ..." with each payment on record and what is still owed, then "Is payment ke baare mein record mein yeh hai:" with up to three items quoted from the record (for example "22 Nov ki call mein: kul paisa ₹22,000 tay hua tha ..."), each with a clip link where the audio exists. The hirer is asked for a screenshot or UPI reference. Send `UPI ref 412345678901` and the worker is asked once more; a second no leaves the claim disputed, and later messages name it.
4. A claim larger than what is owed (`50000 diya`) is answered with what was agreed, when, and a link to the clip, before the usual yes-or-no question.
5. A payment screenshot is proof on its own: from the hirer's phone, tap **+**, choose **Photo**, attach `fixtures/story/advance-5000.png` with the caption `Advance bhej diya`. On the live server Gawah reads it (₹5,000, its transaction id) and logs it without asking the worker.
6. From the worker's phone send `kaam poora ho gaya`. The hirer is asked to confirm; after a yes both are told what is still owed, and about a minute later the hirer gets one reminder of the balance and the worker is told.

In the offline mode WhatsApp text is read by a lookup instead of a model, so only these messages are understood there: `2000 cash diya`, `kaam poora ho gaya`, `8000 bheja, UPI ref 632514789023`, a UPI reference while one is asked for, and `haan` / `nahi` / the buttons. Any picture is read as a ₹8,000 advance screenshot. Anything else gets "Yeh samajh nahi aaya ...". On the live server a model reads ordinary wording.

### (d) A voice note

1. On a simulated phone that is on a deal, tap **+**, choose **Voice note**, and attach one of the recordings in `fixtures/voice-notes/` (`notes.json` there says what each one says). For example, from the worker's phone, `paint-08.ogg`: "Do coat aur putty ka touch-up, material ke saath pachees hazaar lagega madam."
2. **You should see:** the sender gets "Aapka voice note suna: "...". Deal ke record mein rakh liya." Because 25,000 differs from the agreed amount, the hirer is asked whether the total should change ("Isse deal mein kul paisa ₹... se badal kar ₹25,000 ho jayega ... Kya aap maante hain?"), and the worker is told the change holds only if the hirer says yes. On the board the note's fact appears with the whole note as its clip.
3. From the hirer's phone, `tts-paid-3000.ogg` ("maine aaj subah teen hazaar advance GPay kar diya hai") is a payment claim: the worker is asked yes or no, as in journey (c).

On the live server a voice note is transcribed by the real speech model. In the offline mode only the notes in `fixtures/voice-notes/` are understood.

### (e) Offline, with no keys

No `.env`, no keys, nothing outside your machine. See "Run it yourself" for the install.

1. Start the offline mode: `uv run python -m tests.offline --port 8000`
2. Open `http://localhost:8000/dashboard`. **You should see** an empty board.
3. Open `http://localhost:8000/dashboard/phone?number=+919000001001` and send `Ramesh +919000001002`. **You should see** the greeting and a call link; the deal appears on the board. Open `http://localhost:8000/dashboard/phone?number=+919000001002` to see the worker's invitation. Copy the deal id from the call link (`/call/<deal id>/hirer`).
4. Replay a recorded call into that deal, in a second terminal:
   `uv run python tools/replay.py fixtures/call_two_amounts.json --speed 10 --deal-id <deal id>`
   It prints each line as it goes and takes about 15 seconds. Without `--deal-id` it makes a deal of its own.
5. **You should see on the board** (`?deal=<deal id>`): the people (Sunita, Ramesh), about 30 facts in the timeline, all six terms agreed (amount ₹13,000, advance ₹3,000), offers of 15,000, 14,000 and 12,000 in the amount's lane, a red **Contradicted** on the amount (Ramesh's "total 14 hazaar" at line 19 against the 13,000 both agreed at line 11), its card with the original moment, and "Witness chain verified · 32 links". The same is readable as JSON at `/dashboard/state?deal=<deal id>` (a `fact.conflict` event) and `/memory/chain/<deal id>`.
6. Journeys (c) and (d) work on this deal too, on the simulated phones.
7. To see the agreement go out in the offline mode, start it with the call-back step off: `CALLBACKS_ENABLED=false uv run python -m tests.offline --port 8000`, then do steps 3 and 4. Both chats get "Aapki deal ka contract taiyaar hai ..." and two links. Offline nothing is printed or stored, so those links are placeholders; a real agreement made this way is in `fixtures/contract-sample/` (`contract.pdf`, `summary.ogg`, and `v2/` for a second version with its change history).

Also offline: `uv run python tools/walkthrough.py --offline` plays the whole two-call story by itself (simulated phones, both calls, the agreement, a payment, the reminder) with the app in-process, and saves events, each step's result (`steps.json`) and board screenshots to `runs/walk-<time>/`. It takes about 3 minutes and needs a Chrome-family browser. Gawah's voice is a stand-in there, so a step that waits for something Gawah says (the read-back at the end of call 1) may report `broke` even though the brain asked for it.

The offline mode has no real call: the call page opens, but its room is a local stand-in, so speaking into it does nothing. Recorded calls are how calls are seen offline. The other recorded call is `fixtures/call_missing_balance.json` (the balance is never settled, and Gawah asks).

### (f) The tests

```sh
uv run pytest -q
```

About 740 tests in about 3 minutes, with every outside service stood in for and no keys. `ffmpeg` must be installed (one test hears a voice note). `tests/test_whole_flow.py` walks one deal through every part of the app: WhatsApp, the call, the facts, Gawah's questions, the agreement, payments, a voice note and a second call. `tools/ci.sh` runs what CI runs: a frozen `uv sync`, then the tests.

---

## Run it yourself

### Prerequisites

| Tool | Version | Needed for |
|---|---|---|
| `uv` | 0.5 or newer (tested with 0.12) | Installs Python 3.12 (pinned in `.python-version`) and every dependency. Install: `curl -LsSf https://astral.sh/uv/install.sh \| sh`. Do not use the system Python. |
| `git` | any | Cloning |
| `ffmpeg` | any recent | Voice notes, and the tests. `apt-get install ffmpeg` or `brew install ffmpeg` |
| A Chrome-family browser | any recent | Printing the agreement PDF in the full mode (Chrome, Chromium, Edge, Brave, or Debian's `chromium-headless-shell`), and `tools/walkthrough.py`. Not needed for the offline mode or the tests. |
| `cloudflared` | any | Only in the full mode on a laptop: a public https address for WhatsApp webhooks |
| Docker | 24 or newer | Only to build the server image (`Dockerfile`, `deploy/compose.yaml`) |

There is no separate database or front-end build. The database is one SQLite file, made on first start; the pages are static files served by the same server.

### Install

```sh
git clone <this repository> gawah && cd gawah
uv sync
```

### Offline mode (no `.env`, no keys)

```sh
uv run python -m tests.offline --port 8000
```

- Board: `http://localhost:8000/dashboard` (no key)
- Simulated phones: `http://localhost:8000/dashboard/phone?number=+919000001001`
- Health: `http://localhost:8000/health`
- Add `--host 0.0.0.0` to open it from another machine, and `--whatsapp meta` to see Meta's message shapes (buttons, reactions, the agreement as a captioned document) instead of Twilio's.
- Each start uses a fresh database in a temporary folder, so there is nothing to seed: the recorded calls in `fixtures/` are the seed data, played in with the replayer.

Replay a recorded call into a running server (offline or full mode on this machine):

```sh
uv run python tools/replay.py fixtures/call_two_amounts.json --speed 10 [--deal-id <id>] [--url http://localhost:8000]
```

`--speed 1` is real time; 10 is ten times faster. Use 10 or slower: at 0 the whole call reaches Gawah before the first fact does. A recorded call is answered from saved model replies (`tests/brain/recorded/`, `tests/memory/recorded/`), so a replay makes no outside call even in the full mode.

### Full mode (real calls, real WhatsApp)

1. `cp .env.example .env` and fill it in (table below). You need accounts with OpenAI, LiveKit, AWS S3, Levanto (Sage2), and Meta's WhatsApp Cloud API or Twilio's WhatsApp sandbox.
2. Start a tunnel for the webhooks: `cloudflared tunnel --url http://localhost:8000`, and put its `https://...` address in `PUBLIC_BASE_URL`.
3. Start the server: `uv run uvicorn app.main:app --port 8000`
4. Point the provider's webhook at `<PUBLIC_BASE_URL>/whatsapp/webhook` (Meta: WhatsApp > Configuration > Webhook, with `META_VERIFY_TOKEN`; Twilio: the sandbox's "When a message comes in"). Meta's setup step by step is in `tools/META-SETUP.md`.
5. Open `http://localhost:8000/dashboard`.

`uv run python tools/run_live.py` does steps 2 and 3 for you on a fresh database in `runs/`, checks every outside service first (one read-only call each), prints the board's address and the webhook steps, and on Ctrl-C stops everything and closes any call rooms it opened. `uv run python tools/run_live.py --check` only checks the services. A two-phone walk through every step is in `tools/LIVE-RUN.md`.

To make a call alone on your own server, add `ACTOR_ROUTES=1` to `.env` for the "AI plays this person" switch.

### Deployment

The live server is one AWS EC2 instance running the app and Caddy (HTTPS) in Docker, with its settings in AWS Secrets Manager. The scripts are in `tools/deploy/` (`provision.sh`, `push-secrets.sh`, `deploy.sh`, `teardown.sh`) and the steps in `tools/deploy/README.md`. They create paid AWS resources. CI and CD run on GitHub Actions on every push to `main` (`.github/workflows/main.yml`).

---

## Environment variables

Every key is in `.env.example`. The offline mode reads none of them. "Full mode" means needed for real calls and WhatsApp.

| Key | What it is for | Required |
|---|---|---|
| `OPENAI_API_KEY` | Transcription, Gawah's realtime voice, turning lines into facts, reading messages and screenshots, writing the agreement, the spoken summary, search | Full mode |
| `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` | S3 access | Full mode (not on the server, which uses its instance role) |
| `AWS_SESSION_TOKEN` | Only with temporary AWS keys | Optional |
| `AWS_DEFAULT_REGION` | The S3 bucket's region | Full mode |
| `S3_BUCKET` | Recordings, voice notes, screenshots, agreement PDFs and summaries (private; shared by short-lived signed links) | Full mode |
| `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET` | The call rooms | Full mode |
| `SAGE_API_KEY` | Sage2, the live yes/no decisions on each call line | Full mode |
| `WHATSAPP_PROVIDER` | `twilio` (default) or `meta` | Optional |
| `META_WHATSAPP_TOKEN`, `META_PHONE_NUMBER_ID`, `META_VERIFY_TOKEN` | Meta's WhatsApp Cloud API | With `meta` |
| `META_APP_SECRET` | Checks that a webhook came from Meta. Empty: taken unsigned, with a warning | With `meta`; required when `ACCESS_KEY` is set |
| `META_GRAPH_VERSION` | Graph API version (default `v27.0`) | Optional |
| `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_WHATSAPP_NUMBER` | Twilio's WhatsApp sandbox | With `twilio` |
| `TWILIO_PHONE_NUMBER` | A Twilio voice number; not used by the browser calls | Optional |
| `VERIFIED_NUMBERS` | The only numbers Gawah may message, comma-separated with country code. Every other number is a simulated phone | Full mode, for real phones |
| `PUBLIC_BASE_URL` | The server's public https address, used in links and webhooks | Full mode |
| `JUDGE_MODE` | `live` (Gawah picks its moment, default) or `wrapup` (it speaks only at the end) | Optional |
| `REPLY_TIMEOUT_SECONDS` | How long Gawah waits for a WhatsApp yes or no before following up (default 120) | Optional |
| `CALLBACKS_ENABLED` | `true` (default): after a call each person confirms the terms on a short call with Gawah alone. `false`: what both agreed on the call counts as confirmed and the agreement goes out at once | Optional |
| `DATABASE_PATH` | The SQLite file (default `gawah.db` in the project folder) | Optional |
| `DEV_ROUTES` | `true` (default) keeps `/dev/publish` (used by the replayer) and the AI player's routes; `false` removes them | Optional |
| `ACTOR_ROUTES` | `1` turns on "AI plays this person" (needs `DEV_ROUTES`) | Optional |
| `ACCESS_KEY` | Set on a public server: the board, its phones, `/actor`, `/dev` and `/memory` ask for this key; clip links sent on WhatsApp are signed | Public servers |
| `GAWAH_SECRET_ID` | Shell only. The AWS Secrets Manager secret to read settings from (the server uses `gawah/prod`) | Server |
| `SENTINEL_BALANCE_REMINDER_SECONDS` | Shell only. Delay before the "work done, money owed" reminder (default 60) | Optional |
| `SENTINEL_DATE_REMINDER_HOURS_AFTER` | Shell only. Hours after a money term's date before its reminder (default 9) | Optional |
| `GAWAH_CHROME_NO_SANDBOX` | Shell only. `1` runs the PDF browser without its sandbox (set in the Docker image) | Optional |
| `BRAIN_LIVE_REPLAYS`, `MEMORY_LIVE_REPLAYS` | Shell only. `1` sends a replayed call to the live models instead of the saved replies (billed per line) | Optional |

Settings are read in this order, first wins: the environment, the Secrets Manager secret (with `GAWAH_SECRET_ID`), `.env`. "Shell only" keys are read from the environment, not from `.env`.

---

## What is simulated or not finished

- **Simulated phones.** Any number not in `VERIFIED_NUMBERS` is simulated: its messages go through the real webhook and the real intake, and Gawah's replies are shown in its chat instead of being sent.
- **Real WhatsApp** works only for numbers Karan Dua adds to his Meta test number's allowed recipients and to `VERIFIED_NUMBERS`. Meta's 24-hour rule applies: Gawah can message a real phone only within 24 hours of that phone's last message, so a real phone must message Gawah first (`hi` is enough).
- **Calls run in the browser** on LiveKit, from a link. Gawah does not ring a phone number or join a phone-network call.
- **The call-back step is switched off on the live server** (`CALLBACKS_ENABLED=false`): what both people agree on the call is the confirmation, and the agreement is sent right after the call. With it on (the default elsewhere), each person confirms the terms on a short call with Gawah alone, and that call is not recorded.
- **Languages.** Gawah speaks and writes Hindi and Hinglish; the agreement is in Hindi and English. The call pages and the board are in English.
- **The AI player** ("AI plays this person") is a testing aid for one reviewer, not part of the product. It follows a painter's story (a two-bedroom flat, 22,000) and improvises from there.
- **The offline mode** stands in for every outside service: a recorded call gets saved model replies, an unknown call gets none (Gawah stays quiet and the terms stay pending), screenshots are read by a stand-in, only the voice notes in `fixtures/voice-notes/` are understood, and the agreement is not printed.
- **Hearing.** Room noise, a fan switching on, or Gawah's own voice from a loudspeaker can cut Gawah off mid-sentence; use earphones. An amount said once can be misheard ("seventeen" as "seventy"); the read-back is the guard. A phone mutes its microphone when its screen locks or the call page goes to the background.
- **Gawah's judgement of terms** is tuned on painting deals. On other kinds of calls it misses more of the moments it should ask about.
- **WhatsApp edge cases.** A plain "haan" or "nahi" answers that person's oldest open question. A ten-digit number starting 6 to 9 in a message is taken as a new deal. An open payment dispute's request for proof is forgotten if the server restarts. Dates are written as said ("agle somvaar"), not as calendar dates.
- **The board** shows every deal to anyone with the access key, and reads the whole event log on load.
- **Deleting data** is by hand: "delete my data" (or "mera data delete karo") on WhatsApp is answered and logged, and the data is then removed following `tools/DELETE-DATA.md`.
- **The spoken summary's speech model** (`gpt-4o-mini-tts`) is due to be retired by OpenAI on 6 January 2027.
