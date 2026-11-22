// The second phone as a drawer: hidden, it slides out to the right and the deal graph takes
// its width (the timeline keeps its 440); a slim tab at the right edge brings it back. P
// does the same. The frame is only moved off-screen, never unloaded, so a call in it goes
// on. Shown or hidden is remembered in this browser.

import { refit } from "./render.js";
import { fillIcons } from "./icons.js";

const KEY = "gawah.phone";
const $ = (id) => document.getElementById(id);
const stage = $("stage");
const drawer = $("phone-drawer");

let hidden = false;
try { hidden = localStorage.getItem(KEY) === "hidden"; } catch {}

function mark() {
  stage.classList.toggle("phone-hidden", hidden);
  drawer.inert = hidden;
  $("phone-hide").setAttribute("aria-expanded", String(!hidden));
  $("phone-tab").setAttribute("aria-expanded", String(!hidden));
}

export function setPhone(show, animate = true) {
  if (show === !hidden) return;
  try { localStorage.setItem(KEY, show ? "shown" : "hidden"); } catch {}
  if (!animate) {
    stage.classList.add("still");
    hidden = !show;
    mark();
    refit();
    void stage.offsetWidth;
    stage.classList.remove("still");
    return;
  }
  if (show) {
    // The lanes fold for the narrower width before the slide, so no chip wraps during it.
    stage.classList.add("still");
    stage.classList.remove("phone-hidden");
    refit();
    stage.classList.add("phone-hidden");
    void stage.offsetWidth;
    stage.classList.remove("still");
  }
  hidden = !show;
  mark();
  let done = false;
  const end = () => { if (!done) { done = true; refit(); } };
  stage.addEventListener("transitionend", (e) => { if (e.target === stage) end(); }, { once: true });
  setTimeout(end, 400);
}

export function initDrawer() {
  fillIcons($("phone"));
  stage.classList.add("still");
  mark();
  requestAnimationFrame(() => requestAnimationFrame(() => stage.classList.remove("still")));
  $("phone-hide").addEventListener("click", () => setPhone(false));
  $("phone-tab").addEventListener("click", () => setPhone(true));
  addEventListener("keydown", (e) => {
    if (e.key.toLowerCase() !== "p" || e.metaKey || e.ctrlKey || e.altKey || $("deals").open) return;
    if (e.target.closest?.("input, textarea, select")) return;
    setPhone(hidden);
  });
}
