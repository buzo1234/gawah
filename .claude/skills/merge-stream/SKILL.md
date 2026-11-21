---
name: merge-stream
description: Use when a stream's work is ready to go into main, or when main has moved and a worktree needs to catch up. Covers the rebase, the checks before a merge, conflicts, and how to ask for a change to the shared event types.
---

# Merge a stream

Merge small and often. Several merges a day per stream is normal. One large merge at the end is how the demo breaks.

## Before asking for a merge

1. Commit your work on the stream branch.
2. `git fetch` and `git rebase main`.
3. `uv run pytest -q` - all tests pass, including other streams' tests.
4. Run the `prove-it-works` skill for what you changed.
5. Check the diff touches only the folders your stream owns: `git diff --stat main`.
6. Delete `HANDOFF.md` if there is one.

## The merge note

```
Stream: <name>
Adds: <what now works, from the user's side>
Proof: <the prove-it-works report>
New dependencies: <none, or the list>
Events: <any event this stream now sends or listens to for the first time>
Still missing: <what the stream's done-when still needs>
```

Report and stop. Do not merge and do not run `/merge`. The orchestrator reviews the work, pushes your branch, and opens a pull request. The user reviews and merges it. If the orchestrator or the user asks for changes, make them on the same branch and report again.

## Conflicts

- In your own folders: resolve them.
- In `contracts.py`, `bus.py`, `main.py`, or another stream's folder: stop. You should not have a change there. Take `main`'s version and raise it.

## Changing the shared event types

Streams only work in parallel because `app/contracts.py` stays still.

1. Do not edit it on your branch.
2. Write the request: which event, which field, why, and which streams it affects.
3. The person who owns `contracts.py` makes the change on `main`.
4. Every stream rebases.

Adding an optional field is cheap. Renaming or removing a field breaks other streams - avoid it.

## After main moves

Rebase at each checkpoint in `PLAN.md` even if you have nothing to merge. Rebasing a day of drift costs more than rebasing an hour of it.
