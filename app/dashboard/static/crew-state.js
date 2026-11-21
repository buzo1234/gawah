// The crew's part of the fold: facts and their versions, contradictions, amendments, the
// agents' notes, and the witness chain. Called from apply() in state.js, so a reload
// folds these the same way the live page did.

export const AGENTS = [
  ["ears", "Ears", "hears each person"],
  ["scribe", "Scribe", "writes down facts"],
  ["memory", "Memory", "remembers and searches"],
  ["judge", "Judge", "decides what to ask"],
  ["floor", "Floor", "decides when to speak"],
  ["gawah", "Gawah", "the voice on the call"],
  ["clerk", "Clerk", "contract and changes"],
  ["sentinel", "Sentinel", "watches between calls"],
];
const NOTES_KEPT = 2; // what fits in a lane: the newest in full, one before it
const HASH = /^[0-9a-f]{64}$/;

export function emptyCrew() {
  return {
    facts: {}, // id -> the latest version, plus seq (when it was first seen)
    factOrder: [], // ids, first seen first
    seq: 0, // one counter for facts and changes, to tell what came after what
    conflicts: [], // each fact.conflict
    changes: {}, // change_id -> the latest step, plus seq and steps seen
    changeOrder: [],
    notes: Object.fromEntries(AGENTS.map(([key]) => [key, []])), // newest first
    chain: { links: 0, latest: null, problem: null, hashes: new Set() },
  };
}

// The fact a term stands on now: confirmed beats agreed; the latest of either.
export function standing(facts) {
  for (const status of ["confirmed", "agreed"]) {
    const found = facts.filter((f) => f.status === status);
    if (found.length) return found[found.length - 1];
  }
  return null;
}

// A change whose new value memory has since recorded as a fact is shown as that fact.
export function settledBy(state, change) {
  if (change.status !== "confirmed_both") return null;
  return state.factOrder.map((id) => state.facts[id])
    .find((f) => f.replaces === change.fact_id && f.seq > change.seq) || null;
}

function chainLink(chain, fact) {
  chain.links += 1;
  if (chain.problem) return;
  if (!fact.hash || !HASH.test(fact.hash)) chain.problem = `link ${chain.links} has no fingerprint`;
  else if (chain.hashes.has(fact.hash)) chain.problem = `link ${chain.links} repeats an earlier fingerprint`;
  else chain.hashes.add(fact.hash);
  chain.latest = fact.hash || chain.latest;
}

// Folds one crew event into state and fills in change. Returns false if it is not one.
export function applyCrew(state, e, change) {
  switch (e.name) {
    case "fact.recorded": {
      const known = state.facts[e.fact.id];
      if (!known) state.factOrder.push(e.fact.id);
      state.facts[e.fact.id] = { ...e.fact, seq: known ? known.seq : ++state.seq };
      chainLink(state.chain, e.fact);
      if (e.fact.status !== "superseded") change.fact = e.fact.id; // its successor keeps the highlight
      change.panels.push("graph");
      return true;
    }

    case "fact.conflict":
      state.conflicts.push({
        id: e.event_id, factIds: e.fact_ids, explanation: e.explanation, said: e.said,
        speaker: e.speaker, callNo: e.call_no, lineNo: e.line_no, confidence: e.confidence,
      });
      change.conflict = e.event_id;
      change.panels.push("graph", "flow");
      state.view = "graph";
      return true;

    case "fact.changed": {
      const known = state.changes[e.change_id];
      if (!known) state.changeOrder.push(e.change_id);
      state.changes[e.change_id] = {
        id: e.change_id, fact_id: e.fact_id, new_value: e.new_value, status: e.status,
        item: e.item || state.facts[e.fact_id]?.item || null, proposed_by: e.proposed_by || known?.proposed_by,
        confirmed_by: e.confirmed_by, said: e.said, seq: known ? known.seq : ++state.seq,
      };
      change.changed = e.change_id;
      change.panels.push("graph", "checklist");
      state.view = "graph";
      return true;
    }

    case "agent.note": {
      const lane = state.notes[e.agent];
      if (!lane) return true;
      lane.unshift({ id: e.event_id, text: e.text });
      lane.length = Math.min(lane.length, NOTES_KEPT);
      change.note = e.agent;
      change.panels.push("lanes");
      return true;
    }
  }
  return false;
}
