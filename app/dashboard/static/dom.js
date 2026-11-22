// The page's small DOM tools: elements from h() (text only ever as text nodes), text
// measured in the page's own font, lists kept by key, and pointing at facts.

export function h(tag, attrs = {}, ...kids) {
  const el = tag === "svg" || attrs.svg ? document.createElementNS("http://www.w3.org/2000/svg", tag) : document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null || v === false || k === "svg") continue;
    if (k === "class") el.setAttribute("class", v);
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v);
  }
  el.append(...kids.flat(Infinity).filter((k) => k != null && k !== false && k !== ""));
  return el;
}

export const isWebLink = (url) => /^https?:\/\//i.test(url || "");

// Where long text is cut comes from the page's own font.
const ctx = document.createElement("canvas").getContext("2d");
export const measure = (text, font = "500 16px") => {
  ctx.font = `${font} "Public Sans", "Noto Sans Devanagari", sans-serif`;
  return ctx.measureText(text).width;
};

// The children of `parent` made to match `items`, in order, by key. An element whose
// signature is unchanged is kept as it is; one that changed is made again; one that is new
// is made and put in its place. make(item, before) gets the element it replaces, if any.
export function sync(parent, items, keyOf, sigOf, make) {
  const old = new Map([...parent.children].map((el) => [el.dataset.key, el]));
  const want = items.map((item) => {
    const key = keyOf(item), sig = sigOf(item), before = old.get(key);
    old.delete(key);
    if (before && before.dataset.sig === sig) return before;
    const el = make(item, before);
    el.dataset.key = key;
    el.dataset.sig = sig;
    if (before) before.replaceWith(el);
    return el;
  });
  for (const el of old.values()) el.remove();
  want.forEach((el, i) => { if (parent.children[i] !== el) parent.insertBefore(el, parent.children[i] || null); });
}

// What pointing at facts does is set by render.js.
export const hooks = { point: () => {}, pick: () => {} };

// Hover and focus on anything carrying data-facts point at those facts; a click picks them.
export function pointable(el, ids) {
  el.dataset.facts = ids.join(" ");
  if (el.dataset.pointable) return el;
  el.dataset.pointable = "1";
  const ids_ = () => el.dataset.facts.split(" ").filter(Boolean);
  el.addEventListener("mouseenter", () => hooks.point(ids_()));
  el.addEventListener("mouseleave", () => hooks.point(null));
  el.addEventListener("focusin", () => hooks.point(ids_()));
  el.addEventListener("focusout", () => hooks.point(null));
  el.addEventListener("click", (ev) => { if (!ev.target.closest("button")) hooks.pick(ids_()); });
  return el;
}

