---
name: spike
description: Use when answering one of the feasibility questions in PLAN.md Step 2, or any time a build decision depends on whether an outside service actually works. A time-boxed throwaway test that ends in a written answer.
---

# Spike

A spike answers one question. It is not the start of the real code.

## Steps

1. Write the question as yes or no. Example: "Can a Twilio trial account call two Indian mobiles and join them in one call?"
2. Write what you will do if the answer is no. If you cannot name a fallback, find one before you start. The fallbacks for our five spikes are in `PLAN.md`.
3. Set a time box. Default is 45 minutes. Hard stop at 90.
4. Write the shortest script that can answer the question, in `spikes/<number>-<name>.py`. One file. Hard-code what you like. No tests, no structure.
5. Run it against the real service with real inputs: our own verified phones, our own Hinglish speech.
6. Write the answer at the bottom of `PLAN.md` under "Spike answers".

## The answer

```
<n>. <name>: YES / NO / PARTLY
What I ran: <one line>
What happened: <the actual result, with numbers if there are any>
Catch: <limits, costs, or surprises>
Decision: <use it / use the fallback>
```

## Rules

- A spike that is "almost working" at the end of the time box is a NO. Take the fallback.
- Real calls and messages go only to numbers in `VERIFIED_NUMBERS`.
- Do not import spike code into `app/`. If the spike worked, the stream rewrites it properly.
- Record anything that cost money or used up a trial allowance.
- Measure before you judge. For speed, time it. For transcription, compare against what was actually said.
