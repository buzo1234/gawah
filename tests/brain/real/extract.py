"""Turn the user's real deals in .evidence/ (git-ignored) into the replay fixtures beside this file.

    uv run python -m tests.brain.real.extract

Keeps, per deal, in the order they happened: each deal call's start and end, its transcript lines,
what Gawah said (judge.spoke), memory's facts and conflicts (callbacks and voice notes included,
since they move the terms), and the judge.speaks the brain sent on the real call, for comparison.
No phone numbers, media links or WhatsApp messages are kept.
"""

import json
from pathlib import Path

DEALS = ["24d9c0bc0e72", "479b7f788c68", "6aae99c104d1"]
HERE = Path(__file__).parent
EVIDENCE = Path(".evidence")


def extract(deal: str) -> dict:
    events, people = [], None
    for e in json.loads((EVIDENCE / f"{deal}.json").read_text())["events"]:
        if e.get("deal_id") != deal:
            continue
        name = e["name"]
        if name in ("call.started", "call.ended") and e.get("kind") == "deal":
            people = people or [{"role": p["role"], "name": p.get("name")} for p in e.get("people", [])]
            if name == "call.started" and any(x["kind"] == "started" and x["call_no"] == e["call_no"] for x in events):
                continue  # sent again with a name learned on the call
            events.append({"kind": name.split(".")[1], "call_no": e["call_no"]})
        elif name == "transcript.line" and e.get("kind") in (None, "deal"):
            events.append({"kind": "line", **{k: e[k] for k in ("call_no", "line_no", "speaker", "text", "start", "end")}})
        elif name == "judge.spoke" and e.get("text"):
            events.append({"kind": "spoke", **{k: e.get(k) for k in ("text", "reason", "item", "start", "end", "clip_fact_id")}})
        elif name == "judge.speak":
            events.append({"kind": "speak", **{k: e.get(k) for k in ("after_line", "reason", "item", "to")}})
        elif name == "fact.recorded":
            fact = {k: v for k, v in e["fact"].items() if k != "media_url"}
            events.append({"kind": "fact", "fact": fact})
        elif name == "fact.conflict":
            events.append({"kind": "conflict", **{k: e.get(k) for k in ("fact_ids", "explanation", "said", "speaker", "call_no", "line_no")}})
    return {"deal": deal, "people": people, "events": events}


if __name__ == "__main__":
    for deal in DEALS:
        out = HERE / f"{deal}.json"
        out.write_text(json.dumps(extract(deal), ensure_ascii=False, indent=1) + "\n")
        print(f"saved {out}")
