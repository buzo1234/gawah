# Gawah - Tech Feasibility

Checked on 21 November 2026. Prices and limits come from web search today; anything not confirmed is listed under "Not verified".

## Verdict

Buildable in 2 days, at ₹0.

The deal call runs on LiveKit: Gawah sends both people a link on WhatsApp, and tapping it opens the call in the browser. This replaced the earlier plan of real phone calls through Twilio, because the Twilio trial account has no phone number and no verified phones, calling Indian mobiles on a trial is unconfirmed, and we have only one real phone.

What we give up: phones do not ring for the deal call, and each person needs a smartphone browser. The real product would use phone calls; the demo uses a link.

The main risk is now the Judge's timing - knowing when to speak in a live conversation.

## What we have

All confirmed working on 21 Nov unless marked.

- OpenAI credits - key works. Speech-to-text, the realtime voice model, and the reasoning model.
- AWS credits, including Bedrock - keys work (temporary, will expire). S3 bucket created in `us-west-2`.
- LiveKit free plan - keys work. Runs the call.
- Twilio trial - keys work. Used only for the WhatsApp sandbox. No phone number claimed.
- Sage2 (Levanto Labs) free plan - $1 of usage a month. Key is in `.env`, not yet tested.
- Up to ₹1,000 (about $11) for anything else. The plan below does not need it.

## Use the free plans with care

LiveKit and Twilio are both on free plans with monthly allowances. Burning them in testing means no demo.

- Build and test against the fakes and the replayer. Open a real LiveKit room or send a real WhatsApp message only for a spike, a manual check, or a demo run.
- One room at a time. Every room gets a short empty-timeout and a hard maximum length (10 minutes).
- Always disconnect and close the room when a test ends. Never leave the agent sitting in a room.
- No LiveKit recording service. The agent saves the audio itself.
- No loops that send WhatsApp messages. The sandbox allows one message every three seconds; stay well under it.
- Sage2 has the tightest allowance of all: about a dozen full-length calls a month. Replay the saved results in `spikes/5-results/` while building; go live only to tune and to demo.
- Do not poll either service's API in a loop.
- Automated tests never touch LiveKit or Twilio.

## Feature by feature

| Feature | Feasible in 2 days | How | Risk |
|---|---|---|---|
| Gawah connects both parties on a call | Yes | A LiveKit room per deal; each person gets a join link on WhatsApp | Medium - opening the link from inside WhatsApp needs the mic to work |
| Knowing who said what | Yes | Each person is a separate audio track in the room | Low |
| Live transcript in Hindi / Hinglish | Yes | Each track goes to OpenAI `gpt-transcribe`, with a prompt and Hindi plus English hints | Medium - tested on recorded Hinglish; a single amount can be misheard |
| Judge tracks pending contract items, live | Yes | Sage2 stream: one yes/no question per checklist item, updated as each line is said | Low - tested on Hinglish, 286 of 286 answers right |
| Judge speaks like a person in the call | Yes | OpenAI realtime voice model, published into the room as Gawah's audio, silent until told to speak | Medium - we wire this ourselves |
| Picking the right moment to speak | Yes, with tuning | Sage2 decisions on how the call is going, plus waiting for a pause | High - this is the part to tune |
| Read-back of full terms on the call | Yes | Same voice model | Low |
| Independent call-back to each party | Yes | A one-to-one room; the person taps a link | Low - but it is a link, not a ring |
| Replay the clip of a disputed term | Yes, as a stretch | Keep timestamps per transcript line, cut the clip, play it in the room | Medium - extra work |
| Contract sent to both | Yes | Reasoning model writes it, render as PDF, send on WhatsApp with a voice summary | Low |
| WhatsApp bot takes in records | Yes | Twilio WhatsApp sandbox; Meta's free test number as backup | Low |
| Backed vs unbacked records | Yes, for demo | Vision model reads the screenshot; has a transaction ID = backed | Low - not a real bank check |
| Bot asks the other party to confirm | Yes | WhatsApp message with a yes/no reply | Low |
| Follow-up if no WhatsApp reply | Yes | Timer (2 minutes in the demo), then a second message with a call link | Low - a real ring needs a Twilio number |

## Recommended setup

### 1. The deal call

- One party messages Gawah on WhatsApp with the other person's number.
- The server creates a LiveKit room for the deal and sends each person their own join link on WhatsApp.
- The link opens a small page served by our app: one button, mic on, audio only. No install.
- Gawah's agent joins the same room as a third participant.
- Each person is a separate audio track. This is what tells us who is speaking - no speaker-separation model needed.
- The call starts with a short recording notice and both say yes.

LiveKit's agent framework is built around one person talking to one agent. For two people plus Gawah we do not use that ready-made session. The agent subscribes to each person's track itself and handles them separately. LiveKit's repo has a multi-user transcriber example to start from.

### 2. Witness and Judge

One live voice on the call, with a harness behind it deciding what it says and when. Four parts:

- Ears (Witness): each person's audio track goes to OpenAI `gpt-transcribe` (listed at $0.0045 per minute), with a short prompt (the speakers' names, the kind of words to expect) and Hindi plus English language hints. Our own end-of-speech detection decides when a line ends, not OpenAI's, which added words nobody said. The text arrives about a second after the line ends (0.8-0.9 s measured), on top of however long our detection waits to decide the person has stopped. Transcript lines are saved with speaker and timestamp. The agent also writes each track's audio to a file and uploads it to S3 at the end.
- Fast brain (Sage2): every transcript line is appended to a Sage2 stream. Sage2 answers a fixed set of questions about the call so far and sends an update only when an answer changes. Measured from India: about half a second per update (the vendor states 80-130 ms; half of our delay is the network trip to its US servers).
- Mouth (voice model): OpenAI's realtime voice model (`gpt-realtime-2.1`). The agent holds a connection to it and publishes its audio into the room as Gawah's voice. Automatic replies are switched off, so it stays silent until the harness tells it to speak. If someone talks over it, the agent stops the audio, like a person would.
- Slow brain (reasoning model): writes the contract after the call. Not in the live loop.

Questions Sage2 answers during the call (limit is 32 per session):

- Contract items, one yes/no each: has the work been agreed? the amount? the advance? when the balance is paid? the dates? what happens if late or unfinished?
- How the call is going: did someone just speak to Gawah directly? did they move to a new topic and leave the last one unclear? have two different figures been said for the same term? are they wrapping up?
- When an item turns to yes, a small OpenAI text model pulls the value (amount, date, duration). Sage2's own extract call is not used: on Hinglish it found the right words but returned wrong values ("42 hazaar" came back as 42). `gpt-5.4-mini` got all five test values right in about 2 seconds.
- Contract items latch: once an item is yes it stays yes. Sage2 drops the amount back to no when a second figure is said, and the "two different figures" question is the signal for that.

When the Judge speaks:

- Someone speaks to it directly - answer.
- They moved on and left a term unclear - ask about it now, while it is fresh.
- Two different figures for the same term - ask which one is right.
- They are wrapping up with items pending - ask before they hang up.

How it stays polite:

- It only starts in a pause, never mid-sentence.
- One question at a time, to the person who has to answer.
- A minimum gap between two interruptions.
- When the harness decides to speak, it sends the voice model a short text instruction (what to ask, whom to ask). The voice model phrases it naturally in Hindi.

Safety switch: one setting that turns the Judge back to "speak only at wrap-up". If the timing misbehaves on demo day, flip it.

### 3. Call-backs and follow-ups

- The independent call-back is a one-to-one room. Gawah sends the person a link; when they join, the realtime voice model talks to them directly. One person and one agent is the case LiveKit's framework is built for, so this is the easy one.
- "No WhatsApp reply" is followed by a second message with a call link.
- Stretch: claim a Twilio trial number and verify our phone, so this one follow-up is a real ringing call. One outbound call to our own verified phone is the simplest thing a Twilio trial can do.

### 4. WhatsApp

- Twilio's WhatsApp sandbox. It uses a number Twilio provides, so we need no number of our own - only the account keys we already have. Ours is `+17372508034` (the number in Twilio's docs, `+14155238886`, was not the one our console showed).
- Each person joins by sending the join code from the Twilio console to that number. Membership lasts three days. We joined on 21 Nov, so it lapses on 24 Nov.
- Backup: Meta's WhatsApp Cloud API test number - also free, up to 5 verified recipients, more setup.
- Both only allow free-form replies after the user has messaged first. So in the demo, each person starts by messaging Gawah. That also works as onboarding.

### 5. Records

- Incoming image or text goes to a vision-capable model that pulls out amount, date, and transaction ID.
- Rule for the demo: a payment screenshot with a transaction ID is backed and logged directly. Anything else is unbacked and needs the other party to confirm.
- We cannot check a payment with the bank in the demo. Say so if asked.

### 6. Hosting and storage

- The app and the agent run on the laptop during the hackathon. An EC2 server is optional.
- A free `cloudflared` tunnel gives the public https address. Twilio needs it to deliver WhatsApp messages, and phones need https to allow the mic on the call page.
- S3 for recordings, clips, and contract PDFs. SQLite for deals and records.

### AWS backups

- If OpenAI's Hindi transcription is weak: Amazon Transcribe.
- If we want a second reasoning model: any text model on Bedrock.

## If LiveKit fails - real phone calls through Twilio

The earlier plan, kept as the fallback.

- Claim a Twilio trial number, verify our phones, and have Gawah dial both people and join them in a conference. Each call leg is streamed separately, so who-said-what still works.
- Limits: a trial can only call verified numbers (up to 5), plays a trial message at the start of each call, shows a foreign caller ID, and may not be able to call Indian mobiles at all.
- With one phone, the second person would join as a Twilio browser caller.
- Phone audio is lower quality than a browser call, so transcription gets harder.

## Cost

| Item | Cost |
|---|---|
| OpenAI speech and reasoning | Credits. A 10-minute demo call is well under $2. |
| AWS storage | Credits |
| LiveKit calls | Free plan |
| Sage2 decisions | Free plan, $1 of usage a month. Every update re-bills all ten questions, so a 30-line call is about $0.02-0.03 and a full-length call about $0.08. That is roughly a dozen full calls a month. The spike used about $0.11. |
| Twilio WhatsApp sandbox | Trial allowance |
| Tunnel | Free |
| Total out of pocket | ₹0 |

What would cost money, and is not needed for the demo:

- Sage2's first paid plan is $14 a month, just over the ₹1,000 cap. Only needed if the free usage runs out.
- A paid LiveKit plan, if we use up the free allowance.
- Upgrading Twilio, to remove the trial limits.

## Risks, in order

1. Picking the moment to speak. A wrong interruption is worse than silence. Sage2's docs describe live call monitoring, but not turn-taking - that use is ours and unproven. Tune it on recorded practice calls, and keep the safety switch.
2. Two people plus an agent on LiveKit. The framework's ready-made session handles one person. We wire the per-person tracks and the voice output ourselves. Prove it in the first spike.
3. Sage2's free usage. It works on Hinglish, but $1 a month is only about a dozen full-length calls, and the spike has used about a tenth of it. Build the brain against the saved spike results, and use live Sage2 only for tuning runs and the demo. Backup: the same questions on a small OpenAI text model, or Sage2's $14 plan.
4. The call link opened from WhatsApp. Some in-app browsers block the mic. Test on the real phone early; the fix is a "open in browser" prompt.
5. Running out of free allowance. See "Use the free plans with care".
6. An amount said only once can be misheard. In the spike "seventeen thousand" came back as "seventy thousand" every time, and it reads as confidently as a correct line. The read-back on the call and the separate confirmation with each person are what protect the contract.
7. AWS keys expiring mid-build. Replace all three together when they do.
8. Time. See the cut list.

## Test these first (first 3 hours)

1. LiveKit: phone (from a WhatsApp link) and laptop join one room and hear each other. The agent joins and receives the two voices as separate tracks.
2. Send one track to `gpt-transcribe` and speak Hinglish. Read the transcript.
3. Publish the realtime voice model's audio into the room. Check that it stays silent until triggered, speaks Hindi when told, and can be cut off.
4. WhatsApp sandbox: receive a text and an image, reply to both.
5. Sage2: open a stream with three questions, feed it a Hinglish transcript line by line, and check the answers and the delay.

If 1 fails, fall back to Twilio phone calls. If 2 fails, try Amazon Transcribe. If 3 fails, generate speech from text and play that into the room. If 5 fails, use a small OpenAI text model for the decisions.

## Cut list

Build for real:

- The deal call with per-speaker transcript
- Judge asking at the right moment and reading back the terms
- Contract sent on WhatsApp
- Record intake with backed / unbacked, confirm on WhatsApp, follow up if no reply

Simplify:

- Independent call-backs - do it for one party in the demo
- Disagreement flow - show the clip replay only, as the highlight

Skip:

- Judge in disputes, voice forensics, Khatabook

Stretch:

- A real ringing phone for the no-reply follow-up, through a Twilio trial number

## Not verified

- Whether our agent, running on the laptop, counts as a participant against LiveKit's 5,000 call minutes. The pages do not say. Assume it does.
- How much of this month's LiveKit allowance is already used. It is shared across all free projects on the account. Check the LiveKit dashboard.
- Whether the call page's mic works when the link is opened inside WhatsApp.
- Whether our server can receive and reply to sandbox messages. Joining works on the trial (see below); the webhook is untested until the server exists.
- Sage2's real spend so far. The spike estimated $0.11 from token counts; check the Levanto dashboard.
- Sage2 on real transcription output. The Sage2 spike used clean hand-written transcripts; real lines have mishearings and are in Devanagari. Real transcripts to try it on are now in `spikes/2-results/`.
- Transcription on a real two-person call. The spike used one person reading both parts into a laptop mic, one line per file. Our own end-of-speech detection is also untested.
- Current WhatsApp message pricing - sources conflict after 1 October 2026. Irrelevant at demo volume.

Confirmed on 21 Nov:

- OpenAI key: `gpt-realtime-2.1`, `gpt-realtime-2.1-mini`, and `gpt-transcribe` are all available. Also available and worth a look: `gpt-4o-transcribe-diarize`, `gpt-live-1.1`, `gpt-live-transcribe`.
- AWS keys work; S3 bucket created and written to.
- LiveKit keys work.
- LiveKit free plan ("Build"), from its pricing and limits pages: 5,000 call minutes a month, counted per person connected; 100 connections at once; 60 minutes of its recording service. It is a hard cap - once used up, new calls fail, with no charges. It resets on the 1st of each month. The 1,000 "agent session minutes" are for agents hosted on LiveKit's cloud; ours runs on the laptop, and the docs treat that as self-hosted. A 10-minute call with two people and the agent is about 30 minutes of allowance, so roughly 160 such calls a month.
- Sage2 on Hinglish (spike 5, `spikes/5-sage2.md`): yes/no decisions were right on 286 of 286 answers in Roman Hinglish, 285 of 286 in Devanagari, and 147 of 150 on a second, unseen call. About half a second per update. Its extract call is not usable for Hinglish values.
- OpenAI transcription on Hinglish (spike 2, `spikes/2-ears.md`): `gpt-transcribe` with a prompt got 36 to 40 of 42 amounts, dates, names and brands right on 24 recorded lines, always in Devanagari, with the text 0.8-0.9 seconds after the line ends. "Seventeen thousand" was heard as "seventy thousand" in 42 of 43 runs. `gpt-live-transcribe` was less accurate and costs four times as much.
- Amazon Transcribe supports Hindi (`hi-IN`, streaming, `us-west-2`). On five lines it was not clearly better than OpenAI, so it stays a backup.
- Twilio keys work; the account is a trial with no phone number and no verified phones.
- WhatsApp sandbox joined from our phone on the trial account: the join message arrived and Twilio's reply was delivered and read.

## Ruled out

- Amazon Connect: India is listed as outbound-only through a partner beta. Not a 2-day option.
- Exotel and Plivo Indian numbers: KYC documents will not clear in 2 days.
- WhatsApp's own calling API: exists and has an India rate card, but needs a full business setup.

## References

- [LiveKit: OpenAI realtime integration](https://docs.livekit.io/agents/models/realtime/openai/)
- [LiveKit: OpenAI speech-to-text](https://docs.livekit.io/agents/models/stt/openai/)
- [LiveKit: request for multi-participant sessions](https://github.com/livekit/agents/issues/6795)
- [LiveKit: multi-participant transcription issue](https://github.com/livekit/agents/issues/3657)
- [LiveKit: pricing](https://livekit.com/pricing)
- [LiveKit: quotas and limits](https://docs.livekit.io/deploy/admin/quotas-and-limits/)
- [Twilio: WhatsApp sandbox](https://www.twilio.com/docs/whatsapp/sandbox.md)
- [Twilio: free trial account](https://www.twilio.com/docs/usage/tutorials/how-to-use-your-free-trial-account)
- [OpenAI: models](https://developers.openai.com/api/docs/models)
- [OpenAI: gpt-transcribe](https://developers.openai.com/api/docs/models/gpt-transcribe)
- [OpenAI: realtime conversations guide](https://developers.openai.com/api/docs/guides/realtime-conversations)
- [OpenAI: new voice models announcement](https://openai.com/index/advancing-voice-intelligence-with-new-models-in-the-api/)
- [Microsoft: realtime audio, switching off automatic replies](https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/realtime-audio)
- [Forasoft: OpenAI realtime pricing, Nov 2026](https://www.forasoft.com/blog/article/openai-realtime-api-pricing)
- [Levanto: Sage2 model page](https://levanto.ai/model)
- [Levanto: pricing](https://levanto.ai/pricing)
- [Levanto: streaming docs](https://docs.levanto.ai/stream)
- [Meta: WhatsApp calling pricing](https://developers.facebook.com/documentation/business-messaging/whatsapp/calling/pricing)
- [RichAutomate: WhatsApp Cloud API test number limits](https://richautomate.in/blog/whatsapp-cloud-api-test-number-sandbox-india-2026)
- [AWS: Amazon Connect telecoms coverage](https://d1v2gagwb6hfe1.cloudfront.net/Amazon_Connect_Telecoms_Coverage.pdf)
