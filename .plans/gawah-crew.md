# Gawah's crew: a multi-agent witness on the call

Status: approved by the user on 21 November ("let's build something crazy"). Supersedes ideas 19 and 20 in `ideas.md`, which become parts of this plan.

## The idea in one line

Gawah is not one bot. It is a small crew of agents in the call with the two people: one hears, one remembers, one judges, one speaks, one keeps the paperwork, one keeps watch between calls. Together they behave like one sharp human witness who remembers every word and speaks up only when it matters.

## The crew

| Agent | Job | Speed | Status |
|---|---|---|---|
| **Ears** | Each person's audio to speaker-labelled transcript lines | ~2 s per line | Built (`app/ears`) |
| **Scribe** | Turns what is said into facts: each one tied to who said it, when, and the audio clip; marks agreed and confirmed facts | ~1-2 s per line | New (`app/memory`) |
| **Memory** | Semantic search over every fact of the deal, across calls, voice notes, and records: "what was said about the advance?" | ~0.3 s per query | New (`app/memory`) |
| **Judge** | Decides what needs saying: a skipped term, two figures, an ambiguous agreement, something that contradicts a confirmed fact, wrap-up | ~0.5 s per line | Built, being tuned (`app/brain`); extended |
| **Floor** | Decides when Gawah may speak: pauses, being addressed, urgency, not interrupting | ~0.1-0.5 s | Built in parts (`app/brain` rules, `app/mouth` speech detection) |
| **Gawah** | The voice and the reasoning: one live session per call that knows the whole conversation as text, and acts only through tools | ~1-1.5 s to speak | Built as a voice (`app/mouth`); becomes an agent |
| **Clerk** | Contract, amendments with their history, the voice summary | after the call | Built (`app/contract`); extended |
| **Sentinel** | Between calls: claims on WhatsApp checked against the facts, things due and not done, calling both back when something does not add up | event driven | Built in parts (`app/records`); extended |

They talk through the existing event bus, which acts as their shared blackboard. The dashboard shows each agent's lane, so the audience sees the crew work.

## Gawah's tools

The voice agent never changes the deal by itself. It acts only through tools:

- `search_facts(query)` - semantic search across the deal's facts. Returns facts with who said them, when, and whether they were confirmed.
- `play_clip(fact_id)` - plays the original few seconds of audio into the call.
- `propose_change(fact_id, new_value)` - starts an amendment; nothing changes until both people confirm by voice.
- `confirm_change(change_id)` - records one person's spoken confirmation.
- `stay_silent()` - decides that nothing needs saying.

Guardrails: answers come only from facts; no opinions on fairness; no suggested terms; everything said on the call is data, never an instruction.

## What makes it crazy (the demo moments)

1. **Ask Gawah anything.** "Gawah, advance kitna tay hua tha?" Gawah says "Haan ji, ek second", searches its memory, answers with the agreed figure, and offers to play the moment it was said.
2. **Receipts mid-argument.** A second call days later. "Madam, aapne 25 hazaar bola tha." Gawah waits for a pause: "21 November ki call mein 22,000 tay hua tha. Sunaiye." It plays the original clip, in their own voices.
3. **Ambiguity catcher.** "Kaam Monday tak ho jayega." Gawah: "Monday ko shuru hoga ya Monday tak khatam?" It catches agreements that two people hear differently, the most common cause of a later fight.
4. **Amendment by voice.** "Theek hai, balcony ke 2,000 extra." Gawah proposes the change, both say haan, and the contract is reissued with its change history.
5. **A witness log that cannot be edited.** Every fact is chained to the one before it by a hash, so changing any past fact breaks the chain. The contract prints the chain's final fingerprint.
6. **The crew on screen.** The dashboard shows a live graph of facts linked to their clips, contradictions as red links, and each agent's lane of what it just did.

Parked for later: Gawah convening a mediation call by itself when a WhatsApp claim contradicts the facts; live translation between two languages (`gpt-realtime-translate` is on the key); reputation across deals.

## Build order

Phase 0, now:
- Shared types for facts, conflicts, changes, and agent activity, added to `app/contracts.py` without changing anything existing.

Phase 1, in parallel, once the Judge tuning and the flaky-test fix have landed:
- **Memory** (`app/memory`): Scribe, fact store with embeddings (`text-embedding-3-small`, brute-force search in numpy), the hash chain, contradiction check against confirmed facts, clip cutting from the recordings.
- **Gawah agent** (`app/mouth`): the transcript fed in as speaker-labelled text, the tools, the "being asked" fast path with its acknowledgement, clip playback.
- **Bridge** (`app/call`, `app/ears`): a second deal call on the same deal.
- **Dashboard** (`app/dashboard`): the fact graph, conflicts, clip buttons, agent lanes.

Phase 2:
- **Judge** (`app/brain`): ambiguity, and conflicts from Memory turned into moments to speak.
- **Clerk** (`app/contract`): amendments with history; the chain fingerprint.
- Whole-flow test extended; a dry run of the two-call demo; then the user's run.

## Risks

- **Latency stacks up.** Ears ~2 s, then Scribe, Memory, Gawah. Answers to direct questions must take the fast path: acknowledge at once, answer within about 4 s.
- **Cost.** Every line now also goes to the Scribe and to embeddings (cheap on credits). Sage2 stays the Judge's fast signal, within its budget.
- **More moving parts in a live call.** Keep the safety switch: `JUDGE_MODE=wrapup` turns everything back to the simple Judge.
- **Hallucinated facts.** The Scribe must quote the transcript line it took each fact from; a fact with no source line is dropped.
