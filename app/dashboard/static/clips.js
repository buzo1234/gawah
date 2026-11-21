// A fact's few seconds of the call, cut by memory from the recordings (/memory/clip/<id>).
// One plays at a time; pressing the playing one again stops it.

import { h } from "./render.js";

export const clipPath = (factId) => `/memory/clip/${factId}`;

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

// The mark is drawn in CSS: the fact's source (a call line, a call-back, a voice note),
// a triangle to play on hover, a square while playing.
export const clipButton = (factId, label = null, source = null) =>
  h("button", {
    type: "button", class: `play${label ? " labelled" : ""}${source ? ` src-${source}` : ""}`, title: "Play where it was said", "aria-label": label || "Play where it was said",
    onclick: (ev) => playClip(factId, ev.currentTarget),
  }, h("span", { class: "mark", "aria-hidden": "true" }), label);

// Where a fact came from, for one with nothing to play: a WhatsApp text, a screenshot, a
// change asked for.
export const sourceMark = (source) => h("span", { class: `src src-${source}`, "aria-hidden": "true" }, h("span", { class: "mark" }));
