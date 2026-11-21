// The call as the deck draws it: one track per voice along a dotted line, the two people
// in grey and Gawah in green, each line a run of bars where it was said. The newest line
// rises in as it arrives.

import { nameOf } from "./state.js";
import { bars } from "./wave.js";

const $ = (id) => document.getElementById(id);
const NS = "http://www.w3.org/2000/svg";
const W = 916, H = 124, LEFT = 120, RIGHT = 24, ROW = 36, TOP = 26;

const el = (tag, attrs) => {
  const e = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  return e;
};

export function renderTracks(state, view, change = {}) {
  const t = view.tracks;
  const x = (s) => LEFT + (s / t.end) * (W - LEFT - RIGHT);
  const svg = el("svg", { width: W, height: H, viewBox: `0 0 ${W} ${H}`, "aria-hidden": "true" });
  const rows = [["hirer", nameOf(state, "hirer")], ["worker", nameOf(state, "worker")], ["gawah", "Gawah"]];
  rows.forEach(([who, name], i) => {
    const cy = TOP + i * ROW;
    const label = el("text", { x: 20, y: cy + 5, class: `who ${who}` });
    label.textContent = name;
    svg.append(label, el("line", { x1: LEFT, y1: cy, x2: W - RIGHT, y2: cy, class: "dotted" }));
  });
  const fresh = change.line;
  for (const l of t.lines) {
    const i = l.speaker === "worker" ? 1 : 0;
    const key = `${l.call_no ?? 1}:${l.line_no}`;
    const g = bars(svg, l.text, { x: x(l.start), width: Math.max(8, x(l.end) - x(l.start)), cy: TOP + i * ROW, height: 26, step: 5, bar: 2.5, cls: `voice ${l.speaker}${key === fresh ? " rise" : ""}` });
    const title = el("title", {});
    title.textContent = `${nameOf(state, l.speaker)}, line ${l.line_no}: “${l.text}”`;
    g.append(title);
  }
  t.voice.forEach((v, n) => {
    bars(svg, v.text, { x: x(v.start), width: Math.max(8, x(v.end) - x(v.start)), cy: TOP + 2 * ROW, height: 26, step: 5, bar: 2.5, cls: `voice gawah${n === change.spoke ? " rise" : ""}` });
  });
  $("tracks").replaceChildren(svg);
  $("hear-title").textContent = t.lines.length || t.voice.length ? `On the call · call ${t.callNo}${t.live ? " · live" : ""}` : "On the call";
}
