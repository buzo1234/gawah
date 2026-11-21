// The contract checklist: the six terms, each with its value, its state, and where it was
// settled. Rows are kept and filled in place, so a term that moves can ease into its new
// state without the others redrawing under it.

import { ITEMS, isSettled, termView } from "./state.js";
import { h } from "./render.js";

const $ = (id) => document.getElementById(id);
const WORD = { pending: "Pending", agreed: "Agreed", confirmed: "Confirmed", disputed: "Disputed", changed: "Changed" };
const rows = new Map(); // item -> its <li>

function row(key) {
  if (!rows.has(key) || !rows.get(key).isConnected) {
    const li = h("li", { class: "item", "data-item": key });
    li.addEventListener("animationend", () => li.classList.remove("moved"));
    rows.set(key, li);
  }
  return rows.get(key);
}

export function renderChecklist(state, moved = []) {
  const views = ITEMS.map(([key, label]) => [key, label, termView(state, key)]);
  const settled = views.filter(([, , v]) => isSettled(v)).length;
  $("settled-count").textContent = `${settled} of ${ITEMS.length} settled`;
  const list = $("items");
  for (const [key, label, v] of views) {
    const li = row(key);
    li.className = `item ${v.state}${li.classList.contains("moved") ? " moved" : ""}`;
    li.title = v.value || "";
    li.replaceChildren(...[
      h("div", { class: "head" }, h("span", { class: "label" }, label), h("span", { class: "state" }, WORD[v.state])),
      h("div", { class: `value${v.value ? "" : " none"}` }, v.value || "Not agreed yet"),
      (v.when || v.note || v.contradicted) && h("div", { class: "foot" },
        v.when && h("span", { class: "when" }, v.when),
        v.note && h("span", { class: "note" }, v.note),
        v.contradicted && h("span", { class: "contradicted" }, `Contradicted · ${v.contradicted}`)),
    ].filter(Boolean));
    if (moved.includes(key)) {
      li.classList.remove("moved");
      void li.offsetWidth; // restart the animation if it is still running
      li.classList.add("moved");
    }
    if (li.parentNode !== list) list.append(li);
  }
}
