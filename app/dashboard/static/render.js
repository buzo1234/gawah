// Draws the two views from the state. Text only ever goes in through h(), as text nodes.

import { renderChecklist } from "./checklist.js";
import { renderGraph } from "./graph.js";

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

export function renderAll(state) {
  renderChecklist(state);
  renderGraph(state);
}

export function renderChange(state, change) {
  const wants = (panel) => change.panels.includes("all") || change.panels.includes(panel);
  if (wants("checklist")) renderChecklist(state, change.moved);
  if (wants("graph")) renderGraph(state, change);
}
