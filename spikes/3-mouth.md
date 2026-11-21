# Spike 3: the realtime voice model as Gawah's mouth

```
3. mouth: YES (machine-checked; a person has not yet listened to it on a call)
What I ran: The agent from spike 1 held one websocket to OpenAI's realtime voice model with automatic replies off, sent it one English instruction per trigger, and published the audio into the LiveKit room. A listen-only bot recorded the room and timed everything. 27 triggers across gpt-realtime-2.1 and gpt-realtime-2.1-mini, 5 of them talked over by a fake person.
What happened: Silent for 65 s with two people talking and the model hearing one of them: zero replies, zero sound. On a trigger, gpt-realtime-2.1 was heard in the room after 1.1-1.9 s (median 1.3 s, 9 runs) and asked the short question in Hindi and nothing else, 13 times out of 13. Talked over, Gawah went silent in the room 139-158 ms after the person's first sound, 5 times out of 5.
Catch: gpt-realtime-2.1-mini is about 0.2 s quicker but added words in 4 of 9 questions, once suggesting a term ("today or tomorrow?"), and once read the terms back in English. Speech detection is a plain loudness threshold tested only against a digitally silent fake microphone; real room noise and Gawah's own voice coming back through a loudspeaker are untested. Naturalness is judged from transcripts only.
Decision: Use gpt-realtime-2.1, not the mini. Keep the fallback (speech from text) unbuilt. Run the human check for echo and for how it sounds.
```

Numbers are from `./py.sh autotest.py phase1 | phase2 | phase2b | phase3` on 21 Nov, saved in `1-call/results/`. Samples to listen to are in `1-call/samples/`.

## Measurements

### Silent until triggered

Run: two fake people talking for 65 s (11 turns), Gawah's agent in the room with its audio track published and its model connection open (`phase1`).

| Check | Result |
|---|---|
| Replies the model started by itself | 0 |
| Events from the model in those 65 s | 1 (`session.updated`, the reply to our own setup message) |
| Loudest frame on Gawah's track, as recorded by the third bot | -90.3 dB (digital silence), 6,658 frames |
| Frames louder than -80 dB | 0 |
| Gawah's track as each browser page saw it | about 300 packets in 64 s, audio energy 0.00 |

- This was the hard version of the test: Sunita's audio was streamed into the model (`input_audio_buffer.append`) the whole time, with turn detection set to null. It still said nothing.
- In the build we do not send the model any audio at all, which leaves it nothing to reply to.
- Across every other run (27 triggers, about 8 minutes of open connections) the model never started a reply we had not asked for, and never sent audio after `response.done`.
- A published track with nothing to say is not free of traffic: LiveKit sends about 5 small packets a second of silence.

### Trigger to first sound

"From OpenAI" is the first audio chunk arriving at the agent. "Heard in the room" is the first frame louder than -50 dB arriving at the listen-only bot. Both are measured from the moment the trigger was sent.

| Model | Runs | From OpenAI, median (range) | Heard in the room, median (range) |
|---|---|---|---|
| gpt-realtime-2.1 | 9 | 1,146 ms (966-1,688) | 1,333 ms (1,095-1,891) |
| gpt-realtime-2.1, reasoning effort `minimal` | 3 | 899 ms (788-947) | 1,171 ms (1,023-1,186) |
| gpt-realtime-2.1-mini | 9 | 975 ms (695-1,145) | 1,255 ms (967-1,781) |

- `response.created` comes back 260-360 ms after the trigger. The rest of the wait is the model.
- From the agent publishing a frame to the room hearing it: 90-270 ms for gpt-realtime-2.1.
- Opening the websocket takes 0.9-1.3 s, so hold it open for the whole call. Do not connect on a trigger.
- The model sends audio far faster than it is spoken, in 400 ms chunks: 9 s of speech arrived in 0.9 s.
- In 4 of 8 timed runs the second chunk arrived more than 400 ms after the first, so playback ran dry for 130-275 ms right after the first 400 ms of speech (3 of 4 runs on gpt-realtime-2.1, 1 of 4 on the mini). It usually lands on the pause after the name. Not fixed in the spike; see "For the mouth stream".
- In 3 of the mini's 9 runs the room heard the first sound 500-800 ms after the agent published it. I did not find the cause.

### Does it say what the instruction said, and nothing more?

The third bot recorded Gawah's track from the room. `gpt-transcribe` of those recordings agreed with what the model reported saying in all 13 cases checked, apart from single-word slips (`results/phase2.json`). In 2 of the 13 the first syllable came back wrong ("मेश" and "तमेश" for "Ramesh"), which may mean the very start of the speech is clipped on its way into the room. `samples/gawah-2.1-mini-2.wav` is one of the two; listen to it.

gpt-realtime-2.1:

| Instruction | Said |
|---|---|
| Ask Sunita when the balance will be paid. | Sunita, balance kab diya jayega? |
| Ask Ramesh on which date the work will be finished. | Ramesh, kaam kis date tak khatam ho jayega? |
| Two different totals were said, 22 thousand and 25 thousand. Ask both of them which one is final. | आप दोनों अलग-अलग टोटल बता रहे हैं, 22 हजार और 25 हजार। कृपया बताइए इनमें से कौन सा final है? |
| Ask Sunita how much advance she will give. | Sunita, aap kitna advance dengi? |
| Ask Ramesh what happens if the work is not finished on time. | Ramesh, agar kaam time par poora nahi hota, toh uss halat mein kya hota hai? |

- 13 of 13 short questions on gpt-realtime-2.1 asked only what the instruction said. All 3 long read-backs were in Hindi and in order, as far as they got before being cut off.
- The wording changes from run to run ("balance kab diya jayega", "balance kab tak pay ho jaega", "balance कब तक पेमेंट होगा"). The last one is clumsy.
- The model writes its own transcript in Roman or Devanagari at random. Do not show that text to users as is.

gpt-realtime-2.1-mini, same instructions:

| Instruction | Said | Problem |
|---|---|---|
| Ask Sunita when the balance will be paid. | सुनिता, कब तक आपका बैलेंस पे किया जाएगा? क्या आप बता सकते हैं कि आज या फिर कल तक ये चुकता हो जाएगा? | Second question, and it suggests a term |
| Ask Ramesh on which date the work will be finished. | Ramesh, kaun si date tak kaam khatam hoga, batao? Theek hai, batao. | Extra words, curt |
| Ask Sunita how much advance she will give. | मैं आपसे पूछ रहा हूँ, Sunita, आप कितना advance देंगी? | Extra words |
| Ask Ramesh what happens if the work is not finished on time. | रमेश, अगर काम समय पर पूरा नहीं होता, तो क्या होगा? क्या कोई प्रक्रिया या कदम होगा? | Second question |
| Read back all of these agreed terms... | Main dheere dheere sab tay kiye hue terms ek-ek karke aapko sunata hoon: painting of a two BHK flat in Indirapuram including the balcony grill; ... | Read the terms in English |

- 4 of 9 short questions had extra words; 1 of 2 read-backs was in English. The Judge must never suggest a term, so the mini is out.

### Barge-in

Run: Sunita's fake microphone loops 7 s of speech and 9 s of silence; Ramesh's is silent. Gawah is triggered just after Sunita stops, with a long read-back, so her next line lands on top of it (`phase3`). Times are from the listen-only bot's recording of the room.

| Trial | Model | Person's first sound to agent noticing | Person's first sound to Gawah silent in the room |
|---|---|---|---|
| 1 | gpt-realtime-2.1 | 41 ms | 139 ms |
| 2 | gpt-realtime-2.1 | 60 ms | 158 ms |
| 3 | gpt-realtime-2.1 | 60 ms | 151 ms |
| 4 | gpt-realtime-2.1-mini | 59 ms | 158 ms |
| 5 | gpt-realtime-2.1-mini | 41 ms | 150 ms |

- Stopped 5 of 5. From the agent noticing to silence in the room: 90-110 ms.
- How speech is detected: loudness of each 20 ms frame on the person's own track. Three frames in a row above -40 dB means speech started; 600 ms below means it ended. No model, no extra package.
- Control: a short question triggered in the gap, with both microphones quiet, played to the end untouched. Ramesh's silent microphone never triggered a stop in 98 s.
- Does Gawah hear itself? Not through the room: the agent never subscribes to its own track. The only way is Gawah's voice leaving a person's loudspeaker and entering their microphone. The fake microphones cannot show that. It is item 7 of the human check.
- By the time a person talks over it, the model has already sent the whole speech (24-28 s of audio generated, 6-8 s played). What stops the sound is dropping our own buffer and calling `clear_queue()` on the LiveKit source. `response.cancel` only matters if the model is still generating: gpt-realtime-2.1 reported `cancelled` three times, the mini had already finished both times.
- So a cut-off speech is paid for in full.

### Usage

- OpenAI realtime: 29 replies requested (27 in the measured runs, 1 protocol check without a room, 1 while testing the human-check command), about 4 minutes of generated speech in total (239 s), over about 8 minutes of open connections. From the token counts (20 audio tokens per second of speech, about 150 text tokens of instructions per trigger) I estimate under $0.50. Not checked on the dashboard; the mini's prices were not on the page I read.
- `gpt-transcribe`: 15 calls (13 here, 2 in spike 1).
- LiveKit: see spike 1. The mouth runs used 13 of the 22.5 participant-minutes.

## For the mouth stream

### Packages

- `websockets` (already in the project, 17.4) for the OpenAI connection. No OpenAI SDK needed.
- `livekit` 1.3.0 for `rtc.AudioSource`, `rtc.LocalAudioTrack`, `rtc.AudioFrame`.

### The calling pattern that worked

All of it is `1-call/mouth.py` (190 lines). `1-call/smoke_mouth.py` is the same protocol with no LiveKit room, for a quick check of the key and the event names.

Connect once per call, and switch automatic replies off:

```python
ws = await websockets.connect(
    "wss://api.openai.com/v1/realtime?model=gpt-realtime-2.1",
    additional_headers={"Authorization": f"Bearer {key}"}, max_size=None)
# first message from the server is session.created; no OpenAI-Beta header is needed
await ws.send(json.dumps({"type": "session.update", "session": {
    "type": "realtime",
    "output_modalities": ["audio"],
    "instructions": PERSONA,
    "audio": {
        "input":  {"format": {"type": "audio/pcm", "rate": 24000}, "turn_detection": None},
        "output": {"format": {"type": "audio/pcm", "rate": 24000}, "voice": "marin"}}}}))
```

- The default session has `turn_detection: server_vad` with `create_response: true`. `"turn_detection": None` (JSON null) turns it off; `session.updated` echoes it back as null.
- Never send `input_audio_buffer.append`. The mouth does not need to hear.

One spoken reply from one text instruction:

```python
await ws.send(json.dumps({"type": "response.create", "response": {
    "conversation": "none",          # out of band: nothing is added to a conversation
    "input": [],                     # no context: each reply stands alone
    "output_modalities": ["audio"],
    "instructions": f"{PERSONA}\n\nThe instruction: {instruction}"}}))
```

- Per-reply `instructions` replace the session's, so the persona goes in every time.
- Events, in order: `response.created` (keep `response.id`), `response.output_audio.delta` (base64 PCM, 16-bit, 24 kHz mono, in `delta`), `response.output_audio_transcript.done` (the text it said, in `transcript`), `response.done` (`response.status` is `completed` or `cancelled`, and `response.usage` has the token counts). The older `response.audio.delta` names never appeared.

Into the room:

```python
source = rtc.AudioSource(24000, 1, queue_size_ms=200)   # takes 24 kHz as is, no resampling by us
track = rtc.LocalAudioTrack.create_audio_track("gawah-voice", source)
await room.local_participant.publish_track(track, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE))

# one task: cut the received bytes into 20 ms frames and feed the source
await source.capture_frame(rtc.AudioFrame(chunk, 24000, 1, 480))   # blocks when 200 ms is queued, which paces it
await source.wait_for_playout()                                    # after the last frame: speaking is over
```

Stop mid-speech:

```python
buffer.clear()                       # our not-yet-played audio
source.clear_queue()                 # the 200 ms inside LiveKit
await ws.send(json.dumps({"type": "response.cancel", "response_id": response_id}))   # only if response.done has not come
# then ignore any later response.output_audio.delta carrying that response_id
```

### Settings

- Model `gpt-realtime-2.1`, voice `marin`. I did not try other voices.
- `"reasoning": {"effort": "minimal"}` in `session.update` was accepted and was about 250 ms quicker to first audio in 3 runs, with the same wording quality. Three runs is thin; worth a second look if 1.3 s feels slow.
- The persona that held the model to the instruction is `PERSONA` in `mouth.py`: who Gawah is, "say only that, in natural, polite, spoken Hindi", one or two short sentences, no greeting, no additions, no suggesting a term, no second question, then stop. A long read-back still worked when the instruction itself asked for one.
- Barge-in thresholds are `SPEECH_DB`, `START_FRAMES` and `END_FRAMES` at the top of `agent.py`.

### What the stream still has to decide

- Playback running dry after the first chunk (130-275 ms, half the runs). Waiting for the second chunk before starting would remove it and add up to about 0.5 s to the delay. Untested. Listen to `samples/` first; it may not be audible.
- Barge-in on a loudness threshold will fire on a cough, a "haan", or a door. Whether Gawah should stop for those, and whether it should resume, is a product call. A stopped reply cannot be resumed from where it was cut; the played length is known (`played_ms`), the text position is not.
- Echo. If the human check shows Gawah cutting itself off when a laptop is on loudspeaker, the simplest guard is to ignore speech from a person for the first few hundred milliseconds of Gawah's own speech, or to raise the threshold while Gawah is speaking. Neither is built.
- A trigger while Gawah is already speaking raises an error in the spike. The stream needs a rule: queue, drop, or replace.
- One websocket lasts 60 minutes at most (OpenAI's limit, from the docs, not tested). Reconnect on close.

### What went wrong on the way

- Nothing on the OpenAI side. The protocol above worked on the first run.
- The measurement rig, not the mouth: see "What went wrong on the way" in `1-call.md`.

## Not verified

- How it sounds to a person. I cannot listen. `samples/gawah-2.1-1.wav`, `gawah-2.1-2.wav`, `gawah-2.1-mini-1.wav`, `gawah-2.1-mini-2.wav` are the room recordings of the first two questions on each model; `gawah-2.1-cut-off-by-barge-in.wav` is a read-back being cut off.
- Echo and real background noise (human check, items 6 and 7).
- Other voices, speaking speed, and a female or male voice choice.
- Names other than Sunita and Ramesh, and amounts other than round thousands.
- Long calls: the longest connection was about 2 minutes.
- The fallback (speech from text). Not built, because the answer is yes.
- OpenAI's actual charge.
