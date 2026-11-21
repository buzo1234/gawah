# Spike 2: OpenAI transcription on real Hinglish speech

```
2. ears: PARTLY
What I ran: 24 recorded Hinglish lines (135 s, laptop mic) through gpt-transcribe, gpt-4o-transcribe, gpt-4o-mini-transcribe and whisper-1 as file uploads, twice each, with no hint, Hindi, Hindi+English, and a short prompt; then fed at real speed over the realtime socket to gpt-live-transcribe, gpt-realtime-whisper and gpt-transcribe; then Amazon Transcribe streaming on five lines.
What happened: gpt-transcribe with a prompt got 36-40 of 42 amounts, dates, names and brands right, all three short replies right in every run, Devanagari every time, and final text about 0.8-0.9 s after the audio ends. The contract values gpt-5.4-mini pulled from its transcript matched the reference exactly. Without a prompt it got 30-34 of 42. The live-only models were worse: gpt-live-transcribe 28-35 of 42, gpt-realtime-whisper 26 of 42 with Korean, Japanese and Urdu fragments.
Catch: "seventeen thousand" came back as "seventy thousand" in 42 of 43 OpenAI runs and never came back right; Amazon heard it correctly both times. "bees mein" (in twenty) came back as "please" in every gpt-transcribe run. The meaning of the whole line survived on only 19-21 of 24 lines. Server-side turn detection added a "हाँ।" (yes) or "हिंदी।" that nobody said to 5 of 24 lines, and to 3 of 24 with a longer silence setting.
Decision: Use gpt-transcribe with a prompt and Hindi+English hints. Do not switch to Amazon Transcribe. Never trust an amount that was said once: the brain must check it against the other figures and the read-back.
```

## Results

- 42 facts were fixed in `2-ears.py` before the first run: every amount, date, name and brand in the 24 lines.
- "Facts right", "Short replies right", "Meaning kept" and "Invented" were judged by `gpt-5.4-mini`, one call per run. I read all 24 lines of one run and every flagged line of five runs. I disagreed with 2 of about 30 judgments, so read the fact counts as plus or minus 2.
- Two figures in a cell are run 1 and run 2 of the same setting.
- "Invented" counts lines where the judge found words that were not said. Nearly all are mishearings (a wrong word in place of a real one), not free-standing made-up sentences. The real inventions are listed under "What went wrong".
- Delay for file uploads is the time for the HTTP call. Delay for the socket is from the end of the audio (the commit) to the final text.

### File upload (`POST /v1/audio/transcriptions`), 16 kHz wav, 2 runs

| Model | Setting | Script, run 1 (of 24 lines) | Lines that changed script between runs | Facts right (of 42) | Short replies right (of 3) | Meaning kept (of 24) | Lines with invented words | Delay, median / max |
|---|---|---|---|---|---|---|---|---|
| gpt-transcribe | none | Devanagari 21, mixed 1, Urdu 1, Korean 1 | 0 | 30 / 31 | 1 / 1 | 14 / 15 | 12 / 9 | 0.84 / 1.59 s |
| gpt-transcribe | Hindi | Devanagari 24 | 0 | 34 / 31 | 2 / 2 | 17 / 16 | 7 / 8 | 0.83 / 2.08 s |
| gpt-transcribe | Hindi + English | Devanagari 24 | 0 | 33 / 31 | 3 / 2 | 16 / 15 | 8 / 9 | 0.83 / 1.35 s |
| gpt-transcribe | Hindi + English + keywords | Devanagari 22, mixed 2 | 0 | 35 / 36 | 3 / 3 | 19 / 19 | 5 / 6 | 0.84 / 1.47 s |
| gpt-transcribe | Hindi + English + prompt | Devanagari 23, mixed 1 | 0 | 38 / 38 | 3 / 3 | 19 / 20 | 0 / 4 | 0.83 / 1.17 s |
| gpt-transcribe | prompt | Devanagari 23, mixed 1 | 0 | 40 / 38 | 3 / 3 | 21 / 20 | 3 / 4 | 0.82 / 1.33 s |
| gpt-4o-transcribe | none | Devanagari 9, Urdu 13, Roman 1, mixed 1 | 3 | 19 / 19 | 1 / 1 | 7 / 8 | 9 / 8 | 0.98 / 1.71 s |
| gpt-4o-transcribe | Hindi | Devanagari 9, Urdu 13, Roman 1, Chinese 1 | 3 | 21 / 19 | 2 / 2 | 11 / 10 | 9 / 0 | 0.92 / 11.02 s |
| gpt-4o-transcribe | prompt | Devanagari 22, Roman 2 | 5 | 34 / 32 | 2 / 2 | 15 / 13 | 5 / 0 | 0.83 / 11.24 s |
| gpt-4o-mini-transcribe | none | Urdu 19, Devanagari 3, Cyrillic 1, Korean 1 | 1 | 32 / 31 | 1 / 1 | 17 / 16 | 5 / 14 | 0.84 / 1.68 s |
| gpt-4o-mini-transcribe | Hindi | Urdu 19, Devanagari 3, Cyrillic 1, Korean 1 | 1 | 30 / 33 | 1 / 1 | 13 / 17 | 10 / 8 | 0.85 / 1.75 s |
| gpt-4o-mini-transcribe | prompt | Devanagari 14, Urdu 7, Roman 3 | 5 | 37 / 33 | 1 / 1 | 17 / 17 | 7 / 8 | 0.84 / 1.50 s |
| whisper-1 | none | Devanagari 18, mixed 2, Urdu 2, Roman 1, Cyrillic 1 | 1 | 32 / 31 | 1 / 1 | 17 / 16 | 6 / 1 | 2.08 / 10.06 s |
| whisper-1 | Hindi | Devanagari 23, mixed 1 | 0 | 30 / 31 | 2 / 2 | 17 / 18 | 8 / 0 | 2.10 / 9.37 s |
| whisper-1 | prompt | Devanagari 9, Roman 7, Urdu 6, mixed 1, empty 1 | 2 | 23 / 27 | 1 / 1 | 14 / 13 | 6 / 10 | 2.10 / 7.96 s |

- The delays above were measured with 6 calls running at once. One at a time, gpt-transcribe with the prompt took 0.90 s median, 1.35 s max, for lines of 2-9 s.
- The same two prompt settings on the browser's original Opus files instead of the 16 kHz copies: 38 / 36 (prompt) and 34 / 36 (Hindi + English + prompt). No gain from the better audio.
- "Mixed" means Devanagari with a Latin acronym or English word left in Latin, such as "BHK", "UPI" or "Asian Paints".

### Realtime socket, fed at real speed, 1 run

One socket per speaker, that speaker's lines in order, 24 kHz PCM decoded from the browser's Opus recording.

| Model | Setting | End of line decided by | Script (of 24 lines) | Facts right (of 42) | Short replies right (of 3) | Meaning kept (of 24) | Lines with invented words | Final text after the audio ends, median / max |
|---|---|---|---|---|---|---|---|---|
| gpt-transcribe | Hindi + English | the script (commit) | Devanagari 24 | 31 | 3 | 17 | 8 | 0.82 / 1.31 s |
| gpt-transcribe | prompt | the script (commit) | Devanagari 23, mixed 1 | 36 | 3 | 20 | 4 | 0.80 / 1.13 s |
| gpt-transcribe | Hindi + English + prompt | the script (commit) | Devanagari 23, mixed 1 | 37 | 3 | 19 | 5 | 0.83 / 1.01 s |
| gpt-transcribe | Hindi + English + prompt | OpenAI (`server_vad`, defaults) | Devanagari 24 | 32 | 3 | 20 | 7 | 1.05 / 1.68 s |
| gpt-transcribe | Hindi + English + prompt | OpenAI (`server_vad`, 700 ms silence) | Devanagari 23, mixed 1 | 34 | 3 | 19 | 6 | 1.55 / 1.78 s |
| gpt-live-transcribe | Hindi + English | the script (commit) | Devanagari 19, mixed 5 | 28 | 2 | 15 | 10 | 0.78 / 0.96 s |
| gpt-live-transcribe | Hindi + English, `delay: xhigh` | the script (commit) | Devanagari 20, mixed 4 | 28 | 3 | 16 | 8 | 0.79 / 0.96 s |
| gpt-live-transcribe | Hindi + English + prompt | the script (commit) | Devanagari 18, mixed 6 | 35 | 3 | 17 | 6 | 0.80 / 1.00 s |
| gpt-realtime-whisper | none | the script (commit) | Devanagari 12, Urdu 5, mixed 3, Korean 2, Bengali 1, Japanese 1 | 26 | 3 | 12 | 12 | 0.75 / 0.87 s |

- The recordings have almost no silence at the end (0.08 s median, by a simple loudness check), so "after the audio ends" is close to "after the person stops speaking" for the commit rows. In a live call you must add the time it takes to decide the person has stopped.
- With `server_vad` that decision is included. On defaults, OpenAI declared the end of speech 0.58 s (median) after the speech ended, and the final text arrived 1.13 s median, 1.76 s max, after the speech ended. With 700 ms of silence required: 1.10 s, then 1.64 s median, 1.88 s max.
- gpt-live-transcribe and gpt-realtime-whisper send partial text while the person is still speaking (first words about 2.3 s into a line). gpt-transcribe sends nothing until the line is committed.

### What went wrong

- "Seventeen thousand" (line 16) came back as "seventy thousand" in 42 of 43 OpenAI runs, across every model and setting. The other run dropped the amount. It was never right. Amazon Transcribe returned "सेवेंटीन थाउजेंड" (seventeen thousand) on both tries, so the recording is clear enough; this is an OpenAI mishearing.
- "Madam bees mein nahi ho payega" (line 10, "not possible in twenty") came back as "मैडम, प्लीज नहीं हो पाएगा" (madam, please, not possible) in all 12 gpt-transcribe file-upload runs. The twenty is lost. Amazon lost it too ("लीज है").
- The painter's four descriptive lines (4, 6, 7, 8) were garbled in most runs: "Tractor Emulsion hi lagao" became "टाइम का मैच नहीं रहेगा", "do coat aur putty ka touch-up" became "दो कमरों पुट्टी कट" (two rooms). The amount at the end of line 8 (25,000) survived in the gpt-transcribe runs.
- gpt-live-transcribe also changed an amount in the closing summary (line 24): "paanch advance" came back as "पांच सौ" (five hundred) in 2 of its 3 runs, and "total" as "hotel" in 2 of 3.
- Short replies: with a prompt, gpt-transcribe returned "हाँ, ठीक है।" 12 of 12 times, "पक्का।" for "Pakka." 12 of 12, and "पक्का।" for "Pakka?" 10 of 12 (the other two had an invented "हाँ।" next to it, both with `server_vad`). No drop-outs. The question mark on "Pakka?" was never kept. Without a hint, short replies came back in Urdu or Korean script ("아까") or as other words.
- Invented words, not mishearings: with `server_vad` on defaults, gpt-transcribe put "हाँ।" in front of lines 16, 20 and 22 and "हिंदी।" in front of lines 5 and 24. With 700 ms of silence it put "हिंदी।" in front of line 15, "हाँ।" in front of line 24, and "हाँ।" after line 22. None of the 72 lines in the three commit runs had this. gpt-realtime-whisper produced Korean, Japanese, Chinese, Spanish and Bengali fragments. The judge model missed most of these; I found them by reading.
- With `server_vad` defaults, 11 of 24 lines were cut into 2-4 pieces at reading pauses, each arriving as its own transcript. With 700 ms of silence, 3 of 24.
- Numbers come back in three forms, sometimes within one run: "बाईस हज़ार", "22,000", "ट्वेंटी थाउज़ेंड". The script class is stable; the number form is not.
- The prompt named the speakers and the two paint brands that are in the recording, so the brand and name scores with a prompt are flattering. Without the prompt, "Asian Paints ka Royale loge ya normal Tractor Emulsion" came back as "एजेंट्स का रॉयल ओपी और डॉल्फिन".

### Language hints

- `gpt-transcribe` takes `languages[]` with several values (`hi` and `en` together) and returns the detected languages. It also accepted the old single `language=hi` without an error.
- `gpt-4o-transcribe`, `gpt-4o-mini-transcribe` and `whisper-1` take one `language` only. `languages[]` is rejected ("not supported for this model") and `language=hi,en` is rejected.
- On the socket, `gpt-live-transcribe` takes `languages` as a list.
- Setting Hindi did not stop the two gpt-4o models writing Urdu script. Only the prompt moved them to Devanagari, and not on every line.

### End to end

`gpt-5.4-mini` was asked for the total, the advance, the start date and the balance schedule, on the reference text and on the transcript.

| Transcript | Total | Advance | Start date | Balance |
|---|---|---|---|---|
| Reference | 22,000 | 5,000 | 2026-11-23 | 7,000 midway and 10,000 after completion |
| gpt-transcribe, file upload, prompt (run 1) | 22,000 | 5,000 | 2026-11-23 | 7,000 halfway through and 10,000 on completion |
| gpt-transcribe, socket, Hindi + English + prompt | 22,000 | 5,000 | 2026-11-23 | 7,000 after half the work and 10,000 on completion |

- The transcription errors did not change the contract. The values that were misheard are restated later in the call.
- Asked mid-call, with the transcript stopping at line 16 where "seventeen thousand" reads "seventy thousand": `gpt-5.4-mini` still answered 17,000 for the balance on both transcripts. The question also asked for the total and the advance, which may have helped it. A value that is said once and cannot be worked out from other figures has no such protection.

### Amazon Transcribe, five lines

Streaming, 16 kHz, lines 6, 8, 10, 16 and 24, with `hi-IN` and again with Hindi and Indian English identified together. No custom vocabulary.

| Line | Said | Amazon (`hi-IN`) |
|---|---|---|
| 6 | Asian Paints ka Royale loge ya normal Tractor Emulsion? | पील्स का रॉयल या नॉर्मल डक्टर इमरजेंट। |
| 8 | Do coat aur putty ka touch-up, material ke saath pachees hazaar lagega | दो कोट और पत्ते काट के साथ ₹25,000 लग। |
| 10 | Madam bees mein nahi ho payega ... baees hazaar final kar lo | मदम लीज है नहीं हो पाएगा ... चलो ₹22,000 फाइनल कर लो। |
| 16 | balance seventeen thousand ... same day de dungi | और बैलेंस सेवेंटीन थाउजेंड का पूरा होने के बाद सेम के दे दूँगी |
| 24 | total baees hazaar, paanch advance, saat beech mein, aur das kaam ke baad | टोटल ₹22,000 5 एडवांस सा बीच में और 10 काम के बाद |

- By my own reading, 10 of the 15 facts on these lines survived. gpt-transcribe with the prompt got 13 and 11 of the same 15 (judge's count).
- Amazon got the one amount OpenAI never got (seventeen thousand) and lost one OpenAI kept ("saat", the 7,000 in the summary).
- Final text arrived 0.31-0.52 s after the audio ended, about half of OpenAI's delay.
- The two-language setting changed one line, for the worse.
- Five lines is too few to rank the two services. It is enough to say Amazon is not clearly better.

### Cost per minute of audio

List prices from OpenAI's pricing page today. I did not check the bill.

| Model | Price |
|---|---|
| gpt-transcribe | $0.0045 per minute |
| gpt-4o-mini-transcribe | about $0.003 per minute (billed by token) |
| gpt-4o-transcribe | about $0.006 per minute (billed by token) |
| whisper-1 | $0.006 per minute |
| gpt-live-transcribe | $0.017 per minute |
| gpt-realtime-whisper | $0.017 per minute |

- gpt-transcribe reports usage in whole seconds, rounded up per request (a 7.02 s file was reported as 8 s). Short lines cost a little more than the per-minute price suggests.
- A 10-minute call with two people is at most 20 minutes of audio: about $0.09 with gpt-transcribe.
- OpenAI's speech-to-text guide says the gpt-4o transcription models and whisper-1 are deprecated and shut down on 26 February 2027.

## For the bridge stream

Use this:

- Model: `gpt-transcribe`.
- Hints: `languages` = `hi` and `en`, plus a `prompt`. The prompt is what moves accuracy (30-34 facts without, 36-40 with). The languages pin the script to Devanagari.
- Prompt, with the real names from the deal filled in: "Phone call in Hinglish (Hindi and English mixed) between Sunita, a homeowner, and Ramesh, a painter, agreeing a house painting job. Expect rupee amounts (hazaar, thousand), dates and weekdays, and paint brand names such as Asian Paints Royale and Tractor Emulsion." Swap the last clause for the words the trade in this deal uses. The exact text is `PROMPT` in `2-ears.py`.
- One transcription stream per person. Do not mix the two tracks.

Calling pattern, the one I recommend:

- Run your own voice detection on each person's track and cut a line when they have been silent for about 0.6 s.
- Send that line as one 16 kHz mono wav to `POST https://api.openai.com/v1/audio/transcriptions` with form fields `model=gpt-transcribe`, `languages[]=hi`, `languages[]=en`, `prompt=...`. The reply is `{"text": ..., "languages": [...]}`.
- Expect the text 0.9 s after the upload starts (1.35 s worst of 24). So a line reaches the bus about 1.5 s after the person stops speaking.
- This had the best scores of anything tested and needs no open connection.

The same thing over a socket, if you want one connection per person:

- Connect to `wss://api.openai.com/v1/realtime?intent=transcription` with the `Authorization: Bearer` header and no model in the address.
- Send `{"type": "session.update", "session": {"type": "transcription", "audio": {"input": {"format": {"type": "audio/pcm", "rate": 24000}, "transcription": {"model": "gpt-transcribe", "languages": ["hi", "en"], "prompt": "..."}, "turn_detection": null}}}}`.
- Send audio as `input_audio_buffer.append` with base64 24 kHz mono PCM16. I sent 100 ms chunks.
- When your voice detection says the line is over, send `input_audio_buffer.commit`. The text arrives as `conversation.item.input_audio_transcription.completed` with `item_id` and `transcript`, 0.8 s later (1.3 s worst). Match on `item_id`.
- Scores were the same as the file upload within the run-to-run spread.

What to expect to go wrong:

- A single amount can be wrong and look confident: "seventeen thousand" became "seventy thousand" every time. English "-teen" numbers are the known case; assume there are others. The brain should check the balance against total minus advance, and the read-back at the end of the call is the real safety net.
- A number said in passing can vanish: "bees mein" became "please".
- Text is Devanagari with English words spelled in Devanagari ("ट्वेंटी थाउज़ेंड", "एडवांस", "सेम डे"). Amounts arrive as Hindi words, as English words in Devanagari, or as digits. The value extractor has to take all three.
- A question and a statement look the same: "Pakka?" arrives as "पक्का।". Use who said it, not the punctuation.
- Trade words and brand names not named in the prompt will be garbled. Do not rely on the transcript for the paint brand.
- Do not turn on `server_vad` as it stands. `gpt-transcribe` accepts it (`gpt-live-transcribe` refuses it), and it saves you the voice detection, but on its defaults it added a "हाँ।" that nobody said to 3 of 24 lines and cut 11 lines into pieces. An invented "yes" is the worst error this product can make. Raising the silence setting to 700 ms cut the split lines from 11 to 3, but 3 lines still had an invented "हाँ।" or "हिंदी।", and the text arrived 0.5 s later.
- If you use your own voice detection, drop pieces shorter than about 0.3 s before sending them. I did not test this; the invented words above look like what the model writes for a scrap of noise.
- Do not use `gpt-live-transcribe` or `gpt-realtime-whisper`. They cost four times as much, were less accurate, and were no faster to the final text. Their one advantage is partial text while the person is speaking, which Gawah does not need.
- Do not leave the language unset. Lines came back in Urdu and Korean script.
- Results vary from run to run on the same audio by 2-3 facts. Do not write a test that expects exact transcript text.

## Not verified

- A real call. This is one person reading both parts into a laptop mic in a quiet room, one line per file, with no overlap, no phone-browser audio, and no network loss. Real calls will score lower.
- Other voices. Both speakers are the same reader.
- Sage2 on this output. The transcripts are in `2-results/`; spike 5 used clean hand-written text.
- Any voice detection of our own. The commit runs used the end of each file as the end of the line.
- `server_vad` on continuous room noise. My feeder sent digital silence between lines, which may have caused or hidden the invented prefixes.
- The price of `gpt-transcribe` over the realtime socket. The usage came back in seconds, like the file upload; the pricing page lists one price.
- The actual OpenAI and AWS spend. By list price the spike used well under $1 of OpenAI credits.
- Roman-script output. I did not try prompting for it, because Sage2 and `gpt-5.4-mini` both read Devanagari.
- Amazon Transcribe with a custom vocabulary, and on all 24 lines.
- Each socket setting was run once, so its score has the same 2-3 fact spread as the file uploads and no second run to show it.

## Usage

- OpenAI transcription uploads: 863 (22 in two probe runs, 10 of which were rejected on purpose; 720 main; 97 on the Opus files, including one retry; 24 one at a time).
- OpenAI realtime socket: 216 lines in 9 runs of 24 (about 23 minutes of audio), plus 4 connections that only tested a setting.
- OpenAI chat (`gpt-5.4-mini`): 51 (43 judging, 8 contract values). One model-list call.
- AWS: 10 Transcribe streaming sessions of 2-9 s each, 1 identity check. The keys were still valid at 17:18 on 21 Nov.
- No LiveKit, Twilio or Sage2.

## Files

- `2-ears.py` - the script, the facts, the prompt, the judge wording.
- `2-results/batch.json` - every file-upload transcript, with delay and script.
- `2-results/batch-webm.json` - the same for the Opus originals, two settings.
- `2-results/stream.json` - every socket transcript, with the timing of the first partial text, the commit and the final text.
- `2-results/aws.json` - the Amazon transcripts.
- `2-results/judge.json` - the judge's verdict per line per run.
- `2-results/e2e.json` - the contract values and the transcripts they were pulled from.
- `2-results/timing-gpt-transcribe-prompt.json` - the one-at-a-time delay run.
- `2-results/table.md` - the raw table printed by `2-ears.py report`.

The Amazon run needs `uv run --with amazon-transcribe spikes/2-ears.py aws hi`. Nothing was added to `pyproject.toml`.
