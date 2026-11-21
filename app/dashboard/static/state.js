// The whole dashboard is a fold over the event log: apply(state, event) is the only
// place state changes, and it runs the same way for a reload and for a live event.

import { applyCrew, emptyCrew } from "./crew-state.js";

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

// A deal-call line, by its call and its line number (line numbers start again each call).
export const lineAt = (state, lineNo, callNo = state.currentCall) => state.lines[`${callNo}:${lineNo}`];

export function emptyState(dealId) {
  return {
    ...emptyCrew(),
    dealId,
    people: {}, // role -> { name, phone }
    status: dealId ? "requested" : "none",
    callback: null, // the role on a call-back right now
    flow: [], // the conversation: lines, Gawah's lines, and call marks
    lines: {}, // "call:line" -> the deal-call line, for "when was it said"
    calls: {}, // call_no -> { ended, duration }
    currentCall: 1,
    itemCall: {}, // item -> the call it was last changed on, to find its line
    earlier: {}, // item -> its last agreed value on an earlier call, with callNo
    view: "phones", // the right-hand column: "phones", or "graph" (the crew) once a call starts
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

const onCall = (state) => state.status === "in_call" || state.callback != null;

// Returns what the page has to redraw: { panels, flow, agreed, decision, fact, ... }.
export function apply(state, e) {
  const change = { panels: [], flow: null, agreed: [], decision: null };
  if (applyCrew(state, e, change)) return change;
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
      } else if (!state.calls[e.call_no ?? 1]) {
        const no = e.call_no ?? 1;
        // The brain starts each call with a fresh checklist, so keep what was agreed so far.
        for (const i of state.items) if (i.state === "agreed") state.earlier[i.key] = { ...i, callNo: state.itemCall[i.key] ?? state.currentCall };
        state.calls[no] = { ended: false, duration: null };
        state.currentCall = no;
        state.status = "in_call";
        state.view = "graph";
        say({ type: "call", callNo: no, text: no === 1 ? "The deal call" : "A follow-up call on the same deal" });
      } // else: the brain sent it again with a name learned on the call
      change.panels = ["all"];
      break;

    case "call.ended":
      if (e.kind === "callback") {
        state.callback = null;
        say({ type: "mark", text: "Call-back ended" });
      } else {
        const no = e.call_no ?? 1;
        if (state.calls[no]) Object.assign(state.calls[no], { ended: true, duration: e.duration });
        if (state.status === "in_call" || state.status === "requested") state.status = state.contract ? "contract_ready" : "call_ended";
        say({ type: "mark", text: `Call ${no} ended${e.duration != null ? ` after ${clock(e.duration)}` : ""}` });
      }
      change.panels = ["header"];
      break;

    case "transcript.line":
      if (e.kind !== "callback" && e.line_no != null) state.lines[`${e.call_no ?? 1}:${e.line_no}`] = e;
      say({
        type: "line", speaker: e.speaker, text: e.text, start: e.start, lineNo: e.line_no,
        callNo: e.kind === "callback" ? null : e.call_no ?? 1,
      });
      break;

    case "checklist.updated": {
      const before = Object.fromEntries(state.items.map((i) => [i.key, i]));
      const now = Object.fromEntries(e.items.map((i) => [i.key, i]));
      state.items = ITEMS.map(([key]) => now[key] || before[key]);
      for (const key of e.changed || []) state.itemCall[key] = state.currentCall;
      change.agreed = state.items
        .filter((i) => i.state === "agreed" && (before[i.key].state !== "agreed" || before[i.key].value !== i.value))
        .map((i) => i.key);
      change.panels = ["checklist"];
      break;
    }

    case "judge.speak":
      state.decisions.push({
        id: e.event_id, reason: e.reason, item: e.item, to: e.to,
        instruction: e.instruction, afterLine: e.after_line, callNo: state.currentCall, spoken: null, interrupted: false,
      });
      change.decision = e.event_id;
      change.panels = ["why"];
      break;

    case "judge.spoke": {
      const decision =
        state.decisions.find((d) => d.id === e.speak_id) ||
        (e.speak_id ? null : state.decisions.findLast((d) => d.spoken == null));
      const dropped = !e.text && e.start == null;  // the moment passed and nothing was said
      if (decision) {
        decision.spoken = dropped ? null : e.text;
        decision.dropped = dropped;
        decision.interrupted = e.interrupted;
        change.panels = ["why"];
      }
      if (dropped) break;
      say({
        type: "gawah", text: e.text, start: e.start, interrupted: e.interrupted,
        reason: e.reason || decision?.reason, item: e.item || decision?.item, clip: e.clip_fact_id,
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
      if (state.status !== "in_call") state.status = "contract_ready";
      state.contract = { url: e.pdf_url, text: e.text };
      change.panels = ["header"];
      break;

    case "record.received":
      record(state, e.record);
      if (!onCall(state)) state.view = "phones";
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
