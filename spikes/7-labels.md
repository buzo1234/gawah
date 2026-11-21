# Spike 7: generated labels and questions for each deal

```
7. labels: PARTLY (use it for the board's names only)
What I ran: three small models (gpt-5.6-luna effort none, gpt-5.4-mini effort low, gpt-6-luna effort none) read every fixture call (20 calls) line by line until the job was clear, then the whole call, then (gpt-6-luna) every 6 lines in between. They named the six terms for the job, at most three extras both people raised, a spoken question and a yes/no question per term. The generated names then went into the decision questions on spike 6's 18 calls and the six "agreed?" questions on spike 5's two labelled calls, scored against the static wording with the same OpenAI fallback model (luna). No Sage2.
What happened: gpt-6-luna's labels are right for the job on all 20 calls: "Meals and timings", "Monthly pay" (cook), "When the car is ready", "If the car is late" (mechanic), "If cooling fails again" (AC). They are short (4 of 120 over 24 characters) and have no values in them at the first read (lint). They are there by line 3 (median, range 1-7), 4.7 s after the line (p95 5.3 s). 15 extras on 12 calls: none names something nobody said; 13 were raised by both, 2 by one person only. The generated wording changes nothing in the decisions: 9/10 dodged-term moments either way, with 25 false fires against 16 and 23 for two runs of the static wording.
Catch: at the first read only the work label is job-specific (and the amount on about half the calls); the money and date labels say "Advance", "Balance", "Work dates" until those topics are talked about. Re-read later, labels change on almost every read (256 changes in 89 re-reads), so each must be frozen once set. Generated spoken questions drop "{who}" 12% of the time, and my second prompt made 99 of 109 late-term questions add "or not done right", a condition nobody raised.
Decision: Ship labels for the board only: gpt-6-luna, each label frozen once set, linted, falling back to the static name. Keep the Sage2 questions, the Judge's spoken questions and the agreement's headings as they are. Extras only as "Also discussed" rows on the board.
```

## The answer

**Use generated labels on the board; do not use generated wording anywhere the Judge decides or speaks.**

- **Board: yes.** It is the cheapest visible win. A cook's board reads "Meals and timings · Monthly pay · Advance · Monthly payment · Work dates · If work falls short", plus "Monthly days off" and "Household groceries" rows. Today it reads "Work · Amount · Advance · Balance · Dates · If late or unfinished". See `7-results/prototype/`.
  - On the demo call (a painter) the gain is small. Three of the six names change ("Coats and putty touch-up", "Total painting cost", "If painting is late"). So it makes the demo look more real mainly when a second trade is shown.
- **Model: gpt-6-luna at effort none.**
  - It has the fewest lint failures: 0 values and 4 long labels out of 120 at the first read, against gpt-5.6-luna's 6 values and 27 long labels.
  - It is the cheapest of the three: $0.10/$0.50 per million tokens, from third-party trackers, not OpenAI's page.
  - Its latency is about the same as gpt-5.6-luna's: median 4.7 s against 4.1 s, both p95 5.3 s.
  - gpt-5.4-mini (v1 prompt only) said the job was clear but left the labels empty on 5 of 20 calls.
- **Freeze each label.** The first read comes at the median line 3 and only knows the trade. Later reads know more but change labels on almost every read: "Painting work → Rooms and surfaces → Flat painting → Flat painting and putty → Rooms and surfaces" on one call. A label should be set at the first read and allowed one more change, when that term is first talked about. Then it stays.
- **Decision questions: no.** Putting the job's names into `topic_left_unclear` and `balance_skipped` did not catch more dodged terms (9/10 either way). False fires were at or above the top of the run-to-run spread of the static wording (25 against 16 and 23). The six "agreed?" questions with generated wording scored 254/255 against 255/255. No gain, and every Sage2 wording change means re-recording the practice calls.
- **Spoken questions: no, except perhaps the work question.** The generated asks never proposed a value or judged fairness (0 of 654). But:
  - 12% dropped the `{who}` slot the Judge fills.
  - The late-term asks widened the term to "not done right", because of my prompt. That is Gawah raising a condition nobody raised, which the Safety rule forbids.
  - Apart from the work question ("Ask the hirer what meals to cook and when to make them"), the generated asks are today's wording with the trade's name added.
- **Extras: board only.** None of the 15 named a point nobody had raised. But 2 were raised by one person only, and the line numbers the model cited are not reliable enough to check them by machine: 2 bad citations, one on a true extra. They are not fit to go into the agreement or the Judge's questions.

## Labels per call

gpt-6-luna, second prompt (v2). "First read" is the first line at which the job was clear and every label was filled in. "Whole call" is a read of the full call (the labels at the end of the call). "Changes" counts labels that differed from the read before, over the reads at the first line, every 6 lines after it, and the whole call. The verdict is mine, against the call's words.

| Call | Line ready / of | Reply (s) | First read | Whole call | Changes | Verdict |
|---|---|---|---|---|---|---|
| call_missing_balance (painter) | 2 / 32 | 4.4 | Painting work · Total amount · Advance · Balance · Painting dates · If painting is delayed | Flat painting and putty · Total price · Advance · Remaining payment · Start and finish · If the work is late | 12 in 5 | Right; only work is specific |
| call_two_amounts (painter) | 2 / 33 | 4.7 | Flat painting · Total price · Advance · Balance · Painting dates · If painting is late | Rooms and surfaces · **Labour amount** · Advance · Balance · Start and finish · If late or unfinished | 15 in 6 | Right; "Labour amount" catches labour-only |
| demo_script_call (painter) | 1 / 18 | 5.3 | Flat painting · Total price · Advance · Balance · Painting dates · If painting is delayed | Flat painting · Total painting cost · Advance · Balance · Painting dates · If painting is late | 7 in 3 | Right, near-static |
| dry_run_call (painter, raw STT) | 3 / 24 | 4.1 | Flat painting · Total painting cost · Advance · Balance · Painting dates · If painting is delayed | Rooms and coats · Total price · Advance · **Remaining payments** · Start and finish · If work is late | 17 in 4 | Right; plural for the staged balance |
| holdout_carpenter_call | 2 / 16 | 4.7 | Wardrobe size and design · Total price · Advance · Balance · Work dates · If work is delayed | Wardrobe design · Total wardrobe cost · Advance · Balance · Wardrobe work dates · If work is delayed | 9 in 3 | Right |
| second_call (painter, call 2) | 7 / 9 | 4.7 | Rooms to paint · Labour total · Advance · Balance · Painting dates · If painting is unfinished | Rooms to paint · Labour total · … · If painting is delayed | 1 in 1 | Right, but ready only 2 lines from the end |
| spike_painter_call | 2 / 30 | 4.6 | Flat painting · Painting price · Advance · Balance · Painting dates · If painting is delayed | Rooms and coats · Total painting price · Advance · Balance · Work dates · If work is late | 12 in 5 | Right |
| holdout2_ac_repair | 2 / 34 | 4.2 | AC service · Total service charge · Advance · Balance · Service dates · If service is unfinished | AC servicing and check · **Service and gas charges** · Advance · Payment after work · **Service timing** · **If cooling fails again** | 13 in 6 | Right and specific; "Payment after work" leans towards the answer |
| holdout2_car_mechanic | 4 / 33 | 4.8 | Clutch and brake repair · Total repair cost · Advance · Remaining payment · Repair dates · If repair is delayed | Clutch and brake work · Total repair cost · Advance · Remaining payment · **When the car is ready** · **If the car is late** | 11 in 5 | Right and specific |
| holdout2_driver_monthly | 3 / 32 | 5.2 | Driving duties · Driver pay · Advance · Remaining pay · Work dates · If work is missed | Driving duties · **Monthly salary** · Advance · **Salary payment** · Driving dates · If duties aren't met | 11 in 5 | Right |
| holdout2_mason_wall_call1 | 3 / 34 | 5.4 | Wall and gate pillars · Total cost · Advance · Remaining payment · Work dates · If work is unfinished | Wall and pillars · Total price · **Starting payment** · **Progress payments** · Work dates · If work is late or left | 21 in 6 | Right; the staged payments named well |
| holdout2_mason_wall_call2 | 7 / 31 | 5.3 | Wall construction · Total contract amount · Advance · Balance · Work dates · If work is unfinished | Wall construction · Wall and plaster cost · Advance · Remaining payment · Wall completion date · If the wall is late | 11 in 4 | Right |
| holdout2_tailor_lehenga | 3 / 34 | 4.2 | Blouse and suits · Total amount · Advance · Balance · Work dates · If work is delayed | Blouse and **four** suits · Total tailoring price · Advance · Balance · Work dates · If work is late | 22 in 6 | Right; the whole-call work label has a count (lint catches it) |
| holdout_carpenter_wardrobe | 4 / 32 | 4.5 | Wardrobe design · Wardrobe price · Advance · Balance · Wardrobe dates · If the wardrobe is late | Wardrobe and fittings · Total wardrobe cost · Advance · Balance · Wardrobe completion · If the wardrobe is late | 18 in 5 | Right |
| holdout_cook_month | 4 / 33 | 4.5 | Meals to cook · Cooking pay · Advance · Balance · Cooking dates · If cooking is unfinished | **Meals and timings** · **Monthly pay** · Advance · **Monthly payment** · Work dates · If work falls short | 18 in 5 | Right and specific |
| holdout_electrician_shop (raw STT) | 4 / 31 | 4.7 | Shop wiring · Total cost · Advance · Balance · Work dates · If work is delayed | Shop wiring · Total price · Advance · Rest of the price · Work dates · If work is late | 15 in 5 | Right |
| holdout_plumber_leak | 2 / 32 | 4.8 | Bathroom leak repair · Total charge · Advance · Balance · Repair dates · If repair is delayed | Bathroom pipe repair · Repair price · Advance · Balance · Work dates · If work is unfinished | 15 in 5 | Right |
| holdout_tutor_monthly | 4 / 30 | 4.5 | Maths and science tuition · Tuition fee · Advance · Balance · Tuition dates · Missed or unfinished tuition | Maths and science lessons · **Monthly fees** · **First-month advance** · Remaining fees · Tuition dates · **Missed or stopped lessons** | 16 in 5 | Right; two labels 25 characters (over the limit) |
| demo_call_1 (the demo) | 3 / 26 | 4.8 | Flat painting · Total amount · Advance · Balance · Painting dates · If painting is delayed | Coats and putty touch-up · Total painting cost · Advance · Balance · Painting dates · If painting is late | 7 in 4 | Right |
| demo_call_2 (the demo, call 2) | 6 / 12 | 4.6 | Walls to paint · Total painting cost · Advance · Remaining payment · Painting dates · If painting is unfinished | Painted areas · Total payment · Advance · Balance · Work dates · If work is unfinished | 5 in 1 | Right |

In sum, for gpt-6-luna v2:

- **No label on the wrong term, and none wrong for the job.**
- **At the first read, labels are job-specific mainly for work (20/20) and amount (about half).** Advance is "Advance" on 20/20 and balance is "Balance", "Remaining payment" or "Remaining pay" on 20/20. Those are today's names.
- **The whole-call read is where the board looks real, and also where labels start to carry answers.** "Payment after work" leans that way, and "Blouse and four suits" carries a count (the lint catches it).
- **First read versus whole call:** freezing the first read is safe but plain; the whole call is rich but too late for the board during the call. The shipping design below takes each term's label when that term is first talked about. That is untested; see "Not measured".

### The three models and both prompts

"Long" is over 24 characters. "Value" is the mechanical lint: a digit, a number, day or month word, "no", a payment method, or a place or car name said on the call. My review found a few more answer-like labels than the lint does, in the whole-call reads (for example "Payment after work", "Cash after work" in v1).

| Model, prompt | First read: long / value (of 120) | Whole call: long / value | Never ready (of 20) | Line ready, median (range) | Reply with labels, median / p95 | Not-ready reply, median |
|---|---|---|---|---|---|---|
| gpt-6-luna, v2 | **4 / 0** | **2 / 1** | 0 | 3 (1-7) | 4.7 / 5.3 s | 1.9 s |
| gpt-5.6-luna, v2 | 27 / 6 | 21 / 12 | 0 | 3 (1-8) | 4.1 / 5.3 s | 1.7 s |
| gpt-6-luna, v1 | 6 / 0 | 7 / 1 | 0 | 3 (1-7) | 4.3 / 5.4 s | 1.9 s |
| gpt-5.6-luna, v1 | 18 / 0 (of 114) | 17 / 15 | 1 | 3 (1-7) | 4.2 / 4.8 s | 1.8 s |
| gpt-5.4-mini low, v1 | 0 / 0 (of 90) | 0 / 6 | 5 | 3 (1-6) | 4.0 / 5.2 s | 1.6 s |

- **v1 → v2.** v1's whole-call labels turned into answers ("No advance", "Ready by Monday", "Kanpur cab if late", "Cash after work") or went on the wrong term ("Overtime after seven" under late, "Measurement visit" under dates). v2 adds "a label names the question, never the answer", keeps each label to its own term, and asks for the job's most specific words.
- **Why gpt-5.4-mini was dropped after v1.** It said the job was clear but left the labels empty on 5 calls, it uses Title Case ("Start And Finish"), and it is the most expensive. It was not re-run on v2, so the budget could go to the decision comparison.
- **Most of the delay is output.** Six terms times five fields is about 280 output tokens. A labels-only reply would be faster (not measured).

## Extras (raised by both)

gpt-6-luna v2, whole-call read. Checked against the call's words by hand. The mechanical check confirms only that both cited lines exist, come before the read, and were said by the hirer and by the worker.

| Call | Extra | Hirer said | Worker said | Verdict |
|---|---|---|---|---|
| call_two_amounts | Paint supply | 6 "Paint main khud le aaungi" | 7 "Achha, material aapka" | Both ✓ |
| second_call | Paint supply | 6 "paint aa gaya hai" | 7 "Ji madam. Kal subah 10 baje…" | Hirer only ✗ (the reply is about the time) |
| spike_painter_call | Furniture and cleanup | 25 | 26 | Both ✓ |
| holdout2_car_mechanic | Clutch warranty | 24 "Achha good" | 23 | Both, barely ✓ |
| holdout2_driver_monthly | Overtime | 7, 13 | 6 | Both ✓ |
| holdout2_driver_monthly | Sunday work | 18 | 19 | Both ✓ (left open: "वो देखते हैं") |
| holdout2_driver_monthly | Monthly leave | 22 | 23 | Both ✓ |
| holdout2_mason_wall_call2 | Plaster sand | 26 | 27 | Both ✓ |
| holdout2_tailor_lehenga | Who brings lining | 33 | cited 33 (the hirer's line); really 6 | Both ✓, citation wrong |
| holdout_carpenter_wardrobe | Work locations | 17 | 18 | Both ✓ |
| holdout_carpenter_wardrobe | Bedroom electricity | 23 | 22 | Both ✓ (a practical point, not much of a term) |
| holdout_cook_month | Monthly days off | 18 | 19 | Both ✓ |
| holdout_cook_month | Household groceries | 26 | 27 "ठीक है जी" | Both ✓ |
| holdout_electrician_shop | Old board removal | cited 22 (the worker's line) | 22 | Worker only ✗, citation wrong |
| holdout_plumber_leak | Who brings materials | 26 | 27 | Both ✓ |

Totals:

- **Named something nobody said: 0.** That is the fail the brief asked to count.
- **Raised by one person only: 2.**
- **Citation wrong: 2,** one of them on a true extra. So the cited lines cannot be the only gate.
- **Missed:** the wardrobe's laminate colour, left to the hirer's wife but spoken of by both. In mid-call reads, extras came and went, and some were arrangements the prompt excludes ("Payment method", "Food preferences").
- Memory's Scribe already files leave, material and daily hours under `work`. So the facts behind most extras already exist; only their names are new.

## Spoken questions (asks)

Every generated `ask` from gpt-6-luna v2, all reads: 654.

- **Proposes a value, or says what would be fair: 0.**
- **Drops the `{who}` slot** ("Ask both speakers to confirm…"): 78 (12%). The Judge, not the model, decides who is asked (`judge.py` `ASK`).
- **Late-term asks that add "not done right", "not done as agreed" or "does not restore cooling": 99 of 109, on 19 of 20 calls.** My v2 prompt caused this: it described late_or_unfinished as "late, not done, or not done right". On most calls nobody spoke of quality, so asking about it would be Gawah raising a term. A v3 prompt without that phrase was not run (budget).
- **The rest add little.** The amount, advance, balance and dates asks are today's `QUESTION` wording with the trade's name in it ("Ask {who} when the rest of the cooking pay will be paid and against what"). Only the work ask reads clearly better ("Ask {who} what meals to cook and when to make them"; "what wardrobe size and design to make").

## Decisions with generated wording

The same scoring as spike 6 (`6-decide.py` `windows`, `score_q`, `yes_lines`, imported), on spike 6's 18 calls (17 labelled). The model is gpt-5.6-luna at effort none, the OpenAI fallback. Not live Sage2.

- From the line gpt-6-luna's labels arrived (its first read), `topic_left_unclear` and `balance_skipped` named the terms in the job's words. Every other word of the brain's question was kept (`UNCLEAR_T`, `BALANCE_T` in `7-labels.py`).
  - Static: "(price, advance, when the balance is paid, or dates)".
  - Generated, cook: "(the cooking pay, the advance, when the rest of the cooking pay is paid, or when the cooking work starts and finishes)".
- Lines before the labels keep spike 6's saved luna answers, which come from the same input.
- To see how much luna moves between two runs of the same input, I also re-ran the static wording on the same lines ("static, again").

| Question | Sage2 (saved) | luna static (spike 6) | luna static, again | luna generated |
|---|---|---|---|---|
| `topic_left_unclear` hits / false fires (calls) | 3/10, 4 (3) | 6/10, 11 (7) | 5/10, 7 (5) | 6/10, 11 (8) |
| `balance_skipped` (balance moments) | 3/4, 2 (2) | 4/4, 14 (10) | 4/4, 10 (9) | 4/4, 16 (9) |
| either, as the Judge combines them | 6/10, 6 (5) | **9/10, 23 (14)** | **9/10, 16 (12)** | **9/10, 25 (12)** |
| `addressed_gawah` (unchanged wording) | 5/5, 2 (2) | 5/5, 1 (1) | 5/5, 1 (1) | 5/5, 2 (1) |
| wrap-up, as the Judge combines it (unchanged) | 18/18, 10 (8) | 14/18, 0 | 14/18, 0 | 14/18, 0 |
| Delay, median / p95 | - | 1,141 / 1,453 ms | 1,291 / 1,707 ms | 1,262 / 1,633 ms |

- **Hits are the same.** The tailor's late question is caught by the generated run and by spike 6's run, and missed by the static re-run.
- **False fires: the generated run has the most, at the top of the static wording's spread.** Two static runs gave 16 and 23. The extra ones are spread thin: call_two_amounts lines 11 and 25 (during the bargaining, and after), car mechanic lines 17, 19 and 25 on `balance_skipped`.
- **Verdict: no gain; possibly slightly worse.** Keep the static wording. It names the terms generically, and that already works for every trade here.

### The six "agreed?" questions

Spike 5's per-line labels for its painter (30 lines) and carpenter (16 lines) calls, with luna. Static means spike 5's v2 item questions. Generated means each term's `question` from gpt-6-luna's first read, used from line 2 on both calls.

| | work | amount | advance | balance | dates | late | total |
|---|---|---|---|---|---|---|---|
| static | 44/44 | 33/33 | 44/44 | 45/45 | 43/43 | 46/46 | 255/255 |
| generated | 44/44 | 32/33 | 44/44 | 45/45 | 43/43 | 46/46 | 254/255 |

The one miss is painter line 11: "42 hazaar done" is accepted, and the generated question said yes one line late. Both wordings track agreement. The brain no longer asks these (the checklist comes from memory), so this only shows that generated yes/no wording does not break.

## Sage2

**No Sage2 call was made.** The design keeps Sage2's questions as they are, so whether Sage2 accepts questions changed mid-call does not matter. If it ever did matter: `SageStream._start` already reopens a stream with the whole call so far. Swapping questions that way would cost one extra billed update (with every question) per change. That is untested on Sage2.

## Cost

| Part | Requests | Cost (USD) |
|---|---|---|
| Label scans, v1 (luna, mini, gpt-6-luna) | 228 | 0.285 |
| Label scans, v2 (luna, gpt-6-luna) | 173 | 0.053 |
| Re-reads every 6 lines (gpt-6-luna) | 69 | 0.022 |
| Decisions, static again and generated (luna) | 954 | 0.230 |
| Item questions, static and generated (luna) | 90 | 0.018 |
| Effort probes for gpt-6-luna | 2 | ~0 |
| **Total** | **1,516** (+1 `GET /v1/models`) | **$0.61** |

- **Labels in the app would cost almost nothing.** A scan of about 3 requests to the first read, plus at most 6 per-term reads, is about 9 gpt-6-luna requests a call: about $0.002, at third-party prices.
- **No Sage2 updates are added.** The decision questions stay as they are.
- The token counts are in the saved files. gpt-6-luna's price comes from third-party trackers (getmaxim.ai, pricepertoken.com), not OpenAI's page: $0.10 input, $0.01 cached, $0.50 output per million tokens.

## What it would take to ship (design only, not built)

The smallest version that makes the board use generated names. `ItemKey` stays the fixed spine: every fact, checklist item, contract clause and test still uses the six keys. Only the words shown change.

1. **One additive event in `app/contracts.py`.** This needs the orchestrator, because `contracts.py` is a "stop and ask" file.
   ```python
   class TermLabel(BaseModel):
       label: str            # at most 24 characters, no values; shown instead of the static name
       hint: str | None = None

   class ExtraLabel(BaseModel):
       label: str
       hint: str | None = None
       hirer_line: int       # where each said it, on this call
       worker_line: int

   class LabelsUpdated(Event):
       """Sent by brain when it names the terms for this job. Listened to by dashboard (and, later, contract).
       A key missing from labels keeps its static name."""
       name: Literal["labels.updated"] = "labels.updated"
       labels: dict[ItemKey, TermLabel] = {}
       extras: list[ExtraLabel] = []
       call_no: int = 1
       line_no: int | None = None
   ```
2. **Brain: `app/brain/labels.py`, about 120 lines.** It holds the OpenAI client it already has (`values.py`) and runs beside the Judge, never in its way.
   - After each line, up to line 10, while no labels are set and no request is in flight, ask gpt-6-luna (effort none, the v2 prompt minus "not done right", strict JSON). When the job is clear, publish `labels.updated` with all six.
   - **Freeze each term.** When memory's first `fact.recorded` for a term arrives, re-read once and take that term's new label only. After that it never changes. Extras are taken from the same re-reads, at most 3 a deal.
   - **A lint in code (`lint` in `7-labels.py`):** at most 24 characters, no digits, number, day or month words, payment methods, or "no". A label that fails keeps the static name. An extra must have both cited lines from the right speakers.
   - **Replays and tests:** saved replies in `tests/brain/recorded/<call>.labels.json`, found by the words of the call, like the brain's other recordings. A replayed call costs nothing, and `tests/offline.py` gets labels with no key.
3. **Dashboard: about 40 lines of JS.**
   - `state.js` folds `labels.updated` into `state.labels`. `ITEMS` stays the order.
   - A `labelOf(state, key)` replaces the three places that read the static names: `checklist.js`, `board.js` `LABEL`, `chain.js` `ITEM_LABEL`.
   - Extras become rows after the six with an "Also discussed" pill and their hint. `#items` gets an auto height, and the facts panel moves down by 64 px a row (as the prototype does).
4. **Kept as they are, on purpose:**
   - Sage2's questions (no gain measured, and re-recording the practice calls costs time).
   - `judge.py` `QUESTION` and the mouth's `LABEL` (generated asks drop `{who}` and widened the late term; the rest are today's words).
   - The agreement's bilingual headings (labels are English only; a Hindi label was not tried).
   - The Scribe (memory's filing does not change).
5. **Later, if wanted:** the contract stream puts the English label under each fixed bilingual heading ("काम / The work: Meals and timings"). The work question in `judge.py` could take the generated ask, only when it contains `{who}` and passes a check that it names no value.

Tests: one brain test replays `holdout_cook_month` from saved labels and checks the event, the frozen labels and the lint fallback. `tests/test_whole_flow.py` checks that the board's names come through. `call_page_shots` is not affected.

## Not measured

- **The frozen-per-term design** (re-read when a term's first fact arrives). I measured fixed re-reads every 6 lines, which show the churn but not this rule's result.
- **A v3 prompt** without "or not done right" in the late term. The budget was spent.
- **Hindi or Hinglish labels** for the agreement and for WhatsApp.
- **Live Sage2** with generated wording. Luna stood in, as the brief asked.
- **Run-to-run variation of the labels.** One run per model and prompt. The decisions were run twice with static wording, which is how the spread above was measured.
- **gpt-5.4-mini on the v2 prompt.**
- **Real speech-to-text.** Only the calls marked `stt` (cook, electrician, AC repair, driver) and the dry run's real transcript stand in for it. The labels on those were as good as on the clean calls.
- **gpt-6-luna's price** on OpenAI's own page.

## Files

- `7-labels.py`:
  - `gen <luna|mini|luna6>`: the label scan and the whole-call read.
  - `refresh luna6`: re-reads every 6 lines.
  - `decide <static|generated>` and `items <static|generated>`: the decision runs.
  - `score`: reads saved files only, and writes `7-results/scores.json` and `scores.txt`.
  - Each run skips what is already saved.
- `7-prototype.py`: the dashboard shots (offline app in-process, nothing outside).
- `7-results/gen-*.json`: every reply, delay and token count. `-v1` files are the first prompt; each file holds its prompt.
- `7-results/refresh-luna6.json`, `decide-*.json`, `items-*.json`: the other runs.
- `7-results/prototype/`:
  - `index.html`: the shots side by side.
  - `cook-static.png`, `cook-generated.png`, `painter-static.png`, `painter-generated.png`: 1920x1080.
  - `report.json`: the names shown in each shot.
