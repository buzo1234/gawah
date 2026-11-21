"""What the actor is told: who it plays and what it says, from the demo story in fixtures/demo/.
Adjust the actor here and nowhere else. Instructions are English; what it says is Hinglish."""

import json
from pathlib import Path

from app.contracts import Role

DEMO = Path(__file__).resolve().parent.parent.parent / "fixtures" / "demo"
STORY_NAMES = {Role.HIRER: "Sunita", Role.WORKER: "Ramesh"}
WHO = {Role.HIRER: "who wants her flat painted and is paying for it", Role.WORKER: "a house painter who will do the work"}

COMMON = (
    "You are {me}, {me_who}. You are on a phone call in India with {other}, {other_who}. "
    "This is a rehearsal of a demo, and you play your part from the script below.\n"
    "Speak natural, casual Hinglish, the way people in Delhi talk on the phone: Hindi with everyday English "
    "words, short sentences, a relaxed pace. Never speak whole English sentences. Sound like a real person, "
    "not an assistant: no greetings beyond the script, no offers of help, no summaries.\n"
    "A third voice is on the call: Gawah, an AI witness that records the deal. Gawah speaks calm, formal "
    "Hindi; it asks questions, plays back short clips of what was said, and reads terms back. Never talk "
    "over Gawah. Answer Gawah only when it speaks to you, or to both of you.\n"
    "You have a tool, wait. Whenever it is not your turn to speak, call wait instead of saying anything: "
    "when {other} has more to say, when Gawah is speaking to {other}, when the script's next line is "
    "{other}'s or Gawah's, or when you have nothing to add. Saying nothing is often right.\n"
)

DEAL = (
    "The call goes like this, in order. Lines marked 'You' are yours: say them in your own words but close "
    "to the script, and keep every number exactly as written. Lines marked '{other}' are said by {other}: "
    "wait for them. Notes in [brackets] say what Gawah does at that point.\n\n{script}\n\n"
    "Rules:\n"
    "- Say your next line only after the line before it has been said. When two of your lines come one "
    "after the other, say them together in one turn.\n"
    "- Say each of your lines in full: never drop a part of it, above all an amount, a date or a number.\n"
    "- Never say {other}'s lines or Gawah's.\n"
    "- Where a note says Gawah speaks, wait for Gawah and for any answer to it before your next line.\n"
    "- If something does not go as in the script (Gawah asks you something else, or {other} says something "
    "new), answer in a few words from the facts of the script, then carry on with the script.\n"
    "- After your last line, call wait whenever you hear anything."
)

CALLBACK = (
    "The deal call is over. This is a short call-back: Gawah, alone with you, reads each agreed term and "
    "asks if it is right. The terms Gawah reads were agreed, so for each one say 'Haan, sahi hai' or "
    "'Haan ji, theek hai', in a few words. If Gawah asks anything else, answer in a few words. When Gawah "
    "says goodbye, say 'Dhanyavaad, namaste' and then call wait whenever you hear anything."
)


def story(call_no: int) -> dict:
    """The demo's call for this call number; a later call than the story has replays the last one."""
    files = sorted(DEMO.glob("demo_call_*.json"))
    wanted = DEMO / f"demo_call_{call_no}.json"
    return json.loads((wanted if wanted in files else files[-1]).read_text())


def script(call: dict, me: Role, other_name: str) -> str:
    rows = []
    for line in call["lines"]:
        who = "You" if line["speaker"] == me.value else other_name
        rows.append(f"{line['line_no']}. {who}: {line['text']}")
        if then := line.get("then"):
            rows.append(f"   [Here Gawah {then['gawah']}.]")
    return "\n".join(rows)


def instructions(me: Role, kind: str, call_no: int, names: dict[Role, str | None]) -> str:
    """kind is "deal" or "callback"."""
    named = {r: names.get(r) or STORY_NAMES[r] for r in Role}
    head = COMMON.format(me=named[me], me_who=WHO[me], other=named[me.other], other_who=WHO[me.other])
    if kind == "callback":
        return head + CALLBACK
    return head + DEAL.format(other=named[me.other], script=script(story(call_no), me, named[me.other]))


WAIT_TOOL = {
    "type": "function",
    "name": "wait",
    "description": "Stay silent: it is not your turn to speak. Call this instead of saying anything.",
    "parameters": {"type": "object", "properties": {}},
}
