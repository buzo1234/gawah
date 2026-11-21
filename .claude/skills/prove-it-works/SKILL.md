---
name: prove-it-works
description: Use before saying a task is done, before asking for a merge, and before reporting a spike result. Checks the change against the real thing (a replayed call, a real call, a real WhatsApp message) instead of "it compiles" or "tests pass".
---

# Prove it works

A change is done when you have watched it do its job, not when the code looks right.

## Steps

1. Name the behaviour you changed in one sentence, from the user's side. Example: "When the balance date is skipped, the Judge asks Sunita about it."
2. Pick the closest check to the real thing that you can run (see the table).
3. Run it. Read the actual output, not the exit code.
4. If the check fails, first make sure the check itself is right - wrong fixture, stale server, wrong branch. Then fix the cause.
5. If you will run the check more than once, script it and keep the script in `tests/` or `spikes/`.
6. Report using the format below.

## What counts as proof

| Stream | Minimum proof | Better |
|---|---|---|
| bridge | Speaker-labelled lines appear on the dashboard from a real call between the phone and the laptop | The recording is in S3 and plays |
| brain | Replaying both practice calls raises the expected `judge.speak` at the expected line | Same result three runs in a row |
| mouth | A `judge.speak` event is heard on a real call | It stops when talked over |
| whatsapp | A real message in, the right reply out, the right event on the bus | The no-reply timer fires |
| contract | The PDF opens and the terms match the fixture | It arrives on a real phone |
| dashboard | It shows a replayed call live | Readable from across the room |

Real rooms and real messages use up free allowances. Prove with the replayer where that is enough, and use one real call for what only a real call can show.

## What does not count

- The code compiles, or imports without error
- A test that mocks the thing being tested
- Output you remember from an earlier run
- Another agent saying it works

## Report format

```
Changed: <the behaviour, one sentence>
Checked by: <the command or the manual step>
Saw: <the actual output or what happened>
Not checked: <what you could not run, and why>
```

If "Not checked" is not empty, the task is not done. Say so plainly.
