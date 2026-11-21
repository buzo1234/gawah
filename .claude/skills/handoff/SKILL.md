---
name: handoff
description: Use when stopping work that is not finished - end of a session, blocked on a human, or running low on context. Leaves a note that a fresh agent can pick up from without the conversation.
---

# Handoff

The next agent will not have your conversation. Whatever is not written down is lost.

## Before you stop

1. Get to a safe state. Commit what works. If something is half-done and broken, commit it on the stream branch with a message starting `wip:` - do not leave it uncommitted.
2. Stop anything you started: servers, tunnels, calls in progress.
3. Write `HANDOFF.md` at the root of your worktree and commit it.

## HANDOFF.md

```
Stream: <name>            Branch: <branch>
Goal: <the done-when from the brief>

Works now: <what you proved, and how>
In progress: <what is half-done, which files, what state it is in>
Next step: <the single next thing to do>

Tried and failed: <what did not work, and why - so it is not repeated>
Waiting on: <a human, a spike answer, another stream - or nothing>
Unverified: <what you assumed without checking>
How to run: <the exact commands to see the current state>
```

Keep it under a page. Point to files by path.

## Rules

- "Works now" lists only what you ran. If you did not run it, it goes under "Unverified".
- "Tried and failed" matters most. It is what stops the next agent losing the same hour.
- If you are blocked on a human, say exactly what you need from them, in one line they can act on.
- Delete `HANDOFF.md` before the stream merges into `main`.

## Picking up

If you start in a worktree that has a `HANDOFF.md`: read it, run "How to run" to confirm the state is what it says, then continue from "Next step".
