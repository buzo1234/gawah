// The fact graph, worked out from the state alone: the six terms, each a node with its
// versions growing out of it as a lane, oldest on the left, the newest where facts land on
// the right. What two people said with the same value is one chip carrying both their
// colours: that is a term agreed by both. A payment sits in the lane of the term it counts
// towards. A claim that contradicts an agreed version is its own red chip, with a red edge
// back to the version it contradicts.

import { ITEMS, termView } from "./state.js";
import { owed, standing } from "./crew-state.js";
import { claims, itemOfConflict, itemOfFact, contradicting, valueParts } from "./board.js";

const IN_LANE = new Set(["term", "change", "payment", "work"]);
// Which member speaks for a chip: a claim, then the strongest standing, then replaced, then said.
const RANK = { claim: 6, confirmed: 5, agreed: 4, paid: 4, superseded: 3, disputed: 2, said: 1 };

const norm = (s) => s.toLowerCase().replace(/[\s.,;:]+/g, " ").trim();

export function laneFacts(state, key) {
  return state.factOrder.map((id) => state.facts[id]).filter((f) =>
    itemOfFact(state, f) === key && (IN_LANE.has(f.kind) ? f.kind !== "term" || f.value : f.value));
}

function chipStatus(f, claimed) {
  if (claimed.has(f.id)) return "claim";
  if (f.kind === "payment" && f.status !== "disputed" && f.status !== "superseded") return f.status === "said" ? "said" : "paid";
  return f.status;
}

// One lane: its chips, oldest first. Each chip: key (its first fact), ids, the value it
// shows and in full, its status, the people who said or agreed it, its newest seq, whether
// the term stands on it, and whether it came by voice note.
export function lane(state, key, claimed = claims(state)) {
  const stands = standing(state, key);
  const chips = [];
  const byValue = new Map();
  for (const f of laneFacts(state, key)) {
    const parts = valueParts(f);
    const status = chipStatus(f, claimed);
    const merge = f.kind === "payment" || f.kind === "work" || status === "claim" ? null : norm(parts.main);
    let chip = merge && byValue.get(merge);
    if (!chip) {
      chip = { key: f.id, ids: [], value: parts.main, full: [], status, people: [], seq: 0, stands: false, voice: false, kind: f.kind, lead: f.id };
      chips.push(chip);
      if (merge) byValue.set(merge, chip);
    }
    chip.ids.push(f.id);
    chip.full.push(parts.rest ? `${parts.main} ${parts.rest}` : parts.main);
    for (const r of [f.said_by, ...(f.agreed_by || []), ...(f.confirmed_by || [])]) {
      if ((r === "hirer" || r === "worker") && !chip.people.includes(r)) chip.people.push(r);
    }
    if (RANK[status] >= RANK[chip.status]) { chip.status = status; chip.lead = f.id; }
    chip.seq = Math.max(chip.seq, f.seq);
    chip.voice ||= f.source === "voice_note";
    chip.stands ||= stands?.id === f.id;
  }
  for (const c of chips) c.full = [...new Set(c.full)].join("\n");
  const edges = state.conflicts.filter((c) => itemOfConflict(state, c) === key).map((c) => {
    const claim = contradicting(state, c);
    const from = claim && chips.find((x) => x.ids.includes(claim.id));
    const to = chips.find((x) => x.ids.some((id) => c.factIds.includes(id)));
    return from && to && from !== to ? { id: c.id, from: from.key, to: to.key } : null;
  }).filter(Boolean);
  return { chips, edges };
}

// The whole graph: each term's node (its state, value and money) and its lane.
export function graph(state) {
  const claimed = claims(state);
  const money = owed(state);
  return ITEMS.map(([key, label]) => ({ key, label, view: termView(state, key), owed: money[key] || null, ...lane(state, key, claimed) }));
}

// Which chips a lane of `width` shows: every chip if they fit; else the oldest give way,
// gathered into one "+n earlier" chip, but never the version the term stands on, a claim,
// a version a claim contradicts, or the newest. widthOf(chip) is its drawn width.
export function visible(chips, edges, width, widthOf, gap, stub) {
  const total = (list) => list.reduce((sum, c) => sum + widthOf(c), 0) + gap * Math.max(0, list.length - 1);
  if (total(chips) <= width) return { shown: chips, hidden: [] };
  const keep = new Set([...edges.flatMap((e) => [e.from, e.to]), chips.at(-1).key, ...chips.filter((c) => c.stands).map((c) => c.key)]);
  const shown = [...chips], hidden = [];
  for (const c of chips) {
    if (total(shown) + stub + gap <= width) break;
    if (keep.has(c.key)) continue;
    shown.splice(shown.indexOf(c), 1);
    hidden.push(c);
  }
  return { shown, hidden };
}
