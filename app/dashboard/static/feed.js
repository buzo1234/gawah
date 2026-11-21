// Facts as they arrive: every fact memory writes, newest on top, with where it was said,
// who said it, the term it belongs to, its clip, and how long after the line it came.
// A voice note's fact says so, with its own waveform.

import { cut, hasClip, took } from "./board.js";
import { h } from "./render.js";
import { clipButton } from "./clips.js";
import { wave } from "./wave.js";

const $ = (id) => document.getElementById(id);
const VALUE_W = 196;
const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;

export function renderFeed(state, view, fresh = null) {
  const rows = view.feed;
  $("graph-count").replaceChildren(String(rows.length),
    ...(state.conflicts.length ? [h("span", { class: "sep" }, " · "), h("span", { class: "contradictions" }, plural(state.conflicts.length, "contradiction"))] : []));
  const standing = new Set(Object.values(view.stands).filter(Boolean).map((f) => f.id));
  const hot = new Set(state.conflicts.flatMap((c) => (view.contradicting(c) ? [view.contradicting(c).id] : [])));
  $("feed").replaceChildren(...rows.map((r) => {
    const f = r.fact;
    const voice = f.source === "voice_note";
    const li = h("li", {
      id: `fact-${f.id}`, "data-item": r.item || "",
      class: ["row", f.status, `kind-${f.kind}`, standing.has(f.id) && "stands", hot.has(f.id) && "hot", fresh === f.id && "enter"].filter(Boolean).join(" "),
      title: [f.text, f.quote && `“${f.quote}”`].filter(Boolean).join("\n"),
    },
      voice ? h("span", { class: "when label src-voice_note", title: "A WhatsApp voice note" }, wave(f.id, 22, 16), "Voice") : h("span", { class: "when label" }, r.when),
      h("span", { class: "what" },
        h("span", { class: "value" }, cut(r.value, VALUE_W, view.measure, "500 18px")),
        h("span", { class: "sub" }, [r.term, r.who].filter(Boolean).join(" · "))),
      h("span", { class: "took label" }, took(r.latency)),
      hasClip(f) ? clipButton(f.id) : h("span", { class: "no-clip" }));
    li.addEventListener("animationend", () => li.classList.remove("enter"));
    return li;
  }));
}
