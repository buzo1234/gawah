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
  return `Broken at link ${broken.index + 1} (${what})`;
}

export function renderChain(state) {
  const check = state.chainCheck;
  const links = state.chain.links;
  const verdict = !check ? ["wait", `checking ${links} links`]
    : check.error ? ["wait", `not checked: ${check.error}`]
    : !check.verified ? ["bad", brokenAt(state, check.first_broken)]
    : ["ok", `Verified, ${check.links} link${check.links === 1 ? "" : "s"}${links > check.links ? ` · checking ${links - check.links} new` : ""}`];
  const head = check?.verified && check.links ? check.head : null;
  $("chain").title = head ? `Head of the chain: ${head}` : "";
  $("chain").replaceChildren(...(!links && !check?.links ? [] : [
    h("span", { class: "label" }, "Witness chain"),
    head && h("code", {}, `${head.slice(0, 8)}…${head.slice(-4)}`),
    h("span", { class: `verdict ${verdict[0]}` }, verdict[1]),
  ].filter(Boolean)));
}
