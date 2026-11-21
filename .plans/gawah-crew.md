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

## The fact layer: RAG, knowledge graph, or neither?

Decided 21 November, after the user asked. Worked through the scenarios Gawah must handle, then chose the simplest store that serves all of them.

### Scenarios

| # | Scenario | What it really needs | Plain RAG | Full knowledge graph |
|---|---|---|---|---|
| 1 | "Gawah, advance kitna tay hua tha?" | The *current agreed* value of one term, with who said it and the clip | Weak: returns every mention, including offers that were turned down | Works, but overkill |
| 2 | Call 2: "aapne 25 bola tha" | The term's history: 25 was Ramesh's offer, 22 was agreed by both. Gawah says exactly that | Fails: cannot tell an offer from an agreement | Works if versions are kept |
| 3 | "Balcony ke 2,000 extra" | A new version of a term that replaces the old one, confirmed by both, with the history kept | Fails | Works |
| 4 | "3000 cash diya" | Which term the payment counts towards, and what is still owed: arithmetic | Fails: a model cannot be trusted to add up retrieved snippets | Works if values are numbers |
| 5 | "Paint ke baare mein kya baat hui thi?" | Open-ended recall of details that are not one of the six terms (brand, who buys it) | Works well | Weak: needs every detail extracted into the graph first |
| 6 | "Maine screenshot bheja tha na?" | Records and their evidence, linked to the term | Partly | Works |
| 7 | Work marked done three days ago, no balance paid | A schedule: what is due, and when | Fails | Needs rules on top |
| 8 | "Kaam Monday tak" | Interpretation of one line, not retrieval | n/a | n/a |
| 9 | The same worker across many deals | People as entities across deals | Weak | Works |

### Decision: a small versioned fact graph, with vector search on the side

Not plain RAG: retrieval returns mentions, not truth. It cannot tell an offer from an agreement, cannot follow a term's history, and cannot add up payments. Those are scenarios 1 to 4, the core of the product.

Not a full knowledge graph: a deal has tens of facts, not thousands; the queries are one or two hops; extracting every detail of noisy Hinglish speech into a general ontology would produce errors; and a graph database is another service to run. It only pays off across deals (scenario 9), which is parked.

What we build, inside SQLite, no new service:
- **The event log stays the source of truth.** Everything else is built from it and can be rebuilt. The hash chain runs over it.
- **Facts** are typed and versioned: the term they belong to, the value in words and normalised (whole rupees; a date when it can be pinned down), status (said, agreed, confirmed, disputed, superseded), who said and who confirmed it, when it became true and when it was replaced, and the evidence (transcript line and seconds for the clip, or a record and its screenshot).
- **Links between facts**, few and fixed: replaces (a term's history), counts towards (a payment and the term it settles), contradicts (from `fact.conflict`), evidenced by (line, clip, screenshot). This is the "graph": a handful of edge types, followed in plain SQL.
- **Vectors on the side**: embeddings (`text-embedding-3-small`) for every fact and every transcript line, searched by brute force in numpy. Used for open-ended recall (scenario 5) and for finding which confirmed fact a new claim might contradict.

How Gawah's tools use it:
- `get_term(item)`: structured. Current agreed or confirmed value, its history, and the clip. Answers scenarios 1 and 2.
- `owed()`: computed in code from the terms and payments. Scenario 4.
- `search_facts(query)`: hybrid. Semantic search over facts and lines, ranked so confirmed beats agreed beats said, each result with who, when, and the clip. Scenario 5.
- A contradiction check on every new claim: first in code (same term, different normalised value from the confirmed one); only if that cannot decide, a small model judges the claim against the nearest confirmed facts, and must cite them.

Inspiration: temporal knowledge graphs used as agent memory, where a fact carries the time it was valid and a newer fact invalidates an older one (for example Zep's Graphiti). We take the idea, not the infrastructure. Not evaluated today.

### Acceptance tests for the memory stream

Each scenario above (1 to 7) becomes a test on fakes, written before the code. Scenario 2 is the showpiece: on a second call, "aapne 25 bola tha" must produce "25 was your offer; 22 was agreed by both, on 21 November", with the clip.

## Gawah's tools

The voice agent never changes the deal by itself. It acts only through tools:

- `get_term(item)` - the current agreed or confirmed value of one term, its history, and the clip.
- `owed()` - what has been paid towards each term and what is still owed, computed in code.
- `search_facts(query)` - semantic search across the deal's facts and transcript lines. Returns facts with who said them, when, and whether they were confirmed.
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
