// Boot: open the socket first and hold its events, load the log, fold it, then let the
// held events through. Every event has an id, so one that arrives both ways counts once.
// Another deal is picked with ?deal=<id>, or by pressing D.

import { NO_DEAL, apply, emptyState } from "./state.js";
import { h, renderAll, renderChange, renderChecked } from "./render.js";
import { checkChain } from "./chain.js";
import { watchTimeline } from "./timeline.js";

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

// Memory's verdict on the witness chain comes back later; it is drawn only if the page
// still shows the deal it was asked for.
const chainChecked = (checked) => checked === state && renderChecked(state);

// Long text is cut where the page's own font says it no longer fits, so the fonts come first.
const fonts = Promise.all(["400 18px", "500 16px", "600 16px", "600 24px", "400 14px"].map((f) =>
  document.fonts.load(`${f} "Public Sans"`))).then(() => document.fonts.load('400 14px "IBM Plex Mono"')).catch(() => {});

async function load() {
  ready = false;
  const [data] = await Promise.all([fetchState(), fonts]);
  deals = data.deals;
  seen = new Set();
  state = emptyState(data.deal_id);
  for (const e of data.events) fold(e, false);
  renderAll(state);
  checkChain(state, chainChecked);
  ready = true;
  document.body.dataset.loaded = "true";
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
  if (e.deal_id !== state.dealId) return;
  const change = apply(state, e);
  if (!live) return;
  renderChange(state, change);
  if (change.fact) checkChain(state, chainChecked);
}

function onEvent(e) {
  if (!ready) return held.push(e);
  if (e.deal_id !== NO_DEAL && !deals.some((d) => d.id === e.deal_id)) {
    deals.unshift({ id: e.deal_id, ts: e.ts, names: {} });
    if (!pinned() || pinned() === e.deal_id) {
      state = emptyState(e.deal_id);
      renderAll(state);
    }
  }
  fold(e, true);
}

// ---------- picking another deal: out of the way, on D ----------

function showDeals() {
  const label = (d) => {
    const who = [d.names.hirer, d.names.worker].filter(Boolean).join(" and ") || "Deal";
    const when = new Date(d.ts).toLocaleString([], { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
    return `${who} · ${when}`;
  };
  const pick = (id) => () => {
    const url = new URL(location.href);
    if (id) url.searchParams.set("deal", id);
    else url.searchParams.delete("deal");
    history.replaceState(null, "", url);
    $("deals").close();
    reload();
  };
  $("deal-list").replaceChildren(
    h("li", {}, h("button", { type: "button", onclick: pick(null), "aria-current": String(!pinned()) }, "The latest deal")),
    ...deals.map((d) => h("li", {}, h("button", { type: "button", onclick: pick(d.id), "aria-current": String(pinned() === d.id) },
      label(d), h("span", { class: "id" }, d.id)))));
  $("deals").showModal();
}

addEventListener("keydown", (e) => {
  if (e.key.toLowerCase() !== "d" || e.metaKey || e.ctrlKey || e.altKey || $("deals").open) return;
  if (e.target.closest?.("input, textarea, select")) return;
  showDeals();
});

// ---------- the second phone's frame ----------

// A call link tapped in the phone opens inside the frame; the frame's own control brings
// the chat back.
const frame = $("phone-frame");
const phonePage = `/dashboard/phone?embed=1${pinned() ? `&deal=${encodeURIComponent(pinned())}` : ""}`;
frame.src = phonePage;
frame.addEventListener("load", () => {
  let path = null;
  try { path = frame.contentWindow.location.pathname; } catch {}
  $("phone-back").hidden = path === "/dashboard/phone";
});
$("phone-back").addEventListener("click", () => { frame.src = phonePage; });

function connect() {
  const ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/dashboard/ws`);
  ws.onopen = () => {
    document.body.dataset.conn = "live";
    reload();
  };
  ws.onmessage = (m) => onEvent(JSON.parse(m.data));
  ws.onclose = () => {
    document.body.dataset.conn = "reconnecting";
    setTimeout(connect, 1000);
  };
}

// The board is laid out for 1920 by 1080 and scaled to whatever window shows it, centred,
// so a 1440 by 900 laptop or a 1280 by 720 projector shows the same board.
function fit() {
  const scale = Math.min(innerWidth / 1920, innerHeight / 1080);
  const x = (innerWidth - 1920 * scale) / 2, y = (innerHeight - 1080 * scale) / 2;
  $("stage").style.transform = `translate(${x}px, ${y}px) scale(${scale})`;
}
addEventListener("resize", fit);
fit();

watchTimeline();
renderAll(state);
connect();
