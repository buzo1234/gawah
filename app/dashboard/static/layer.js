// The fact layer, as the deck's slide 9: one term's fact as a card (term and version, the
// value large, the words it came from, who said it, when, its clip, who confirmed it),
// the version before it dashed with "replaced by", a claim that contradicts it in red
// with "contradicts", and the same versions as links of the witness chain under them.
// Under that, the open contradiction as the deck's slide 7, or else the last words said.

import { at, nameOf } from "./state.js";
import { LABEL, cut, hasClip, took, valueOf, whereOf } from "./board.js";
import { h } from "./render.js";
import { clipButton } from "./clips.js";
import { wave } from "./wave.js";

const $ = (id) => document.getElementById(id);
export const SLOT = { side: 190, arrow: 112, main: 312 };

const sideX = { prev: 0, main: SLOT.side + SLOT.arrow, claim: SLOT.side + SLOT.arrow * 2 + SLOT.main };

function big(f, measure, width, money) {
  const v = valueOf(f);
  return money ? v : cut(v, width * 1.7, measure, "600 26px");
}

function arrow(label, tone) {
  return h("div", { class: `arrow ${tone}` },
    h("span", { class: "label" }, label),
    h("span", { class: "line", "aria-hidden": "true" }));
}

function mainCard(state, L, view, fresh) {
  const f = L.current;
  const money = f.value_rupees != null && /^[\d,]+ rupees$/i.test((f.value || "").trim());
  const tone = L.pill === "Agreed" || L.pill === "Confirmed" || L.pill === "Changed" ? "ok" : L.pill === "Disputed" ? "bad" : "";
  const quote = f.quote && cut(`“${f.quote}”`, SLOT.main - 44, view.measure, "400 17px");
  const voice = f.source === "voice_note";
  const el = h("div", {
    class: ["fact-card", f.status, tone, L.claim && "contradicted", fresh && "enter"].filter(Boolean).join(" "),
    "data-fact": f.id, style: `left: ${sideX.main}px; width: ${SLOT.main}px`, title: [f.text, f.quote && `“${f.quote}”`].filter(Boolean).join("\n"),
  },
    h("div", { class: "head" }, h("span", { class: "label" }, `${L.label} · v${L.version}`), h("span", { class: `pill ${tone}` }, L.pill)),
    h("div", { class: `big${money ? " money" : ""}` }, big(f, view.measure, SLOT.main - 44, money)),
    quote && h("div", { class: "quote" }, quote),
    h("dl", {},
      h("dt", {}, "Said by"), h("dd", {}, L.said || "—"),
      h("dt", {}, "When"), h("dd", {}, whereOf(f)),
      h("dt", {}, "Clip"), h("dd", { class: "clip" },
        hasClip(f) ? [clipButton(f.id), wave(f.id, voice ? 96 : 150, 22, `wave${tone === "ok" || voice ? " ok" : ""}`), voice && h("span", { class: "label" }, "Voice note")]
          : h("span", { class: "none" }, f.source === "screenshot" ? "Screenshot" : "None")),
      h("dt", {}, "Confirmed"), h("dd", {}, L.confirmed)));
  el.addEventListener("animationend", () => el.classList.remove("enter"));
  return el;
}

// The parts joined with " · ", as many as fit on a side card, the first cut at a word.
function fits(parts, view) {
  const [first, ...rest] = parts.filter(Boolean);
  let text = cut(first, SLOT.side - 32, view.measure, "400 16px");
  for (const part of rest) if (view.measure(`${text} · ${part}`, "400 16px") <= SLOT.side - 32) text += ` · ${part}`;
  return text;
}

function sideCard(kind, x, head, value, who, title) {
  return h("div", { class: `side-card ${kind}`, style: `left: ${x}px; width: ${SLOT.side}px`, title },
    h("span", { class: "label" }, head), h("div", { class: "value" }, value), h("div", { class: "who" }, who));
}

function renderLayer(state, view, change) {
  const L = view.layer;
  $("layer-title").textContent = `The fact layer · ${L.label}`;
  $("layer-time").textContent = L.latency != null ? `Fact in ${took(L.latency)}` : "";
  if (!L.current) {
    $("layer").replaceChildren(h("div", { class: "empty-card", style: `left: ${sideX.main}px; width: ${SLOT.main}px` },
      h("span", { class: "label" }, L.label), h("div", {}, "Nothing said about it yet")));
    $("chain-row").replaceChildren();
    return;
  }
  const fresh = change.fact === L.current.id || change.changed;
  const parts = [];
  if (L.previous) {
    const p = L.previous;
    parts.push(sideCard("previous", sideX.prev, `v${p.version} · ${p.fact.source === "call" ? `call ${p.fact.call_no ?? 1}` : whereOf(p.fact)}`, cut(p.value, SLOT.side - 32, view.measure, "600 22px"),
      fits([`${p.note}${p.who ? ` · ${p.who}` : ""}`, L.earlier && `${L.earlier} earlier`], view), p.fact.text));
    parts.push(h("div", { class: "arrow-slot", style: `left: ${SLOT.side}px; width: ${SLOT.arrow}px` }, arrow("replaced by", "old")));
  }
  parts.push(mainCard(state, L, view, fresh));
  if (L.claim) {
    const c = L.claim;
    parts.push(h("div", { class: "arrow-slot", style: `left: ${SLOT.side + SLOT.arrow + SLOT.main}px; width: ${SLOT.arrow}px` }, arrow("contradicts", "bad")));
    parts.push(sideCard(`claim${change.conflict === c.conflict.id ? " enter" : ""}`, sideX.claim, `Claim · ${c.where}`, cut(c.value, SLOT.side - 32, view.measure, "600 22px"), c.who, c.conflict.explanation));
  }
  $("layer").replaceChildren(...parts);
  renderChainRow(state, L);
}

// The term's versions as links: "v1 · #prev + this", in green when verified, red from
// a broken link on.
export function renderChainRow(state, L) {
  if (!L.current) return $("chain-row").replaceChildren();
  const check = state.chainCheck;
  const broken = check && !check.error && !check.verified ? (check.first_broken?.index ?? -1) + 1 : null;
  const checked = check && !check.error ? check.links : 0;
  const x = { old: sideX.prev, ok: sideX.main, "": sideX.main, bad: sideX.claim };
  const w = { old: SLOT.side, ok: SLOT.main, "": SLOT.main, bad: SLOT.side };
  const boxes = L.chain.map((link) => {
    const n = link.fact.last;
    const state_ = broken != null && n >= broken ? "broken" : n <= checked ? "verified" : "waiting";
    return h("div", {
      class: `link-box ${link.tone} ${state_}`, style: `left: ${x[link.tone]}px; width: ${w[link.tone]}px`,
      title: `Link ${n} of the witness chain${link.fact.hash ? `: ${link.fact.hash.slice(0, 16)}…` : ""}`,
    }, h("span", { class: "name" }, link.label), h("span", { class: "label" }, state_ === "broken" ? "broken" : "#prev + this"));
  });
  const first = L.chain[0], last = L.chain.at(-1);
  const rule = L.chain.length > 1 && h("div", { class: "chain-rule", style: `left: ${x[first.tone] + w[first.tone]}px; width: ${x[last.tone] - x[first.tone] - w[first.tone]}px` });
  $("chain-row").replaceChildren(...[rule, ...boxes].filter(Boolean));
}

// The deck's slide 7: what was claimed, struck through, beside what was agreed, and the
// moment it was agreed, to play.
function conflictCard(state, open, view, fresh) {
  const { conflict: c, agreed, claim } = open;
  const claimed = claim ? valueOf(claim) : c.said ? `“${c.said}”` : "";
  const start = c.lineNo == null ? null : state.lines[`${c.callNo}:${c.lineNo}`]?.start;
  const el = h("div", { class: `conflict card${fresh ? " enter" : ""}`, id: `conflict-${c.id}`, title: c.explanation },
    h("div", { class: "head" },
      h("span", { class: "pill bad" }, "Contradiction"),
      h("span", { class: "label" }, [LABEL[open.item], c.lineNo != null ? at(c.callNo, start) : "On WhatsApp", open.latency != null && `raised in ${took(open.latency)}`].filter(Boolean).join(" · "))),
    c.said && h("div", { class: "said" }, cut(`${nameOf(state, c.speaker)}: “${c.said}”`, 800, view.measure, "400 18px")),
    h("div", { class: "versus" },
      h("div", { class: "now" }, h("span", { class: "who" }, `${nameOf(state, claim?.said_by || c.speaker)}, now`), h("s", { class: "value" }, cut(claimed, 380, view.measure, "600 48px"))),
      h("div", { class: "then" }, h("span", { class: "who" }, `Agreed, ${whereOf(agreed).replace(" · ", ", ")}`), h("span", { class: "value" }, cut(valueOf(agreed), 380, view.measure, "600 48px")))),
    h("div", { class: "moment" },
      hasClip(agreed) ? clipButton(agreed.id) : h("span", { class: "mark-off" }),
      wave(agreed.id, 560, 30, "wave ok"),
      h("span", { class: "moment-label" }, "Original moment")));
  el.addEventListener("animationend", () => el.classList.remove("enter"));
  return el;
}

// The last few things said on the call, Gawah's own words in green, as slide 7 quotes them.
function lastWords(state, view) {
  const t = view.tracks;
  const said = [...t.lines.map((l) => ({ start: l.start, who: nameOf(state, l.speaker), text: l.text, gawah: false })),
    ...t.voice.map((v) => ({ start: v.start, who: "Gawah", text: v.text, gawah: true }))].sort((a, b) => a.start - b.start).slice(-3);
  return h("div", { class: "last-words" },
    h("span", { class: "label" }, said.length ? `Last words · call ${t.callNo}` : "Last words"),
    ...(said.length ? said.map((s) => h("div", { class: `said${s.gawah ? " gawah" : ""}` },
      h("span", { class: "label" }, s.who), h("span", { class: "text" }, cut(`“${s.text}”`, 690, view.measure, "400 20px"))))
      : [h("div", { class: "said none" }, "Nothing said on a call yet.")]));
}

export function renderLayerAndBelow(state, view, change = {}) {
  renderLayer(state, view, change);
  const open = view.open;
  $("below").replaceChildren(open ? conflictCard(state, open, view, change.conflict === open.conflict.id) : lastWords(state, view));
}
