// What the board shows, worked out from the state alone (no DOM), so a reload shows
// exactly what the live page did, and Node can test it.
//
// The fact layer, as the deck's slide 9: for one term at a time, the fact it stands on
// (or the newest thing said about it) with its version, the version before it dashed
// and "replaced by", and a claim that contradicts it in red. The witness chain under
// them is the same versions, each a link. The term shown is the one touched last, or the
// one a person picked, or the one whose link broke.

import { ITEMS, at, clock, lineAt, nameOf, termView } from "./state.js";
import { standing } from "./crew-state.js";

export const LABEL = Object.fromEntries(ITEMS);
const SOURCES = new Set(["call", "callback", "voice_note", "text", "screenshot", "record"]);

export const rupees = (n) => "₹ " + Number(n).toLocaleString("en-IN");
export const hasClip = (f) => !!f && f.start != null && ["call", "callback", "voice_note"].includes(f.source);
export const sourceOf = (f) => (f && SOURCES.has(f.source) ? f.source : "call");

// Text width in a font ("600 30px"; 16px by default): Node has no fonts, so tests use this
// estimate; the page measures.
export const estimate = (text, font = "500 16px") => text.length * 8.4 * (Number(/(\d+)px/.exec(font)[1]) / 16) * (font.startsWith("6") || font.startsWith("7") ? 1.05 : 1);

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

// "15,000 rupees" reads as ₹ 15,000; anything with more words stays as said.
export function valueOf(f) {
  if (!f) return "";
  const v = f.value || f.text || "";
  if (f.kind === "payment") return `Paid ${f.value_rupees != null ? rupees(f.value_rupees) : v}`;
  if (f.kind === "work") return `Work done${f.value ? `: ${f.value}` : ""}`;
  return f.value_rupees != null && /^[\d,]+ rupees$/i.test(v.trim()) ? rupees(f.value_rupees) : v;
}

// Where it was said, as the page names it: "Call 1 · 0:55", "WhatsApp voice note".
export function whereOf(f) {
  if (!f) return "";
  if (f.source === "voice_note") return "WhatsApp voice note";
  if (f.source === "screenshot") return "Screenshot on WhatsApp";
  if (f.source === "text" || f.source === "record") return "WhatsApp";
  if (f.source === "callback") return "Call-back";
  return at(f.call_no ?? 1, f.start) || "Call";
}

const seconds = (a, b) => {
  const s = (Date.parse(b) - Date.parse(a)) / 1000;
  return Number.isFinite(s) && s >= 0 && s < 60 ? Math.round(s * 10) / 10 : null;
};

// From the line reaching the board to the fact (or the contradiction) memory wrote from
// it, by the two events' own times. Null when there is no line (WhatsApp) or no times.
export const factLatency = (state, f) => {
  const line = f && f.line_no != null && f.source === "call" ? lineAt(state, f.line_no, f.call_no ?? 1) : null;
  return line ? seconds(line.ts, f.ts) : null;
};
export const took = (s) => (s == null ? "" : `${s < 0.1 ? "<0.1" : s.toFixed(1)} s`);
export const conflictLatency = (state, c) => {
  const line = c.lineNo != null ? lineAt(state, c.lineNo, c.callNo ?? 1) : null;
  return line ? seconds(line.ts, c.ts) : null;
};

// What just said a contradicted thing: the fact from the same line, by the same person,
// about the same term. Missing when the line gave memory nothing new to write down.
export function contradicting(state, c) {
  const item = c.factIds.map((id) => state.facts[id]?.item).find(Boolean);
  return state.factOrder.map((id) => state.facts[id]).findLast((f) =>
    c.lineNo != null && f.line_no === c.lineNo && (f.call_no ?? 1) === (c.callNo ?? 1)
    && f.item === item && (!c.speaker || f.said_by === c.speaker) && !c.factIds.includes(f.id)) || null;
}

const itemOfConflict = (state, c) => c.factIds.map((id) => state.facts[id]?.item).find(Boolean) || null;
const itemOfFact = (state, f) => state.facts[f.counts_towards]?.item || f.item || null;

// The term to show: the one picked, else the one whose chain link broke, else the one
// with a contradiction open (it stays in view until the term changes or the call ends),
// else the one touched last (a fact, a change, or a contradiction), else the first.
export function focusItem(state, picked = null) {
  if (picked) return picked;
  const broken = state.chainCheck && !state.chainCheck.error && !state.chainCheck.verified && state.chainCheck.first_broken;
  const brokenItem = broken && state.facts[broken.fact_id]?.item;
  if (brokenItem) return brokenItem;
  const open = openConflict(state);
  if (open) return open.item;
  const touched = [
    ...state.factOrder.map((id) => state.facts[id]).map((f) => ({ seq: f.seq, item: itemOfFact(state, f) })),
    ...state.changeOrder.map((id) => state.changes[id]).map((c) => ({ seq: c.seq, item: c.item })),
    ...state.conflicts.map((c) => ({ seq: c.seq, item: itemOfConflict(state, c) })),
  ].filter((t) => t.item && LABEL[t.item]);
  return touched.reduce((a, b) => (b.seq > a.seq ? b : a), { seq: -1, item: ITEMS[0][0] }).item;
}

// The open contradiction, shown as the deck's slide 7: the newest one on this call, while
// the fact it contradicts is still the one its term stands on.
export function openConflict(state) {
  const c = state.conflicts.findLast((x) => (x.callNo ?? state.currentCall) === state.currentCall);
  if (!c) return null;
  const item = itemOfConflict(state, c);
  const agreed = item && standing(state, item);
  if (!agreed || !c.factIds.includes(agreed.id)) return null;
  const claim = contradicting(state, c);
  return { conflict: c, item, agreed, claim, latency: conflictLatency(state, c) };
}

// Who said it, and who agreed: "Sunita and Ramesh", or one name.
export function saidBy(state, f) {
  const roles = [...new Set([f.said_by, ...(f.agreed_by || []), ...(f.confirmed_by || [])].filter((r) => r === "hirer" || r === "worker"))];
  return roles.length === 2 ? `${nameOf(state, "hirer")} and ${nameOf(state, "worker")}` : roles.map((r) => nameOf(state, r)).join("") || "";
}

export function confirmedBy(state, f, view) {
  const both = (f.confirmed_by || []).length >= 2;
  if (view?.state === "changed") return f.source === "voice_note" ? "Both, by voice note" : "Both, by voice";
  if (both || view?.state === "confirmed") return f.source === "callback" || view?.state === "confirmed" ? "Both, on call-backs" : "Both, by voice";
  if ((f.confirmed_by || []).length === 1) return `${nameOf(state, f.confirmed_by[0])} only`;
  if (f.status === "agreed") return "Not yet";
  return "Not yet";
}

const PILL = { said: "Said", agreed: "Agreed", confirmed: "Confirmed", disputed: "Disputed", superseded: "Replaced" };

// The fact layer for one term: { item, current, version, previous, earlier, claim, chain }.
export function factLayer(state, item) {
  const terms = state.factOrder.map((id) => state.facts[id]).filter((f) => f.item === item && (f.kind === "term" || f.kind === "change"));
  const view = termView(state, item);
  const stands = standing(state, item);
  const current = stands || terms.findLast((f) => f.status !== "superseded" && f.status !== "disputed") || terms.at(-1) || null;
  if (!current) return { item, label: LABEL[item], view, current: null, previous: null, claim: null, chain: [] };
  const version = terms.indexOf(current) + 1;
  const conflict = state.conflicts.findLast((c) => c.factIds.includes(current.id));
  const claimFact = conflict && contradicting(state, conflict);
  const claim = conflict && {
    conflict, fact: claimFact, version: claimFact ? terms.indexOf(claimFact) + 1 : null,
    value: claimFact ? valueOf(claimFact) : conflict.said ? `“${conflict.said}”` : "",
    who: nameOf(state, claimFact?.said_by || conflict.speaker),
    where: conflict.callNo != null ? `call ${conflict.callNo}` : "WhatsApp",
  };
  const before = terms.filter((f) => f.seq < current.seq && f.id !== claimFact?.id);
  const prev = current.replaces ? state.facts[current.replaces] : before.at(-1);
  const previous = prev && {
    fact: prev, version: terms.indexOf(prev) + 1, value: valueOf(prev), who: nameOf(state, prev.said_by),
    note: prev.status === "superseded" ? "Replaced" : terms.indexOf(prev) === 0 ? "First offer" : "Offer",
  };
  const pill = view.state === "changed" && current === stands ? "Changed" : PILL[current.status] || current.status;
  const chain = [
    previous && { label: `v${previous.version}`, fact: previous.fact, tone: "old" },
    { label: `v${version}`, fact: current, tone: current.status === "agreed" || current.status === "confirmed" ? "ok" : "" },
    claim?.fact && { label: "Claim", fact: claim.fact, tone: "bad" },
  ].filter(Boolean);
  return {
    item, label: LABEL[item], view, current, version, pill, previous, earlier: Math.max(0, before.length - (previous ? 1 : 0)),
    claim, chain, latency: factLatency(state, current),
    said: saidBy(state, current), confirmed: confirmedBy(state, current, current === stands ? view : null),
  };
}

// Every fact, newest first, as the feed lists them.
export function feed(state) {
  return state.factOrder.map((id) => state.facts[id]).sort((a, b) => b.seq - a.seq).map((f) => ({
    fact: f, value: valueOf(f), item: itemOfFact(state, f), term: LABEL[itemOfFact(state, f)] || "Other detail",
    who: f.said_by ? nameOf(state, f.said_by) : f.kind === "payment" ? nameOf(state, "hirer") : "",
    when: f.source === "call" ? (f.start != null ? `${f.call_no ?? 1} · ${clock(f.start)}` : `Call ${f.call_no ?? 1}`)
      : f.source === "voice_note" ? "Voice" : f.source === "callback" ? "Back" : "WA",
    latency: factLatency(state, f),
  }));
}

// The speaker tracks for one deal call: who spoke when, and Gawah's own turns.
export function tracks(state) {
  const callNo = state.live?.kind === "deal" ? state.live.callNo : state.currentCall;
  const lines = Object.values(state.lines).filter((l) => (l.call_no ?? 1) === callNo).sort((a, b) => a.start - b.start);
  const voice = state.voice.filter((v) => v.callNo === callNo);
  const end = Math.max(30, ...lines.map((l) => l.end), ...voice.map((v) => v.end));
  const last = lines.at(-1) || null;
  return { callNo, live: state.live?.kind === "deal", lines, voice, end, last };
}
