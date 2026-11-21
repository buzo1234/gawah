// The two chats. The second phone plays a person with no real phone: its chat shows every
// whatsapp.message for its number, and what is typed here goes to the WhatsApp webhook
// (through /dashboard/phone/send) the way a real message would. The real phone's chat is
// every other number, read only. Nothing is drawn until whatsapp.message says it happened.

import { h, isWebLink } from "./render.js";

const $ = (id) => document.getElementById(id);
const DEFAULT_NUMBER = "+910000000002"; // not a real number: the worker in the practice calls
const digits = (phone) => (phone || "").replace(/\D/g, "");

let messages = [];
let people = {};

function number() {
  return $("second-number").value.trim() || DEFAULT_NUMBER;
}

function linked(text) {
  return text.split(/(https?:\/\/\S+)/).flatMap((part) => {
    if (!isWebLink(part)) return part;
    const url = part.replace(/[.,;:!?)\]]+$/, "");
    return [h("a", { href: url, target: "_blank", rel: "noopener" }, url), part.slice(url.length)];
  });
}

function bubble(m) {
  const image = isWebLink(m.media_url) && (m.media_type || "").startsWith("image/");
  return h("div", { class: `bubble ${m.direction} ${m.direction === "in" ? m.role || "" : ""}` },
    image && h("a", { href: m.media_url, target: "_blank", rel: "noopener" }, h("img", { src: m.media_url, alt: "attached image" })),
    !image && isWebLink(m.media_url) && h("a", { href: m.media_url, target: "_blank", rel: "noopener" },
      `Attachment${m.media_type ? ` (${m.media_type.split("/").pop()})` : ""}`),
    m.text && h("div", { class: "text" }, linked(m.text)),
    h("div", { class: "meta" }, m.direction === "out" ? "Gawah · " : "",
      new Date(m.ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })));
}

function chatFor(m) {
  return digits(m.phone) === digits(number()) ? $("second-chat") : $("real-chat");
}

function personWith(phone) {
  return Object.entries(people).find(([, p]) => p.phone && digits(p.phone) === digits(phone));
}

function label(phone) {
  const found = personWith(phone);
  return found ? found[1].name || found[0] : "";
}

export function render() {
  for (const id of ["second-chat", "real-chat"]) $(id).replaceChildren();
  for (const m of messages) chatFor(m).append(bubble(m));
  for (const id of ["second-chat", "real-chat"]) {
    if (!$(id).children.length) $(id).append(h("div", { class: "empty" }, "No messages yet."));
    $(id).scrollTop = $(id).scrollHeight;
  }
  const real = messages.findLast((m) => digits(m.phone) !== digits(number()));
  $("second-name").textContent = label(number());
  $("real-name").textContent = real ? label(real.phone) || `ends ${digits(real.phone).slice(-4)}` : "";
}

export function reset() {
  messages = [];
}

export function add(m, live) {
  messages.push(m);
  if (live) render();
}

export function setPeople(now) {
  people = now;
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
      if (!up.ok) throw new Error((await up.json()).detail || "the image could not be stored");
      media = await up.json();
    }
    const found = personWith(number());
    const response = await fetch("/dashboard/phone/send", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        phone: number(), text, media_url: media.url, media_type: media.content_type,
        profile_name: found?.[1].name || "Second phone",
      }),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(typeof result.detail === "string" ? result.detail : "the message was not accepted");
    if (result.status >= 300) throw new Error(`the WhatsApp webhook answered ${result.status}`);
    status.textContent = "Delivered to Gawah";
    $("text").value = "";
    $("file").value = "";
    showAttached();
  } catch (error) {
    status.className = "send-status failed";
    status.textContent = `Not delivered: ${error.message}`;
  }
}

function showAttached() {
  const file = $("file").files[0];
  $("attached").hidden = !file;
  $("attached").replaceChildren(...(file ? [
    `Photo: ${file.name} `,
    h("button", { type: "button", onclick: () => { $("file").value = ""; showAttached(); } }, "Remove"),
  ] : []));
}

export function start() {
  let saved = null;
  try { saved = localStorage.getItem("gawah.second-phone"); } catch {}
  $("second-number").value = saved || DEFAULT_NUMBER;
  $("second-number").addEventListener("change", () => {
    try { localStorage.setItem("gawah.second-phone", number()); } catch {}
    render();
  });
  $("file").addEventListener("change", showAttached);
  $("composer").addEventListener("submit", send);
}
