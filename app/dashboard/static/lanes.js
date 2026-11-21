// The crew's lanes: one per agent, its latest agent.note lines, newest on top. A lane
// pulses once when its agent acts; a lane with no notes yet stays quiet.

import { AGENTS } from "./crew-state.js";
import { h } from "./render.js";

export function renderLanes(state, pulse = null) {
  document.getElementById("lanes").replaceChildren(...AGENTS.map(([key, name, job]) => {
    const notes = state.notes[key];
    return h("section", { class: `lane${notes.length ? "" : " quiet"}${pulse === key ? " pulse" : ""}`, "data-agent": key },
      h("h3", {}, h("span", { class: "dot" }), name),
      h("div", { class: "job" }, job),
      h("ol", {}, notes.map((n, i) => h("li", { class: i === 0 ? "latest" : "" }, n.text))));
  }));
}
