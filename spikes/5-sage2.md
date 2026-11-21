# Spike 5: Sage2 on a Hinglish call transcript

```
5. sage2: PARTLY
What I ran: 30-line painter call streamed line by line to wss://sage.levanto.ai/v1/stream with 10 yes/no questions, in Roman Hinglish, Devanagari and English, plus a 16-line held-out carpenter call; /v1/extract when an item turned yes.
What happened: Yes/no answers were right on 286/286 scored answers in Hinglish, 285/286 in Devanagari, 286/286 in English, and 147/150 on the held-out call. Each update took about 0.5-0.6 s wall clock from India (max 0.9 s). Extract found the right words but returned wrong values: "42 hazaar" came back as 42, not 42,000.
Catch: The first wording scored 278/286 with 16 extra flips; the three "how the call is going" questions needed rewording. Extract's typed values are not usable for Hinglish or Devanagari. Dollar cost not confirmed: the output-token price is not published and I could not see the dashboard.
Decision: Use Sage2's stream for the live yes/no decisions. Do not use Sage2 extract for values; get them from a small OpenAI model (gpt-5.4-mini got all five right in 2.2 s).
```

## Results

Scored answers leave out the lines I marked in advance as "either answer is fine" (a one-sided offer not yet accepted, and the total after the contradicting figure). Expected answers were fixed in `5-sage2.py` before the first run. A null answer (Sage2's near-tie) is scored as wrong.

| Transcript | Wording | Right | Extra flips | Nulls | Delay per update, wall clock (median / max) | Vendor `latency_ms` (median) |
|---|---|---|---|---|---|---|
| Hinglish (Roman) | v1 | 278/286 | 16 | 5 | 512 / 696 ms | 204 ms |
| Hinglish (Roman) | v2 | 286/286 | 2 | 1 | 570 / 784 ms | 270 ms |
| Devanagari | v2 | 285/286 | 3 | 0 | 616 / 842 ms | 296 ms |
| English | v2 | 286/286 | 1 | 0 | 573 / 889 ms | 267 ms |
| Held-out Hinglish call (16 lines) | v2 | 147/150 | 5 | 1 | 488 / 676 ms | 180 ms |

- Network round trip (WebSocket ping) was 250-300 ms of each delay. Sage2 is deployed in the US.
- Vendor `latency_ms` was 165-490 ms with 10 questions, above the 80-130 ms the vendor states.
- "Extra flips" are answer changes beyond the ones the call calls for.

### What went wrong, by run

- Hinglish v1: `topic_left_unclear` said yes on four lines that simply ended in a question nobody had answered yet (7, 11, 13, 17). `conflicting_figures` said yes on a counter-offer (line 15). `wrapping_up` went null on "theek hai" / "pakka" lines (16, 20, 22). All fixed by the v2 wording.
- All v2 runs: `amount_agreed` turns back to no after line 24, where Ramesh says 43 thousand after 42 was agreed. I had marked that as either-way. It accounts for the 1-2 extra flips.
- Devanagari v2: one false yes on `addressed_gawah` at line 25 ("हाँ ठीक है। और देखो, फर्नीचर…"). Nobody spoke to Gawah.
- Held-out call: `work_agreed` turned yes two lines early (at "Ban jayega didi", before the size was given). On line 13, where a conflicting total is said, `advance_agreed` went null and `balance_when` went no for one line, then both returned to yes.
- The four "how the call is going" questions fired on exactly the right line in every v2 run except the one Devanagari false yes.

### Extract

Called at the line where each item first turned yes, and once on the whole call. 20 calls. Delay 420-1840 ms wall clock; the median per run was 725-1120 ms.

| Field | Said | Hinglish | Devanagari | English |
|---|---|---|---|---|
| Total | 42 hazaar / 42 thousand | 42 (words: "42 hazaar") | 42 (words: "42 हज़ार") | 42000 |
| Advance | das hazaar / ten thousand | 10, probability 0.24-0.47 | 10, probability 0.19-0.49 | 10000 at the line; 10 on the whole call |
| Start date | 23 November | `--11-23` (no year) | parse error on "23 नवंबर" | `--11-23` (no year) |
| Finish date | 30 November | `--11-30` (no year) | parse error on "30 नवंबर" | `--11-30` (no year) |
| Duration | saat din / seven days | parse error on "Saat din" | parse error on "सात दिन" | parse error on "seven" |
| Work | scope of the job | null, then "2BHK andar se" | null, then "2BHK" | "bedrooms", then "2BHK inside" |

- Extract returns a span of the source text, not a summary. The span was the right one for amounts and dates in all three scripts.
- Currency was always null, though the preamble says amounts are in rupees.
- Adding "hazaar means thousand" and "saat din is 7 days" to the field definitions changed nothing.

OpenAI on the whole call, same values, one call each:

| Model | Script | Delay | Result |
|---|---|---|---|
| gpt-5.4-mini | Hinglish | 2188 ms | all five right (42000, 10000, 2026-11-23, 2026-11-30, 7) |
| gpt-5.4-nano | Hinglish | 3441 ms | total 43000 (took the later, contradicting figure); other four right |
| gpt-5.4-nano | Devanagari | 2359 ms | total 43000; other four right |

### Usage

- 145 stream updates, 20 extract calls, 3 OpenAI chat calls (plus one OpenAI model-list call).
- Sage2 tokens: 149,492 input and 110,113 output across stream and extract.
- Each stream update is billed about 940 question tokens plus the new line (20-35 tokens), and reports about 735 output tokens. The questions are re-billed on every update.
- Input price from `GET /models` is $0.05 per million tokens, so input cost about $0.0075. The output-token price is not published. If it is as high as the $1 per million listed for reasoning tokens, the spike cost about $0.11 in total. Check the dashboard for the real figure.

## For the brain stream

- Feed Sage2 whichever script the transcription gives. Roman Hinglish, Devanagari and English all worked for decisions. No need to transliterate or translate first.
- Start the session with a short preamble in `content`: who the two speakers are, that Gawah is an AI witness on the call, today's date. Append each line as `Name: text\n`.
- The stream sends one full decision right after `start` (with `seq: null`), before any line. With the default `emit: "changes"` it then sends only when an answer changes; I used `emit: "all"` to time every line. Every server frame is followed by a `sig` frame to ignore.
- Treat a null answer as no.
- Latch contract items: once an item is yes, keep it yes. `amount_agreed` drops to no when a conflicting figure is said, and other items can wobble for one line at that moment. `conflicting_figures` is the signal for that case.
- The REST base address is `https://sage.levanto.ai`. Paths are `/decide` (no `/v1`) and `/v1/extract`.

## Question wording that worked best (v2)

All `kind: "yesno"`. These are the `QUESTIONS` in `5-sage2.py`. The first seven are unchanged from v1; the last three are the v2 rewrites.

- `work_agreed`: Have both speakers agreed on what work is to be done (the scope of the job)? Answer yes only if one person has described the work and the other has accepted it.
- `amount_agreed`: Have both speakers agreed on the total price for the whole job? Answer yes only if one final total amount has been accepted by both. An offer or counter-offer that the other person has not accepted is not an agreement.
- `advance_agreed`: Have both speakers agreed on an advance payment amount (money paid before the work starts)? Answer yes only if both have accepted the same advance amount.
- `balance_when`: Have both speakers agreed on when the remaining balance (the total minus the advance) will be paid? Answer yes only if a specific time or condition for paying the balance was stated and accepted. If the question was asked but brushed aside or not answered, answer no.
- `dates_agreed`: Have both speakers agreed on both the start date and the finish date of the work?
- `late_terms`: Have the speakers agreed on what happens if the work is finished late or left unfinished, such as a penalty, a deduction or a refund? A promise to finish on time is not enough; answer yes only if a consequence was agreed.
- `addressed_gawah`: In the last line of the transcript, is the speaker talking directly to Gawah, the AI witness, for example by calling it by name?
- `topic_left_unclear`: Is there a contract term (price, advance, when the balance is paid, or dates) that one speaker asked about, where the other speaker has already replied without giving a clear answer and moved on to a different topic? A question in the last line that the other speaker has not yet had a chance to answer does not count. Answer yes only if that term is still unsettled.
- `conflicting_figures`: Has a figure that both speakers had already accepted (for example the total price or the advance) later been stated as a different number for that same term? Answer no for bargaining: an offer, a counter-offer, or a lower or higher number proposed before both speakers accepted is not a conflict.
- `wrapping_up`: Is the call ending right now? Answer yes only if, in the last two lines, a speaker says goodbye, says they are hanging up, or thanks the other person to close the conversation. Agreeing to a term (for example 'theek hai', 'pakka', 'done') or promising to finish the work on time is not ending the call.

What made the difference in v2: say that a question in the last line does not count as unanswered, say that bargaining is not a conflict, and name the Hindi agreement words that are not goodbyes.

## Not verified

- Real transcription output. The transcripts are hand-written, clean and punctuated. Real `gpt-transcribe` lines will have mishearings, no punctuation, and mixed scripts.
- The v2 wording was tuned on the painter call. The 16-line held-out call is the only independent check.
- `topic_left_unclear` names four terms. A dropped question about late or unfinished work is not in its list and was not tested.
- One run per configuration. The seven unchanged questions gave identical answers in the v1 and v2 Hinglish runs, but I did not repeat a run to test for variation.
- Calls longer than 30 lines. The session limit is 16,384 tokens; this call used about 750 for the transcript and 940 for the questions.
- A conflict that the speakers then resolve themselves. In both calls the conflicting figure was left standing.
- The OpenAI fallback for the yes/no questions. Sage2 was not wrong or borderline on Hinglish, so I did not run it. The `openai` command in the script is untested.
- Actual spend against the $1 monthly allowance.

## Files

- `5-sage2.py` - the script, the questions, the expected answers.
- `5-transcript-hinglish.txt`, `5-transcript-devanagari.txt`, `5-transcript-english.txt` - the same 30-line call, line for line.
- `5-transcript-holdout.txt` - the 16-line carpenter call.
- `5-results/` - every answer, probability and delay per line, and every extract result.
