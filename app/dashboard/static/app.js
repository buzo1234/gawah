// Boot: open the socket first and hold its events, load the log, fold it, then let the
// held events through. Every event has an id, so one that arrives both ways counts once.

import { NO_DEAL, apply, emptyState } from "./state.js";
import { h, renderAll, renderChange } from "./render.js";
import * as phones from "./phone.js";

const $ = (id) => document.getElementById(id);

let state = emptyState(null);
let deals = [];
let seen = new Set();
let ready = false;
let held = [];
let loading = Promise.resolve();

const pinned = () => new URLSearchParams(location.search).get("deal");

async function fetchState() {
  const response = await fetch(`/dashboard/state${pinned() ? `?deal=${encodeURIComponent(pinned())}` : ""}`);
  if (!response.ok) throw new Error(`state ${response.status}`);
  return response.json();
}

function drawEverything() {
  phones.setPeople(state.people);
  renderAll(state);
  phones.render();
  renderPicker();
}

async function load() {
  ready = false;
  const data = await fetchState();
  deals = data.deals;
  seen = new Set();
  phones.reset();
  state = emptyState(data.deal_id);
  for (const e of data.events) fold(e, false);
  drawEverything();
  ready = true;
  const waiting = held;
  held = [];
  for (const e of waiting) onEvent(e);
  setTimeout(catchUp, 2000);
}

const reload = () => (loading = loading.then(load).catch(() => setTimeout(reload, 1000)));

// The socket and the log are written separately, so an event sent just before this page
// connected may not have been in the log yet when it was read. Look once more.
async function catchUp() {
  try {
    const data = await fetchState();
    if (ready && data.events.some((e) => !seen.has(e.event_id))) reload();
  } catch {}
}

function fold(e, live) {
  if (seen.has(e.event_id)) return;
  seen.add(e.event_id);
  if (e.name === "whatsapp.message") return phones.add(e, live);
  if (e.deal_id !== state.dealId) return;
  const change = apply(state, e);
  if (!live) return;
  renderChange(state, change);
  if (change.panels.includes("all")) {
    phones.setPeople(state.people);
    phones.render();
    renderPicker();
  }
}

function onEvent(e) {
  if (!ready) return held.push(e);
  const isNewDeal = e.deal_id !== NO_DEAL && !deals.some((d) => d.id === e.deal_id);
  if (isNewDeal) {
    deals.unshift({ id: e.deal_id, ts: e.ts, names: {} });
    if (!pinned()) {
      state = emptyState(e.deal_id);
      drawEverything();
    }
  }
  fold(e, true);
  if (isNewDeal) renderPicker();
}

function renderPicker() {
  const entry = deals.find((d) => d.id === state.dealId);
  if (entry) for (const [role, p] of Object.entries(state.people)) if (p.name) entry.names[role] = p.name;
  const label = (d) => {
    const who = [d.names.hirer, d.names.worker].filter(Boolean).join(" and ") || "Deal";
    const when = new Date(d.ts).toLocaleString([], { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
    return `${who} · ${when} · ${d.id}`;
  };
  $("deal-picker").replaceChildren(
    h("option", { value: "" }, deals.length ? "Latest deal" : "No deals yet"),
    ...deals.map((d) => h("option", { value: d.id }, label(d))));
  $("deal-picker").value = pinned() && deals.some((d) => d.id === pinned()) ? pinned() : "";
}

$("deal-picker").addEventListener("change", (event) => {
  const url = new URL(location.href);
  if (event.target.value) url.searchParams.set("deal", event.target.value);
  else url.searchParams.delete("deal");
  history.replaceState(null, "", url);
  reload();
});

function connect() {
  const ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/dashboard/ws`);
  ws.onopen = () => {
    $("conn").textContent = "live";
    $("conn").className = "conn live";
    reload();
  };
  ws.onmessage = (m) => onEvent(JSON.parse(m.data));
  ws.onclose = () => {
    $("conn").textContent = "reconnecting";
    $("conn").className = "conn";
    setTimeout(connect, 1000);
  };
}

phones.start();
drawEverything();
connect();
