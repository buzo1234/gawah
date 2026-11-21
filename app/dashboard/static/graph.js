// The fact graph: one row per contract term. The top track is the term's versions in the
// order they came (an offer, the agreed value, a change); the track under it holds what
// points at them (payments that count towards a term, contradictions). Links are drawn
// over the cards in one SVG once the cards are laid out.

import { ITEMS, clock, nameOf } from "./state.js";
import { settledBy, standing } from "./crew-state.js";
import { h, isWebLink } from "./render.js";

const $ = (id) => document.getElementById(id);
const SVG = "http://www.w3.org/2000/svg";
const ROWS = [...ITEMS.map(([k, label]) => [k, k === "late_or_unfinished" ? "If late" : label]), ["payments", "Payments"], ["other", "Other details"]];
const MONEY = new Set(["amount", "advance", "balance"]);
const NOT_COUNTED = new Set(["disputed", "superseded"]);
const STATUS = { said: "Said", agreed: "Agreed", confirmed: "Confirmed", disputed: "Disputed", superseded: "Replaced" };
const SOURCE = { voice_note: "Voice note", text: "WhatsApp", screenshot: "Screenshot", record: "Record" };
const rupees = (n) => "₹" + Number(n).toLocaleString("en-IN");
export const clipPath = (factId) => `/memory/clip/${factId}`;

// ---------- clips ----------

let playing = null; // { button, audio }

function stopClip() {
  if (!playing) return;
  playing.audio.pause();
  playing.button.classList.remove("playing");
  playing = null;
}

function playClip(factId, button) {
  const again = playing?.button === button;
  stopClip();
  if (again) return;
  const audio = new Audio(clipPath(factId));
  playing = { button, audio };
  button.classList.add("playing");
  audio.addEventListener("ended", stopClip);
  audio.play().catch(() => {
    stopClip();
    button.classList.add("missing");
  });
}

export const clipButton = (factId, label = "Clip") =>
  h("button", { type: "button", class: "play", title: "Play where it was said", onclick: (ev) => playClip(factId, ev.currentTarget) }, label);

const hasClip = (f) => f && f.start != null && ["call", "callback", "voice_note"].includes(f.source);

// ---------- cards ----------

function people(state, roles) {
  const set = new Set(roles.filter(Boolean));
  return set.size >= 2 ? "both" : [...set].map((r) => nameOf(state, r)).join("");
}

// Read after the status, short enough for the corner of a card ("Agreed by both",
// "Said · Ramesh"). The full sentence and the quote are in the card's title.
function who(state, f) {
  if (f.status === "confirmed" && f.confirmed_by?.length) return `by ${people(state, f.confirmed_by)}`;
  if (f.status === "agreed" && f.agreed_by?.length) return `by ${people(state, [f.said_by, ...f.agreed_by])}`;
  return f.said_by ? nameOf(state, f.said_by) : "";
}

function source(f) {
  if (f.source === "call") return f.call_no != null ? `Call ${f.call_no}${f.start != null ? ` · ${clock(f.start)}` : ""}` : "Call";
  if (f.source === "callback") return "Call-back";
  return SOURCE[f.source] || "";
}

function factCard(state, f, amended) {
  const label = f.kind === "payment" ? "Payment" : f.kind === "work" ? "Work done" : STATUS[f.status];
  return h("div", { class: `fact ${f.status} kind-${f.kind}`, id: `fact-${f.id}`, title: f.quote ? `“${f.quote}”` : f.text },
    h("div", { class: "top" }, h("span", { class: "status" }, label), h("span", { class: "by" }, who(state, f))),
    h("div", { class: "value" }, f.value || f.text),
    amended && h("div", { class: "amended" }, "Changed by voice · both said yes"),
    h("div", { class: "src" }, h("span", {}, source(f)),
      hasClip(f) && clipButton(f.id),
      !hasClip(f) && isWebLink(f.media_url) && h("a", { href: f.media_url, target: "_blank", rel: "noopener" }, "proof")));
}

function changeCard(state, c) {
  const step = (done, text) => h("span", { class: `step${done ? " done" : ""}` }, text);
  const yes = (role) => c.confirmed_by?.includes(role);
  const head = { proposed: "Change", confirmed_one: "Change · 1 of 2", confirmed_both: "Change holds", withdrawn: "Withdrawn" }[c.status];
  return h("div", { class: `fact change ${c.status}`, id: `change-${c.id}`, title: c.said ? `“${c.said}”` : null },
    h("div", { class: "top" }, h("span", { class: "status" }, head),
      h("span", { class: "by" }, c.proposed_by ? `by ${nameOf(state, c.proposed_by)}` : "")),
    h("div", { class: "value" }, c.new_value),
    c.status !== "withdrawn" && h("div", { class: "steps" },
      ["hirer", "worker"].map((role) => step(yes(role), `${nameOf(state, role)}${yes(role) ? " ✓ yes" : ": not yet"}`))));
}

function conflictCard(state, c) {
  const target = c.factIds.map((id) => state.facts[id]).find(hasClip);
  const where = c.lineNo != null ? `call ${c.callNo ?? "?"} · line ${c.lineNo}` : "on WhatsApp";
  return h("div", { class: "conflict", id: `conflict-${c.id}` },
    h("div", { class: "top" }, h("span", { class: "status" }, "Contradiction"),
      h("span", { class: "by" }, [c.speaker && nameOf(state, c.speaker), where].filter(Boolean).join(" · "))),
    c.said && h("div", { class: "said" }, `“${c.said}”`),
    h("div", { class: "why" }, c.explanation),
    target && h("div", { class: "src" }, clipButton(target.id, "Hear what was agreed")));
}

// ---------- rows ----------

function rowsOf(state) {
  const rows = Object.fromEntries(ROWS.map(([key]) => [key, { versions: [], below: [], payments: [] }]));
  const amendedBy = {};
  for (const id of state.changeOrder) {
    const c = state.changes[id];
    const fact = settledBy(state, c);
    if (fact) amendedBy[fact.id] = c;
    else rows[c.item || state.facts[c.fact_id]?.item || "other"]?.versions.push({ seq: c.seq, el: changeCard(state, c) });
  }
  for (const id of state.factOrder) {
    const f = state.facts[id];
    const counts = f.kind === "payment" || f.kind === "work";
    const target = counts && state.facts[f.counts_towards];
    if (target?.item) {
      rows[target.item].below.push({ seq: f.seq, el: factCard(state, f) });
      if (f.kind === "payment") rows[target.item].payments.push(f);
    } else {
      const key = f.item && !counts ? f.item : f.kind === "payment" ? "payments" : "other";
      rows[key].versions.push({ seq: f.seq, el: factCard(state, f, amendedBy[f.id]), fact: f });
    }
  }
  for (const c of state.conflicts) {
    const key = c.factIds.map((id) => state.facts[id]?.item).find(Boolean) || "other";
    rows[key].below.push({ seq: Infinity, el: conflictCard(state, c) });
  }
  return rows;
}

function moneyLine(row) {
  const term = standing(row.versions.map((v) => v.fact).filter(Boolean));
  const paid = row.payments.filter((p) => !NOT_COUNTED.has(p.status)).reduce((sum, p) => sum + (p.value_rupees || 0), 0);
  if (!row.payments.length || term?.value_rupees == null) return null;
  return h("div", { class: "owed" }, `Paid ${rupees(paid)}`, h("br"), `${rupees(term.value_rupees - paid)} left`);
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
  const box = body.getBoundingClientRect();
  svg.setAttribute("width", body.scrollWidth);
  svg.setAttribute("height", body.scrollHeight);
  const rel = (el) => {
    const r = el.getBoundingClientRect();
    const left = r.left - box.left, top = r.top - box.top;
    return { left, top, right: left + r.width, bottom: top + r.height, cx: left + r.width / 2, cy: top + r.height / 2 };
  };
  const paths = wanted.map(([from, to, kind]) => {
    const a = document.getElementById(from), b = document.getElementById(to);
    if (!a || !b || !body.contains(a) || !body.contains(b)) return null;
    const p = rel(a), q = rel(b);
    let d;
    if (q.left >= p.right - 4 || q.right <= p.left + 4) {
      const [x1, x2] = q.left >= p.right - 4 ? [p.right, q.left] : [p.left, q.right];
      const bend = (x2 - x1) / 2;
      d = `M${x1},${p.cy} C${x1 + bend},${p.cy} ${x2 - bend},${q.cy} ${x2},${q.cy}`;
    } else {
      const [y1, y2] = q.bottom <= p.top ? [p.top, q.bottom] : [p.bottom, q.top];
      const bend = (y2 - y1) / 2;
      d = `M${p.cx},${y1} C${p.cx},${y1 + bend} ${q.cx},${y2 - bend} ${q.cx},${y2}`;
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
    for (const [k, v] of Object.entries({ id: `arrow-${kind}`, viewBox: "0 0 10 10", refX: "9", refY: "5", markerWidth: "5", markerHeight: "5", orient: "auto-start-reverse" }))
      marker.setAttribute(k, v);
    const tip = document.createElementNS(SVG, "path");
    tip.setAttribute("d", "M0,0 L10,5 L0,10 z");
    tip.setAttribute("class", `tip ${kind}`);
    marker.append(tip);
    defs.append(marker);
  }
  svg.append(defs);
  return svg;
}

// Each fact.recorded is one link. Without memory's hash formula in the contract the page
// cannot recompute a fingerprint, so it checks what it can: every link has one, well
// formed, and none repeats.
function renderChain(state) {
  const chain = state.chain;
  $("chain").title = chain.latest || "";
  $("chain").replaceChildren(...(!chain.links ? [] : [
    h("span", { class: "label" }, "Witness chain"),
    h("code", {}, chain.latest ? `${chain.latest.slice(0, 8)}…${chain.latest.slice(-4)}` : "none"),
    h("span", { class: `verdict ${chain.problem ? "bad" : "ok"}` }, chain.problem ? `Broken: ${chain.problem}` : `${chain.links} links, none missing`),
  ]));
}

// ---------- entry points ----------

let lastLinks = [];

export function renderGraph(state, fresh = {}) {
  const box = $("graph");
  const rows = rowsOf(state);
  const any = state.factOrder.length || state.changeOrder.length || state.conflicts.length;
  const facts = state.factOrder.length;
  $("graph-count").textContent = facts ? `${facts} fact${facts > 1 ? "s" : ""}` : "";
  $("conflict-count").textContent = state.conflicts.length ? `${state.conflicts.length} contradiction${state.conflicts.length > 1 ? "s" : ""}` : "";
  if (!any) {
    renderChain(state);
    box.replaceChildren(h("div", { class: "empty" }, "No facts yet. The scribe writes one down each time a term is said."));
    lastLinks = [];
    return;
  }
  const body = h("div", { class: "graph-body" }, svgDefs(),
    ROWS.map(([key, label]) => {
      const row = rows[key];
      const order = (list) => list.sort((a, b) => a.seq - b.seq).map((x) => x.el);
      if (!row.versions.length && !row.below.length) {
        return ITEMS.some(([k]) => k === key)
          ? h("div", { class: "term-row quiet" }, h("div", { class: "term-label" }, label), h("div", { class: "nothing" }, "Nothing said yet"))
          : null;
      }
      return h("div", { class: "term-row" },
        h("div", { class: "term-label" }, label, MONEY.has(key) && moneyLine(row)),
        h("div", { class: "tracks" },
          h("div", { class: "track" }, order(row.versions)),
          row.below.length > 0 && h("div", { class: "track below" }, order(row.below))));
    }));
  box.replaceChildren(body);
  renderChain(state);
  lastLinks = links(state);
  const target = fresh.conflict ? `conflict-${fresh.conflict}` : fresh.changed ? `change-${fresh.changed}` : fresh.fact ? `fact-${fresh.fact}` : null;
  const el = target && document.getElementById(target);
  if (el) el.classList.add(fresh.conflict ? "fresh-conflict" : "fresh");
  if (fresh.conflict) for (const id of state.conflicts.at(-1).factIds) document.getElementById(`fact-${id}`)?.classList.add("fresh-conflict");
  requestAnimationFrame(() => {
    drawLinks(body, lastLinks);
    // Bring the whole term row into view from its top, so a contradiction is seen with
    // the fact it contradicts.
    const row = el?.closest(".term-row");
    if (row) {
      const r = row.getBoundingClientRect(), b = box.getBoundingClientRect();
      if (r.top < b.top || r.bottom > b.bottom) box.scrollTop += r.top - b.top;
    }
  });
}

// Links are measured from the laid-out cards, so they are drawn again whenever the graph
// is shown or the window changes size.
export function relink() {
  const body = document.querySelector("#graph .graph-body");
  if (body) requestAnimationFrame(() => drawLinks(body, lastLinks));
}

addEventListener("resize", relink);
