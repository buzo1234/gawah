// Memory's part of the fold: facts and their versions, contradictions, amendments, and
// how many links the witness chain has. Called from apply() in state.js, so a reload
// folds these the same way the live page did. The chain itself is checked by memory
// (/memory/chain/<deal>, see chain.js), not here.

const NOT_COUNTED = new Set(["disputed", "superseded"]);

export function emptyCrew() {
  return {
    facts: {}, // id -> the latest version, plus seq (when it was first seen), ts (the event's time then) and last (its newest link)
    factOrder: [], // ids, first seen first
    seq: 0, // one counter for facts and changes, to tell what came after what
    conflicts: [], // each fact.conflict
    changes: {}, // change_id -> the latest step, plus seq and steps seen
    changeOrder: [],
    chain: { links: 0, list: [] }, // one link per fact.recorded, each with where it came from
    chainCheck: null, // memory's answer from /memory/chain/<deal>, set by chain.js
  };
}

// The fact a term stands on now, as memory's current() picks it: only term facts;
// confirmed beats agreed; of those, the one with the newest version.
export function standing(state, item) {
  const terms = state.factOrder.map((id) => state.facts[id]).filter((f) => f.item === item && f.kind === "term");
  for (const status of ["confirmed", "agreed"]) {
    const found = terms.filter((f) => f.status === status);
    if (found.length) return found.reduce((a, b) => (b.last > a.last ? b : a));
  }
  return null;
}

// What is paid and owed on each money term, by memory's own rules (Memory.owed): every
// payment counts towards the amount; towards the advance, those that count towards an
// advance; towards the balance, those that count towards the balance or the amount. The
// balance is the agreed balance figure, or else the amount less the advance.
export function owed(state) {
  const figure = (item) => standing(state, item)?.value_rupees ?? null;
  const payments = state.factOrder.map((id) => state.facts[id])
    .filter((f) => f.kind === "payment" && !NOT_COUNTED.has(f.status) && f.value_rupees);
  const towards = (p) => state.facts[p.counts_towards]?.item || p.item || "amount";
  const [amount, advance] = [figure("amount"), figure("advance")];
  let balance = figure("balance");
  if (balance == null && amount != null && advance != null) balance = amount - advance;
  const row = (item, agreed, counted) => {
    const paid = counted.reduce((sum, p) => sum + p.value_rupees, 0);
    return { item, agreed, paid, owed: agreed == null ? null : agreed - paid, payments: counted.map((p) => p.id) };
  };
  return {
    amount: row("amount", amount, payments),
    advance: row("advance", advance, payments.filter((p) => towards(p) === "advance")),
    balance: row("balance", balance, payments.filter((p) => ["balance", "amount"].includes(towards(p)))),
  };
}

// A change whose new value memory has since recorded as a fact is shown as that fact.
export function settledBy(state, change) {
  if (change.status !== "confirmed_both") return null;
  return state.factOrder.map((id) => state.facts[id])
    .find((f) => f.replaces === change.fact_id && f.seq > change.seq) || null;
}

// The stretch of the deal a link was sealed in, for the timeline's moments. A fact
// from a call takes the call going on when it is sealed (a call-1 term confirmed on call 2
// is sealed on call 2), or its own call if it lands just after the call ends; anything
// from WhatsApp goes by the day.
export function sealedIn(fact, live, ts) {
  if (fact.source === "call" || fact.source === "callback") {
    if (live) return live.kind === "callback" ? "Call-backs" : `Call ${live.callNo}`;
    return fact.source === "callback" ? "Call-backs" : `Call ${fact.call_no ?? 1}`;
  }
  const day = ts ? new Date(ts) : null;
  return day && !isNaN(day) ? `WhatsApp · ${day.toLocaleDateString("en-GB", { day: "numeric", month: "short" })}` : "WhatsApp";
}

// Folds one crew event into state and fills in change. Returns false if it is not one.
export function applyCrew(state, e, change) {
  switch (e.name) {
    case "fact.recorded": {
      const known = state.facts[e.fact.id];
      if (!known) state.factOrder.push(e.fact.id);
      state.facts[e.fact.id] = { ...e.fact, seq: known ? known.seq : ++state.seq, ts: known ? known.ts : e.ts, last: ++state.chain.links };
      state.chain.list.push({ factId: e.fact.id, status: e.fact.status, where: sealedIn(e.fact, state.live, e.ts), ts: e.ts, source: e.fact.source, since: state.live?.since ?? null });
      // Memory sends a replacement first and the old version again as superseded after
      // it: the highlight stays on the replacement.
      change.fact = e.fact.status === "superseded"
        ? state.factOrder.findLast((id) => state.facts[id].replaces === e.fact.id)
        : e.fact.id;
      change.panels.push("graph", "chain", "checklist");
      return true;
    }

    case "fact.conflict":
      state.conflicts.push({
        id: e.event_id, factIds: e.fact_ids, explanation: e.explanation, said: e.said,
        speaker: e.speaker, callNo: e.call_no, lineNo: e.line_no, confidence: e.confidence, seq: ++state.seq, ts: e.ts,
      });
      change.conflict = e.event_id;
      change.panels.push("graph", "checklist");
      return true;

    case "fact.changed": {
      const known = state.changes[e.change_id];
      if (!known) state.changeOrder.push(e.change_id);
      state.changes[e.change_id] = {
        id: e.change_id, fact_id: e.fact_id, new_value: e.new_value, status: e.status,
        item: e.item || state.facts[e.fact_id]?.item || null, proposed_by: e.proposed_by || known?.proposed_by,
        confirmed_by: e.confirmed_by, said: e.said, seq: known ? known.seq : ++state.seq,
        callNo: known ? known.callNo : state.currentCall,
      };
      change.changed = e.change_id;
      change.panels.push("graph", "checklist");
      return true;
    }
  }
  return false;
}
