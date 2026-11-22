// The second phone's icons, inline SVG: one size (20px), one stroke (2), round ends, drawn
// in the text colour. Nothing is loaded from outside.

const SVG = "http://www.w3.org/2000/svg";
const PATHS = {
  plus: ["M12 5v14", "M5 12h14"],
  photo: ["M5 5h14a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2z", "M21 15l-5-5-9 9", "M9.5 10.5a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3z"],
  mic: ["M12 3a3 3 0 0 1 3 3v5a3 3 0 0 1-6 0V6a3 3 0 0 1 3-3z", "M5.5 11a6.5 6.5 0 0 0 13 0", "M12 17.5V21"],
  send: ["M21 3L10.5 13.5", "M21 3l-6.5 18-4-7.5L3 9.5 21 3z"],
  phone: ["M6.6 3.5h2.8l1.4 4.2-2 1.3a10.5 10.5 0 0 0 6.2 6.2l1.3-2 4.2 1.4v2.8a1.8 1.8 0 0 1-1.9 1.8A16.5 16.5 0 0 1 4.8 5.4a1.8 1.8 0 0 1 1.8-1.9z"],
  check: ["M5 12.5l4.5 4.5L19 7.5"],
  chevronRight: ["M9 6l6 6-6 6"],
  chevronLeft: ["M15 6l-6 6 6 6"],
  reply: ["M10 8L5 12.5 10 17", "M5 12.5h9a5 5 0 0 1 5 5V19"],
};

export function icon(name, label = null) {
  const svg = document.createElementNS(SVG, "svg");
  for (const [k, v] of Object.entries({ class: `icon icon-${name}`, width: 20, height: 20, viewBox: "0 0 24 24" })) svg.setAttribute(k, v);
  if (label) { svg.setAttribute("role", "img"); svg.setAttribute("aria-label", label); } else svg.setAttribute("aria-hidden", "true");
  for (const d of PATHS[name]) {
    const path = document.createElementNS(SVG, "path");
    path.setAttribute("d", d);
    svg.append(path);
  }
  return svg;
}

// Every <span data-icon="name"> in the page becomes that icon.
export function fillIcons(root = document) {
  for (const el of root.querySelectorAll("[data-icon]")) el.replaceWith(icon(el.dataset.icon));
}
