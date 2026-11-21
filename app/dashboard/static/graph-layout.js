// Where everything on the knowledge graph goes, worked out from the state alone (no DOM),
// so a reload lays it out exactly as the live page did, and Node can test it.
//
// The hirer stands on the left and the worker on the right. The six terms run down the
// middle: that column is the contract checklist. What each person said sits on their
// side of its term, with an edge back to them and one on to the term. The fact a term
// stands on sits in the term itself, tied to both people. Older versions step back into
// dots; a payment sits with the term it counts towards; a contradiction is a red edge
// from what was just said to what it contradicts. Its card sits in the band under the
// terms, where nothing else is drawn, with a red link up the gap beside the terms to
// what was just said. Labels too long for their place are cut at a word, in full on hover.

import { ITEMS, nameOf, termView } from "./state.js";
import { settledBy, standing } from "./crew-state.js";

export const G = {
  hubX: 508, hubW: 440, hubH: 96, top: 124, pitch: 112, cardTop: 808, cardH: 156, cardX: 188, cardW: 1080,
  people: { hirer: 96, worker: 1360 }, r: 24, fan: 20,
  zone: 280, gap: 40, pillH: 32, slots: 3, slotStep: 36, dotStep: 13, dotsPerColumn: 7,
  valueFont: "600 23px", valueW: 392,
};
export const SIDES = ["hirer", "worker"];
const SETTLED = new Set(["agreed", "confirmed"]);
const SOURCES = new Set(["call", "callback", "voice_note", "text", "screenshot", "record"]);

export const rupees = (n) => "₹" + Number(n).toLocaleString("en-IN");
export const hasClip = (f) => !!f && f.start != null && ["call", "callback", "voice_note"].includes(f.source);

// "15,000 rupees" reads as ₹15,000; anything with more words stays as said.
export function shortValue(f) {
  const v = f.value || f.text || "";
  return f.value_rupees != null && /^[\d,]+ rupees$/i.test(v.trim()) ? rupees(f.value_rupees) : v;
}

// Text width in a font ("600 23px"; 16px by default): Node has no fonts, so tests use this
// estimate; the page measures.
export const estimate = (text, font = "500 16px") => text.length * 8.4 * (Number(/(\d+)px/.exec(font)[1]) / 16) * (font.startsWith("600") ? 1.05 : 1);

// The text, or as many of its words as fit in `max` with an ellipsis, never part of a word
// (a first word too long for the place is cut where it must be).
export function cut(text, max, measure = estimate, font) {
  if (!text || measure(text, font) <= max) return text;
  const words = text.split(/\s+/);
  for (let n = words.length - 1; n > 0; n--) {
    const short = words.slice(0, n).join(" ").replace(/[\s;:,.\-–—(]+$/, "") + "…";
    if (measure(short, font) <= max) return short;
  }
  let short = text;
  while (short.length > 1 && measure(short + "…", font) > max) short = short.slice(0, -1);
  return short + "…";
}

const side = (role) => (role === "worker" ? "worker" : "hirer");

function labelOf(state, f) {
  if (f.kind === "payment") return `${f.status === "disputed" ? "Payment denied" : "Paid"} ${f.value_rupees != null ? rupees(f.value_rupees) : shortValue(f)}`;
  if (f.kind === "work") return `Work done${f.value ? `: ${f.value}` : ""}`;
  return shortValue(f);
}

function changeLabel(state, c) {
  const yes = c.confirmed_by?.length || 0;
  return c.status === "withdrawn" ? `Withdrawn: ${c.new_value}` : `Change: ${c.new_value}${yes ? ` · ${yes} of 2 yes` : ""}`;
}

// The open contradiction whose card is shown: the newest one on this call, while the fact
// it contradicts is still the one its term stands on. Older ones keep their red edge.
function openCard(state, stands) {
  const c = state.conflicts.findLast((x) => (x.callNo ?? state.currentCall) === state.currentCall);
  if (!c) return null;
  const item = c.factIds.map((id) => state.facts[id]?.item).find(Boolean);
  const row = ITEMS.findIndex(([key]) => key === item);
  return row >= 0 && c.factIds.includes(stands[item]?.id) ? { conflict: c, item, row, top: G.cardTop, x: G.cardX, w: G.cardW, h: G.cardH } : null;
}

// What just said a contradicted thing: the fact from the same line, by the same person,
// about the same term. Missing when the line gave memory nothing new to write down.
export function contradicting(state, c) {
  const item = c.factIds.map((id) => state.facts[id]?.item).find(Boolean);
  return state.factOrder.map((id) => state.facts[id]).findLast((f) =>
    c.lineNo != null && f.line_no === c.lineNo && (f.call_no ?? 1) === (c.callNo ?? 1)
    && f.item === item && (!c.speaker || f.said_by === c.speaker) && !c.factIds.includes(f.id)) || null;
}

export function layout(state, measure = estimate) {
  const views = Object.fromEntries(ITEMS.map(([key]) => [key, termView(state, key)]));
  const stands = Object.fromEntries(ITEMS.map(([key]) => [key, standing(state, key)]));
  const card = openCard(state, stands);

  // Rows: a term's hub, at the same place whatever happens, so nothing jumps when a card
  // opens; the card has the band under the last row to itself.
  const rows = {};
  ITEMS.forEach(([key], i) => {
    const top = G.top + i * G.pitch;
    rows[key] = { top, cy: top + G.hubH / 2, index: i, value: cut(views[key].value, G.valueW, measure, G.valueFont) };
  });
  const first = rows[ITEMS[0][0]].cy, last = rows[ITEMS.at(-1)[0]].cy;
  const people = Object.fromEntries(SIDES.map((role) => [role, { cx: G.people[role], cy: Math.round((first + last) / 2), name: nameOf(state, role) }]));

  // Everything to place, by the term and side it belongs to.
  const groups = {}; // "item:side" -> [{ id, seq, big, ... }]
  const loose = { hirer: [], worker: [] };
  const nodes = [];
  const standIds = new Set(Object.values(stands).filter(Boolean).map((f) => f.id));
  const hot = new Map(); // fact id -> conflict, for what said a contradicted thing
  for (const c of state.conflicts) {
    const f = contradicting(state, c);
    if (f) hot.set(f.id, c);
  }
  for (const id of state.factOrder) {
    const f = state.facts[id];
    if (standIds.has(id)) {
      nodes.push({ id: `fact-${id}`, place: "hub", item: f.item, fact: f, x: G.hubX + 20, y: rows[f.item].top + G.hubH - 20, w: 0, h: 0 });
      continue;
    }
    const target = (f.kind === "payment" || f.kind === "work") && state.facts[f.counts_towards];
    const item = target?.item || f.item;
    const entry = {
      id: `fact-${id}`, fact: f, seq: f.seq, item, side: side(f.kind === "payment" && !f.said_by ? "hirer" : f.said_by),
      big: f.kind !== "other", label: labelOf(state, f), hot: hot.get(id) || null, source: sourceOf(f),
      kind: f.kind === "payment" || f.kind === "work" ? "money" : f.kind === "change" ? "change" : "fact",
    };
    if (!rows[item]) loose[entry.side].push(entry);
    else (groups[`${item}:${entry.side}`] ||= []).push(entry);
  }
  for (const id of state.changeOrder) {
    const c = state.changes[id];
    if (settledBy(state, c)) continue;
    const item = c.item || state.facts[c.fact_id]?.item;
    if (!rows[item]) continue;
    const entry = { id: `change-${id}`, change: c, seq: c.seq, item, side: side(c.proposed_by), big: c.status !== "withdrawn", label: changeLabel(state, c), kind: "asked" };
    (groups[`${item}:${entry.side}`] ||= []).push(entry);
  }

  // A side of a term: its newest few as pills (hot ones and payments first in line to
  // stay), the rest as dots stepping back towards the person.
  for (const [key, list] of Object.entries(groups)) {
    const [item, who] = key.split(":");
    list.sort((a, b) => a.seq - b.seq);
    const keep = new Set(list.filter((e) => e.big).slice(-G.slots).map((e) => e.id));
    const pills = list.filter((e) => keep.has(e.id));
    const dots = list.filter((e) => !keep.has(e.id));
    const cy = rows[item].cy;
    pills.forEach((e, i) => {
      const proof = e.fact && !hasClip(e.fact) && /^https?:\/\//i.test(e.fact.media_url || "") ? measure("Proof") + 10 : 0;
      e.full = e.label;
      e.label = cut(e.label, G.zone - 54 - proof, measure);
      const w = Math.min(G.zone, Math.ceil(measure(e.label) + proof) + 54);
      const y = cy + (i - (pills.length - 1) / 2) * G.slotStep;
      const x = who === "hirer" ? G.hubX - G.gap - w : G.hubX + G.hubW + G.gap;
      nodes.push({ ...e, place: "pill", x, y, w, h: G.pillH });
    });
    dots.forEach((e, i) => {
      const col = Math.floor(i / G.dotsPerColumn), k = i % G.dotsPerColumn;
      const inCol = Math.min(G.dotsPerColumn, dots.length - col * G.dotsPerColumn);
      const edge = who === "hirer" ? G.hubX - G.gap - G.zone - 16 - col * 14 : G.hubX + G.hubW + G.gap + G.zone + 16 + col * 14;
      nodes.push({ ...e, place: "dot", x: edge, y: cy + (k - (inCol - 1) / 2) * G.dotStep, w: 10, h: 10 });
    });
  }
  // Details about no term in particular: small dots under the person who said them.
  for (const who of SIDES) {
    loose[who].sort((a, b) => a.seq - b.seq).forEach((e, i, all) => {
      const p = people[who];
      nodes.push({ ...e, place: "dot", x: p.cx + (i - (all.length - 1) / 2) * 16, y: p.cy + 104, w: 10, h: 10 });
    });
  }

  const byId = Object.fromEntries(nodes.map((n) => [n.id, n]));
  const edges = [];
  // Edges leave a person spread over the side of the circle that faces the terms, each at
  // the height of where it goes, so they fan out instead of meeting in one point.
  const span = { lo: rows[ITEMS[0][0]].cy, hi: rows[ITEMS.at(-1)[0]].cy };
  const port = (who, y = people[who].cy) => {
    const t = Math.max(-1, Math.min(1, (y - people[who].cy) / ((span.hi - span.lo) / 2 || 1)));
    const a = t * 0.6; // radians either side of level
    const r = G.r + 4, sx = who === "hirer" ? 1 : -1;
    return { x: people[who].cx + sx * r * Math.cos(a), y: people[who].cy + r * Math.sin(a), dx: sx * Math.cos(a), dy: Math.sin(a) };
  };
  const hubPort = (item, who) => ({ x: who === "hirer" ? G.hubX : G.hubX + G.hubW, y: rows[item].cy });
  const outer = (n) => ({ x: n.place === "dot" ? n.x : n.side === "hirer" ? n.x : n.x + n.w, y: n.y });
  const inner = (n) => ({ x: n.side === "hirer" ? n.x + n.w : n.x, y: n.y });
  const add = (key, a, b, cls) => edges.push({ key, cls, d: curve(a, b) });

  // An agreement ties both people to the term.
  for (const [item, f] of Object.entries(stands)) {
    if (!f) continue;
    const confirmed = f.status === "confirmed";
    for (const who of SIDES) add(`tie:${item}:${who}`, port(who, rows[item].cy), hubPort(item, who), `tie${confirmed ? " confirmed" : ""}`);
  }
  for (const n of nodes) {
    if (n.place === "hub") continue;
    const f = n.fact;
    const tone = n.hot ? " hot" : n.kind === "money" ? " money" : f && SETTLED.has(f.status) ? " agreed" : f?.status === "superseded" ? " old" : n.kind === "asked" ? " asked" : "";
    add(`said:${n.id}`, port(n.side, n.y), outer(n), `said${tone}${n.place === "dot" ? " faint" : ""}`);
    if (n.place === "pill" && rows[n.item]) add(`of:${n.id}`, inner(n), hubPort(n.item, n.side), `of${tone}`);
  }
  for (const c of state.conflicts) {
    const from = [...hot].find(([, x]) => x === c)?.[0];
    for (const id of c.factIds) {
      const target = byId[`fact-${id}`];
      if (!target) continue;
      const a = from && byId[`fact-${from}`] ? inner(byId[`fact-${from}`]) : c.speaker ? port(c.speaker, rows[target.item]?.cy) : null;
      if (!a) continue;
      const b = target.place === "hub" ? hubPort(target.item, byId[`fact-${from}`]?.side || side(c.speaker)) : outer(target);
      add(`conflict:${c.id}:${id}`, a, b, "conflict");
    }
  }

  // The open card's link: up the gap beside the terms on the speaker's side, then in to
  // what was just said (or to the term, when the line gave memory nothing new).
  if (card) {
    const from = [...hot].find(([, x]) => x === card.conflict)?.[0];
    const said = from && byId[`fact-${from}`];
    const who = said?.side || side(card.conflict.speaker);
    const gx = who === "hirer" ? G.hubX - G.gap / 2 : G.hubX + G.hubW + G.gap / 2;
    const end = said ? inner(said) : hubPort(card.item, who);
    const toward = Math.sign(end.x - gx) * Math.min(12, Math.abs(end.x - gx));
    const r = (n) => Math.round(n * 10) / 10;
    edges.push({ key: `card:${card.conflict.id}`, cls: "conflict card-link", d: `M${r(gx)},${card.top} L${r(gx)},${r(end.y + 12)} Q${r(gx)},${r(end.y)} ${r(gx + toward)},${r(end.y)} L${r(end.x)},${r(end.y)}` });
  }

  const counts = { facts: state.factOrder.length, conflicts: state.conflicts.length };
  return { rows, people, nodes, edges, card, views, stands, counts };
}

// A bezier that leaves and arrives level, so edges fan out of a person and into a term.
// One that leaves a person (a port with a direction) leaves along that direction, like a
// spoke, so the edges spread out of the circle instead of running together.
export function curve(a, b) {
  const mx = (a.x + b.x) / 2;
  const r = (n) => Math.round(n * 10) / 10;
  const reach = Math.abs(b.x - a.x) / 2;
  const c1 = a.dx == null ? { x: mx, y: a.y } : { x: a.x + a.dx * reach, y: a.y + a.dy * reach };
  return `M${r(a.x)},${r(a.y)} C${r(c1.x)},${r(c1.y)} ${r(mx)},${r(b.y)} ${r(b.x)},${r(b.y)}`;
}

export const sourceOf = (f) => (f && SOURCES.has(f.source) ? f.source : "call");
