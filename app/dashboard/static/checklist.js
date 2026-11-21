// The contract checklist, down the middle of the graph: the six terms, each with its value,
// its state, the fact it stands on (with its clip), and what is paid and owed on it. Rows
// are kept and filled in place, so a term that moves eases to its new state and place
// without the others redrawing under it.

import { ITEMS, isSettled } from "./state.js";
import { owed } from "./crew-state.js";
import { G, hasClip, rupees, sourceOf } from "./graph-layout.js";
import { h } from "./render.js";
import { clipButton } from "./clips.js";

const $ = (id) => document.getElementById(id);
const WORD = { pending: "Pending", agreed: "Agreed", confirmed: "Confirmed", disputed: "Disputed", changed: "Changed" };
const rows = new Map(); // item -> its <li>

function row(key) {
  if (!rows.has(key) || !rows.get(key).isConnected) {
    const li = h("li", { class: "item", "data-item": key });
    li.addEventListener("animationend", () => li.classList.remove("moved", "pulse"));
    rows.set(key, li);
  }
  return rows.get(key);
}

// Shown once a payment counts towards the term; the balance, with no figure of its own
// agreed, is the amount less the advance, as memory works it out.
function moneyLine(r) {
  if (!r?.payments.length || r.agreed == null) return null;
  return h("span", { class: "owed", title: `${rupees(r.agreed)} agreed` }, `Paid ${rupees(r.paid)}`, h("span", { class: "sep" }, " · "), `${rupees(r.owed)} left`);
}

// A term changed after it was agreed says how: by voice on a call, or by a voice note.
const changedBy = (f) => (f?.source === "voice_note" ? "Changed by voice note, both said yes" : "Changed by voice, both said yes");

function stands(f, v) {
  if (!f) return v.when && h("span", { class: "when" }, v.when);
  const by = f.status === "confirmed" ? "confirmed by both" : "agreed by both";
  return h("div", { class: `fact stands ${f.status}`, id: `fact-${f.id}`, title: f.quote ? `“${f.quote}”` : f.text },
    hasClip(f) && clipButton(f.id, null, sourceOf(f)),
    h("span", { class: "when" }, v.when || by));
}

export function renderChecklist(state, L, moved = [], live = false) {
  const money = owed(state);
  const settled = ITEMS.filter(([key]) => isSettled(L.views[key])).length;
  $("settled-count").textContent = `${settled} of ${ITEMS.length} settled`;
  const list = $("items");
  for (const [key, label] of ITEMS) {
    const v = L.views[key];
    const li = row(key);
    const keep = ["moved", "pulse"].filter((c) => li.classList.contains(c));
    li.className = ["item", v.state, v.contradicted && "contradicted", L.stands[key] && "tied", ...keep].filter(Boolean).join(" ");
    li.title = [v.value, v.state === "changed" && changedBy(L.stands[key]), v.note].filter(Boolean).join("\n");
    li.style.transform = `translate(${G.hubX}px, ${L.rows[key].top}px)`;
    li.style.width = `${G.hubW}px`;
    li.replaceChildren(
      h("div", { class: "head" }, h("span", { class: "label" }, label), moneyLine(money[key]), h("span", { class: "state" }, WORD[v.state])),
      h("div", { class: `value${v.value ? "" : " none"}` }, L.rows[key].value || "Not agreed yet"),
      h("div", { class: "foot" },
        stands(L.stands[key], v),
        v.state === "changed" && h("span", { class: "note changed-by" }, changedBy(L.stands[key])),
        v.state !== "changed" && v.note && h("span", { class: "note" }, v.note),
        v.contradicted && h("span", { class: "contradicted" }, `Contradicted · ${v.contradicted}`)));
    if (live && moved.includes(key)) {
      li.classList.remove("moved");
      void li.offsetWidth; // restart the animation if it is still running
      li.classList.add(v.contradicted ? "pulse" : "moved");
    }
    if (li.parentNode !== list) list.append(li);
  }
}
