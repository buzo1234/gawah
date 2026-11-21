// Draws the panels from the state. Text only ever goes in through h(), as text nodes.

import { ITEMS, clock, lineAt, nameOf, otherRole } from "./state.js";
import { relink, renderGraph } from "./graph.js";
import { clipButton } from "./clips.js";
import { renderLanes } from "./lanes.js";

const $ = (id) => document.getElementById(id);
const ITEM_LABEL = Object.fromEntries(ITEMS);

const REASONS = {
  addressed_directly: "Someone asked Gawah directly",
  term_unclear: "A term was left unclear",
  conflicting_figures: "Two different figures were said",
  wrapping_up: "They are wrapping up",
  ambiguous: "An agreement could mean two things",
  contradicts_record: "It contradicts the record",
};
const KINDS = {
  advance: "Advance", payment: "Payment", work_day: "Day of work",
  milestone: "Milestone", work_done: "Work finished", other: "Record",
};

export function h(tag, attrs = {}, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v);
  }
  el.append(...kids.flat(Infinity).filter((k) => k != null && k !== false && k !== ""));
  return el;
}

export const isWebLink = (url) => /^https?:\/\//i.test(url || "");
const rupees = (n) => "₹" + Number(n).toLocaleString("en-IN");
const empty = (text) => h("div", { class: "empty" }, text);

function nearBottom(box) {
  return box.scrollHeight - box.scrollTop - box.clientHeight < 120;
}

// ---------- conversation ----------

const conflictAt = (state, f) =>
  f.lineNo != null && f.callNo != null && state.conflicts.findLast((c) => c.lineNo === f.lineNo && (c.callNo ?? 1) === f.callNo);

function flowRow(state, f, live) {
  if (f.type === "mark") return h("div", { class: "mark" }, f.text);
  if (f.type === "call") return h("div", { class: "callband" }, h("b", {}, `Call ${f.callNo}`), f.text);
  if (f.type === "gawah") {
    const why = [REASONS[f.reason], ITEM_LABEL[f.item]].filter(Boolean).join(" · ");
    return h("div", { class: `turn gawah${live ? " enter" : ""}` },
      h("div", { class: "who" }, "Gawah", h("span", { class: "when" }, clock(f.start))),
      h("div", { class: "said" }, f.text, f.interrupted && h("span", { class: "cut" }, " (cut off)"),
        why && h("div", { class: "because" }, why),
        f.clip && h("div", { class: "because" }, "Played the clip: ", clipButton(f.clip, "Play it again"))));
  }
  const conflict = conflictAt(state, f);
  return h("div", { class: `turn ${f.speaker}${conflict ? " contradicts" : ""}` },
    h("div", { class: "who" }, nameOf(state, f.speaker), h("span", { class: "when" }, clock(f.start))),
    h("div", { class: "said" }, f.text,
      conflict && h("div", { class: "against" }, `Contradicts the record: ${conflict.explanation}`)));
}

function renderFlow(state) {
  const box = $("flow");
  box.replaceChildren(...(state.flow.length
    ? state.flow.map((f) => flowRow(state, f, false))
    : [empty(state.dealId ? "The call has not started." : "No deal yet. Waiting for someone to message Gawah.")]));
  box.scrollTop = box.scrollHeight;
}

function addToFlow(state, f) {
  const box = $("flow");
  const follow = nearBottom(box);
  if (state.flow.length === 1) box.replaceChildren();
  box.append(flowRow(state, f, true));
  if (follow) box.scrollTop = box.scrollHeight;
}

// ---------- checklist ----------

function termChips(state, key) {
  return ["hirer", "worker"].map((role) => {
    const t = state.terms[role][key];
    if (!t) return null;
    const said = t.said ? `: “${t.said}”` : "";
    return h("div", { class: `chip ${t.ok ? "ok" : "bad"}` },
      t.ok ? `${nameOf(state, role)} confirmed` : `${nameOf(state, role)} disputes this${said}`);
  });
}

function changeChip(state, key) {
  const c = state.changeOrder.map((id) => state.changes[id]).findLast((x) => x.item === key && x.status !== "withdrawn");
  if (!c) return null;
  if (c.status === "confirmed_both") return h("div", { class: "chip ok" }, `Changed to ${c.new_value} · both said yes`);
  const yes = c.confirmed_by?.length ? ` · ${c.confirmed_by.map((r) => nameOf(state, r)).join(", ")} said yes` : "";
  return h("div", { class: "chip warn" }, `Change proposed: ${c.new_value}${yes}`);
}

function renderChecklist(state, flash = []) {
  const agreed = state.items.filter((i) => i.state === "agreed").length;
  const before = state.items.filter((i) => i.state !== "agreed" && state.earlier[i.key]).length;
  $("agreed-count").textContent = before ? `${agreed} of ${state.items.length} now · ${before} earlier` : `${agreed} of ${state.items.length} agreed`;
  $("items").replaceChildren(...state.items.map((item) => {
    const on = item.state === "agreed";
    const earlier = !on && state.earlier[item.key];
    const line = lineAt(state, item.line_no, state.itemCall[item.key]);
    const when = item.line_no == null ? "" : line ? `said at ${clock(line.start)} · line ${item.line_no}` : `line ${item.line_no}`;
    return h("li", { class: `item ${on ? "agreed" : earlier ? "earlier" : "pending"}${flash.includes(item.key) ? " flash" : ""}`, title: item.source_text },
      h("div", { class: "tick" }, on || earlier ? "✓" : ""),
      h("div", { class: "body" },
        h("div", { class: "head" }, h("span", { class: "label" }, ITEM_LABEL[item.key]),
          on && h("span", { class: "when" }, when),
          earlier && h("span", { class: "when" }, `from call ${earlier.callNo}`)),
        h("div", { class: "value" }, on ? item.value || "Agreed" : earlier ? earlier.value || "Agreed" : "Not agreed yet"),
        item.note && h("div", { class: "note" }, item.note),
        termChips(state, item.key), changeChip(state, item.key)));
  }));
}

// ---------- why Gawah spoke ----------

function renderWhy(state, entering) {
  $("spoke-count").textContent = state.decisions.length ? `${state.decisions.length} time${state.decisions.length > 1 ? "s" : ""}` : "";
  const cards = state.decisions.toReversed().map((d, i) => {
    const line = lineAt(state, d.afterLine, d.callNo);
    const after = d.afterLine == null ? null
      : line ? `${nameOf(state, line.speaker)} at ${clock(line.start)}, line ${d.afterLine}: “${line.text}”`
      : `line ${d.afterLine}`;
    const asked = d.question || (d.reason === "addressed_directly" ? line?.text : null);
    return h("article", { class: `decision${i === 0 ? " latest" : ""}${d.id === entering ? " enter" : ""}` },
      h("div", { class: "reason" }, REASONS[d.reason] || d.reason, d.item && h("span", { class: "about" }, ITEM_LABEL[d.item])),
      // A question put to Gawah reads as the question and the answer under it. The brain
      // does not send the question yet; the line it spoke after is the one that asked.
      asked ? h("dl", {},
        h("dt", {}, "Asked"), h("dd", { class: "asked" }, `${line ? `${nameOf(state, line.speaker)}: ` : ""}“${asked}”`),
        h("dt", {}, "Answer"), h("dd", {}, d.spoken ? `“${d.spoken}”${d.interrupted ? " (cut off)" : ""}`
          : d.dropped ? "Nothing: the moment passed" : `${d.instruction} (not said yet)`))
      : h("dl", {},
        after && [h("dt", {}, "Right after"), h("dd", { class: "clamp" }, after)],
        h("dt", {}, "Told to ask"), h("dd", {}, `${d.instruction} (to ${nameOf(state, d.to)})`),
        d.spoken && [h("dt", {}, "Gawah said"), h("dd", {}, `“${d.spoken}”${d.interrupted ? " (cut off)" : ""}`)],
        d.dropped && [h("dt", {}, "Gawah said"), h("dd", {}, "Nothing: the moment passed")]));
  });
  $("decisions").replaceChildren(...(cards.length ? cards
    : [empty("Gawah has not spoken. It stays silent until it decides a question is needed.")]));
  $("decisions").scrollTop = 0;
}

// ---------- record ledger ----------

function recordStatus(state, entry) {
  const r = entry.record;
  if (r.backing === "backed") return ["ok", "Logged"];
  const them = nameOf(state, entry.askedOf || otherRole(r.sender));
  if (entry.answer === true) return ["ok", `${them} confirmed`];
  if (entry.answer === false) return ["bad", `${them} refused`];
  if (entry.timedOut) return ["warn", `No answer from ${them} · followed up`];
  if (entry.askedOf) return ["wait", `Asked ${them} · no answer yet`];
  return ["wait", `${them} not asked yet`];
}

function renderLedger(state) {
  $("record-count").textContent = state.records.length ? `${state.records.length}` : "";
  const rows = state.records.map((entry) => {
    const r = entry.record;
    const [tone, status] = recordStatus(state, entry);
    const details = [r.text && `“${r.text}”`, r.date, r.transaction_id && `txn ${r.transaction_id}`].filter(Boolean).join(" · ");
    return h("div", { class: "record" },
      h("div", { class: "main" },
        h("span", { class: `sender ${r.sender}` }, nameOf(state, r.sender)),
        h("span", { class: "kind" }, KINDS[r.kind] || r.kind),
        r.amount != null && h("span", { class: "amount" }, rupees(r.amount))),
      h("div", { class: "tags" },
        h("span", { class: `tag ${r.backing === "backed" ? "ok" : "plain"}` }, r.backing === "backed" ? "Backed by proof" : "Unbacked"),
        h("span", { class: `tag ${tone}` }, status)),
      (details || isWebLink(r.media_url)) && h("div", { class: "details" }, details,
        isWebLink(r.media_url) && h("a", { href: r.media_url, target: "_blank", rel: "noopener" }, "screenshot")));
  });
  $("records").replaceChildren(...(rows.length ? rows : [empty("No payments or work logged yet.")]));
  $("records").scrollTop = $("records").scrollHeight;
}

// ---------- the deal's state ----------

function termsSummary(state, role) {
  const t = state.terms[role];
  const disputed = Object.keys(t).filter((k) => !t[k].ok);
  const confirmed = Object.keys(t).filter((k) => t[k].ok);
  if (disputed.length) return ["bad", `disputes ${disputed.map((k) => ITEM_LABEL[k] || "the terms").join(", ").toLowerCase()}`];
  if (t.all || confirmed.length >= ITEMS.length) return ["ok", "confirmed the terms"];
  if (confirmed.length) return ["wait", `confirmed ${confirmed.length} of ${ITEMS.length}`];
  return ["wait", "not confirmed yet"];
}

function renderHeader(state) {
  const roles = ["hirer", "worker"];
  $("people").replaceChildren(...(state.dealId ? roles.map((role) =>
    h("span", { class: `person ${role}` }, h("b", {}, nameOf(state, role)), state.people[role]?.name ? ` ${role}` : "")) : []));

  // Across calls: which call is on, and each finished call's own length.
  const calls = Object.entries(state.calls);
  const lengths = calls.filter(([, c]) => c.ended && c.duration != null).map(([, c]) => clock(c.duration));
  const ran = lengths.length ? ` · ${lengths.join(" + ")}` : "";
  const status = {
    none: "No deal yet",
    requested: "Waiting for the call",
    in_call: calls.length > 1 ? `On call ${state.currentCall}` : "On the call",
    call_ended: `${calls.length > 1 ? `${calls.length} calls over` : "Call over"}${ran}`,
    contract_ready: `Contract ready${calls.length > 1 ? ran : ""}`,
  }[state.status];
  $("status").textContent = state.callback ? `Call-back with ${nameOf(state, state.callback)}` : status;
  $("status").className = `pill ${state.callback ? "in_call" : state.status}`;

  $("terms").replaceChildren(...(state.dealId ? roles.map((role) => {
    const [tone, text] = termsSummary(state, role);
    return h("span", { class: `chip ${tone}` }, `${nameOf(state, role)} ${text}`);
  }) : []));

  const c = state.contract;
  $("contract").replaceChildren(...(!c ? []
    : isWebLink(c.url) ? [h("a", { class: "contract-link", href: c.url, target: "_blank", rel: "noopener" }, "Open the contract")]
    : c.text ? [h("button", { class: "contract-link", type: "button", onclick: () => {
        $("contract-body").textContent = c.text;
        $("contract-text").showModal();
      } }, "Read the contract")]
    : []));
}

// ---------- entry points ----------

let shown = null;

export function renderView(state) {
  if (state.view === shown) return;
  shown = state.view;
  for (const view of ["graph", "phones"]) {
    $(`${view}-view`).hidden = state.view !== view;
    $(`tab-${view}`).setAttribute("aria-selected", String(state.view === view));
  }
  if (state.view === "graph") relink();
}

export function renderAll(state) {
  renderHeader(state);
  renderFlow(state);
  renderChecklist(state);
  renderWhy(state);
  renderLedger(state);
  renderGraph(state);
  renderLanes(state);
  renderView(state);
}

export function renderChange(state, change) {
  const all = change.panels.includes("all");
  const wants = (panel) => all || change.panels.includes(panel);
  if (wants("header")) renderHeader(state);
  if (all || wants("flow")) renderFlow(state);
  else if (change.flow) addToFlow(state, change.flow);
  if (wants("checklist")) renderChecklist(state, change.agreed);
  if (wants("why")) renderWhy(state, change.decision);
  if (wants("ledger")) renderLedger(state);
  if (wants("graph")) renderGraph(state, change);
  if (wants("lanes")) renderLanes(state, change.note);
  renderView(state);
}
