# Spike 6: Sage2 or OpenAI for the Judge's live yes/no decisions

```
6. decide: NO (do not switch)
What I ran: Sage2's saved answers against three OpenAI models (gpt-5.6-luna effort none, gpt-5.4-mini effort low, gpt-realtime-2.1 text), with the same transcript so far on every line of 18 calls (518 lines), the five questions the Judge reads, scored against the labels of the 17 calls that have them (509 lines).
What happened: Sage2 is the fastest (p95 0.70 s against 1.45-4.7 s) and the best at wrap-up (wrapping_up 16/18, no false fires; the OpenAI models 12-14/18). All four catch someone talking to Gawah (5/5). Sage2's weak spot is a term that was dodged: 6/10 required moments, missing four on the held-out calls. The OpenAI models catch 9-10/10, but they also fire falsely in 7 to 17 of the 17 calls.
Catch: gpt-realtime-2.1 trades best on dodged terms (9/10, 8 false fires) but costs $0.19 a call, takes over 3 s on 34% of lines, and gave unparseable text on 2% of them. Prices come from OpenAI's pricing page; Sage2's output price is still unpublished.
Decision: Keep Sage2 for all five questions. gpt-5.6-luna is the fallback if Sage2's free allowance runs out: $0.007 a call, p95 1.45 s, but its wording needs tuning first.
```

## The answer

Keep Sage2 for all five questions on the live path. On `addressed_gawah` every engine catches 5 of 5, and Sage2 is two to four times faster than any OpenAI model. On `wrapping_up` Sage2 is better: 16/18 with no false fire, against 12-14/18 for the OpenAI models. On the dodged term (`topic_left_unclear` or `balance_skipped`, which the Judge combines), Sage2 catches only 6 of 10 required moments. All four misses are on the held-out calls: driver, tailor, cook and plumber. Every OpenAI model catches 9 or 10 of 10, but with more false fires. gpt-5.6-luna has 23 in 14 of 17 calls, and 14 of those come from `balance_skipped`, which makes the Judge ask about the balance directly. gpt-5.4-mini fires falsely in all 17 calls. Only gpt-realtime-2.1 in text mode is cleaner (9/10, 8 false fires in 7 calls), and it costs $0.19 a call. Its p95 is 4.7 s, so it is past the brain's 3 s Sage timeout on a third of the lines, and 2% of its replies could not be parsed. A Sage2 miss costs less than a false fire. The term is still open at wrap-up, and the Judge asks every open term then, so a miss means a later question. A false fire interrupts the call mid-way. No switch for the demo. If Sage2's free allowance (about a dozen calls a month) runs out, use gpt-5.6-luna at effort none, behind the same `Decisions` protocol. It costs $0.007 for a 30-line call, has a p95 of 1.45 s, matches Sage2 on `addressed_gawah` and on spike 5's per-line labels, and has no false wrap-up. Tune its `balance_skipped` wording before you rely on it.

## Results

Every labelled call: 17 calls, 509 lines. The two practice calls, the demo call and the dry-run call, spike 5's painter and carpenter calls (labelled line by line), and all 11 held-out calls. `second_call` (9 lines) has no label for these questions, so it counts only in the agreement table. "Hits" means required moments with a yes inside the window. "False fires" means the times an answer turned yes outside every window where a yes is allowed, followed by the number of calls with at least one.

| Question | Sage2 (saved) | gpt-5.6-luna, effort none | gpt-5.4-mini, effort low | gpt-realtime-2.1, text |
|---|---|---|---|---|
| `addressed_gawah` hits / false fires | **5/5**, 2 (2 calls) | **5/5**, 1 (1) | 5/5, 4 (3) | **5/5, 0** |
| `topic_left_unclear` | 3/10, 4 (3) | 6/10, 11 (7) | 8/10, 39 (17) | 6/10, 6 (6) |
| `balance_skipped` (balance moments only) | 3/4, 2 (2) | 4/4, 14 (10) | 4/4, 16 (10) | **4/4, 3 (2)** |
| either of the two, as the Judge combines them | 6/10, 6 (5) | 9/10, 23 (14) | 10/10, 48 (17) | **9/10, 8 (7)** |
| `closing_soon` | 16/16, 26 (12 of 15) | 15/16, 5 (4) | 14/16, 7 (6) | 14/16, 4 (4) |
| `wrapping_up` | **16/18, 0** | 13/18, 0 | 14/18, 0 | 12/18, 0 |
| `wrapping_up`, or `closing_soon` twice in a row | 18/18, 10 (8) | 14/18, 0 | 16/18, 1 (1) | 14/18, 1 (1) |
| Spike 5's per-line labels (3 questions, 135 lines) | 135/135 | 135/135 | 128/135 | 133/135 |
| Delay per decision, median / p95 (max) | **576 / 702 ms (889)** | 1,141 / 1,453 ms (5,287) | 1,567 / 2,304 ms (3,866) | 2,581 / 4,688 ms (8,227) |
| Lines over the brain's 3 s Sage timeout | 0 of 106 | 4 of 518 | 3 of 518 | 176 of 518 |
| Replies that could not be parsed | 0 | 0 | 0 | 11 of 518 |
| Cost per 30-line call | not published (see below); free plan is about a dozen calls a month | **$0.007** | $0.037 | $0.191 |
| Cost of this spike | 0 (saved answers) | $0.121 | $0.634 | $3.301 |

Where each misses a required dodged-term moment:

- Sage2 misses four, all on held-out calls. `holdout2_driver_monthly` (Sunday pay, "वो देखते हैं"), `holdout2_tailor_lehenga` (the late question dodged with a story), `holdout_cook_month` (the pay put off with "वो देख लेंगे") and `holdout_plumber_leak` (the balance, "mil jayega").
- luna misses the driver's Sunday pay.
- realtime misses the tailor's late question.
- mini misses none.

`addressed_gawah` false fires:

- Sage2, luna and mini said yes at car mechanic line 20 ("Gawah sun raha hai", spoken about Gawah, not to it). Sage2 and mini said yes at mason call 2 line 24, two lines after the real question to Gawah.
- mini also said yes on painter lines 25-26.

Sage2's 26 `closing_soon` false fires are why the brain counts it only twice in a row or before a silence. Under that rule Sage2 still has 10 false fires in 8 calls, but this scoring leaves out the brain's other condition, at least four terms agreed (`CLOSE_MIN_AGREED`), so the real number is lower.

### Agreement where the labels do not decide

The labels name moments, not every line, so the table below compares engines on every line of all 18 calls (518 lines; `balance_skipped` 488, because spike 5's painter recording never asked it). These are agreement rates, not accuracy.

| Question | Sage2~luna | Sage2~mini | Sage2~realtime | luna~mini | luna~realtime | mini~realtime |
|---|---|---|---|---|---|---|
| `addressed_gawah` | 99.6% | 99.0% | 99.6% | 98.6% | 99.6% | 98.6% |
| `topic_left_unclear` | 90.0% | 80.3% | 85.7% | 80.3% | 88.8% | 82.2% |
| `balance_skipped` | 92.4% | 92.4% | 96.9% | 92.6% | 93.4% | 93.9% |
| `closing_soon` | 84.2% | 83.8% | 85.1% | 94.6% | 95.9% | 94.8% |
| `wrapping_up` | 96.5% | 96.5% | 96.7% | 98.5% | 99.0% | 99.0% |

The three OpenAI models agree with each other on `closing_soon` (95%) far more than any of them agrees with Sage2 (84-85%). That is Sage2's habit of saying yes to `closing_soon` mid-call.

## How it was scored

- **The same input as Sage2.** Each OpenAI request carries an instruction, the five question texts word for word from the saved Sage2 recordings, and then the saved preamble and every line up to the current one, exactly as Sage2 was sent them. One request per line answers all five questions, as one Sage2 update does. Sage2 yes means a probability of at least 0.5, and null counts as no.
- **Labels.** The labels come from each call's `expected` and `must_stay_silent`, its `wrap_up_starts_line`, and spike 5's per-line labels for the painter and the 16-line carpenter call. Calls without `required` count every moment as required.
  - `addressed_gawah` is scored on `question_to_gawah` moments. Every yes outside them is a false fire, because the Judge answers every time.
  - The dodged-term questions are scored on `term_unclear` moments, and `balance_skipped` only on those about the balance. A yes is also allowed at a two-meanings or contradiction moment and from the wrap-up on, but it is never required there: other parts of the brain handle those moments.
  - `closing_soon` and `wrapping_up` are scored on `wrapping_up` moments. A yes counts from one line before the wrap-up starts (the plumber note allows that) to the end of the call.
  - A false fire is a no→yes change outside the allowed lines. An answer that stays yes after a correct fire is not counted again.
- **Unparseable replies.** A reply that could not be parsed (realtime only) keeps the previous line's answers, with `addressed_gawah` set to no. That is what the brain does when Sage2 gives no answer.
- **Delay.** Measured from this laptop in India, with four calls running at once and each call's lines in order. Sage2's delay comes from spike 5's timed runs (106 updates with 10 questions, `spikes/5-results/sage2-*-v2.json`), because the saved recordings here carry no timings.
- **Prices.** Read on 22 November 2026 from developers.openai.com/api/docs/pricing and each model's page. USD per 1M tokens, input / cached input / output:
  - gpt-5.6-luna: 0.20 / 0.02 / 1.20
  - gpt-5.4-mini: 0.75 / 0.075 / 4.50
  - gpt-realtime-2.1 text: 4.00 / 0.40 / 24.00
- **Sage2's cost.** Each update re-bills about 940-1,150 question tokens plus the line, at $0.05 per million input tokens, and reports about 735 output tokens at a price that is not published. Spike 5 put that at about $0.02 a call if output costs $1 per million. What limits Sage2 is its $1 monthly free allowance, not the price.

### Why these models

- **gpt-5.6-luna, effort none.** The small, fast model. The pricing page lists it as the nano tier, and the key has it. gpt-5.4-nano is marked deprecated, and in spike 5 it took the wrong figure.
- **gpt-5.4-mini, effort low.** The reasoning model at low effort. The brain already calls it, at that effort, for values and for naming the unclear term (`VALUES_MODEL`), so it would add no new dependency.
- **gpt-realtime-2.1, text mode.** The mouth already holds a connection to this model for the whole call. Each line was sent as an out-of-band response (`conversation: "none"`) on a separate connection per call.

## What each would need in the code

- **Sage2 (today).** `SageStream` keeps one WebSocket per call and appends only the new line. The server holds the transcript. The answers are probabilities. Every update re-bills all the questions, and the free allowance is the limit.
- **An OpenAI text model.** A new `Decisions` class: the protocol in `app/brain/sage.py` (`open`, `append`, `close`), with no change to the Judge.
  - It keeps the transcript string and sends the instructions plus the whole transcript on each append. The brain already does this for its values lookups.
  - Use strict JSON schema output, which never failed to parse in 1,036 requests. It returns true or false, not a probability, so map them to 1.0 and 0.0.
  - Input grows with the call, so cost grows with the square of its length. 518 lines averaged about 920 input tokens each.
  - Prompt caching barely helped: luna reported no cached tokens even with `prompt_cache_key` and prompts over 1,024 tokens, and mini cached 16%.
  - Each decision arrives 0.6-1.0 s later than Sage2's (median), which pushes back every question the Judge asks.
- **The realtime model.** There is no structured output, so 2% of replies were prose, HTML, a list or a refusal ("This content may violate our usage policies", on demo call line 4).
  - Sharing the mouth's connection could save a connection, but it was not tried. An out-of-band response while Gawah is speaking might delay or collide with its speech.
  - Its delay is too long for live use either way.

## Not measured

- **No new Sage2 calls.** Sage2's delay on these calls and its dollar cost come from spike 5's numbers, not from this run.
- **Questions, not the whole Judge.** The scores leave out what the brain adds on top: the memory's checklist (an item is asked only while it is still pending), `CLOSE_MIN_AGREED`, the silence rule (the demo and dry-run wrap-ups depend on it, so `wrapping_up` alone misses them for every engine), and the gpt-5.4-mini lookup that names the unclear term and drops it if it is not pending. So the false fires here overstate what a listener would hear, for every engine.
- **One run each.** No repeat to measure variation. The OpenAI models got Sage2's wording unchanged, which was tuned for Sage2. Rewording might help them, luna's `balance_skipped` most of all.
- **Lines no label covers** are compared only as agreement between engines (the table above), not as accuracy.
- **Not run.** `fixtures/demo/demo_call_1.json` and `demo_call_2.json` have no saved Sage2 answers and no labels. A realtime decision on the mouth's own connection was not tried.
- **Real speech-to-text.** Only the held-out calls marked `stt` stand in for it.

## Usage

- 1,554 OpenAI requests: 518 per model, no retries needed. Plus one `GET /v1/models`. The six smoke-test lines are counted in the 518 and were not sent again.
- $4.06 in all: luna $0.121, mini $0.634, realtime $3.301, from the token counts in the saved results.
- No Sage2, LiveKit or WhatsApp use.

## Files

- `6-decide.py`:
  - `run <luna|mini|realtime>` calls OpenAI and skips lines already saved.
  - `score` reads only saved files and calls nothing.
- `6-results/luna.json`, `mini.json`, `realtime.json`: every answer, delay and token count, per call and line.
- `6-results/scores.json`, `scores.txt`: the scores above, per call and in total.
