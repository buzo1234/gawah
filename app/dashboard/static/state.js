// The whole dashboard is a fold over the event log: apply(state, event) is the only
// place state changes, and it runs the same way for a reload and for a live event.

import { applyCrew, emptyCrew, settledBy } from "./crew-state.js";

export const NO_DEAL = "no-deal";

export const ITEMS = [
  ["work", "Work"],
  ["amount", "Amount"],
  ["advance", "Advance"],
  ["balance", "Balance"],
  ["dates", "Dates"],
  ["late_or_unfinished", "If late or unfinished"],
];

export const clock = (s) =>
  s == null ? "" : `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
export const nameOf = (state, role) =>
  state.people[role]?.name || { hirer: "Hirer", worker: "Worker", both: "both" }[role] || role;

// A deal-call line, by its call and its line number (line numbers start again each call).
export const lineAt = (state, lineNo, callNo = state.currentCall) => state.lines[`${callNo}:${lineNo}`];

// "Call 1 · 0:55": where something was said, as the page names it everywhere.
export const at = (callNo, start) =>
  callNo == null ? "" : `Call ${callNo}${start != null ? ` · ${clock(start)}` : ""}`;

export function emptyState(dealId) {
  return {
    ...emptyCrew(),
    dealId,
    people: {}, // role -> { name, phone }
    lines: {}, // "call:line" -> the deal-call line, for "when was it said"
    calls: [], // the deal calls seen, by call_no
    currentCall: 1,
    itemCall: {}, // item -> the call it was last changed on, to find its line
    earlier: {}, // item -> its last agreed value on an earlier call, with callNo
    items: ITEMS.map(([key]) => ({ key, state: "pending" })),
    terms: { hirer: {}, worker: {} }, // role -> item or "all" -> { ok, said }
  };
}

function people(state, list) {
  for (const p of list || []) {
    // As in the store: a later event fills in what is missing and never replaces it.
    const known = state.people[p.role] || {};
    state.people[p.role] = { name: known.name || p.name, phone: known.phone || p.phone };
  }
}

// Returns what the page has to redraw: { panels, moved, fact, conflict, changed }.
// moved: the checklist terms whose state or value just changed.
export function apply(state, e) {
  const change = { panels: [], moved: [] };
  const before = Object.fromEntries(ITEMS.map(([key]) => [key, termView(state, key)]));
  if (!applyCrew(state, e, change)) applyDeal(state, e, change);
  if (change.panels.includes("checklist")) {
    change.moved = ITEMS.map(([key]) => key).filter((key) => {
      const [a, b] = [before[key], termView(state, key)];
      return a.state !== b.state || a.value !== b.value;
    });
  }
  return change;
}

function applyDeal(state, e, change) {
  switch (e.name) {
    case "deal.requested":
      people(state, [e.requested_by, e.other]);
      change.panels = ["all"];
      break;

    case "call.started": {
      people(state, e.people);
      const no = e.call_no ?? 1;
      if (e.kind !== "callback" && !state.calls.includes(no)) {
        // The brain starts each call with a fresh checklist, so keep what was agreed so far.
        for (const i of state.items) if (i.state === "agreed") state.earlier[i.key] = { ...i, callNo: state.itemCall[i.key] ?? state.currentCall };
        state.calls.push(no);
        state.currentCall = no;
      } // else: a call-back, or the brain sent it again with a name learned on the call
      change.panels = ["all"];
      break;
    }

    case "transcript.line":
      if (e.kind !== "callback" && e.line_no != null) state.lines[`${e.call_no ?? 1}:${e.line_no}`] = e;
      break;

    case "checklist.updated": {
      const before = Object.fromEntries(state.items.map((i) => [i.key, i]));
      const now = Object.fromEntries(e.items.map((i) => [i.key, i]));
      state.items = ITEMS.map(([key]) => now[key] || before[key]);
      for (const key of e.changed || []) state.itemCall[key] = state.currentCall;
      change.panels = ["checklist"];
      break;
    }

    case "terms.confirmed":
      if (e.item) state.terms[e.person][e.item] = { ok: true, said: e.said };
      else state.terms[e.person] = { all: { ok: true, said: e.said } };
      change.panels = ["checklist"];
      break;

    case "terms.disputed":
      state.terms[e.person][e.item || "all"] = { ok: false, said: e.said };
      change.panels = ["checklist"];
      break;
  }
}

// ---------- one checklist term, as the page shows it ----------

const ROLES = ["hirer", "worker"];
const SETTLED = new Set(["agreed", "confirmed", "changed"]);
export const isSettled = (view) => SETTLED.has(view.state);

// { state, value, when, note, contradicted }. state is one of pending, agreed, confirmed,
// disputed, changed. A dispute outweighs everything; then a change both people agreed
// to; then both people confirming on their call-backs; then agreed, on this call or an
// earlier one.
export function termView(state, key) {
  const item = state.items.find((i) => i.key === key);
  const earlier = item.state !== "agreed" && state.earlier[key];
  const agreed = item.state === "agreed" ? item : earlier || null;
  const callNo = item.state === "agreed" ? state.itemCall[key] ?? state.currentCall : earlier?.callNo;
  const agreedAt = agreed ? at(callNo, agreed.line_no == null ? null : lineAt(state, agreed.line_no, callNo)?.start) : "";
  const said = (role) => state.terms[role][key] || state.terms[role].all;
  const view = { state: agreed ? "agreed" : "pending", value: agreed?.value || null, when: agreedAt, note: null, contradicted: null };

  const changes = state.changeOrder.map((id) => state.changes[id]).filter((c) => c.item === key && c.status !== "withdrawn");
  const held = changes.findLast((c) => c.status === "confirmed_both");
  const asked = changes.findLast((c) => c.status !== "confirmed_both" && (!held || c.seq > held.seq));
  const disputing = ROLES.filter((role) => said(role)?.ok === false);
  const confirming = ROLES.filter((role) => said(role)?.ok === true);

  if (disputing.length) {
    const quote = said(disputing[0]).said;
    return { ...view, state: "disputed", note: `${disputing.map((r) => nameOf(state, r)).join(" and ")} disputes this${quote ? `: “${quote}”` : ""}` };
  }
  if (held) {
    const fact = settledBy(state, held);
    view.state = "changed";
    view.value = fact?.value || held.new_value;
    view.when = fact?.source === "voice_note" ? "WhatsApp voice note" : at(fact?.call_no ?? held.callNo, fact?.start);
    view.note = agreed?.value && agreed.value !== view.value ? `Was ${agreed.value}` : null;
  } else if (confirming.length === ROLES.length && agreed) {
    view.state = "confirmed";
    view.note = "Both confirmed on their call-backs";
  } else if (confirming.length && agreed) {
    view.note = `${nameOf(state, confirming[0])} confirmed`;
  }
  if (asked) {
    const yes = asked.confirmed_by?.length ? ` · ${asked.confirmed_by.map((r) => nameOf(state, r)).join(" and ")} said yes` : "";
    view.note = `Change asked: ${asked.new_value}${yes}`;
  }
  // A contradiction on this call that came after the term's last change is still open.
  if (view.state === "agreed" || view.state === "pending") {
    const c = state.conflicts.findLast((x) => (x.callNo ?? state.currentCall) === state.currentCall
      && x.factIds.some((id) => state.facts[id]?.item === key));
    if (c) view.contradicted = at(c.callNo, c.lineNo == null ? null : lineAt(state, c.lineNo, c.callNo)?.start) || "On WhatsApp";
  }
  return view;
}
