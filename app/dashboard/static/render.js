// Draws the board from the state: one layout, then the graph, the checklist down its
// middle, and the chain under it. Text only ever goes in through h(), as text nodes.

import { layout } from "./graph-layout.js";
import { renderChecklist } from "./checklist.js";
import { renderGraph } from "./graph.js";
import { renderChain } from "./chain.js";

export function h(tag, attrs = {}, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v);
  }
  el.append(...kids.flat(Infinity).filter((k) => k != null && k !== false && k !== ""));
  return el;
}

export const isWebLink = (url) => /^https?:\/\//i.test(url || "");

// Pill widths and where a long label is cut come from the page's own font.
const ctx = document.createElement("canvas").getContext("2d");
const measure = (text, font = "500 16px") => {
  ctx.font = `${font} ${getComputedStyle(document.body).fontFamily}`;
  return ctx.measureText(text).width;
};

// A reload, or another deal: everything at once, nothing animated.
export function renderAll(state) {
  const stage = document.getElementById("stage");
  stage.classList.add("instant");
  const L = layout(state, measure);
  renderGraph(state, L);
  renderChecklist(state, L);
  renderChain(state);
  void stage.offsetWidth;
  requestAnimationFrame(() => stage.classList.remove("instant"));
}

// One live event: what is new enters, what moved eases there.
export function renderChange(state, change) {
  const wants = (panel) => change.panels.includes("all") || change.panels.includes(panel);
  if (change.panels.includes("all")) return renderAll(state);
  if (!wants("graph") && !wants("checklist") && !wants("chain")) return;
  const L = layout(state, measure);
  renderGraph(state, L, change, true); // before the checklist: a replaced version steps back from its term
  renderChecklist(state, L, change.conflict ? [...change.moved, ...conflictItems(state, change.conflict)] : change.moved, true);
  if (wants("chain")) renderChain(state, true);
}

const conflictItems = (state, id) =>
  state.conflicts.find((c) => c.id === id)?.factIds.map((f) => state.facts[f]?.item).filter(Boolean) || [];
