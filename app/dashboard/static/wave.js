// The deck's motif: speech as a row of bars. The events carry no audio levels, so the bar
// heights come from the words (a hash of the text), the same every time: a reload draws
// the same waveform, and two lines never look alike.

const SVG = "http://www.w3.org/2000/svg";

function hash(text) {
  let x = 2166136261;
  for (let i = 0; i < text.length; i++) x = Math.imul(x ^ text.charCodeAt(i), 16777619);
  return x >>> 0;
}

// n heights from 0.18 to 1, with the rise and fall of a phrase: louder in the middle.
export function heights(seed, n) {
  let x = hash(String(seed)) || 1;
  const out = [];
  for (let i = 0; i < n; i++) {
    x ^= x << 13; x ^= x >>> 17; x ^= x << 5; x >>>= 0;
    const noise = (x % 1000) / 1000;
    const envelope = Math.sin(Math.PI * (i + 0.5) / n) ** 0.6;
    out.push(0.18 + 0.82 * envelope * (0.35 + 0.65 * noise));
  }
  return out;
}

// Bars as SVG rects into `svg`, from x over `width` at a step, centred on cy.
export function bars(svg, seed, { x = 0, width, cy, height, step = 6, bar = 3, cls = "" }) {
  const n = Math.max(2, Math.floor(width / step));
  const g = document.createElementNS(SVG, "g");
  if (cls) g.setAttribute("class", cls);
  heights(seed, n).forEach((v, i) => {
    const h = Math.max(2, v * height);
    const r = document.createElementNS(SVG, "rect");
    r.setAttribute("x", x + i * step);
    r.setAttribute("y", cy - h / 2);
    r.setAttribute("width", bar);
    r.setAttribute("height", h);
    r.setAttribute("rx", bar / 2);
    g.append(r);
  });
  svg.append(g);
  return g;
}

// A small waveform on its own, as the deck draws a clip.
export function wave(seed, width, height, cls = "wave") {
  const svg = document.createElementNS(SVG, "svg");
  svg.setAttribute("class", cls);
  svg.setAttribute("width", width);
  svg.setAttribute("height", height);
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  svg.setAttribute("aria-hidden", "true");
  bars(svg, seed, { width, cy: height / 2, height, step: 5, bar: 2.5 });
  return svg;
}
