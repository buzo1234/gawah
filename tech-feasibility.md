# Gawah - Tech Feasibility

Checked on 21 November 2026. Prices and limits come from web search today; anything not confirmed is listed under "Not verified".

## Verdict

Buildable in 2 days, at ₹0 if the phone leg works on a free trial.

The one real risk is placing phone calls to Indian numbers without a paid, KYC-verified telephony account. Everything else (speech, the judge, WhatsApp, the contract) is standard and covered by the OpenAI and AWS credits.

So: test the phone leg in the first 3 hours. If it fails, switch to Plan B (a call that runs in the browser from a WhatsApp link) and keep everything else the same.

## What we have

- OpenAI credits - speech-to-text, the voice agent, text-to-speech, and the reasoning model.
- AWS credits, including Bedrock - the server, storage, and a backup for speech and reasoning.
- Sage2 (Levanto Labs) free plan - a fast decision and extraction model, with $1 of usage a month. Enough for the demo.
- Up to ₹1,000 (about $11) for anything else. The plan below does not need it.

## Feature by feature

| Feature | Feasible in 2 days | How | Risk |
|---|---|---|---|
| Gawah calls both parties and connects them | Yes, if the trial allows calls to India | Twilio trial: two outbound calls joined in a conference | High - test first |
| Knowing who said what | Yes | Each person is a separate call leg; stream each leg's audio separately | Low |
| Live transcript in Hindi / Hinglish | Yes | OpenAI `gpt-transcribe` on each leg's audio stream | Medium - phone audio is low quality |
| Judge tracks pending contract items, live | Yes | Sage2 stream: one yes/no question per checklist item, updated as each line is said | Medium - Hinglish support not stated |
| Judge speaks like a person in the call | Yes | OpenAI realtime voice model joins as a third participant, silent until told to speak | Medium - needs careful session settings |
| Picking the right moment to speak | Yes, with tuning | Sage2 decisions on how the call is going, plus waiting for a pause | High - this is the part to tune |
| Read-back of full terms on the call | Yes | Same voice model | Low |
| Independent call-back to each party | Yes | One-to-one call with OpenAI's realtime voice model | Medium |
| Replay the clip of a disputed term | Yes, as a stretch | Keep timestamps per transcript line, cut the clip, play it in the call | Medium - extra work |
| Contract sent to both | Yes | Reasoning model writes it, render as PDF, send on WhatsApp with a voice summary | Low |
| WhatsApp bot takes in records | Yes | Twilio WhatsApp sandbox or Meta's free test number | Low |
| Backed vs unbacked records | Yes, for demo | Vision model reads the screenshot; has a transaction ID = backed | Low - not a real bank check |
| Bot asks the other party to confirm | Yes | WhatsApp message with a yes/no reply | Low |
| Call only if no WhatsApp reply | Yes | Timer (2 minutes in the demo), then an outbound call | Low |

## Recommended setup

### 1. The bridge call

- One party messages Gawah on WhatsApp with the other person's number.
- The server places two outbound calls through Twilio and joins them in a conference.
- Each call leg streams its own audio to the server. This is what tells us who is speaking - no speaker-separation model needed.
- The call starts with a short recording notice and both say yes.

### 2. Witness and Judge

One live voice on the call, with a harness behind it deciding what it says and when. Four parts:

- Ears (Witness): each leg's audio goes to OpenAI `gpt-transcribe` (listed at $0.0045 per minute). Transcript lines are saved with speaker and timestamp. The full call recording goes to S3.
- Fast brain (Sage2): every transcript line is appended to a Sage2 stream. Sage2 answers a fixed set of questions about the call so far and sends an update only when an answer changes (about 80-130 ms, vendor-stated).
- Mouth (voice model): OpenAI's realtime voice model (`gpt-realtime-2.1`) sits in the call as a third participant. Automatic replies are switched off, so it stays silent until the harness tells it to speak. If someone talks over it, it stops, like a person would.
- Slow brain (reasoning model): writes the contract after the call. Not in the live loop.

Questions Sage2 answers during the call (limit is 32 per session):

- Contract items, one yes/no each: has the work been agreed? the amount? the advance? when the balance is paid? the dates? what happens if late or unfinished?
- How the call is going: did someone just speak to Gawah directly? did they move to a new topic and leave the last one unclear? have two different figures been said for the same term? are they wrapping up?
- When an item turns to yes, Sage2's extract call pulls the value (money, date, duration, text) with the source words and a probability.

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

### 3. Call-backs and no-reply calls

- These are one-to-one calls, so use OpenAI's realtime voice model (`gpt-realtime-2.1`, or the cheaper `gpt-realtime-2.1-mini`). Connecting a Twilio call to it is a well-documented pattern.
- Same setup is reused for "call only if no WhatsApp reply".

### 4. WhatsApp

- First choice: Twilio's WhatsApp sandbox - same account as the calls, minutes to set up.
- Backup: Meta's WhatsApp Cloud API test number - free, up to 5 verified recipients.
- Both only allow free-form replies after the user has messaged first. So in the demo, each person starts by messaging Gawah. That also works as onboarding.

### 5. Records

- Incoming image or text goes to a vision-capable model that pulls out amount, date, and transaction ID.
- Rule for the demo: a payment screenshot with a transaction ID is backed and logged directly. Anything else is unbacked and needs the other party to confirm.
- We cannot check a payment with the bank in the demo. Say so if asked.

### 6. Hosting and storage

- One small EC2 server running the whole app. Audio streaming needs long-lived connections, so a single server is simpler than serverless.
- A free tunnel (cloudflared or ngrok) for the public address Twilio needs during development.
- S3 for recordings, clips, and contract PDFs. SQLite on the server for deals and records.

### AWS backups

- If OpenAI's Hindi transcription is weak: Amazon Transcribe.
- If OpenAI's Hindi voice is weak: Amazon Polly.
- If we want a second reasoning model: any text model on Bedrock.

## Plan B - no phone network

If trial accounts cannot call Indian numbers:

- Gawah sends both parties a link on WhatsApp. Tapping it opens an audio call in the phone's browser.
- Use LiveKit (open source, free plan) for the audio room. Each person is a separate audio track, so who-said-what still works.
- Witness, Judge, WhatsApp, records, and the contract stay exactly the same.
- LiveKit's agent framework supports a realtime voice model joining a room (from memory, not checked today), so the live Judge may be easier to wire up here than on a phone conference.
- What we lose: the phone does not ring. The "call only if no reply" step becomes a second WhatsApp nudge with the link.

Decide by hour 3. Do not spend the first day fighting telephony.

## Cost

| Item | Cost |
|---|---|
| OpenAI speech and reasoning | Credits. A 10-minute demo call is well under $2. |
| AWS server and storage | Credits |
| Sage2 decisions and extraction | Free plan, $1 of usage a month. A live call costs about $0.0013 at listed rates. |
| Twilio calls and WhatsApp sandbox | Trial allowance |
| Tunnel, LiveKit free plan | Free |
| Total out of pocket | ₹0 |

What would cost money, and is not needed for the demo:

- Removing Twilio's trial message and the verified-numbers limit means upgrading the account.
- Sage2's first paid plan is $14 a month, just over the ₹1,000 cap. Only needed if the free usage runs out.
- An Indian phone number from an Indian provider (Exotel, Plivo) needs KYC documents, which will not clear in 2 days.

## Risks, in order

1. Calling Indian numbers on a trial. Trial accounts can only call verified numbers (up to 5), play a trial message at the start of each call, and may be limited to the sign-up country. Sign up with an Indian mobile number and verify the team's phones.
2. Picking the moment to speak. A wrong interruption is worse than silence. Sage2's docs describe live call monitoring, but not turn-taking - that use is ours and unproven. Tune it on recorded practice calls, and keep the safety switch.
3. Sage2 on Hinglish. Its pages do not mention Hindi or any Indian language. Backup: ask the same questions of a small, fast OpenAI text model - slower, but known to handle Hinglish.
4. The voice model in a three-way call. It hears both voices mixed together, and there are bug reports of it replying on its own even with automatic replies off. Test the session settings early.
5. Hindi and Hinglish accuracy on phone audio. Sources disagree on how good OpenAI's models are for Indian languages. Test with our own voices early.
6. Foreign caller ID. Calls will show a non-Indian number. Fine for a demo on our own phones, not fine for real users.
7. Time. More moving parts than the simple version. See the cut list.

## Test these first (first 3 hours)

1. Twilio trial: call one Indian mobile. Then call two and join them in a conference.
2. Stream one leg's audio to `gpt-transcribe` and speak Hinglish. Read the transcript.
3. Add the realtime voice model to the conference as a third participant. Check that it stays silent until triggered, speaks Hindi when told, and stops when talked over.
4. WhatsApp sandbox: receive a text and an image, reply to both.
5. Sage2: open a stream with three questions, feed it a Hinglish transcript line by line, and check the answers and the delay.

If 1 fails, go to Plan B. If 2 fails, try Amazon Transcribe. If 5 fails, use a small OpenAI text model for the decisions.

## Cut list

Build for real:

- Bridge call with per-speaker transcript
- Judge asking pending questions and reading back the terms
- Contract sent on WhatsApp
- Record intake with backed / unbacked, confirm on WhatsApp, call if no reply

Simplify:

- Independent call-backs - do it for one party in the demo
- Disagreement flow - show the clip replay only, as the highlight

Skip:

- Judge in disputes, voice forensics, Khatabook

## Not verified

- Whether a Twilio trial signed up in India can call Indian mobiles, and the per-minute rate.
- Whether the Twilio WhatsApp sandbox works on a trial account.
- Twilio's exact trial allowance (sources say 75 voice minutes or about $15 of credit).
- How exactly the realtime voice model joins a Twilio conference as a participant, and whether a trial account allows it.
- Whether Sage2 handles Hindi or Hinglish text, its free-plan rate limits, and whether signup needs a card.
- Sage2's speed figures are the vendor's own.
- That Amazon Transcribe and Amazon Polly support Hindi - from memory, not checked today.
- Current WhatsApp message pricing - sources conflict after 1 October 2026. Irrelevant at demo volume.
- OpenAI model names are from OpenAI's models page via search; confirm in the dashboard.

## Ruled out

- Amazon Connect: India is listed as outbound-only through a partner beta. Not a 2-day option.
- Exotel: KYC is mandatory and audio streaming needs support to switch it on.
- WhatsApp's own calling API: exists and has an India rate card, but needs a full business setup.

## References

- [Twilio: free trial account](https://www.twilio.com/docs/usage/tutorials/how-to-use-your-free-trial-account)
- [Twilio: error 21608, unverified numbers](https://www.twilio.com/docs/api/errors/21608)
- [OpenAI: models](https://developers.openai.com/api/docs/models)
- [OpenAI: gpt-transcribe](https://developers.openai.com/api/docs/models/gpt-transcribe)
- [OpenAI: realtime transcription guide](https://developers.openai.com/api/docs/guides/realtime-transcription)
- [OpenAI: new voice models announcement](https://openai.com/index/advancing-voice-intelligence-with-new-models-in-the-api/)
- [Forasoft: OpenAI realtime pricing, Nov 2026](https://www.forasoft.com/blog/article/openai-realtime-api-pricing)
- [OpenAI: realtime conversations guide](https://developers.openai.com/api/docs/guides/realtime-conversations)
- [Microsoft: realtime audio, switching off automatic replies](https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/realtime-audio)
- [Levanto: Sage2 model page](https://levanto.ai/model)
- [Levanto: pricing](https://levanto.ai/pricing)
- [Levanto: streaming docs](https://docs.levanto.ai/stream)
- [Meta: WhatsApp calling pricing](https://developers.facebook.com/documentation/business-messaging/whatsapp/calling/pricing)
- [RichAutomate: WhatsApp Cloud API test number limits](https://richautomate.in/blog/whatsapp-cloud-api-test-number-sandbox-india-2026)
- [AWS: Amazon Connect telecoms coverage](https://d1v2gagwb6hfe1.cloudfront.net/Amazon_Connect_Telecoms_Coverage.pdf)
- [LiveKit: pricing](https://livekit.com/pricing)
- [Anchor Terminal: Plivo Voice review](https://www.anchorterminal.com/tools/plivo-voice)
- [TalkEasy: Exotel alternatives in India](https://talk.groweasy.ai/feed/best/exotel-alternatives-india)
