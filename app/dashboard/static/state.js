// The whole dashboard is a fold over the event log: apply(state, event) is the only
// place state changes, and it runs the same way for a reload and for a live event.

export const NO_DEAL = "no-deal";

export const ITEMS = [
  ["work", "Work"],
  ["amount", "Amount"],
  ["advance", "Advance"],
  ["balance", "Balance"],
  ["dates", "Dates"],
  ["late_or_unfinished", "If late or unfinished"],
];

export const otherRole = (role) => (role === "hirer" ? "worker" : "hirer");
export const clock = (s) =>
  s == null ? "" : `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
export const nameOf = (state, role) =>
  state.people[role]?.name || { hirer: "Hirer", worker: "Worker", both: "both" }[role] || role;

export function emptyState(dealId) {
  return {
    dealId,
    people: {}, // role -> { name, phone }
    status: dealId ? "requested" : "none",
    callback: null, // the role on a call-back right now
    duration: null,
    flow: [], // the conversation: lines, Gawah's lines, and call marks
    lines: {}, // line_no -> the deal-call line, for "when was it said"
    items: ITEMS.map(([key]) => ({ key, state: "pending" })),
    decisions: [], // each judge.speak, with what was then said
    records: [], // { record, askedOf, answer, timedOut }
    terms: { hirer: {}, worker: {} }, // role -> item or "all" -> { ok, said }
    contract: null,
  };
}

function people(state, list) {
  for (const p of list || []) {
    // As in the store: a later event fills in what is missing and never replaces it.
    const known = state.people[p.role] || {};
    state.people[p.role] = { name: known.name || p.name, phone: known.phone || p.phone };
  }
}

function record(state, r) {
  let entry = state.records.find((x) => x.record.id === r.id);
  if (!entry) {
    entry = { record: r, askedOf: null, answer: null, timedOut: false };
    state.records.push(entry);
  }
  entry.record = r;
  if (r.confirmed != null) entry.answer = r.confirmed;
  return entry;
}

// Returns what the page has to redraw: { panels, flow, agreed, decision }.
export function apply(state, e) {
  const change = { panels: [], flow: null, agreed: [], decision: null };
  const say = (entry) => {
    state.flow.push(entry);
    change.flow = entry;
  };

  switch (e.name) {
    case "deal.requested":
      people(state, [e.requested_by, e.other]);
      change.panels = ["all"];
      break;

    case "call.started":
      people(state, e.people);
      if (e.kind === "callback") {
        state.callback = e.people?.[0]?.role || null;
        say({ type: "mark", text: `Call-back with ${e.people?.[0] ? nameOf(state, e.people[0].role) : "one person"}: confirming the terms alone` });
      } else {
        state.status = "in_call";
        say({ type: "mark", text: "Call started" });
      }
      change.panels = ["all"];
      break;

    case "call.ended":
      if (e.kind === "callback") {
        state.callback = null;
        say({ type: "mark", text: "Call-back ended" });
      } else {
        if (state.status === "in_call" || state.status === "requested") state.status = "call_ended";
        state.duration = e.duration;
        say({ type: "mark", text: `Call ended${e.duration != null ? ` after ${clock(e.duration)}` : ""}` });
      }
      change.panels = ["header"];
      break;

    case "transcript.line":
      if (e.kind !== "callback" && e.line_no != null) state.lines[e.line_no] = e;
      say({ type: "line", speaker: e.speaker, text: e.text, start: e.start, lineNo: e.line_no });
      break;

    case "checklist.updated": {
      const before = Object.fromEntries(state.items.map((i) => [i.key, i]));
      const now = Object.fromEntries(e.items.map((i) => [i.key, i]));
      state.items = ITEMS.map(([key]) => now[key] || before[key]);
      change.agreed = state.items
        .filter((i) => i.state === "agreed" && (before[i.key].state !== "agreed" || before[i.key].value !== i.value))
        .map((i) => i.key);
      change.panels = ["checklist"];
      break;
    }

    case "judge.speak":
      state.decisions.push({
        id: e.event_id, reason: e.reason, item: e.item, to: e.to,
        instruction: e.instruction, afterLine: e.after_line, spoken: null, interrupted: false,
      });
      change.decision = e.event_id;
      change.panels = ["why"];
      break;

    case "judge.spoke": {
      const decision =
        state.decisions.find((d) => d.id === e.speak_id) ||
        (e.speak_id ? null : state.decisions.findLast((d) => d.spoken == null));
      if (decision) {
        decision.spoken = e.text;
        decision.interrupted = e.interrupted;
        change.panels = ["why"];
      }
      say({
        type: "gawah", text: e.text, start: e.start, interrupted: e.interrupted,
        reason: e.reason || decision?.reason, item: e.item || decision?.item,
      });
      break;
    }

    case "terms.confirmed":
      if (e.item) state.terms[e.person][e.item] = { ok: true, said: e.said };
      else state.terms[e.person] = { all: { ok: true, said: e.said } };
      change.panels = ["header", "checklist"];
      break;

    case "terms.disputed":
      state.terms[e.person][e.item || "all"] = { ok: false, said: e.said };
      change.panels = ["header", "checklist"];
      break;

    case "contract.ready":
      state.status = "contract_ready";
      state.contract = { url: e.pdf_url, text: e.text };
      change.panels = ["header"];
      break;

    case "record.received":
      record(state, e.record);
      change.panels = ["ledger"];
      break;

    case "record.confirm_requested": {
      const entry = e.record ? record(state, e.record) : state.records.find((x) => x.record.id === e.record_id);
      if (entry) entry.askedOf = e.confirm_by;
      change.panels = ["ledger"];
      break;
    }

    case "record.confirmed": {
      const entry = e.record ? record(state, e.record) : state.records.find((x) => x.record.id === e.record_id);
      if (entry) {
        entry.answer = e.confirmed;
        entry.askedOf = e.confirmed_by;
      }
      change.panels = ["ledger"];
      break;
    }

    case "reply.timeout": {
      const entry = state.records.find((x) => x.record.id === e.record_id);
      if (entry) entry.timedOut = true;
      change.panels = ["ledger"];
      break;
    }
  }
  return change;
}
