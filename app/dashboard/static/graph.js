// The versioned knowledge graph: one lane per contract term. The top track is the term's
// versions in the order they came (offers, the agreed value, a change); the track under it
// holds what points at them (payments that count towards the term, contradictions).
// Links are drawn over the lanes in one SVG once they are laid out.

import { ITEMS, at, nameOf } from "./state.js";
import { owed, settledBy, standing } from "./crew-state.js";
import { h, isWebLink } from "./render.js";
import { clipButton } from "./clips.js";
import { renderChain } from "./chain.js";

const $ = (id) => document.getElementById(id);
const SVG = "http://www.w3.org/2000/svg";
const LANES = [...ITEMS, ["payments", "Payments"], ["other", "Other details"]];
const MONEY = new Set(["amount", "advance", "balance"]);
const STATUS = { said: "Said", agreed: "Agreed", confirmed: "Confirmed", disputed: "Disputed", superseded: "Replaced" };
const SOURCE = { voice_note: "WhatsApp voice note", text: "WhatsApp", screenshot: "Screenshot", record: "WhatsApp" };
const rupees = (n) => "₹" + Number(n).toLocaleString("en-IN");
const hasClip = (f) => f && f.start != null && ["call", "callback", "voice_note"].includes(f.source);
const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;

// ---------- nodes ----------

function people(state, roles) {
  const set = new Set(roles.filter(Boolean));
  return set.size >= 2 ? "both" : [...set].map((r) => nameOf(state, r)).join("");
}

function who(state, f) {
  if (f.status === "confirmed" && f.confirmed_by?.length) return people(state, f.confirmed_by);
  if (f.status === "agreed" && f.agreed_by?.length) return people(state, [f.said_by, ...f.agreed_by]);
  return f.said_by ? nameOf(state, f.said_by) : "";
}

function source(f) {
  if (f.source === "call") return at(f.call_no, f.start) || "Call";
  if (f.source === "callback") return "Call-back";
  return SOURCE[f.source] || "";
}

function label(f, stands) {
  if (f.kind === "payment") return f.status === "disputed" ? "Payment denied" : "Payment";
  if (f.kind === "work") return "Work done";
  if (f.kind === "change" && f.status === "said") return "Change asked";
  return `${STATUS[f.status]}${stands ? " · current" : ""}`;
}

const line = (...parts) => parts.filter(Boolean).join(" · ");

// stands: the fact the term rests on now, as memory's get_term gives it.
function factNode(state, f, amended, stands) {
  return h("div", { class: `fact ${f.status} kind-${f.kind}${stands ? " stands" : ""}`, id: `fact-${f.id}`, title: f.quote ? `“${f.quote}”` : f.text },
    h("div", { class: "status" }, line(label(f, stands), who(state, f))),
    h("div", { class: "value" }, f.value || f.text),
    amended && h("div", { class: "aside" }, "Changed by voice, both said yes"),
    h("div", { class: "src" },
      hasClip(f) && clipButton(f.id),
      h("span", {}, source(f)),
      !hasClip(f) && isWebLink(f.media_url) && h("a", { href: f.media_url, target: "_blank", rel: "noopener" }, "Proof")));
}

function changeNode(state, c) {
  const yes = (role) => c.confirmed_by?.includes(role);
  const head = { proposed: "Change asked", confirmed_one: "Change asked", confirmed_both: "Change holds", withdrawn: "Withdrawn" }[c.status];
  return h("div", { class: `fact change ${c.status}`, id: `change-${c.id}`, title: c.said ? `“${c.said}”` : null },
    h("div", { class: "status" }, line(head, c.proposed_by && nameOf(state, c.proposed_by))),
    h("div", { class: "value" }, c.new_value),
    c.status !== "withdrawn" && h("div", { class: "src" },
      ["hirer", "worker"].map((role) => `${nameOf(state, role)} ${yes(role) ? "yes" : "not yet"}`).join(" · ")));
}

function conflictNode(state, c) {
  const target = c.factIds.map((id) => state.facts[id]).find(hasClip);
  const start = c.lineNo == null ? null : state.lines[`${c.callNo}:${c.lineNo}`]?.start;
  return h("div", { class: "conflict", id: `conflict-${c.id}` },
    h("div", { class: "status" }, line("Contradiction", c.speaker && nameOf(state, c.speaker), c.lineNo != null ? at(c.callNo, start) : "On WhatsApp")),
    c.said && h("div", { class: "said" }, `“${c.said}”`),
    h("div", { class: "why" }, c.explanation),
    target && h("div", { class: "src" }, clipButton(target.id, "Hear what was agreed")));
}

// ---------- lanes ----------

// A term's lane holds the facts memory files under that item: terms, and changes asked
// for. Payments and work go under the term they count towards; any other detail, even one
// about a term, goes to "Other details", as memory never takes it as the term's value.
function laneFor(f) {
  if (f.kind === "payment") return "payments";
  if (f.item && (f.kind === "term" || f.kind === "change")) return f.item;
  return "other";
}

function lanesOf(state) {
  const lanes = Object.fromEntries(LANES.map(([key]) => [key, { versions: [], below: [] }]));
  const stands = new Set(ITEMS.map(([key]) => standing(state, key)?.id).filter(Boolean));
  const amendedBy = {};
  for (const id of state.changeOrder) {
    const c = state.changes[id];
    const fact = settledBy(state, c);
    if (fact) amendedBy[fact.id] = c;
    else lanes[c.item || state.facts[c.fact_id]?.item || "other"]?.versions.push({ seq: c.seq, el: changeNode(state, c) });
  }
  for (const id of state.factOrder) {
    const f = state.facts[id];
    const counts = f.kind === "payment" || f.kind === "work";
    const target = counts && state.facts[f.counts_towards];
    if (target?.item) lanes[target.item].below.push({ seq: f.seq, el: factNode(state, f) });
    else lanes[laneFor(f)].versions.push({ seq: f.seq, el: factNode(state, f, amendedBy[f.id], stands.has(f.id)) });
  }
  for (const c of state.conflicts) {
    const key = c.factIds.map((id) => state.facts[id]?.item).find(Boolean) || "other";
    lanes[key].below.push({ seq: Infinity, el: conflictNode(state, c) });
  }
  return lanes;
}

// Shown once a payment counts towards the term; the balance, with no figure of its own
// agreed, is the amount less the advance, as memory works it out.
function moneyLine(row) {
  if (!row?.payments.length || row.agreed == null) return null;
  return h("span", { class: "owed", title: `${rupees(row.agreed)} agreed` }, `Paid ${rupees(row.paid)}`, h("span", { class: "sep" }, " · "), `${rupees(row.owed)} left`);
}

function links(state) {
  const out = [];
  for (const id of state.factOrder) {
    const f = state.facts[id];
    if (f.replaces) out.push([`fact-${f.replaces}`, `fact-${f.id}`, "replaces"]);
    if (f.counts_towards) out.push([`fact-${f.id}`, `fact-${f.counts_towards}`, "counts"]);
  }
  for (const id of state.changeOrder) out.push([`fact-${state.changes[id].fact_id}`, `change-${id}`, "change"]);
  for (const c of state.conflicts) for (const id of c.factIds) out.push([`conflict-${c.id}`, `fact-${id}`, "conflict"]);
  return out;
}

// ---------- links ----------

function drawLinks(body, wanted) {
  const svg = body.querySelector("svg.links");
  svg.setAttribute("width", body.scrollWidth);
  svg.setAttribute("height", body.scrollHeight);
  // From layout offsets, not the screen: a node still rising into place is drawn shifted,
  // and its links must not keep that shift.
  const rel = (el) => {
    let left = 0, top = 0;
    for (let n = el; n && n !== body; n = n.offsetParent) {
      left += n.offsetLeft;
      top += n.offsetTop;
    }
    const [w, hgt] = [el.offsetWidth, el.offsetHeight];
    return { left, top, right: left + w, bottom: top + hgt, cx: left + w / 2, cy: top + hgt / 2 };
  };
  const paths = wanted.map(([from, to, kind]) => {
    const a = document.getElementById(from), b = document.getElementById(to);
    if (!a || !b || !body.contains(a) || !body.contains(b)) return null;
    const p = rel(a), q = rel(b);
    let d;
    const sameRow = Math.abs(p.top - q.top) < 8;
    const between = sameRow && [...a.parentNode.children].some((el) => {
      const r = rel(el);
      return el !== a && el !== b && Math.abs(r.top - p.top) < 8 && r.left > Math.min(p.left, q.left) && r.left < Math.max(p.left, q.left);
    });
    if (between) {
      // Versions with others between them on the same line: an arc under the line.
      const y = Math.max(p.bottom, q.bottom) + 14;
      d = `M${p.cx},${p.bottom + 4} C${p.cx},${y} ${q.cx},${y} ${q.cx},${q.bottom + 4}`;
    } else if (q.left >= p.right - 4 || q.right <= p.left + 4) {
      const [x1, x2] = q.left >= p.right - 4 ? [p.right + 4, q.left - 4] : [p.left - 4, q.right + 4];
      const bend = (x2 - x1) / 2;
      d = `M${x1},${p.cy} C${x1 + bend},${p.cy} ${x2 - bend},${q.cy} ${x2},${q.cy}`;
    } else {
      const [y1, y2] = q.bottom <= p.top ? [p.top - 2, q.bottom + 4] : [p.bottom + 4, q.top - 2];
      const x1 = kind === "conflict" ? Math.min(Math.max(q.cx, p.left + 24), p.right - 24) : p.cx;
      const bend = (y2 - y1) / 2;
      d = `M${x1},${y1} C${x1},${y1 + bend} ${q.cx},${y2 - bend} ${q.cx},${y2}`;
    }
    const path = document.createElementNS(SVG, "path");
    path.setAttribute("d", d);
    path.setAttribute("class", `link ${kind}`);
    path.setAttribute("marker-end", `url(#arrow-${kind})`);
    return path;
  }).filter(Boolean);
  svg.querySelectorAll("path.link").forEach((p) => p.remove());
  svg.append(...paths);
}

function svgDefs() {
  const svg = document.createElementNS(SVG, "svg");
  svg.setAttribute("class", "links");
  svg.setAttribute("aria-hidden", "true");
  const defs = document.createElementNS(SVG, "defs");
  for (const kind of ["replaces", "counts", "change", "conflict"]) {
    const marker = document.createElementNS(SVG, "marker");
    for (const [k, v] of Object.entries({ id: `arrow-${kind}`, viewBox: "0 0 10 10", refX: "8", refY: "5", markerWidth: "7", markerHeight: "7", markerUnits: "userSpaceOnUse", orient: "auto-start-reverse" }))
      marker.setAttribute(k, v);
    const tip = document.createElementNS(SVG, "path");
    tip.setAttribute("d", "M0,1 L9,5 L0,9 z");
    tip.setAttribute("class", `tip ${kind}`);
    marker.append(tip);
    defs.append(marker);
  }
  svg.append(defs);
  return svg;
}

// ---------- entry points ----------

let lastLinks = [];
let holdUntil = 0;
let scrollTo = null; // the node whose lane to bring into view once the graph is laid out
const CONFLICT_HOLD_MS = 12000;

// The graph is drawn afresh for every event, so a node that just came in keeps its
// highlight across the redraws that follow it, carried on from where it had got to.
const GLOW_MS = { fresh: 1800, "fresh-conflict": 3200 };
const glowing = new Map(); // element id -> { cls, since }

const glow = (id, cls) => glowing.set(id, { cls, since: Date.now() });

function showGlow() {
  const now = Date.now();
  for (const [id, { cls, since }] of glowing) {
    if (now - since > GLOW_MS[cls]) {
      glowing.delete(id);
      continue;
    }
    const el = document.getElementById(id);
    if (!el) continue;
    el.classList.add(cls);
    el.style.animationDelay = `-${now - since}ms`;
  }
}

function header(state) {
  const facts = state.factOrder.length;
  const conflicts = state.conflicts.length;
  $("graph-count").replaceChildren(...(facts ? [plural(facts, "fact")] : []),
    ...(conflicts ? [h("span", { class: "sep" }, " · "), h("span", { class: "contradictions" }, plural(conflicts, "contradiction"))] : []));
}

export function renderGraph(state, fresh = {}) {
  const box = $("graph");
  const lanes = lanesOf(state);
  const money = owed(state);
  header(state);
  renderChain(state);
  const body = h("div", { class: "graph-body" }, svgDefs(),
    LANES.map(([key, name]) => {
      const lane = lanes[key];
      const order = (list) => list.sort((a, b) => a.seq - b.seq).map((x) => x.el);
      const paid = MONEY.has(key) && moneyLine(money[key]);
      const empty = !lane.versions.length && !lane.below.length;
      if (empty && !ITEMS.some(([k]) => k === key)) return null;
      return h("section", { class: `lane${empty ? " empty" : ""}`, "data-item": key },
        h("div", { class: "lane-head" }, h("h3", { class: "lane-label" }, name), paid),
        // A balance nobody named can still be owed: memory takes it as the amount less the advance.
        empty ? h("div", { class: "nothing" }, paid ? "The amount less the advance" : "Nothing said yet")
          : [h("div", { class: "track" }, order(lane.versions)),
            lane.below.length > 0 && h("div", { class: "track below" }, order(lane.below))]);
    }));
  box.replaceChildren(body);
  lastLinks = links(state);
  const target = fresh.conflict ? `conflict-${fresh.conflict}` : fresh.changed ? `change-${fresh.changed}` : fresh.fact ? `fact-${fresh.fact}` : null;
  if (target) glow(target, fresh.conflict ? "fresh-conflict" : "fresh");
  // Bring the newest node's lane into view, so a contradiction is seen with the fact it
  // contradicts. A contradiction holds the view for a while: the facts written down right
  // after it do not scroll it away.
  if (target && (fresh.conflict || Date.now() > holdUntil)) scrollTo = target;
  if (fresh.conflict) {
    for (const id of state.conflicts.at(-1).factIds) glow(`fact-${id}`, "fresh-conflict");
    holdUntil = Date.now() + CONFLICT_HOLD_MS;
  }
  showGlow();
  requestAnimationFrame(() => {
    if (!body.isConnected) return; // a newer event has drawn the graph again, and will do this
    drawLinks(body, lastLinks);
    const lane = scrollTo && document.getElementById(scrollTo)?.closest(".lane");
    scrollTo = null;
    if (lane) {
      const r = lane.getBoundingClientRect(), b = box.getBoundingClientRect();
      if (r.top < b.top || r.bottom > b.bottom) box.scrollTo({ top: box.scrollTop + r.top - b.top, behavior: "smooth" });
    }
  });
}

// Links are measured from the laid-out nodes, so they are drawn again whenever the
// window changes size.
export function relink() {
  const body = document.querySelector("#graph .graph-body");
  if (body) requestAnimationFrame(() => drawLinks(body, lastLinks));
}

addEventListener("resize", relink);
