"""The tuned Judge on the held-out calls in fixtures/holdout/: record once, then score.

    uv run python -m tests.brain.holdout.run sage fixtures/holdout/<call>.json     # live Sage2: one update per line plus one
    uv run python -m tests.brain.holdout.run values fixtures/holdout/<call>.json   # live OpenAI, only lookups not yet saved
    uv run python -m tests.brain.holdout.run score                                  # no outside calls

Recordings live in tests/brain/holdout/recorded/, not tests/brain/recorded/, so the
offline app and the practice-call tests never answer from them. `values` replays the call
three ways (live mode, wrapup mode, and live mode with no names known at the start, as a
WhatsApp deal starts) and saves every lookup each one makes. `score` replays the same
three on the saved answers and scores them against each fixture's `expected` and
`must_stay_silent`.
"""

import asyncio
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

from app.brain import Brain, sage, tuning
from app.brain.values import OpenAIValues, RecordedValues
from app.bus import Bus
from app.config import get_settings
from app.contracts import CallStarted, ChecklistUpdated, Event, JudgeSpeak, Person, Role
from fakes.replayer import load
from tests.brain.record import _Saving
from tests.brain.replaying import Run, play

OUT = Path(__file__).parent / "recorded"
CALLS = sorted(Path("fixtures/holdout").glob("*.json"))
VARIANTS = {"live": ("live", True), "wrapup": ("wrapup", True), "unnamed": ("live", False)}
# The names each person is called by on the call. The cook's hirer is only ever "Sharma ji".
HEARD = {
    "holdout_carpenter_wardrobe": {"hirer": {"Deepak"}, "worker": {"Abdul"}},
    "holdout_cook_month": {"hirer": {"Sharma", None}, "worker": {"Kamla"}},
    "holdout_electrician_shop": {"hirer": {"Imran"}, "worker": {"Suresh"}},
    "holdout_plumber_leak": {"hirer": {"Sunita"}, "worker": {"Raju"}},
    "holdout_tutor_monthly": {"hirer": {"Ruma"}, "worker": {"Ankit"}},
}
# The carpenter's note: in live mode the conflict question after line 26 can satisfy the
# wrap-up moment after line 27. (fixture id, expected after_line) -> first line that counts.
COVERED_FROM = {("holdout_carpenter_wardrobe", 27): 26}


def people(fixture: dict, named: bool) -> list[Person]:
    return [Person(**(p if named else {**p, "name": None})) for p in fixture["people"]]


# ---- recording ----


async def record_sage(path: str) -> None:
    fixture = load(path)
    who = people(fixture, True)
    tuning.SAGE_TIMEOUT_S = 20.0
    stream = sage.SageStream(get_settings().require("sage_api_key"), sage.QUESTIONS)
    preamble = sage.preamble(who)
    answers, lines, holes = {"0": await stream.open(preamble)}, {}, []
    try:
        for line in fixture["lines"]:
            text = lines[str(line["line_no"])] = sage.line_text(sage.speaker_name(who, Role(line["speaker"])), line["text"])
            got = answers[str(line["line_no"])] = await stream.append(line["line_no"], text)
            if got is None:
                holes.append(line["line_no"])
            print(line["line_no"], "".join("-" if not got or got.get(q) is None else "Y" if sage.yes(got, q) else "n" for q in sage.QUESTIONS), flush=True)
    finally:
        await stream.close()
        OUT.mkdir(exist_ok=True)
        out = OUT / f"{fixture['id']}.sage.json"
        # Saved even with holes: a hole is a line Sage2 did not answer in time, which the brain
        # handles as on a real call. Recording again would cost the whole call again.
        out.write_text(json.dumps({
            "fixture": fixture["id"], "recorded_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "preamble": preamble, "questions": sage.QUESTIONS, "updates": stream.updates, "holes": holes,
            "lines": lines, "answers": answers,
        }, ensure_ascii=False, indent=1) + "\n")
        print(f"saved {out}; sage2 updates sent: {stream.updates}; holes: {holes}")


async def record_values(path: str) -> None:
    fixture = load(path)
    out = OUT / f"{fixture['id']}.values.json"
    tuning.LOOKUP_WAIT_S = 30.0
    silence_s, tuning.CLOSING_SILENCE_S = tuning.CLOSING_SILENCE_S, 3600.0
    openai = OpenAIValues(get_settings().require("openai_api_key"))
    saving = _Saving(openai, json.loads(out.read_text())["replies"] if out.exists() else None)
    for variant, (mode, named) in VARIANTS.items():
        print("--", variant, flush=True)
        bus = Bus()
        bus.start()
        brain = Brain(bus, mode, lambda started: (sage.RecordedDecisions(OUT / f"{fixture['id']}.sage.json"), saving))

        async def emit(event: Event | None) -> None:
            if event:
                bus.publish(event)
            await bus.drain(60)
            await brain.idle()
            await bus.drain(60)

        await play({**fixture, "people": [p.model_dump() for p in people(fixture, named)]}, brain, emit, fixture["id"], silence_s)
        await bus.stop()
        saving.saved |= saving.replies
    await openai.close()
    out.write_text(json.dumps({
        "fixture": fixture["id"], "recorded_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "model": tuning.VALUES_MODEL, "replies": saving.saved,
    }, ensure_ascii=False, indent=1) + "\n")
    print(f"saved {out}; openai calls: {openai.calls}")


# ---- replaying ----


async def replay(path: Path, variant: str) -> Run:
    mode, named = VARIANTS[variant]
    fixture = load(path)
    fixture = {**fixture, "people": [p.model_dump() for p in people(fixture, named)]}
    values = RecordedValues(OUT / f"{fixture['id']}.values.json")
    bus = Bus()
    bus.start()
    brain = Brain(bus, mode, lambda started: (sage.RecordedDecisions(OUT / f"{fixture['id']}.sage.json"), values))
    events, started = [], []

    async def collect(event) -> None:
        if isinstance(event, (JudgeSpeak, ChecklistUpdated)):
            events.append(event)
        if isinstance(event, CallStarted):
            started.append(event)

    async def emit(event: Event | None) -> None:
        if event:
            bus.publish(event)
        await bus.drain()

    bus.subscribe_all(collect)
    await play(fixture, brain, emit, f"{fixture['id']}-holdout")
    await bus.stop()
    run = Run(fixture, events, values)
    run.started = started
    return run


# ---- scoring ----


def _pending_alts(want: dict) -> list[tuple[str, int | None]]:
    alts = []
    for text in want.get("also_pending", []):
        m = re.match(r"(\w+)(?: \(until line (\d+)\))?", text)
        alts.append((m.group(1), int(m.group(2)) if m.group(2) else None))
    return alts


def score(run: Run, mode: str) -> dict:
    fid = run.fixture["id"]
    speaks = run.speaks
    wants = [w for w in run.fixture["expected"] if mode in w["modes"]]
    used: set[int] = set()
    outcome: dict[int, tuple[str, int | None, str]] = {}  # want index -> (verdict, speak index, detail)

    def in_window(s, w):
        return w["after_line"] <= s.after_line <= w["by_line"]

    def reasons(w):
        return {w["reason"], *w.get("reason_also_ok", [])}

    def take(i, w, verdict, test, detail="", reuse=False):
        if i in outcome:
            return
        for j, s in enumerate(speaks):
            if (reuse or j not in used) and test(s, w):
                outcome[i] = (verdict, j, detail)
                used.add(j)
                return

    for i, w in enumerate(wants):  # exact
        take(i, w, "hit", lambda s, w: in_window(s, w) and s.reason in reasons(w) and (s.item or None) == w["item"])
    for i, w in enumerate(wants):  # another item they list as open at that moment
        alts = _pending_alts(w)
        take(i, w, "hit", lambda s, w: in_window(s, w) and s.reason in reasons(w) and s.item is not None and any(
            s.item == item and (until is None or s.after_line < until) for item, until in alts), "on an also_pending item")
    for i, w in enumerate(wants):
        start = COVERED_FROM.get((fid, w["after_line"]))
        if start is not None and mode == "live":
            take(i, w, "hit", lambda s, w: start <= s.after_line <= w["by_line"] and s.item == w["item"],
                 "covered by the question already asked", reuse=True)
    for i, w in enumerate(wants):
        take(i, w, "late", lambda s, w: s.after_line > w["by_line"] and s.reason in reasons(w) and (s.item or None) == w["item"])
    for i, w in enumerate(wants):
        take(i, w, "wrong item", lambda s, w: in_window(s, w))

    silent = {m["after_line"] for m in run.fixture["must_stay_silent"]}
    false = [(j, "after a must-stay-silent line" if s.after_line in silent else "") for j, s in enumerate(speaks) if j not in used]
    rows = []
    for i, w in enumerate(wants):
        verdict, j, detail = outcome.get(i, ("missed" if w["required"] else "not taken (optional)", None, ""))
        rows.append({"want": w, "verdict": verdict, "speak": j, "detail": detail})
    return {"rows": rows, "false": false}


def _fmt(s: JudgeSpeak) -> str:
    return f"after {s.after_line}: {s.reason.value} {s.item.value if s.item else '-'} to {s.to.value} | {s.instruction}"


async def score_all() -> dict:
    report = {}
    for path in CALLS:
        fixture = load(path)
        fid = fixture["id"]
        report[fid] = {"noise": fixture["noise"]}
        for variant in VARIANTS:
            run = await replay(path, variant)
            mode = VARIANTS[variant][0]
            result = score(run, mode)
            print(f"\n=== {fid} [{fixture['noise']}] {variant}")
            for j, s in enumerate(run.speaks):
                print(f"  #{j} {_fmt(s)}")
            for row in result["rows"]:
                w = row["want"]
                req = "required" if w["required"] else "optional"
                print(f"  {w['after_line']}-{w['by_line']} {w['reason']} {w['item']} ({req}, to {w['to']}): {row['verdict']}"
                      + (f" by #{row['speak']}" if row["speak"] is not None else "") + (f" [{row['detail']}]" if row["detail"] else ""))
            for j, why in result["false"]:
                print(f"  FALSE FIRE #{j} {why}")
            final = run.final
            print("  final checklist:", "; ".join(
                f"{k}={v.state.value}" + (f" ({v.value})" if v.value else "") + (f" [{v.note}]" if v.note else "") for k, v in final.items()))
            if run.values.missing:
                print("  MISSING recorded values:", run.values.missing)
            names = None
            if variant == "unnamed":
                last = run.started[-1]
                got = {p.role.value: p.name for p in last.people}
                names = {role: (got.get(role), got.get(role) in HEARD[fid][role]) for role in ("hirer", "worker")}
                print("  names learned:", names, "| call.started sent", len(run.started), "times")
            report[fid][variant] = {
                "speaks": [_fmt(s) for s in run.speaks], "rows": [{**r, "want": {k: r["want"][k] for k in ("after_line", "by_line", "reason", "item", "required")}} for r in result["rows"]],
                "false": result["false"], "names": names, "missing": run.values.missing,
            }
    return report


def summary(report: dict) -> None:
    print("\n=== summary")
    for variant in VARIANTS:
        tot = {"required": 0, "hit": 0, "late": 0, "missed": 0, "wrong item": 0, "false": 0, "opt_taken": 0, "opt": 0}
        for fid, r in report.items():
            v = r[variant]
            req = [row for row in v["rows"] if row["want"]["required"]]
            opt = [row for row in v["rows"] if not row["want"]["required"]]
            counts = {k: sum(row["verdict"] == k for row in req) for k in ("hit", "late", "missed", "wrong item")}
            print(f"  {variant:8} {fid:30} required {len(req)} hit {counts['hit']} late {counts['late']} missed {counts['missed']} "
                  f"wrong {counts['wrong item']} | optional taken {sum(row['verdict'] == 'hit' for row in opt)}/{len(opt)} "
                  f"| false fires {len(v['false'])}" + (f" | names {v['names']}" if v["names"] else ""))
            tot["required"] += len(req)
            for k in counts:
                tot[k] += counts[k]
            tot["false"] += len(v["false"])
        print(f"  {variant:8} TOTAL required {tot['required']} hit {tot['hit']} late {tot['late']} missed {tot['missed']} "
              f"wrong {tot['wrong item']} false fires {tot['false']} ({tot['false'] / len(report):.1f} per call)")


if __name__ == "__main__":
    command = sys.argv[1]
    if command == "sage":
        asyncio.run(record_sage(sys.argv[2]))
    elif command == "values":
        asyncio.run(record_values(sys.argv[2]))
    elif command == "score":
        report = asyncio.run(score_all())
        summary(report)
        if len(sys.argv) > 2:
            Path(sys.argv[2]).write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str))
    else:
        raise SystemExit(__doc__)
