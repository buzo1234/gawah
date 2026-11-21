// Draws the board from the state: one view worked out from it (board.js), then each
// panel from that view. A live event redraws the panels with what is new marked, so it
// rises in; a reload draws the same thing at once. Text only ever goes in through h(),
// as text nodes.

import { ITEMS, nameOf, termView } from "./state.js";
import { standing } from "./crew-state.js";
import { contradicting, factLayer, feed, focusItem, openConflict, tracks } from "./board.js";
import { renderChecklist } from "./checklist.js";
import { renderFeed } from "./feed.js";
import { renderTracks } from "./tracks.js";
import { renderChainRow, renderLayerAndBelow } from "./layer.js";
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

// Where a long label is cut comes from the page's own font.
const ctx = document.createElement("canvas").getContext("2d");
const measure = (text, font = "500 16px") => {
  ctx.font = `${font} ${getComputedStyle(document.body).fontFamily}`;
  return ctx.measureText(text).width;
};

let picked = null; // the term a person picked in the contract, until something new happens
let current = null; // the state last drawn, for a pick to redraw
let shown = null; // the term the fact layer shows

function viewOf(state) {
  const focus = focusItem(state, picked);
  return {
    views: Object.fromEntries(ITEMS.map(([key]) => [key, termView(state, key)])),
    stands: Object.fromEntries(ITEMS.map(([key]) => [key, standing(state, key)])),
    focus, measure, contradicting: (c) => contradicting(state, c),
    pick: (key) => { picked = key; renderAll(current, true); },
    feed: feed(state), tracks: tracks(state), layer: factLayer(state, focus), open: openConflict(state),
  };
}

function header(state, view) {
  const hirer = state.people.hirer?.name, worker = state.people.worker?.name;
  document.getElementById("deal-title").textContent = hirer || worker ? `${nameOf(state, "hirer")} · ${nameOf(state, "worker")}` : "Gawah";
  const pill = document.getElementById("call-pill");
  const live = state.live;
  pill.replaceChildren(...(live ? [h("span", { class: "dot" }), live.kind === "callback" ? "Call-back · live" : `Call ${live.callNo} · live`]
    : state.calls.length ? [`After call ${state.currentCall}`] : state.dealId ? ["Before the call"] : []));
  pill.className = `pill${live ? " live" : ""}`;
  pill.hidden = !pill.textContent;
}

function draw(state, change = {}, live = false) {
  current = state;
  const view = viewOf(state);
  shown = view.focus;
  header(state, view);
  renderTracks(state, view, live ? change : {});
  renderChecklist(state, view, change.moved || [], live);
  renderFeed(state, view, live ? change.fact : null);
  renderLayerAndBelow(state, view, live ? change : {});
  renderChain(state);
}

// A reload, another deal, or a term picked: everything at once, nothing animated.
export function renderAll(state, keepPick = false) {
  if (!keepPick) picked = null;
  const stage = document.getElementById("stage");
  stage.classList.add("instant");
  draw(state);
  void stage.offsetWidth;
  requestAnimationFrame(() => stage.classList.remove("instant"));
}

// One live event: what is new rises in.
export function renderChange(state, change) {
  if (change.panels.includes("all")) return renderAll(state, true);
  if (!change.panels.length) return;
  if (change.fact || change.conflict || change.changed) picked = null;
  draw(state, change, true);
}

// Memory's answer on the chain: the verdict and the links on screen; the whole board only
// when a broken link moves the fact layer to its term.
export function renderChecked(state) {
  const view = viewOf(state);
  if (view.focus !== shown) return draw(state);
  renderChain(state);
  renderChainRow(state, view.layer);
}
