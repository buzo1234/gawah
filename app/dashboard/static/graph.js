// Draws the knowledge graph from layout(): the two people, each fact as a pill or a dot,
// the edges, and the open contradiction's card in the band under the terms. Elements are kept by id between draws, so
// a live event only adds what is new (its edges draw in), and what moved eases to its new
// place. A reload draws the same layout at once, in the same order.

import { at, nameOf } from "./state.js";
import { hasClip, sourceOf } from "./graph-layout.js";
import { h, isWebLink } from "./render.js";
import { clipButton, sourceMark } from "./clips.js";

const $ = (id) => document.getElementById(id);
const SVG = "http://www.w3.org/2000/svg";
const STATUS = { said: "Said", agreed: "Agreed", confirmed: "Confirmed", disputed: "Disputed", superseded: "Replaced" };
const SOURCE = { call: "Call", callback: "Call-back", voice_note: "WhatsApp voice note", text: "WhatsApp", screenshot: "Screenshot", record: "WhatsApp" };
const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;

const nodes = new Map(); // id -> element
const paths = new Map(); // edge key -> path
let people = null;

function where(f) {
  if (!f) return "";
  if (f.source === "call") return at(f.call_no, f.start) || "Call";
  return SOURCE[f.source] || "";
}

// Hover text: what was said and by whom, for anyone at the screen.
function titleOf(state, n) {
  if (n.change) return [n.full || n.label, n.change.said && `“${n.change.said}”`].filter(Boolean).join("\n");
  const f = n.fact;
  return [`${STATUS[f.status] || f.status} · ${f.said_by ? nameOf(state, f.said_by) : ""} · ${where(f)}`, f.value || f.text, f.quote && `“${f.quote}”`].filter(Boolean).join("\n");
}

function classOf(n) {
  const f = n.fact;
  const status = f ? f.status : n.change.status;
  return ["node", n.place, `side-${n.side}`, `kind-${n.kind}`, status, n.hot && "hot"].filter(Boolean).join(" ");
}

function content(n) {
  const f = n.fact;
  const mark = f && hasClip(f) ? clipButton(f.id, null, sourceOf(f)) : sourceMark(n.change ? "asked" : sourceOf(f));
  const proof = f && !hasClip(f) && isWebLink(f.media_url) && h("a", { class: "proof", href: f.media_url, target: "_blank", rel: "noopener" }, "Proof");
  return [mark, h("span", { class: "text" }, n.label), proof].filter(Boolean);
}

function place(el, n) {
  if (n.place === "dot") {
    el.style.transform = `translate(${n.x - 5}px, ${n.y - 5}px)`;
    el.style.width = "";
  } else {
    el.style.transform = `translate(${n.x}px, ${n.y - n.h / 2}px)`;
    el.style.width = `${n.w}px`;
  }
}

// Keeps #nodes in the order things were first seen, so a reload lists them the same way.
function insertSorted(box, el, seq) {
  el.dataset.seq = seq;
  const next = [...box.children].find((c) => Number(c.dataset.seq) > seq);
  box.insertBefore(el, next || null);
}

function drawNodes(state, L, live, fresh) {
  const box = $("nodes");
  const wanted = new Set();
  const graphRect = $("graph").getBoundingClientRect();
  for (const n of L.nodes) {
    if (n.place === "hub") continue;
    wanted.add(n.id);
    let el = nodes.get(n.id);
    const sig = `${n.place}|${n.label}|${classOf(n)}`;
    if (!el) {
      el = h("div", { id: n.id });
      el.addEventListener("animationend", () => el.classList.remove("enter", "fresh", "pulse"));
      // A version that leaves its term (replaced) steps back from where it stood.
      const was = live && document.getElementById(n.id);
      nodes.set(n.id, el);
      if (was) {
        const r = was.getBoundingClientRect();
        el.style.transform = `translate(${r.left - graphRect.left}px, ${r.top - graphRect.top}px)`;
        el.style.transition = "none";
        requestAnimationFrame(() => requestAnimationFrame(() => { el.style.transition = ""; place(el, n); }));
      } else if (live) el.classList.add("enter");
      insertSorted(box, el, n.seq);
    }
    if (el.dataset.sig !== sig) {
      const entering = el.classList.contains("enter");
      el.className = classOf(n) + (entering ? " enter" : "");
      el.dataset.item = n.item || "";
      el.dataset.sig = sig;
      el.replaceChildren(...(n.place === "pill" ? content(n) : []));
    }
    el.title = titleOf(state, n);
    if (!el.style.transition) place(el, n);
    if (live && fresh.has(n.id)) flash(el, n.hot ? "pulse" : "fresh");
  }
  for (const [id, el] of nodes) if (!wanted.has(id) || !el.isConnected) { el.remove(); nodes.delete(id); }
}

function flash(el, cls) {
  el.classList.remove(cls);
  void el.offsetWidth;
  el.classList.add(cls);
}

function drawEdges(L, live) {
  const svg = $("edges");
  const wanted = new Set();
  for (const e of L.edges) {
    wanted.add(e.key);
    let p = paths.get(e.key);
    const cls = `link ${e.cls}`;
    if (!p) {
      p = document.createElementNS(SVG, "path");
      p.dataset.key = e.key;
      paths.set(e.key, p);
      svg.append(p);
      p.setAttribute("class", cls);
      p.style.d = `path("${e.d}")`;
      if (live) {
        // Solid edges draw in from where they start; dashed ones fade in.
        if (/old|asked/.test(e.cls)) p.classList.add("fade-in");
        else {
          p.setAttribute("pathLength", "1");
          p.classList.add("draw");
        }
        p.addEventListener("animationend", () => {
          p.classList.remove("draw", "fade-in");
          p.removeAttribute("pathLength");
        }, { once: true });
      }
      continue;
    }
    if (p.getAttribute("class").replace(/ (draw|fade-in)/g, "") !== cls) p.setAttribute("class", cls + (p.classList.contains("draw") ? " draw" : ""));
    p.style.d = `path("${e.d}")`;
  }
  for (const [key, p] of paths) if (!wanted.has(key) || !p.isConnected) { p.remove(); paths.delete(key); }
  // Contradictions and ties on top of the hairlines.
  for (const p of svg.querySelectorAll(".link.tie, .link.conflict")) svg.append(p);
}

function drawPeople(L) {
  if (!people || !people.isConnected) {
    people = h("div", { class: "people-layer" });
    $("graph").append(people);
  }
  people.replaceChildren(...["hirer", "worker"].map((role) => {
    const p = L.people[role];
    const title = role === "hirer" ? "Hirer" : "Worker";
    return h("div", { class: `person ${role}`, style: `transform: translate(${p.cx}px, ${p.cy}px)` },
      h("span", { class: "dot-big", "aria-hidden": "true" }),
      h("span", { class: "name" }, p.name),
      p.name !== title && h("span", { class: "role" }, title));
  }));
}

function drawCard(state, L, live, fresh) {
  const slot = $("card-slot");
  const c = L.card?.conflict;
  const old = slot.firstElementChild;
  if (!c) return slot.replaceChildren();
  if (old?.id === `conflict-${c.id}`) return;
  const target = c.factIds.map((id) => state.facts[id]).find(hasClip);
  const start = c.lineNo == null ? null : state.lines[`${c.callNo}:${c.lineNo}`]?.start;
  const el = h("div", {
    class: `conflict card${live ? " enter" : ""}`, id: `conflict-${c.id}`, onanimationend: () => el.classList.remove("enter", "pulse"),
    style: `transform: translate(${L.card.x}px, ${L.card.top}px); width: ${L.card.w}px; height: ${L.card.h}px`,
  },
    h("div", { class: "status" }, ["Contradiction", c.speaker && nameOf(state, c.speaker), c.lineNo != null ? at(c.callNo, start) : "On WhatsApp"].filter(Boolean).join(" · ")),
    c.said && h("div", { class: "said" }, `“${c.said}”`),
    h("div", { class: "why" }, c.explanation),
    target && h("div", { class: "hear" }, clipButton(target.id, "Hear what was agreed")));
  slot.replaceChildren(el);
  if (live && fresh.has(`conflict-${c.id}`)) flash(el, "pulse");
}

export function renderGraph(state, L, change = {}, live = false) {
  const conflicts = L.counts.conflicts;
  $("graph-count").replaceChildren(...(L.counts.facts ? [plural(L.counts.facts, "fact")] : []),
    ...(conflicts ? [h("span", { class: "sep" }, " · "), h("span", { class: "contradictions" }, plural(conflicts, "contradiction"))] : []));
  const fresh = new Set();
  if (change.fact) fresh.add(`fact-${change.fact}`);
  if (change.changed) fresh.add(`change-${change.changed}`);
  if (change.conflict) {
    fresh.add(`conflict-${change.conflict}`);
    for (const n of L.nodes) if (n.hot?.id === change.conflict) fresh.add(n.id);
  }
  drawEdges(L, live);
  drawPeople(L);
  drawNodes(state, L, live, fresh);
  drawCard(state, L, live, fresh);
}
