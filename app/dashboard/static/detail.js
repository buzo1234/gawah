// The card under the graph. While a contradiction is open it is the deck's slide 7: what
// was just claimed, struck through, beside what was agreed and when, the words said, and
// the original moment to play. Otherwise it is slide 9 for one fact: the fact that just
// landed, or the one pointed at on the graph or the timeline: its term and version, the
// value large, the words it came from, who said and agreed it, when, its clip, who
// confirmed it, and how long after its line memory wrote it. With no deal, or before the
// call, it says what will happen.

import { ITEMS, at, termView } from "./state.js";
import { standing } from "./crew-state.js";
import { lane } from "./lanes.js";
import { LABEL, confirmedBy, factLatency, fit, hasClip, openConflict, person, statusWord, took, valueParts, whereOf } from "./board.js";
import { clipButton } from "./clips.js";
import { wave } from "./wave.js";
import { h, measure } from "./dom.js";

const $ = (id) => document.getElementById(id);

// The fact to show for a set of ids pointed at: the one its term stands on, else the newest.
function chosen(state, ids) {
  const facts = ids.map((id) => state.facts[id]).filter(Boolean);
  return facts.find((f) => f.item && standing(state, f.item)?.id === f.id) || facts.reduce((a, b) => (!a || b.seq > a.seq ? b : a), null);
}

// The fact the newest link of the chain is about; a version re-sent as replaced points at
// what replaced it.
function latest(state) {
  const link = state.chain.list.findLast((l) => l.status !== "superseded");
  return link ? state.facts[link.factId] : null;
}

const tag = (p) => h("span", { class: `tag ${p.role}` }, p.name);

function factCard(state, f) {
  const item = f.item;
  const parts = valueParts(f);
  const stands = item && standing(state, item)?.id === f.id;
  const view = item && ITEMS.some(([k]) => k === item) ? termView(state, item) : null;
  const n = item ? lane(state, item).chips.findIndex((c) => c.ids.includes(f.id)) + 1 : 0;
  const { word, tone } = stands && view?.state === "changed" ? { word: "Changed", tone: "ok" } : statusWord(state, f);
  const latency = factLatency(state, f);
  const agreed = [...new Set([...(f.agreed_by || []), ...(f.confirmed_by || [])])].filter((r) => r !== f.said_by && (r === "hirer" || r === "worker"));
  const sub = [parts.rest, f.quote && f.quote.trim() !== parts.rest.trim() && `“${f.quote}”`].filter(Boolean).join(" · ");
  const voice = f.source === "voice_note";
  return h("div", { class: "fact-card", "data-fact": f.id },
    h("div", { class: "head" },
      h("span", { class: "label" }, [LABEL[item] || "Other detail", n > 0 && `v${n}`].filter(Boolean).join(" · ")),
      h("span", { class: `pill ${tone}` }, word),
      h("span", { class: "label took" }, latency != null ? `Written ${took(latency)} after it was said` : voice ? "From a WhatsApp voice note" : f.source === "call" || f.source === "callback" ? "" : "From WhatsApp")),
    h("div", { class: "body" },
      h("div", { class: "what" },
        h("div", { class: `hero${parts.money ? " money" : ""}`, title: parts.main }, parts.money ? parts.main : fit(parts.main, 420, 2, measure, "600 24px")),
        sub && h("p", { class: "quote", title: sub }, fit(sub, 420, parts.money ? 2 : 1, measure, "400 16px"))),
      h("dl", {},
        h("dt", {}, "Said by"), h("dd", {}, f.said_by ? tag(person(state, f.said_by)) : tag(person(state, null)),
          agreed.length ? [h("span", { class: "and" }, "agreed by"), ...agreed.map((r) => tag(person(state, r)))] : null),
        h("dt", {}, "When"), h("dd", {}, whereOf(f)),
        h("dt", {}, "Clip"), h("dd", { class: "clip" }, hasClip(f)
          ? [clipButton(f.id), wave(f.id, 200, 24, "wave ok")]
          : h("span", { class: "none" }, f.source === "screenshot" ? "A screenshot, no audio" : "No audio")),
        h("dt", {}, "Confirmed"), h("dd", {}, confirmedBy(state, f, stands ? view : null)))));
}

// The deck's slide 7.
function conflictCard(state, open) {
  const { conflict: c, agreed, claim } = open;
  const claimed = claim ? valueParts(claim).main : c.said ? `“${c.said}”` : "";
  const start = c.lineNo == null ? null : state.lines[`${c.callNo}:${c.lineNo}`]?.start;
  const who = person(state, claim?.said_by || c.speaker);
  const both = (agreed.confirmed_by || []).length >= 2 ? "Confirmed by both" : (agreed.agreed_by || []).length ? "Agreed by both" : "Agreed";
  const said = c.said ? `${who.name}: “${c.said}”` : c.explanation;
  return h("div", { class: "conflict-card", id: `conflict-${c.id}`, title: c.explanation },
    h("div", { class: "head" },
      h("span", { class: "pill bad" }, "Contradicted"),
      h("span", { class: "label" }, [LABEL[open.item], c.lineNo != null ? at(c.callNo, start) : "On WhatsApp"].filter(Boolean).join(" · ")),
      h("span", { class: "label took bad" }, open.latency != null ? `Caught ${took(open.latency)} after it was said` : "")),
    h("div", { class: "body" },
      h("div", { class: "now" }, h("span", { class: "who" }, tag(who), "now"), h("s", { class: "value" }, claimed)),
      h("div", { class: "then" }, h("span", { class: "who" }, `${both} · ${whereOf(agreed)}`), h("span", { class: "value" }, valueParts(agreed).main)),
      h("div", { class: "proof" },
        h("p", { class: "said", title: said }, fit(said, 268, 2, measure, "400 16px")),
        h("div", { class: "moment" },
          hasClip(agreed) ? clipButton(agreed.id) : h("span", { class: "mark-off" }),
          wave(agreed.id, 120, 24, "wave ok"),
          h("span", { class: "moment-label" }, "Original moment")))));
}

// Before anything is said: how a deal is witnessed, in three steps, the one reached marked.
const STEPS = [
  ["On WhatsApp", "The hirer sends Gawah the worker’s number. Both get a call link."],
  ["On the call", "Gawah listens. Each term lands here the moment it is said, with who said it."],
  ["After", "Both confirm on a call-back; payments and changes arrive on WhatsApp."],
];
function emptyCard(state) {
  const reached = state.dealId ? 1 : 0;
  return h("div", { class: "empty-card" },
    h("span", { class: "label" }, state.dealId ? "Waiting for the call" : "No deal yet"),
    h("ol", { class: "steps" }, ...STEPS.map(([title, text], i) => h("li", { class: i === reached ? "now" : i < reached ? "done" : "" },
      h("span", { class: "n" }, String(i + 1)), h("div", {}, h("b", {}, title), h("p", {}, text))))));
}

let shownKey = null;
let later = null;
// ms: a new fact's card comes in with its chip; the contradiction once its edge has drawn.
const AFTER_FACT = 240, AFTER_CONFLICT = 880;

export function renderDetail(state, ids = null, fresh = {}) {
  const open = !ids && openConflict(state);
  const f = ids ? chosen(state, ids) : open ? null : latest(state);
  const key = JSON.stringify(open ? ["c", open.conflict.id, open.claim?.id, open.agreed.id, open.latency]
    : f ? ["f", f.id, f.status, f.confirmed_by, f.agreed_by, state.chainCheck?.verified, termView(state, f.item || "work").state] : ["e", state.dealId]);
  if (key === shownKey) return;
  shownKey = key;
  const card = open ? conflictCard(state, open) : f ? factCard(state, f) : emptyCard(state);
  const drawing = open && fresh.conflict === open.conflict.id;
  const landing = !ids && !open && (fresh.fact || fresh.changed);
  clearTimeout(later);
  const show = () => {
    if (drawing) card.classList.add("enter");
    if (landing) card.classList.add("swap");
    $("detail").replaceChildren(card);
    if (drawing || landing) later = setTimeout(() => card.classList.remove("enter", "swap"), 1000);
  };
  if (drawing || landing) later = setTimeout(show, drawing ? AFTER_CONFLICT : AFTER_FACT);
  else show();
}
