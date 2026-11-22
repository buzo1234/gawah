// Explore only: folds the offline dry run's events (events.json) up to ?at=<index> with the
// board's own fold, for three throwaway drawings of the fact graph.
import { apply, emptyState, ITEMS, nameOf } from "/app/dashboard/static/state.js";
import { standing } from "/app/dashboard/static/crew-state.js";

export { ITEMS, nameOf, standing };

export async function folded() {
  const events = await (await fetch("events.json")).json();
  const at = Number(new URLSearchParams(location.search).get("at") || events.length);
  const state = emptyState(events.find((e) => e.deal_id !== "no-deal").deal_id);
  for (const e of events.slice(0, at)) if (e.deal_id === state.dealId) apply(state, e);
  state.people.worker = { ...state.people.worker, name: state.people.worker?.name || "Ramesh" };
  return state;
}

export const money = (f) => {
  const v = f.value || "";
  const m = /^([\d,]+) rupees/.exec(v);
  if (f.kind === "payment") return `Paid ₹ ${Number(f.value_rupees).toLocaleString("en-IN")}`;
  return m && f.value_rupees ? `₹ ${Number(f.value_rupees).toLocaleString("en-IN")}` : v || f.text;
};

export function laneFacts(state, key) {
  return state.factOrder.map((id) => state.facts[id]).filter((f) =>
    (f.item === key || state.facts[f.counts_towards]?.item === key) && (f.value || f.kind === "payment"));
}

export const COLORS = { hirer: "#3d5a80", worker: "#8a5a1c", none: "#7a7b7f" };
