// The board's words and numbers, worked out from the state alone (no DOM), so a reload
// says exactly what the live page did, and Node can test it. One word for one thing:
// the graph, the timeline and the detail card all name a status from here.

import { ITEMS, at, clock, lineAt, nameOf } from "./state.js";
import { standing } from "./crew-state.js";

export const LABEL = Object.fromEntries(ITEMS);
const THIN = "\u202f"; // a narrow space that never breaks: "₹ 22,000" and "0.4 s" stay on one line

export const rupees = (n) => `₹${THIN}${Number(n).toLocaleString("en-IN")}`;
export const hasClip = (f) => !!f && f.start != null && ["call", "callback", "voice_note"].includes(f.source);

// The person responsible: their name, their role, and the colour that marks them. A record
// or anything no one said is Gawah's, in grey.
export function person(state, role) {
  if (role !== "hirer" && role !== "worker") return { role: "none", name: "Gawah", named: true };
  const name = state.people[role]?.name;
  return { role, name: name || nameOf(state, role), named: !!name };
}

// "22,000 rupees" reads as ₹ 22,000; "500 rupees per day" as ₹ 500 per day (a few words
// after the figure stay with it, they are part of the term); "24,000 rupees (22,000 agreed
// + 2,000 extra)" as ₹ 24,000 with the rest beside it; anything else stays as said. `n` is
// the figure memory read, when there is one: the words must say the same.
export function splitMoney(value, n = null) {
  const v = (value || "").trim();
  const m = /^([\d,]+) rupees\b[\s,;:]*(.*)$/i.exec(v);
  const figure = m && Number(m[1].replace(/,/g, ""));
  if (!m || (n != null && figure !== n)) return { main: v, rest: "", money: false, bare: false };
  const rest = m[2].trim();
  const short = rest && rest.split(/\s+/).length <= 3 && !/[()]/.test(rest);
  return { main: short ? `${rupees(figure)} ${rest}` : rupees(figure), rest: short ? "" : rest, money: true, bare: !rest };
}

export function valueParts(f) {
  if (!f) return { main: "", rest: "", money: false, bare: false };
  if (f.kind === "payment") return { main: `Paid ${f.value_rupees != null ? rupees(f.value_rupees) : f.value || ""}`.trim(), rest: "", money: true, bare: true };
  if (f.kind === "work") return { main: "Work done", rest: f.value || "", money: false, bare: false };
  if (f.value_rupees != null) {
    const parts = splitMoney(f.value, f.value_rupees);
    if (parts.money) return parts;
  }
  return { main: (f.value || "").trim() || f.text || "", rest: "", money: false, bare: false };
}
export const valueOf = (f) => { const p = valueParts(f); return p.rest ? `${p.main} ${p.rest}` : p.main; };

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
export const took = (s) => (s == null ? "" : `${s < 0.1 ? `<${THIN}0.1` : s.toFixed(1)}${THIN}s`);
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
export const claims = (state) => new Set(state.conflicts.map((c) => contradicting(state, c)?.id).filter(Boolean));

export const itemOfConflict = (state, c) => c.factIds.map((id) => state.facts[id]?.item).find(Boolean) || null;
export const itemOfFact = (state, f) => state.facts[f.counts_towards]?.item || f.item || null;

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

// A fact's status in the board's words. Confirmed says by whom.
export function statusWord(state, f, claimed = claims(state)) {
  if (claimed.has(f.id)) return { word: "Contradicted", tone: "bad" };
  if (f.status === "superseded") return { word: "Replaced", tone: "" };
  if (f.status === "disputed") return { word: "Disputed", tone: "bad" };
  if (f.kind === "payment") return { word: f.status === "said" ? "Paid, unconfirmed" : "Paid", tone: f.status === "said" ? "" : "ok" };
  if (f.status === "confirmed") {
    const by = [...new Set(f.confirmed_by || [])];
    return { word: by.length === 1 ? `Confirmed by ${person(state, by[0]).name}` : "Confirmed by both", tone: "ok" };
  }
  if (f.status === "agreed") return { word: "Agreed", tone: "ok" };
  return { word: "Said", tone: "" };
}

// A term's state in the same words.
export const TERM_WORD = { pending: "Waiting", agreed: "Agreed", confirmed: "Confirmed by both", disputed: "In dispute", changed: "Changed" };
export const TERM_TONE = { pending: "", agreed: "ok", confirmed: "ok", changed: "ok", disputed: "bad" };

// Who said it, and who agreed or confirmed: the roles, the speaker first.
export function people(f) {
  return [...new Set([f.said_by, ...(f.agreed_by || []), ...(f.confirmed_by || [])])].filter((r) => r === "hirer" || r === "worker");
}

export function confirmedBy(state, f, view) {
  if (view?.state === "changed") return f.source === "voice_note" ? "Both, by voice note" : "Both, by voice";
  const by = [...new Set(f.confirmed_by || [])];
  if (by.length >= 2 || view?.state === "confirmed") return f.source === "callback" || view?.state === "confirmed" ? "Both, on their call-backs" : "Both, by voice";
  if (by.length === 1) return `${person(state, by[0]).name} only`;
  return "Not yet";
}

// ---------- text that must fit ----------

// Text width in a font ("600 18px"; 16px by default): Node has no fonts, so tests use this
// estimate; the page measures with a canvas.
export const estimate = (text, font = "500 16px") => text.length * 8.4 * (Number(/(\d+)px/.exec(font)[1]) / 16) * (/^[67]/.test(font) ? 1.05 : 1);

const trim = (s) => s.replace(/[\s;:,.\-–—(]+$/, "");

// The text, or as many of its words as fit in `max` with an ellipsis, never part of a word
// (a first word too long for the place is cut where it must be).
export function cut(text, max, measure = estimate, font) {
  if (!text || measure(text, font) <= max) return text;
  const words = text.split(/[ \t\n]+/);
  for (let n = words.length - 1; n > 0; n--) {
    const short = trim(words.slice(0, n).join(" ")) + "…";
    if (measure(short, font) <= max) return short;
  }
  let short = text;
  while (short.length > 1 && measure(short + "…", font) > max) short = short.slice(0, -1);
  return short + "…";
}

// The text laid in `lines` lines of `width`, as the browser wraps it, cut at a word with an
// ellipsis when it does not fit. A number, a date or a name is never split: only whole
// words are dropped.
export function fit(text, width, lines, measure = estimate, font) {
  if (!text) return text;
  const words = text.split(/[ \t\n]+/);
  let line = 0, used = "", i = 0;
  for (; i < words.length; i++) {
    const next = used ? `${used} ${words[i]}` : words[i];
    if (measure(next, font) <= width) { used = next; continue; }
    if (!used) return cut(text, width, measure, font); // one word wider than the line
    if (++line >= lines) break;
    used = words[i];
    if (measure(used, font) > width) break;
  }
  if (i >= words.length) return text;
  const kept = words.slice(0, i);
  for (let n = kept.length; n > 0; n--) {
    const short = trim(kept.slice(0, n).join(" ")) + "…";
    if (fit(short, width, lines, measure, font) === short) return short;
  }
  return cut(text, width, measure, font);
}

export { clock };
