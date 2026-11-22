// The fact graph on screen: one row per term. On the left the term's node: the value of
// the fact the term stands on (memory's current term, the same fact as the lane's chip
// marked as standing), its state, what is paid and left; out of it, the lane of versions
// (lanes.js), each a chip marked with the colours of the people who said or agreed it,
// green once agreed, struck once replaced, red for a claim, with a red arc back to the
// version it contradicts. A new chip lands at the right end, says how long after its line
// it came, and its connector draws in; the node updates last.

import { graph, visible } from "./lanes.js";
import { TERM_TONE, TERM_WORD, factLatency, rupees, splitMoney, statusWord, took, valueOf, valueParts } from "./board.js";
import { h, measure, pointable, sync } from "./dom.js";
import { nameOf } from "./state.js";

const $ = (id) => document.getElementById(id);
const CHIP_TEXT = 268; // where a chip's words are cut, a little short of where its box wraps them (280)
const GAP = 16; // between chips, where the connector runs
const NODE_TEXT = 288; // the node's 340px less its padding, and a little
const NODE_AFTER = 780; // ms: after the timeline entry (240), the chip (240) and its connector (300)
const WORD = { said: "Said", agreed: "Agreed", confirmed: "Confirmed by both", superseded: "Replaced", disputed: "Disputed", claim: "Contradicted" };

const chipFont = (c) => (["claim", "confirmed", "disputed"].includes(c.status) ? "600 16px" : "500 16px");
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

function node(state, row) {
  const v = row.view;
  const f = row.stands;
  const parts = f ? valueParts(f) : splitMoney(v.value);
  const pending = !f && !v.value;
  const shown = pending ? (row.chips.length ? "Not agreed yet" : "Not said yet")
    : parts.bare ? parts.main : fitLines(parts.main, NODE_TEXT, "500 18px").replace("\n", " ");
  const pill = v.state !== "pending" ? { word: TERM_WORD[v.state], tone: TERM_TONE[v.state] } : f ? statusWord(state, f, new Set()) : null;
  const changed = v.state === "changed" && (row.chips.find((c) => c.stands)?.voice ? "Changed by voice note, both said yes" : "Changed by voice, both said yes");
  return h("div", { class: "node", "data-value": pending ? "" : parts.main, title: [f ? valueOf(f) : v.value, changed, v.note, v.when && `Settled: ${v.when}`].filter(Boolean).join("\n") },
    h("div", { class: "l1" }, h("span", { class: "name label" }, row.label),
      h("span", { class: "pills" },
        pill && h("span", { class: `state pill ${pill.tone || ""}` }, pill.word),
        v.contradicted && h("span", { class: "contradicted pill bad", title: `Contradicted · ${v.contradicted}` }, "Contradicted"))),
    h("div", { class: "l2" },
      h("div", { class: `value${parts.bare ? " money" : ""}${pending ? " none" : ""}` }, shown),
      v.versus ? versusLine(state, v.versus) : owedLine(row.owed)));
}

// A term in dispute: the other version, beside the one on record, in its speaker's words.
function versusLine(state, versus) {
  const fact = state.facts[versus.factId];
  const said = fact?.value_rupees != null ? rupees(fact.value_rupees) : `“${versus.value}”`;
  const who = nameOf(state, versus.by);
  return h("span", { class: "owed versus", title: `${who}'s version: ${versus.value}` }, `${who}: `, fitLines(said, NODE_TEXT / 2, "500 16px").replace("\n", " "));
}

function check() {
  return h("svg", { class: "check", width: 12, height: 12, viewBox: "0 0 12 12", "aria-label": "confirmed by both", role: "img" },
    h("path", { svg: true, d: "M 2 6.5 L 5 9.5 L 10 3" }));
}

function chip(state, c, fresh, before) {
  const lines = chipText(c);
  const lead = state.facts[c.lead];
  const latency = fresh.fact && c.ids.includes(fresh.fact) ? took(factLatency(state, state.facts[fresh.fact])) : "";
  const broken = brokenFact(state);
  const el = h("div", {
    class: ["chip", c.status, `kind-${c.kind}`, c.stands && "stands", c.ids.includes(broken) && "broken",
      fresh.fact && c.ids.includes(fresh.fact) && (before ? "landed" : "enter")].filter(Boolean).join(" "),
    tabindex: 0, role: "button", "data-took": latency || null, "data-value": c.value,
    title: `${c.full}\n${WORD[c.status] || c.status}${lead?.text ? `\n${lead.text}` : ""}`,
  },
    h("span", { class: "who", "aria-hidden": "true" }, ...(c.people.length ? c.people : ["none"]).map((r) => h("i", { class: r }))),
    c.voice && voiceMark(),
    c.status === "confirmed" && check(),
    h("span", { class: "v" }, lines));
  if (latency || (fresh.fact && c.ids.includes(fresh.fact))) setTimeout(() => el.classList.remove("enter", "landed"), 2700);
  return pointable(el, c.ids);
}

function brokenFact(state) {
  const check = state.chainCheck;
  return check && !check.error && !check.verified ? check.first_broken?.fact_id : null;
}

// The red edge: one bracket per version contradicted, over the lane, with one
// "contradicts" label, an arrow down to that version and a tick down to each claim against
// it. A second version contradicted in the same lane gets its bracket one level higher
// (the lane makes room: --levels), so labels never sit on each other. When the lane takes
// a second line, a claim there gets its own bracket in the gap above its line, labelled
// with the version it contradicts, so no line ever crosses a chip. Drawn after the chips
// are laid out, from where they sit.
const LEVEL = 28; // px between bracket levels: a label's 24 and 4 apart (the lane's padding above, per level)
const LABEL_FONT = "600 16px";

const contradicted = (row) => [...new Set(row.edges.map((e) => e.to))];

function arcs(laneEl, row, fresh) {
  const chips = laneEl.querySelector(".chips");
  const svg = laneEl.querySelector("svg.arcs");
  const shown = [...chips.children].filter((el) => !el.hidden);
  const at = (key) => shown.find((el) => el.dataset.key === key);
  const lineOf = new Map();
  let lines = -1, lastTop = -Infinity;
  for (const el of shown) {
    if (el.offsetTop > lastTop + 1) { lines++; lastTop = el.offsetTop; }
    lineOf.set(el, lines);
  }
  const x = (el) => chips.offsetLeft + el.offsetLeft + el.offsetWidth / 2;
  const top = (el) => chips.offsetTop + el.offsetTop; // every line ends on a chip's top edge exactly
  const lineTop = (i) => Math.min(...shown.filter((el) => lineOf.get(el) === i).map(top));
  const r = 6;
  const drawn = [];
  contradicted(row).forEach((to, level) => {
    const edges = row.edges.filter((e) => e.to === to);
    const target = at(to), claims = edges.map((e) => at(e.from)).filter(Boolean);
    if (!target || !claims.length) return;
    const drawing = edges.some((e) => e.id === fresh.conflict);
    for (const line of new Set(claims.map((el) => lineOf.get(el)))) {
      const ends = [target, ...claims].filter((el) => lineOf.get(el) === line).sort((a, b) => x(a) - x(b));
      const home = ends.includes(target);
      const word = home ? "contradicts" : `contradicts ${target.dataset.value}`;
      const w = Math.ceil(measure(word, LABEL_FONT)) + 24;
      const y = lineTop(line) - 16 - (line === 0 ? level * LEVEL : 0);
      const left = ends[0], right = ends.at(-1);
      let d, mid;
      if (ends.length > 1) {
        d = [`M ${x(left)} ${top(left)} V ${y + r} Q ${x(left)} ${y} ${x(left) + r} ${y} H ${x(right) - r} Q ${x(right)} ${y} ${x(right)} ${y + r} V ${top(right)}`,
          ...ends.slice(1, -1).map((el) => `M ${x(el)} ${y} V ${top(el)}`)].join(" ");
        mid = (x(left) + x(right)) / 2;
      } else {
        mid = x(left) + r + w / 2;
        d = `M ${x(left)} ${top(left)} V ${y + r} Q ${x(left)} ${y} ${x(left) + r} ${y}`;
      }
      mid = Math.min(Math.max(mid, w / 2), laneEl.clientWidth - w / 2);
      const tx = x(target), tip = top(target);
      drawn.push(h("g", { svg: true, class: `arc${drawing ? " draw" : ""}`, "data-claims": ends.length - (home ? 1 : 0) },
        h("path", { svg: true, d, pathLength: 100 }),
        home && h("path", { svg: true, class: "head", d: `M ${tx - 5} ${tip - 7} L ${tx} ${tip} L ${tx + 5} ${tip - 7}` }),
        h("rect", { svg: true, class: "tag-bg", x: mid - w / 2, y: y - 12, width: w, height: 24, rx: 6 }),
        h("text", { svg: true, x: mid, y: y + 6, "text-anchor": "middle" }, word)));
    }
  });
  svg.replaceChildren(...drawn);
}

// Every chip is laid out at its own size; if the lane is too short for them all, the
// oldest give way (lanes.js visible()) behind one "n earlier" chip at the start, which
// lists them on hover and points at them.
function lane(state, row, laneEl, fresh) {
  const chips = laneEl.querySelector(".chips");
  sync(chips, [{ stub: true }, ...row.chips],
    (c) => (c.stub ? "stub" : c.key),
    (c) => (c.stub ? "stub" : JSON.stringify([c.value, c.status, c.people, c.stands, c.voice, c.ids.length, c.ids.includes(brokenFact(state))])),
    (c, before) => (c.stub ? pointable(h("div", { class: "chip stub", tabindex: 0 }), []) : chip(state, c, fresh, before)));
  const [stub, ...els] = chips.children;
  for (const el of els) el.hidden = false;
  stub.hidden = false;
  stub.textContent = "00 earlier";
  laneEl.style.setProperty("--levels", Math.max(1, contradicted(row).length));
  // A chip is never narrower than its content, so a figure always shows whole. If the
  // chips that must stay (the standing one, a claim and what it contradicts, the newest)
  // still do not fit, the lane takes a second line.
  const width = new Map(els.map((el) => [el.dataset.key, el.offsetWidth]));
  const broken = brokenFact(state);
  for (const c of row.chips) c.broken = c.ids.includes(broken);
  const { hidden } = visible(row.chips, row.edges, chips.clientWidth, (c) => width.get(c.key), GAP, stub.offsetWidth + GAP);
  const gone = new Set(hidden.map((c) => c.key));
  for (const el of els) el.hidden = gone.has(el.dataset.key);
  stub.hidden = !hidden.length;
  stub.textContent = `${hidden.length} earlier`;
  stub.title = hidden.map((c) => c.value).join("\n");
  stub.dataset.facts = hidden.flatMap((c) => c.ids).join(" ");
  laneEl.classList.toggle("empty", !row.chips.length);
  let prev = null;
  for (const el of chips.children) {
    if (el.hidden) continue;
    el.classList.toggle("line-start", !!prev && el.offsetTop > prev.offsetTop + 1);
    prev = el;
  }
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
    const sig = JSON.stringify([row.view, row.owed?.paid, row.owed?.owed, row.owed?.payments.length, row.chips.length > 0,
      row.stands && [row.stands.id, row.stands.status, row.stands.value]]);
    if (li.dataset.sig !== sig) {
      li.dataset.sig = sig;
      clearTimeout(li._later);
      const moved = (fresh.moved || []).includes(row.key);
      const apply = () => {
        li.querySelector(".node-slot").replaceChildren(node(state, row));
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
