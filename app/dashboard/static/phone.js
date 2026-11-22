// The second phone, on its own page (/dashboard/phone) and in the board's frame. It plays
// a person with no real phone: its chat is every whatsapp.message for its number, and what
// is typed here goes to the WhatsApp webhook (through /dashboard/phone/send) the way a real
// message would. Nothing is drawn until whatsapp.message says it happened.
//
// ?number=<phone> shows another number's chat, read the same way. A call link opens in
// this same page (so in the board's frame). With "AI plays this person" on, a call link
// that arrives starts the actor (/actor/start) instead, and the call's state is shown.

// It looks like WhatsApp's chat; chat.js reads each message into what it shows.

import { NO_DEAL, phoneLabel } from "./state.js";
import { h, isWebLink } from "./dom.js";
import { fillIcons, icon } from "./icons.js";
import { buttonIds, callLink, chosen, parse } from "./chat.js";

const $ = (id) => document.getElementById(id);
const DEFAULT_NUMBER = "+910000000002"; // not a real number: the worker in the practice calls
const digits = (phone) => (phone || "").replace(/\D/g, "");
const store = {
  get: (k) => { try { return localStorage.getItem(k); } catch { return null; } },
  set: (k, v) => { try { localStorage.setItem(k, v); } catch {} },
};

let messages = [];
let asked = []; // record.confirm_requested, fact.changed, record.confirmed and term.dispute: what each reply button answers
const tapping = new Map(); // message event id -> the button tapped here, until the answer comes back
let people = {}; // role -> { name, phone }, from the deal the board shows
let dealId = null;
let seen = new Set();
let actorReady = false; // the actor's endpoints answer
let actor = null; // { deal_id, role, kind, active } once started from here
let call = null; // "on" or "ended", for the actor's call

const number = () => $("number").value.trim() || DEFAULT_NUMBER;
const mine = (m) => digits(m.phone) === digits(number());
const personWith = (phone) => Object.entries(people).find(([, p]) => p.phone && digits(p.phone) === digits(phone));

function linked(text) {
  return text.split(/(https?:\/\/\S+)/).flatMap((part) => {
    if (!isWebLink(part)) return part;
    const url = part.replace(/[.,;:!?)\]]+$/, "");
    const rest = part.slice(url.length);
    const link = callLink(url);
    if (!link) return [h("a", { href: url, target: "_blank", rel: "noopener" }, url), rest];
    return [h("a", { href: link.href, class: "call-link", onclick: (ev) => openCall(ev, link) }, url), rest];
  });
}

function bubble(m) {
  const image = isWebLink(m.media_url) && (m.media_type || "").startsWith("image/");
  const voice = isWebLink(m.media_url) && (m.media_type || "").startsWith("audio/");
  const { text, replies, cta } = parse(m);
  const ids = replies.length ? buttonIds(m, text, asked) : null;
  const picked = replies.length ? chosen(m, replies, ids, messages, asked, tapping) : null;
  return h("div", { class: `bubble ${m.direction}${cta || replies.length ? " actions" : ""}` },
    image && h("a", { href: m.media_url, target: "_blank", rel: "noopener" }, h("img", { src: m.media_url, alt: "attached image" })),
    voice && h("audio", { src: m.media_url, controls: true, preload: "none", "aria-label": "voice note" }),
    !image && !voice && isWebLink(m.media_url) && h("a", { href: m.media_url, target: "_blank", rel: "noopener" },
      `Attachment${m.media_type ? ` (${m.media_type.split("/").pop()})` : ""}`),
    text && h("div", { class: "text" }, linked(text)),
    h("div", { class: "meta" }, m.direction === "out" ? "Gawah · " : "",
      new Date(m.ts).toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" }).toLowerCase()),
    cta && h("a", { href: cta.href, class: "call-link cta", onclick: (ev) => openCall(ev, cta) }, icon("phone"), cta.label),
    replies.length > 0 && h("div", { class: `replies${picked ? " used" : ""}` }, ...replies.map((title, i) =>
      h("button", {
        type: "button", class: `reply${picked === title ? " picked" : ""}`, disabled: picked ? "" : null, "data-id": ids?.[i] || null,
        onclick: () => tap(m, title, ids?.[i]),
      }, picked === title ? icon("check") : icon("reply"), title))));
}

function render() {
  const chat = $("chat");
  const shown = messages.filter(mine);
  chat.replaceChildren(...(shown.length ? shown.map(bubble) : [h("div", { class: "empty" }, "No messages yet.")]));
  chat.scrollTop = chat.scrollHeight;
  $("name").textContent = phoneLabel(people, number(), dealId);
  // The board titles its frame by whose phone this is, so it is told which number is shown.
  if (parent !== window) parent.postMessage({ secondPhone: number() }, location.origin);
}

// ---------- the actor: "AI plays this person" ----------

async function post(path, body) {
  const r = await fetch(path, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
  if (!r.ok) {
    const error = new Error(`${path} answered ${r.status}`);
    error.status = r.status;
    error.detail = (await r.json().catch(() => ({}))).detail;
    throw error;
  }
  return r.json().catch(() => ({}));
}

const busy = (error) => error.status === 409 && error.detail?.error === "busy";
const pause = (ms) => new Promise((done) => setTimeout(done, ms));

// What a refused /actor/start means, in plain words.
function whyNot(error, link) {
  const d = error.detail || {};
  if (busy(error)) {
    return d.deal_id === link.deal_id ? "The AI is still leaving the last call. Try again in a moment."
      : "The AI is on another deal's call. Stop it there first.";
  }
  if (d.join === 410) return "That call has ended.";
  // A call-back with nothing left to ask is over too: its terms were all confirmed.
  if (d.join === 404) return link.kind === "callback" ? "That call has ended: nothing is left to confirm." : "That call link is not valid.";
  return "The AI could not start. Try again in a moment.";
}

async function probeActor() {
  try {
    const r = await fetch(`/actor/status?deal_id=${encodeURIComponent(dealId || "")}`);
    actorReady = r.status !== 404;
    if (r.ok) {
      const s = await r.json();
      if (s.active) actor = { deal_id: dealId, role: s.role, kind: s.kind, active: true };
    }
  } catch {
    actorReady = false;
  }
  $("actor").hidden = !actorReady;
  showCall();
}

const actorOn = () => actorReady && $("actor-on").checked;

async function startActor(link) {
  actor = { ...link, active: false, error: null };
  call = null;
  showCall();
  const body = { deal_id: link.deal_id, role: link.role, kind: link.kind };
  try {
    // The call-back's link can come while the AI is still leaving the deal call: ask once more.
    await post("/actor/start", body).catch(async (error) => {
      if (!busy(error)) throw error;
      await pause(2500);
      return post("/actor/start", body);
    });
    actor.active = true;
  } catch (error) {
    actor.error = whyNot(error, link);
  }
  showCall();
}

async function stopActor() {
  if (!actor) return;
  const { deal_id, role } = actor;
  actor = null;
  showCall();
  try { await post("/actor/stop", { deal_id, role }); } catch {}
}

function showCall() {
  const box = $("call-state");
  box.hidden = !actor;
  if (!actor) return box.replaceChildren();
  const what = actor.kind === "callback" ? "call-back" : "deal call";
  const text = actor.error ? actor.error
    : !actor.active ? `Starting the AI for the ${what}`
    : call === "ended" ? `The ${what} is over`
    : call === "on" ? `The AI is on the ${what}`
    : `The AI is joining the ${what}`;
  box.className = `call-state${call === "on" ? " on" : ""}${actor.error ? " failed" : ""}`;
  const stop = actor.active && call !== "ended" ? [h("button", { type: "button", class: "quiet", onclick: stopActor }, "Stop")] : [];
  box.replaceChildren(h("span", {}, text), ...stop);
}

function openCall(ev, link) {
  if (!actorOn()) return; // the link opens the call page here, as a tap on a phone would
  ev.preventDefault();
  startActor(link);
}

// ---------- events ----------

function onEvent(e, live) {
  if (seen.has(e.event_id)) return;
  seen.add(e.event_id);
  if (e.name === "whatsapp.message") {
    messages.push(e);
    if (!live) return;
    render();
    const link = mine(e) && e.direction === "out" && e.text && e.text.match(/https?:\/\/\S+/g)?.map(callLink).find(Boolean);
    if (link && actorOn()) startActor(link);
    return;
  }
  if (e.deal_id === NO_DEAL || (dealId && e.deal_id !== dealId)) return;
  if (["record.confirm_requested", "record.confirmed", "fact.changed", "term.dispute"].includes(e.name)) {
    asked.push(e);
    if (live) render();
    return;
  }
  const list = e.name === "deal.requested" ? [e.requested_by, e.other] : e.name === "call.started" ? e.people : [];
  for (const p of list || []) {
    const known = people[p.role] || {};
    people[p.role] = { name: known.name || p.name, phone: known.phone || p.phone };
  }
  if (actor && e.deal_id === actor.deal_id && (e.name === "call.started" || e.name === "call.ended")
      && (e.kind === "callback") === (actor.kind === "callback")) {
    call = e.name === "call.started" ? "on" : "ended";
    showCall();
  }
  if (live && list?.length) render();
}

async function load() {
  const deal = new URLSearchParams(location.search).get("deal");
  const r = await fetch(`/dashboard/state${deal ? `?deal=${encodeURIComponent(deal)}` : ""}`);
  const data = await r.json();
  dealId = data.deal_id;
  messages = [];
  asked = [];
  people = {};
  seen = new Set();
  for (const e of data.events) onEvent(e, false);
  render();
  probeActor();
  document.body.dataset.loaded = "true";
}

function connect() {
  const ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/dashboard/ws`);
  ws.onopen = () => load().catch(() => {});
  ws.onmessage = (m) => {
    const e = JSON.parse(m.data);
    if (dealId == null && e.deal_id !== NO_DEAL) dealId = e.deal_id; // the first deal, started while open
    onEvent(e, true);
  };
  ws.onclose = () => setTimeout(connect, 1000);
}

// ---------- sending ----------

// A reply button tapped: sent as Meta sends a tap, with the button's id; with no id found,
// as the words, which the intake also takes as a yes or a no.
async function tap(m, title, id) {
  if (tapping.has(m.event_id)) return;
  tapping.set(m.event_id, title);
  render();
  const status = $("send-status");
  try {
    await deliver(id ? { text: title, button: { id, title } } : { text: title });
    status.className = "send-status";
    status.textContent = "Delivered to Gawah";
  } catch (error) {
    tapping.delete(m.event_id);
    render();
    status.className = "send-status failed";
    status.textContent = `Not delivered: ${error.message}`;
  }
}

async function deliver(body) {
  const found = personWith(number());
  const response = await fetch("/dashboard/phone/send", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ phone: number(), profile_name: found?.[1].name || "", ...body }),
  });
  const result = await response.json();
  if (!response.ok) throw new Error(typeof result.detail === "string" ? result.detail : "the message was not accepted");
  if (result.status >= 300) throw new Error(`the WhatsApp webhook answered ${result.status}`);
}

async function send(event) {
  event.preventDefault();
  const text = $("text").value.trim();
  const file = $("file").files[0];
  const status = $("send-status");
  if (!text && !file) return;
  status.className = "send-status";
  status.textContent = "Sending";
  try {
    let media = {};
    if (file) {
      const up = await fetch("/dashboard/media", { method: "POST", headers: { "content-type": file.type }, body: file });
      if (!up.ok) throw new Error((await up.json()).detail || "the file could not be stored");
      media = await up.json();
    }
    await deliver({ text, media_url: media.url, media_type: media.content_type });
    status.textContent = "Delivered to Gawah";
    $("text").value = "";
    $("file").value = "";
    showAttached();
    canSend();
  } catch (error) {
    status.className = "send-status failed";
    status.textContent = `Not delivered: ${error.message}`;
  }
}

function showAttached() {
  const file = $("file").files[0];
  $("attached").hidden = !file;
  $("attached").replaceChildren(...(file ? [
    `${(file.type || "").startsWith("audio/") ? "Voice note" : "Photo"}: ${file.name} `,
    h("button", { type: "button", class: "quiet", onclick: () => { $("file").value = ""; showAttached(); canSend(); } }, "Remove"),
  ] : []));
}

// The send button works once there is something to send.
const canSend = () => { $("send").disabled = !$("text").value.trim() && !$("file").files[0]; };

// "+": a small menu, Photo or Voice note, each opening the file picker for its kind.
function menu(open) {
  $("attach-menu").hidden = !open;
  $("attach").setAttribute("aria-expanded", String(open));
}
$("attach").addEventListener("click", () => menu($("attach-menu").hidden));
for (const item of $("attach-menu").querySelectorAll("[data-accept]")) {
  item.addEventListener("click", () => { $("file").accept = item.dataset.accept; menu(false); $("file").click(); });
}
addEventListener("click", (ev) => { if (!ev.target.closest(".attach")) menu(false); });
addEventListener("keydown", (ev) => { if (ev.key === "Escape") menu(false); });
$("text").addEventListener("input", canSend);

const pinnedNumber = new URLSearchParams(location.search).get("number");
$("number").value = pinnedNumber || store.get("gawah.second-phone") || DEFAULT_NUMBER;
$("number").addEventListener("change", () => {
  if (!pinnedNumber) store.set("gawah.second-phone", number());
  render();
});
$("actor-on").checked = store.get("gawah.actor") === "on";
$("actor-on").addEventListener("change", () => store.set("gawah.actor", $("actor-on").checked ? "on" : "off"));
$("file").addEventListener("change", () => { showAttached(); canSend(); });
fillIcons();
$("composer").addEventListener("submit", send);
if (new URLSearchParams(location.search).has("embed")) document.body.classList.add("embed");
render();
connect();
