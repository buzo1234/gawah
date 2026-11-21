# Open items

Known gaps, faults, and follow-ups found while building and reviewing. Each says where it was found. Status is Open, In progress, Fixed, or Accepted (known and left as is for the demo).

Last updated: 21 November 2026.

## Blocking the demo

| # | Item | Found in | Status |
|---|---|---|---|
| 1 | **Real WhatsApp sends are refused.** Twilio answers error 21654 ("ContentSid Required") to every free-form message to the real phone. Nothing has reached a real phone. Next step: tunnel up, sandbox webhook address set in the Twilio console, the real phone sends a normal message, then retry. Fallback: Meta's test number. | PR 3 | Open |
| 2 | **Speech detection fails on real microphones.** A plain loudness threshold treats room noise as speech: Gawah was cut off 3 times out of 3 with nobody speaking. Earphones were in, so this was room noise and not echo. Both `bridge` and `mouth` now use a speech detector plus each person's own noise floor: no false cut-offs on noise and clicks in their tests. Needs the phone check repeated once both are merged. | The user's phone check | In review (PRs 10, 11) |
| 3 | **`bridge` and `mouth` are built, not merged.** No real call has run through the whole product yet. | - | In review (PRs 10, 11) |
| 4 | **The streams have never run together on a real call.** The whole-flow test now covers every stream on fakes, and one dry run walked the demo on the real services with simulated phones (see `REPORT.md` of the e2e branch). A run with a person is still to do. | PR 9 | In progress |

## Should fix before the demo

| # | Item | Found in | Status |
|---|---|---|---|
| 10 | **The worker's name is unknown at deal start.** A deal starts with only the worker's phone, so the Judge may say "Ask Worker ...". Either take the name from the hirer's first message, or from the names said at the start of the call. | PR 9 | Open |
| 11 | **Wrap-up is detected late on one practice call**, about two seconds before the call ends. | PR 4 | Open |
| 12 | **An amount said only once can be misheard.** "Seventeen thousand" came back as "seventy thousand" in 42 of 43 runs. The read-back and the call-back are the protection; check the Judge really reads figures back. | PR 7 | Open |
| 13 | **The phone mutes its microphone** when the screen locks or the page goes to the background. The call page should keep the screen awake and say so. | The user's phone check | In progress |
| 14 | **WhatsApp says "PDF below" with nothing attached** when the contract event has no usable file. Now the line names only what is attached, and says so when nothing could be. | PR 9 | Fixed (e2e) |
| 15 | **Nobody has listened to the contract's voice summary.** It was checked by transcribing it back. | PR 6 | Open |
| 16 | **Echo.** Whether Gawah's own voice coming out of a loudspeaker cuts it off has not been tested. The user's check had earphones in, so it is still open. | PR 8, PR 11 | Open |
| 17 | **A sudden jump in room noise** (a fan switching on) while Gawah speaks can still cut it off. | PR 11 | Open |
| 18 | **A record confirmed on the call-back is not reported on WhatsApp.** `app/records` does not listen for `record.confirmed` from the call-back, so the sender is not told, and a later "haan" on WhatsApp would answer it again. Records now closes the question and tells the sender. | PR 11 | Fixed (e2e) |
| 19 | **A dropped question publishes nothing**, so the brain waits out its 12-second timeout before asking anything else. Mouth now sends an empty `judge.spoke` with no start time; the brain stops waiting and does not count it as heard. | PR 11 | Fixed (e2e) |
| 22 | **A second call on a deal** (PR followup-call): the brain restarts its checklist and asks every term again; its re-sent `call.started` has no `call_no`; WhatsApp re-sends the call-back links and does not tell the other person a call has started; a contract written after call 2 calls it "the call". For Phase 2. | Second-call stream | Open |
| 21 | **The Judge tracks terms poorly on calls it was not tuned on.** 4 of 10 required moments on five held-out calls. A filler "theek hai" can mark a term agreed for good; "no advance" is not taken as settled; a rejected counter-offer (35,000) was read as the agreed total (38,000) and would be read back aloud. Planned fix: the checklist comes from the memory's facts (Phase 2 of `gawah-crew.md`). | Held-out evaluation | Open |
| 20 | **Nobody has listened to Gawah's voice samples** in `fixtures/mouth-samples/`. | PR 11 | Open |

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
| 42 | A transcript line arrives about 2.3 seconds after the person stops (1 second of it is the wait for silence). | PR 10 | Accepted |
| 43 | Someone much quieter than the recordings may be dropped by the one fixed level left in the line detector. | PR 10 | Accepted |
| 44 | One call per deal; after it ends, the link says the call is over. | PR 10 | Accepted |
| 45 | The call-back is not recorded or transcribed, and anyone with its link can open it. | PR 11 | Accepted |
| 46 | A real call costs about 40 LiveKit participant-minutes per 10 minutes (two people, the hidden listener, and Gawah), and sends the brain to live Sage2. | PR 10, PR 11 | Accepted |

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
| 58 | **A rare test failure under heavy load.** Seen twice while five or six agents ran tests at once; its name was never captured. With two agents running, `main` passed 8 runs out of 8 (443 tests). Run the suite before the demo on a quiet laptop. | Open |
