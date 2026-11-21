---
name: stream-brief
description: Use when starting a parallel agent on one of the build streams in PLAN.md, or restarting one after a failed attempt. Sets up the worktree and writes the short brief the agent works from.
---

# Stream brief

Each stream runs in its own worktree with its own agent. The brief is the only context that agent starts with, so it has to stand on its own.

## Set up the worktree

Write the brief to a file first, then:

```
workmux add <stream> -b -P <brief file>
```

`.workmux.yaml` branches from `main`, copies `.env` in, and installs dependencies. The worktree lands in `.worktrees/<stream>`.

Check `workmux list` first. If the worktree exists, reuse it: `workmux send <stream> -f <follow-up file>` if its agent is running, or `workmux open <stream> --continue -P <follow-up file>` if its window is closed.

## Write the brief

Five parts, in this order. Take the facts from the stream table in `PLAN.md`.

```
Goal: <what this stream builds, one or two sentences>
Owns: <the folders it may edit>
Events: listens to <...>; sends <...>
Done when: <the exact line from the PLAN.md table>
Rules: read AGENTS.md first. Build against the fakes. Do not edit
  contracts.py, bus.py, or main.py. Use prove-it-works before reporting.
```

Then add only what this agent cannot find in the repo:

- The answer to its spike, copied from the bottom of `PLAN.md`
- Which fixture files to build against
- Anything already tried that did not work

Point to files by path. Do not paste their contents into the brief.

## Restarting a stream

- Start a fresh agent with the original brief plus the last agent's report or `HANDOFF.md`.
- Resume the old agent only if it holds something a new one cannot get: uncommitted work, or a running process.
- Add one line saying what failed last time, so the new agent does not repeat it.

## Start order

`brain`, `whatsapp`, `contract`, and `dashboard` can start as soon as the scaffold is merged. `bridge` waits for spikes 1 and 2. `mouth` waits for spike 3.
