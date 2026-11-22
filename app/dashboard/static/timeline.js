// The timeline: every fact as memory wrote it (moments.js), newest at the top, under quiet
// separators for each moment. Newest at the top because that is where the eye already is
// when something is said: the header, the count and the newest fact sit together, and
// nothing has to scroll for a new fact to be seen. Each entry: the time, who is responsible
// (their name on their colour), the fact in plain words, its term and status, how long
// after its line it came, and its clip. It scrolls on its own; when the viewer has scrolled
// down, new entries go in above without moving what they are reading, and a pill says how
// many are newer.

import { moments, grouped } from "./moments.js";
import { fit, took } from "./board.js";
import { clipButton } from "./clips.js";
import { h, measure, pointable, sync } from "./dom.js";

const $ = (id) => document.getElementById(id);
const TEXT_W = 296;
const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;
let unseen = 0;

function voiceMark() {
  return h("span", { class: "src-voice_note", title: "A WhatsApp voice note" },
    h("svg", { width: 16, height: 16, viewBox: "0 0 16 16", "aria-hidden": "true" },
      ...[[2, 6, 4], [6, 3, 10], [10, 5, 6]].map(([x, y, hh]) => h("rect", { svg: true, x, y, width: 3, height: hh, rx: 1.5 }))),
    "Voice note");
}

function entry(e, fresh, before) {
  const text = fit(e.text, TEXT_W, 2, measure, "400 18px");
  const el = h("li", {
    class: ["entry", e.claim && "claim", e.replaced && "replaced", e.follow && "follow", fresh && (before ? "landed" : "enter")].filter(Boolean).join(" "),
    "data-fact": e.factId, "data-item": e.item, tabindex: 0, title: e.text,
  },
    h("span", { class: "time" }, e.time),
    h("div", { class: "main" },
      h("div", { class: "people" }, ...e.people.map((p) => h("span", { class: `tag ${p.role}` }, p.name)), e.voice && voiceMark()),
      h("p", { class: "text" }, text),
      h("div", { class: "meta label" },
        !e.follow && [h("span", {}, e.term), h("span", { class: "sep" }, " · ")], h("span", { class: `word ${e.tone}` }, e.word),
        e.latency != null && [h("span", { class: "sep" }, " · "), h("span", { class: "took" }, took(e.latency))])),
    e.clip ? clipButton(e.factId) : h("span", { class: "no-clip" }));
  if (fresh) setTimeout(() => el.classList.remove("enter", "landed"), 1900);
  return pointable(el, [e.factId]);
}

export function renderTimeline(state, fresh = {}) {
  const list = moments(state);
  const facts = state.factOrder.length;
  $("fact-count").replaceChildren(...(facts ? [plural(facts, "fact"),
    ...(state.conflicts.length ? [h("span", { class: "sep" }, " · "), h("span", { class: "contradictions" }, plural(state.conflicts.length, "contradiction"))] : [])] : []));
  const items = grouped(list).flatMap((run) => [{ group: true, moment: run.moment, key: `m|${run.moment}|${run.entries.at(-1).key}`, count: run.entries.length }, ...run.entries]);
  const box = $("timeline");
  const scroller = box;
  const away = scroller.scrollTop > 4;
  const anchor = away ? [...box.children].find((el) => el.offsetTop + el.offsetHeight > scroller.scrollTop) : null;
  const anchorTop = anchor ? anchor.offsetTop - scroller.scrollTop : 0;
  const before = box.children.length;
  if (!items.length) {
    box.replaceChildren(h("li", { class: "empty", "data-key": "empty" }, state.dealId ? "Facts appear here the moment they are said." : "Nothing said yet."));
    return;
  }
  box.querySelector(".empty")?.remove();
  sync(box, items, (i) => i.key, (i) => (i.group ? `${i.moment}|${i.count}` : JSON.stringify([i.text, i.word, i.tone, i.people, i.time, i.latency, i.replaced, i.claim])),
    (i, prev) => (i.group
      ? h("li", { class: "moment" }, h("span", { class: "label" }, i.moment), h("span", { class: "label count" }, plural(i.count, "fact")))
      : entry(i, fresh.fact === i.factId, prev)));
  if (anchor && anchor.isConnected) {
    scroller.scrollTop = anchor.offsetTop - anchorTop;
    unseen += Math.max(0, box.children.length - before);
  } else unseen = 0;
  const pill = $("newer");
  pill.hidden = !unseen;
  pill.textContent = unseen ? `↑ ${plural(unseen, "newer entry").replace("entrys", "entries")}` : "";
}

export function watchTimeline() {
  const scroller = $("timeline");
  scroller.addEventListener("scroll", () => {
    if (scroller.scrollTop <= 4 && unseen) { unseen = 0; $("newer").hidden = true; }
  });
  $("newer").addEventListener("click", () => { scroller.scrollTo({ top: 0, behavior: "smooth" }); });
}
