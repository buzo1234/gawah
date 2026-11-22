// The second phone's messages, read into what WhatsApp would show (no DOM).
//
// It looks like WhatsApp's chat. The event log has each message as the text Gawah logged:
// on Meta, a link Meta shows as a button is still in the text, and reply buttons are a last
// line "[Haan, sahi hai]  [Nahi]". The page draws them as WhatsApp does: the link as a call
// button inside the bubble, the reply buttons as rows under it. A tapped reply button is
// sent as Meta sends a tap, with the button's id; the id ("yes:<id>" or "no:<id>", as the
// question was sent) is found from the question's own event: record.confirm_requested
// with the same words, or the fact.changed the question asks about.

const CALL_PATH = /^\/(call|callback)\/([^/]+)\/(hirer|worker)\/?$/;
// The labels Meta's link button carries (app/whatsapp/words.py), for a call and a call-back.
const CALL_LABEL = { deal: "Call kholiye", callback: "Gawah se baat kariye" };
const REPLIES = /(?:^|\n)((?:\[[^\]\n]+\][ \t]*)+)$/;
const digits = (phone) => (phone || "").replace(/\D/g, "");

// A link to a call page on this server, opened here, at this page's own address.
export function callLink(url) {
  let u;
  try { u = new URL(url); } catch { return null; }
  const m = u.pathname.match(CALL_PATH);
  return m ? { href: u.pathname + u.search, kind: m[1] === "call" ? "deal" : "callback", deal_id: m[2], role: m[3] } : null;
}

// What a message of Gawah's shows: its words, the call link as a button (the link taken out
// of the words, as Meta does), and the reply buttons.
export function parse(m) {
  let text = m.text || "";
  let replies = [];
  let cta = null;
  if (m.direction !== "out") return { text, replies, cta };
  const found = text.match(REPLIES);
  if (found) {
    replies = [...found[1].matchAll(/\[([^\]]+)\]/g)].map((x) => x[1]);
    text = text.slice(0, found.index).trimEnd();
  }
  for (const raw of text.match(/https?:\/\/\S+/g) || []) {
    const url = raw.replace(/[.,;:!?)\]]+$/, "");
    const link = callLink(url);
    if (!link) continue;
    cta = { ...link, label: CALL_LABEL[link.kind] };
    text = text.replace(`: ${url}`, ".").replace(url, "").split(/\s+/).join(" ").trim();
    break;
  }
  return { text, replies, cta };
}

// The id each reply button was sent with, in the order the buttons were (yes, then no).
export function buttonIds(m, words, asked) {
  const record = asked.find((e) => e.name === "record.confirm_requested" && e.deal_id === m.deal_id && (e.question || "").trim() === words.trim());
  const change = !record && asked.filter((e) => e.name === "fact.changed" && e.deal_id === m.deal_id && e.ts <= m.ts
    && e.proposed_by !== m.role && !["confirmed_both", "withdrawn"].includes(e.status)).at(-1);
  const id = record?.record_id || change?.change_id;
  return id ? [`yes:${id}`, `no:${id}`] : null;
}

// The button already chosen, as WhatsApp shows it: the question's own event says it was
// answered (record.confirmed, or the change confirmed or withdrawn), or it was just tapped
// here. With no id to go by, the person's next message, if it was one of the buttons.
export function chosen(m, replies, ids, messages, asked, tapping) {
  if (!ids) {
    const next = messages.find((x) => x.direction === "in" && digits(x.phone) === digits(m.phone) && x.ts > m.ts);
    return next && replies.includes((next.text || "").trim()) ? next.text.trim() : tapping.get(m.event_id) || null;
  }
  const id = ids[0].slice(4);
  const done = id && asked.find((e) => (e.name === "record.confirmed" && e.record_id === id)
    || (e.name === "fact.changed" && e.change_id === id && ["confirmed_both", "withdrawn"].includes(e.status)));
  if (done) return replies[(done.name === "record.confirmed" ? done.confirmed : done.status === "confirmed_both") ? 0 : 1];
  return tapping.get(m.event_id) || null;
}

