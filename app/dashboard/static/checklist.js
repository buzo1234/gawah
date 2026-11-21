// The contract: the six terms as rows, as the deck's slide 7 lists them. Each row: the
// term, what is paid and owed on it (or that it was contradicted), its state as a pill;
// under that the value, cut at a word (in full on hover), and where it was settled. A row
// picked shows its term in the fact layer.

import { ITEMS, isSettled } from "./state.js";
import { owed } from "./crew-state.js";
import { cut, rupees } from "./board.js";
import { h } from "./render.js";

const $ = (id) => document.getElementById(id);
const WORD = { pending: "Pending", agreed: "Agreed", confirmed: "Confirmed", disputed: "Disputed", changed: "Changed" };
const TONE = { agreed: "ok", confirmed: "ok", changed: "ok", disputed: "bad", pending: "" };
const ROW_W = 384;

const money = (v) => (v && /^[\d,]+ rupees$/i.test(v.trim()) ? `₹ ${v.trim().split(" ")[0]}` : v);

// Shown once a payment counts towards the term; the balance, with no figure of its own
// agreed, is the amount less the advance, as memory works it out.
function moneyLine(r) {
  if (!r?.payments.length || r.agreed == null) return null;
  return h("span", { class: "owed", title: `${rupees(r.agreed)} agreed` }, `Paid ${rupees(r.paid)}`, h("span", { class: "sep" }, " · "), `${rupees(r.owed)} left`);
}

const changedBy = (f) => (f?.source === "voice_note" ? "Changed by voice note, both said yes" : "Changed by voice, both said yes");

export function renderChecklist(state, view, moved = [], live = false) {
  const paid = owed(state);
  const settled = ITEMS.filter(([key]) => isSettled(view.views[key])).length;
  $("settled-count").textContent = `${settled} of ${ITEMS.length} settled`;
  $("items").replaceChildren(...ITEMS.map(([key, label]) => {
    const v = view.views[key];
    const owes = moneyLine(paid[key]);
    const when = owes ? "" : v.when || "";
    const right = owes || (when && h("span", { class: "when" }, when));
    const rightW = owes ? view.measure(owes.textContent, "500 16px") + 14 : when ? view.measure(when, "400 16px") + 14 : 0;
    const li = h("li", {
      class: ["item", v.state, v.contradicted && "contradicted", view.focus === key && "focus", live && moved.includes(key) && (v.contradicted ? "pulse" : "moved")].filter(Boolean).join(" "),
      "data-item": key, "data-when": v.when || "", title: [v.value, v.state === "changed" && changedBy(view.stands[key]), v.note, owes && v.when].filter(Boolean).join("\n"),
      onclick: () => view.pick(key),
    },
      h("span", { class: "top-line" },
        h("span", { class: "name label" }, label),
        v.contradicted && h("span", { class: "contradicted pill bad", title: `Contradicted · ${v.contradicted}` }, "Contradicted"),
        h("span", { class: `state pill ${TONE[v.state] || ""}` }, WORD[v.state])),
      h("span", { class: "foot" },
        h("span", { class: `value${v.value ? "" : " none"}` }, v.value ? cut(money(v.value), ROW_W - rightW, view.measure, "500 20px") : "Not agreed yet"),
        right));
    li.addEventListener("animationend", () => li.classList.remove("moved", "pulse"));
    return li;
  }));
}
