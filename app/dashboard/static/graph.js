// The fact graph on screen: one row per term. On the left the term's node, as the contract
// has it (its value, its state, what is paid and left); out of it, the lane of versions
// (lanes.js), each a chip marked with the colours of the people who said or agreed it,
// green once agreed, struck once replaced, red for a claim, with a red arc back to the
// version it contradicts. A new chip lands at the right end, says how long after its line
// it came, and its connector draws in; the node updates last.

import { graph, visible } from "./lanes.js";
import { TERM_TONE, TERM_WORD, factLatency, rupees, splitMoney, took } from "./board.js";
import { h, measure, pointable, sync } from "./dom.js";

const $ = (id) => document.getElementById(id);
const CHIP_TEXT = 140; // where a chip's words are cut, a little short of where its box wraps them (152)
const GAP = 16; // between chips, where the connector runs
const NODE_TEXT = 248;
const NODE_AFTER = 780; // ms: after the timeline entry (240), the chip (240) and its connector (300)
const WORD = { said: "Said", agreed: "Agreed", confirmed: "Confirmed by both", superseded: "Replaced", disputed: "Disputed", claim: "Contradicted", paid: "Paid" };

const chipFont = (c) => (["claim", "confirmed", "paid", "disputed"].includes(c.status) ? "600 16px" : "500 16px");
const chipText = (c) => fitLines(c.value, CHIP_TEXT, chipFont(c));

// Words laid in two lines as the browser will, cut at a word; "\n" only marks the measure.
function fitLines(text, width, font) {
  const words = (text || "").split(/[ \t\n]+/);
  const lines = [""];
  for (let i = 0; i < words.length; i++) {
    const next = lines.at(-1) ? `${lines.at(-1)} ${words[i]}` : words[i];
    if (measure(next, font) <= width || !lines.at(-1)) { lines[lines.length - 1] = next; continue; }
    if (lines.length === 2) {
      let last = lines[1];
      while (last.includes(" ") && measure(`${last}…`, font) > width) last = last.slice(0, last.lastIndexOf(" "));
      lines[1] = `${last.replace(/[\s;:,.\-–—(]+$/, "")}…`;
      break;
    }
    lines.push(words[i]);
  }
  return lines.join("\n");
}

const oneLine = (text, width, font) => {
  if (measure(text, font) <= width) return text;
  const words = text.split(/[ \t\n]+/);
  for (let n = words.length - 1; n > 0; n--) {
    const short = `${words.slice(0, n).join(" ").replace(/[\s;:,.\-–—(]+$/, "")}…`;
    if (measure(short, font) <= width) return short;
  }
  return text;
};

function voiceMark() {
  return h("svg", { class: "voice-mark", width: 16, height: 16, viewBox: "0 0 16 16", "aria-label": "voice note", role: "img" },
    ...[[2, 6, 4], [6, 3, 10], [10, 5, 6]].map(([x, y, hh]) => h("rect", { svg: true, x, y, width: 3, height: hh, rx: 1.5 })));
}

function owedLine(r) {
  if (!r?.payments.length || r.agreed == null) return null;
  return h("span", { class: "owed", title: `${rupees(r.agreed)} agreed` }, `Paid ${rupees(r.paid)}`, h("span", { class: "sep" }, " · "), `${rupees(r.owed)} left`);
}

function node(row) {
  const v = row.view;
  const parts = splitMoney(v.value);
  const money = parts.bare;
  const shown = !v.value ? (row.chips.length ? "Not agreed yet" : "Not said yet") : money ? parts.main : oneLine(parts.main, NODE_TEXT, "500 18px");
  const changed = v.state === "changed" && (row.chips.find((c) => c.stands)?.voice ? "Changed by voice note, both said yes" : "Changed by voice, both said yes");
  return h("div", { class: "node", title: [v.value, changed, v.note, v.when && `Settled: ${v.when}`].filter(Boolean).join("\n") },
    h("div", { class: "l1" }, h("span", { class: "name label" }, row.label), owedLine(row.owed)),
    h("div", { class: `value${money ? " money" : ""}${v.value ? "" : " none"}` }, shown),
    h("div", { class: "l3" },
      h("span", { class: `state pill ${TERM_TONE[v.state] || ""}` }, TERM_WORD[v.state]),
      v.contradicted && h("span", { class: "contradicted pill bad", title: `Contradicted · ${v.contradicted}` }, "Contradicted")));
}

function chip(state, c, fresh, before) {
  const lines = chipText(c);
  const lead = state.facts[c.lead];
  const latency = fresh.fact && c.ids.includes(fresh.fact) ? took(factLatency(state, state.facts[fresh.fact])) : "";
  const broken = brokenFact(state);
  const el = h("div", {
    class: ["chip", c.status, `kind-${c.kind}`, c.stands && "stands", c.ids.includes(broken) && "broken",
      fresh.fact && c.ids.includes(fresh.fact) && (before ? "landed" : "enter")].filter(Boolean).join(" "),
    tabindex: 0, role: "button", "data-took": latency || null,
    title: `${c.full}\n${WORD[c.status] || c.status}${lead?.text ? `\n${lead.text}` : ""}`,
  },
    h("span", { class: "who", "aria-hidden": "true" }, ...(c.people.length ? c.people : ["none"]).map((r) => h("i", { class: r }))),
    c.voice && voiceMark(),
    h("span", { class: "v" }, lines.replace("\n", " ")));
  if (latency || (fresh.fact && c.ids.includes(fresh.fact))) setTimeout(() => el.classList.remove("enter", "landed"), 2700);
  return pointable(el, c.ids);
}

function brokenFact(state) {
  const check = state.chainCheck;
  return check && !check.error && !check.verified ? check.first_broken?.fact_id : null;
}

// The red edge: from the claim's chip, up and back along the lane to the version it
// contradicts, labelled. Drawn after the chips are laid out, from where they sit.
function arcs(laneEl, row, fresh) {
  const chips = laneEl.querySelector(".chips");
  const svg = laneEl.querySelector("svg.arcs");
  const at = (key) => [...chips.children].find((el) => el.dataset.key === key);
  const paths = row.edges.map((e) => {
    const a = at(e.from), b = at(e.to);
    if (!a || !b) return null;
    const x1 = chips.offsetLeft + a.offsetLeft + a.offsetWidth / 2, x2 = chips.offsetLeft + b.offsetLeft + b.offsetWidth / 2;
    const y = a.offsetTop + chips.offsetTop - 2, top = 12, r = 6, dir = x2 < x1 ? -1 : 1;
    const mid = (x1 + x2) / 2;
    // up from the claim, along, and down onto the version it contradicts, with an arrowhead
    const d = `M ${x1} ${y} V ${top + r} Q ${x1} ${top} ${x1 + dir * r} ${top} H ${x2 - dir * r} Q ${x2} ${top} ${x2} ${top + r} V ${b.offsetTop + chips.offsetTop - 2}`;
    const tip = b.offsetTop + chips.offsetTop - 2;
    const drawing = fresh.conflict === e.id;
    return h("g", { svg: true, class: `arc${drawing ? " draw" : ""}` },
      h("path", { svg: true, d, pathLength: 100 }),
      h("path", { svg: true, class: "head", d: `M ${x2 - 5} ${tip - 7} L ${x2} ${tip} L ${x2 + 5} ${tip - 7}` }),
      h("rect", { svg: true, class: "tag-bg", x: mid - 52, y: top - 10, width: 104, height: 20, rx: 6 }),
      h("text", { svg: true, x: mid, y: top + 5, "text-anchor": "middle" }, "contradicts"));
  });
  svg.replaceChildren(...paths.filter(Boolean));
}

// Every chip is laid out at its own size; if the lane is too short for them all, the
// oldest give way (lanes.js visible()) behind one "+n" chip at the start.
function lane(state, row, laneEl, fresh) {
  const chips = laneEl.querySelector(".chips");
  sync(chips, [{ stub: true }, ...row.chips],
    (c) => (c.stub ? "stub" : c.key),
    (c) => (c.stub ? "stub" : JSON.stringify([c.value, c.status, c.people, c.stands, c.voice, c.ids.length, c.ids.includes(brokenFact(state))])),
    (c, before) => (c.stub ? pointable(h("div", { class: "chip stub", tabindex: 0 }), []) : chip(state, c, fresh, before)));
  const [stub, ...els] = chips.children;
  for (const el of els) el.hidden = false;
  stub.hidden = false;
  stub.textContent = "+00";
  const width = new Map(els.map((el) => [el.dataset.key, el.offsetWidth]));
  const { hidden } = visible(row.chips, row.edges, chips.clientWidth, (c) => width.get(c.key), GAP, stub.offsetWidth + GAP);
  const gone = new Set(hidden.map((c) => c.key));
  for (const el of els) el.hidden = gone.has(el.dataset.key);
  stub.hidden = !hidden.length;
  stub.textContent = `+${hidden.length}`;
  stub.title = hidden.map((c) => c.value).join("\n");
  stub.dataset.facts = hidden.flatMap((c) => c.ids).join(" ");
  laneEl.classList.toggle("empty", !row.chips.length);
  arcs(laneEl, row, fresh);
}

export function renderGraph(state, fresh = {}) {
  const rows = graph(state);
  const settled = rows.filter((r) => ["agreed", "confirmed", "changed"].includes(r.view.state)).length;
  $("settled-count").textContent = state.dealId ? `${settled} of ${rows.length} settled` : "";
  const list = $("rows");
  if (list.children.length !== rows.length) {
    list.replaceChildren(...rows.map((r) => h("li", { class: "term", "data-item": r.key },
      h("div", { class: "node-slot" }), h("div", { class: "lane" }, h("div", { class: "chips" }), h("svg", { class: "arcs", "aria-hidden": "true" })))));
  }
  rows.forEach((row, i) => {
    const li = list.children[i];
    const sig = JSON.stringify([row.view, row.owed?.paid, row.owed?.owed, row.owed?.payments.length]);
    if (li.dataset.sig !== sig) {
      li.dataset.sig = sig;
      clearTimeout(li._later);
      const moved = (fresh.moved || []).includes(row.key);
      const apply = () => {
        li.querySelector(".node-slot").replaceChildren(node(row));
        li.className = ["term", row.view.state, row.view.contradicted && "contradicted", moved && (row.view.contradicted ? "pulse" : "moved")].filter(Boolean).join(" ");
        li.dataset.when = row.view.when || "";
        if (moved) li._later = setTimeout(() => li.classList.remove("moved", "pulse"), 1000);
      };
      // The term's state changes last, once its chip has landed and its connector drawn.
      if (moved && (fresh.fact || fresh.conflict || fresh.changed)) li._later = setTimeout(apply, NODE_AFTER);
      else apply();
    }
    pointable(li.querySelector(".node-slot"), row.chips.filter((c) => c.stands).flatMap((c) => c.ids));
    lane(state, row, li.querySelector(".lane"), fresh);
  });
}
