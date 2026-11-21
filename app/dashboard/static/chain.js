// The witness chain, checked by memory: GET /memory/chain/<deal> recomputes every link's
// hash (the formula is in app/memory/chain.py) and names the first link that does not
// match. Asked when a deal loads and after new facts, at most once every few seconds;
// a request that comes in the gap is sent when the gap is over.

import { ITEMS } from "./state.js";
import { h } from "./render.js";

const $ = (id) => document.getElementById(id);
const ITEM_LABEL = Object.fromEntries(ITEMS);

const GAP_MS = 3000;
let timer = null;
let busy = false;
let lastAt = 0;
let wanted = null; // { state, done }: the newest request

export function checkChain(state, done) {
  if (!state.dealId) return;
  wanted = { state, done };
  if (timer || busy) return;
  timer = setTimeout(run, Math.max(0, lastAt + GAP_MS - Date.now()));
}

async function run() {
  timer = null;
  const { state, done } = wanted;
  wanted = null;
  busy = true;
  lastAt = Date.now();
  try {
    const response = await fetch(`/memory/chain/${encodeURIComponent(state.dealId)}`);
    state.chainCheck = response.ok ? await response.json() : { error: `memory answered ${response.status}` };
  } catch {
    state.chainCheck = { error: "memory did not answer" };
  }
  busy = false;
  done(state);
  if (wanted) checkChain(wanted.state, wanted.done);
}

// Each fact.recorded is one link. The page shows memory's answer: verified with the
// number of links, or the first link that is broken.
function brokenAt(state, broken) {
  const f = state.facts[broken.fact_id];
  const what = f ? [ITEM_LABEL[f.item] || f.kind, f.line_no != null && `call ${f.call_no ?? 1} line ${f.line_no}`].filter(Boolean).join(", ") : broken.fact_id;
  return `broken at link ${broken.index + 1} (${what})`;
}

// The chain as a strip along the bottom, one link per fact.recorded, grouped by where it
// was sealed (call 1, WhatsApp on a day, call 2): links memory has verified in the "ok"
// colour, the broken one and everything after it in red, new ones not yet checked grey.
const STRIP = { x: 8, width: 1030, step: 22, glyph: 10 };
let drawn = 0;

function drawLinks(state, live) {
  const svg = $("chain-links");
  const list = state.chain.list;
  const check = state.chainCheck;
  const broken = check && !check.error && !check.verified ? check.first_broken?.index ?? null : null;
  const checked = check && !check.error ? check.links : 0;
  const groups = [];
  for (const [i, link] of list.entries()) {
    if (groups.at(-1)?.where !== link.where) groups.push({ where: link.where, from: i, to: i });
    else groups.at(-1).to = i;
  }
  // Each stretch is as wide as its links, and never narrower than its name.
  const gapW = 18;
  const named = (g) => g.where.length * 8.4 + 12;
  let step = STRIP.step;
  const total = () => groups.reduce((sum, g) => sum + Math.max((g.to - g.from + 1) * step, named(g)) + gapW, 0);
  while (step > 6 && total() > STRIP.width) step -= 1;
  let left = STRIP.x;
  for (const g of groups) {
    g.left = left;
    left += Math.max((g.to - g.from + 1) * step, named(g)) + gapW;
  }
  const x = (i) => {
    const g = groups.find((gr) => i >= gr.from && i <= gr.to);
    return g.left + (i - g.from) * step + step / 2;
  };
  const NS = "http://www.w3.org/2000/svg";
  const el = (tag, attrs) => {
    const e = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
    return e;
  };
  const parts = [];
  for (const g of groups) {
    const label = el("text", { x: g.left, y: 16, class: "where" });
    label.textContent = g.where;
    parts.push(label, el("line", { x1: g.left, y1: 24, x2: g.left, y2: 58, class: "tick" }));
  }
  for (const [i, link] of list.entries()) {
    const tone = broken != null && i >= broken ? (i === broken ? "broken" : "after") : i < checked ? "ok" : "waiting";
    if (i && groups.some((g) => g.from === i) === false) parts.push(el("line", { x1: x(i - 1) + STRIP.glyph / 2, y1: 44, x2: x(i) - STRIP.glyph / 2, y2: 44, class: `joint ${tone}` }));
    const rect = el("rect", { x: x(i) - STRIP.glyph / 2, y: 34, width: STRIP.glyph, height: 20, rx: 5, class: `link-glyph ${tone}${live && i >= drawn ? " enter" : ""}` });
    const title = el("title", {});
    title.textContent = `Link ${i + 1}: ${state.facts[link.factId]?.text || link.factId} (${link.status})`;
    rect.append(title);
    parts.push(rect);
  }
  svg.replaceChildren(...parts);
  drawn = list.length;
}

export function renderChain(state, live = false) {
  const check = state.chainCheck;
  const links = state.chain.links;
  const el = $("chain");
  const plural = (n) => `${n} link${n === 1 ? "" : "s"}`;
  const [tone, text] = !check ? ["wait", `checking ${plural(links)}`]
    : check.error ? ["wait", `not checked: ${check.error}`]
    : !check.verified ? ["bad", brokenAt(state, check.first_broken)]
    : ["ok", `verified · ${plural(check.links)}${links > check.links ? ` · checking ${links - check.links} new` : ""}`];
  const head = check?.verified && check.links ? check.head : null;
  el.title = head ? `Head of the chain: ${head}` : "";
  el.className = `chain ${tone}`;
  el.replaceChildren(...(!links && !check?.links ? [] : ["Witness chain ", h("span", { class: "verdict" }, text)]));
  $("chain-head").textContent = head ? `head ${head.slice(0, 12)}` : "";
  drawLinks(state, live);
}
