# Open items

Known gaps, faults, and follow-ups found while building and reviewing. Each says where it was found. Status is Open, In progress, Fixed, or Accepted (known and left as is for the demo).

Last updated: 21 November 2026.

## Blocking the demo

| # | Item | Found in | Status |
|---|---|---|---|
| 1 | **Real WhatsApp sends are refused.** Twilio answers error 21654 ("ContentSid Required") to every free-form message to the real phone. Nothing has reached a real phone. Next step: tunnel up, sandbox webhook address set in the Twilio console, the real phone sends a normal message, then retry. Fallback: Meta's test number. | PR 3 | Open |
| 2 | **Speech detection fails on real microphones.** A plain loudness threshold treats room noise as speech: Gawah was cut off 3 times out of 3 with nobody speaking. Earphones were in, so this was room noise and not echo. Both `bridge` and `mouth` are replacing it with a real voice-activity detector. | The user's phone check | In progress |
| 3 | **`bridge` and `mouth` are not built yet.** No real call has run through the product. | - | In progress |
| 4 | **The streams have never run together on a real call.** The whole-flow test covers WhatsApp, brain, and records on fakes. | PR 9 | Open |

## Should fix before the demo

| # | Item | Found in | Status |
|---|---|---|---|
| 10 | **The worker's name is unknown at deal start.** A deal starts with only the worker's phone, so the Judge may say "Ask Worker ...". Either take the name from the hirer's first message, or from the names said at the start of the call. | PR 9 | Open |
| 11 | **Wrap-up is detected late on one practice call**, about two seconds before the call ends. | PR 4 | Open |
| 12 | **An amount said only once can be misheard.** "Seventeen thousand" came back as "seventy thousand" in 42 of 43 runs. The read-back and the call-back are the protection; check the Judge really reads figures back. | PR 7 | Open |
| 13 | **The phone mutes its microphone** when the screen locks or the page goes to the background. The call page should keep the screen awake and say so. | The user's phone check | In progress |
| 14 | **WhatsApp says "PDF below" with nothing attached** when the contract event has no usable file. | PR 9 | Open |
| 15 | **Nobody has listened to the contract's voice summary.** It was checked by transcribing it back. | PR 6 | Open |
| 16 | **Echo.** Whether Gawah's own voice coming out of a loudspeaker cuts it off has not been tested. | PR 8 | Open |

## Accepted for the demo

| # | Item | Found in | Status |
|---|---|---|---|
| 30 | A "haan" or "nahi" answers the person's oldest open question, which may be the wrong one if several are open. | PR 3 | Accepted |
| 31 | A 10-digit number starting 6-9 inside a record message is taken as a new deal. | PR 3 | Accepted |
| 32 | A record's image link is Twilio's, so the dashboard cannot show the image. | PR 3 | Accepted |
| 33 | The dashboard is readable through the tunnel by anyone with a call link. | PR 5 | Accepted |
| 34 | The dashboard reads the whole event log on load, and chats are per number across all deals. Start the demo on a fresh database. | PR 5 | Accepted |
| 35 | The dashboard's default second-phone number only starts a deal if typed with `+91`. | PR 9 | Accepted |
| 36 | The contract leaves "tomorrow morning" and "next Monday" as said. | PR 6 | Accepted |
| 37 | If a term changes after one person confirmed, that confirmation still stands. | PR 6 | Accepted |
| 38 | The contract is not retried automatically after a failure. | PR 6 | Accepted |
| 39 | Only one conflict per call is tracked by the brain. | PR 4 | Accepted |
| 40 | A person who drops without leaving is reported gone only after 22 seconds. | PR 8 | Accepted |
| 41 | Docstrings in `app/contracts.py` name some listeners that do not exist. | PR 9 | Accepted |

## Around the build

| # | Item | Status |
|---|---|---|
| 50 | **The laptop's network drops out.** Several agents hit brief DNS failures reaching OpenAI and the package index. Have a phone hotspot ready for the demo. | Open |
| 51 | **AWS keys are temporary** and will expire. Replace all three together. | Open |
| 52 | **WhatsApp sandbox membership lapses on 24 November.** Rejoin with the same join code. | Open |
| 53 | **Sage2's free usage** is about a dozen full-length calls a month. A second free account is the user's fallback; check Levanto's terms. | Open |
| 54 | **The speech model for the voice summary is retired on 6 January 2027.** | Open |
| 55 | **Disk space on the laptop is tight.** `~/.cache/uv` is 50 GB; `uv cache prune` is the safe way to recover it. | Open |
| 56 | Proof files left in the S3 bucket under `contracts/contract-proof-*`. | Open |
| 57 | Rehearse without `--reload`: a restart drops WhatsApp's open questions. | Open |
