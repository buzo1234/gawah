// The timeline, worked out from the state alone: every fact as memory wrote it, newest at
// the top, grouped by the moment it was written in ("Call 1", "Call-backs", "WhatsApp ·
// day 2", "Call 2", "Voice note · day 5"). It is built from the witness chain's links, so
// a term said on call 1 and confirmed on the call-backs appears in both moments; versions
// of one fact inside one moment are one entry, at its newest status. A version re-sent as
// replaced is not an entry: the entries of that fact are marked replaced.

import { LABEL, claims, factLatency, hasClip, itemOfFact, person, statusWord, valueParts } from "./board.js";
import { clock } from "./state.js";

const DAY = 86400000;
const midnight = (ts) => { const d = new Date(ts); d.setHours(0, 0, 0, 0); return d.getTime(); };
const hhmm = (ts) => new Date(ts).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });

function momentOf(link, first) {
  if (link.where.startsWith("Call")) return link.where;
  const day = Math.round((midnight(link.ts) - midnight(first)) / DAY) + 1;
  return `${link.source === "voice_note" ? "Voice note" : "WhatsApp"} · day ${day}`;
}

// Entries newest first, each: key, factId, moment, text (the fact in plain words), term,
// word and tone (its status), roles (who is responsible), time, latency, clip, voice,
// replaced, follow (a later step of a fact first written in another moment).
export function moments(state) {
  const links = state.chain.list;
  if (!links.length) return [];
  const first = links[0].ts;
  const claimed = claims(state);
  const entries = new Map();
  const seenIn = new Map(); // fact id -> the moment it was first written in
  links.forEach((link, n) => {
    if (link.status === "superseded") return;
    const moment = momentOf(link, first);
    const key = `${link.factId}|${moment}`;
    if (!seenIn.has(link.factId)) seenIn.set(link.factId, moment);
    const known = entries.get(key);
    entries.set(key, { key, factId: link.factId, moment, n: known ? known.n : n, status: link.status, ts: known ? known.ts : link.ts });
  });
  return [...entries.values()].sort((a, b) => b.n - a.n).map((e) => {
    const f = state.facts[e.factId];
    const follow = seenIn.get(e.factId) !== e.moment;
    const version = { ...f, status: e.status };
    const { word, tone } = statusWord(state, version, claimed);
    const item = itemOfFact(state, f);
    const parts = valueParts(f);
    const roles = follow
      ? [...new Set(e.status === "confirmed" ? f.confirmed_by || [] : f.agreed_by || [])]
      : [f.said_by || (f.kind === "payment" ? "hirer" : null)];
    const onCall = (f.source === "call" && !follow) && f.start != null;
    return {
      key: e.key, factId: e.factId, moment: e.moment, follow,
      text: follow ? `${LABEL[item] || "Other detail"}: ${parts.main}` : f.text,
      term: LABEL[item] || "Other detail", item: item || "",
      word: f.status === "superseded" ? "Replaced" : word, tone: f.status === "superseded" ? "" : tone,
      people: roles.filter((r) => r === "hirer" || r === "worker").map((r) => person(state, r)).concat(roles.some((r) => r === "hirer" || r === "worker") ? [] : [person(state, null)]),
      time: onCall ? clock(f.start) : hhmm(e.ts),
      latency: follow ? null : factLatency(state, f),
      status: f.status, clip: hasClip(f), voice: f.source === "voice_note", replaced: f.status === "superseded", claim: claimed.has(f.id),
    };
  });
}

// The entries in runs of one moment, newest run first: [{ moment, entries }].
export function grouped(list) {
  const runs = [];
  for (const e of list) {
    if (runs.at(-1)?.moment !== e.moment) runs.push({ moment: e.moment, entries: [] });
    runs.at(-1).entries.push(e);
  }
  return runs;
}
