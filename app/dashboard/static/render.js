// Draws the board from the state: the header, the fact graph (graph.js), the detail card
// under it (detail.js), the timeline (timeline.js) and the witness chain (chain.js). Lists
// are kept by key, so a live event adds what is new and leaves the rest where it is: nothing
// under the viewer's eye jumps, and only the new thing moves. A reload draws the same thing
// at once. Text only ever goes in through h(), as text nodes.

import { nameOf, phoneLabel } from "./state.js";
import { person } from "./board.js";
import { renderGraph } from "./graph.js";
import { renderTimeline } from "./timeline.js";
import { renderDetail } from "./detail.js";
import { renderChain } from "./chain.js";
import { h, hooks } from "./dom.js";

export { h };

// ---------- what the detail card shows, and what is lit across the board ----------

let current = null; // the state last drawn
let hovered = null; // fact ids under the pointer or keyboard focus
let picked = null; // fact ids clicked, until something new happens

function point(ids) {
  hovered = ids && ids.length ? ids : null;
  light();
  if (current) renderDetail(current, hovered || picked);
}
function pick(ids) {
  picked = ids && ids.length ? ids : null;
  if (current) renderDetail(current, hovered || picked);
}

hooks.point = point;
hooks.pick = pick;

// Everything that stands for one of the facts pointed at, on the graph and the timeline.
function light() {
  for (const el of document.querySelectorAll(".lit")) el.classList.remove("lit");
  for (const id of hovered || []) {
    for (const el of document.querySelectorAll(`[data-facts~="${CSS.escape(id)}"]`)) el.classList.add("lit");
  }
}

function header(state) {
  const title = document.getElementById("deal-title");
  const named = ["hirer", "worker"].map((r) => person(state, r));
  const known = state.people.hirer || state.people.worker;
  title.replaceChildren(...(known ? named.flatMap((p, i) => [
    i ? h("span", { class: "sep" }, " · ") : null,
    h("span", { class: `who ${p.role}` }, h("span", { class: "dot", "aria-hidden": "true" }), p.named ? p.name : `The ${p.role}`),
    p.named ? h("span", { class: "role label" }, p.role) : null,
  ]).filter(Boolean) : ["Gawah"]));
  title.title = known ? `${nameOf(state, "hirer")} and ${nameOf(state, "worker")}` : "";
  const pill = document.getElementById("call-pill");
  const live = state.live;
  pill.replaceChildren(...(live ? [h("span", { class: "dot" }), live.kind === "callback" ? "Call-backs · live" : `Call ${live.callNo} · live`]
    : state.calls.length ? [`After call ${state.currentCall}`] : state.dealId ? ["Before the call"] : ["No deal yet"]));
  pill.className = `pill${live ? " live" : ""}`;
}

// The second phone's frame is titled by whose phone it shows: the number comes from the
// phone page in the frame, the name from the board's own fold.
let phoneNumber = null;
export function showPhone(number) {
  phoneNumber = number;
  if (current) phoneTitle(current);
}
function phoneTitle(state) {
  const label = phoneLabel(state.people, phoneNumber, state.dealId);
  document.getElementById("phone-title").textContent = label;
  document.getElementById("phone-frame").title = label;
  document.getElementById("phone-tab-label").textContent = label;
  document.getElementById("phone-hide").setAttribute("aria-label", `Hide ${label} (P)`);
  document.getElementById("phone-tab").setAttribute("aria-label", `Show ${label} (P)`);
}

// Lays the graph out again at its column's width (the phone drawer changed it).
export function refit() {
  if (current) renderGraph(current, {});
}

function draw(state, change = {}, live = false) {
  current = state;
  const fresh = live ? change : {};
  header(state);
  phoneTitle(state);
  renderGraph(state, fresh);
  renderTimeline(state, fresh);
  renderDetail(state, hovered || picked, fresh);
  renderChain(state, fresh);
  light();
}

// A reload, another deal: everything at once, nothing animated.
export function renderAll(state) {
  picked = hovered = null;
  const stage = document.getElementById("stage");
  stage.classList.add("instant");
  draw(state);
  void stage.offsetWidth;
  requestAnimationFrame(() => stage.classList.remove("instant"));
}

// One live event: what is new comes in, in the order speech becomes a fact: the timeline
// entry, then its chip and edges in the graph, then the term's state.
export function renderChange(state, change) {
  if (change.panels.includes("all")) return renderAll(state);
  if (!change.panels.length) return;
  if (change.fact || change.conflict || change.changed) picked = null;
  draw(state, change, true);
}

// Memory's answer on the chain: the verdict, the links, and a broken link's chip.
export function renderChecked(state) {
  renderChain(state, {});
  renderGraph(state, {});
}
