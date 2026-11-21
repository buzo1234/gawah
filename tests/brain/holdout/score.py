"""Scoring for tests/brain/holdout/run.py: each expected moment as hit, late, missed or wrong
item, each judge.speak no moment took as a false fire, and the memory's terms per call."""

import asyncio
import json
import re
from pathlib import Path

from app.contracts import JudgeSpeak, SpeakReason
from tests.brain.holdout.run import SETS, VARIANTS, deals, replay

# The names each person is called by on the call (None: never named, so nothing to learn).
HEARD = {
    "holdout_carpenter_wardrobe": {"hirer": {"Deepak"}, "worker": {"Abdul"}},
    "holdout_cook_month": {"hirer": {"Sharma", None}, "worker": {"Kamla"}},
    "holdout_electrician_shop": {"hirer": {"Imran"}, "worker": {"Suresh"}},
    "holdout_plumber_leak": {"hirer": {"Sunita"}, "worker": {"Raju"}},
    "holdout_tutor_monthly": {"hirer": {"Ruma"}, "worker": {"Ankit"}},
    "holdout2_tailor_lehenga": {"hirer": {"Sunita", "Bansal", "Sunita Bansal"}, "worker": {None, "Master", "Master ji"}},
    "holdout2_car_mechanic": {"hirer": {"Abhishek"}, "worker": {"Salim"}},
    "holdout2_driver_monthly": {"hirer": {"Ananya", "अनन्या"}, "worker": {"Santosh", "संतोष"}},
    "holdout2_ac_repair": {"hirer": {None}, "worker": {"Vikas", "विकास"}},
    "holdout2_mason_wall_call1": {"hirer": {None, "Fauji", "Fauji sahab"}, "worker": {"Shakeel"}},
}
# The carpenter's note: in live mode the conflict question after line 26 can satisfy the
# wrap-up moment after line 27. (fixture id, expected after_line) -> first line that counts.
COVERED_FROM = {("holdout_carpenter_wardrobe", 27): 26}
# The fresh set names reasons in plain words.
REASON = {"two_meanings": SpeakReason.AMBIGUOUS.value, "question_to_gawah": SpeakReason.ADDRESSED_DIRECTLY.value}
CONTRADICTION = {SpeakReason.CONFLICTING_FIGURES.value, SpeakReason.CONTRADICTS_RECORD.value}


def reasons(w: dict) -> set[str]:
    ok = {REASON.get(r, r) for r in (w["reason"], *w.get("reason_also_ok", []))}
    # A figure that differs from one already agreed is raised from the memory's fact.conflict
    # as contradicts_record; both names count for a contradiction.
    return ok | CONTRADICTION if ok & CONTRADICTION else ok


def _pending_alts(want: dict) -> list[tuple[str, int | None]]:
    alts = []
    for text in want.get("also_pending", []):
        m = re.match(r"(\w+)(?: \(until line (\d+)\))?", text)
        alts.append((m.group(1), int(m.group(2)) if m.group(2) else None))
    return alts


def score(run, mode: str) -> dict:
    fid = run.fixture["id"]
    speaks = run.speaks
    wants = [w for w in run.fixture["expected"] if mode in w["modes"]]
    used: set[int] = set()
    outcome: dict[int, tuple[str, int | None, str]] = {}

    def in_window(s, w):
        return w["after_line"] <= s.after_line <= w["by_line"]

    def item_ok(s, w):
        # An answer to someone who spoke to Gawah is about no one item.
        return (s.item or None) == w["item"] or (s.reason == SpeakReason.ADDRESSED_DIRECTLY and w["reason"] == "question_to_gawah")

    def take(i, w, verdict, test, detail="", reuse=False):
        if i in outcome:
            return
        for j, s in enumerate(speaks):
            if (reuse or j not in used) and test(s, w):
                outcome[i] = (verdict, j, detail)
                used.add(j)
                return

    for i, w in enumerate(wants):
        take(i, w, "hit", lambda s, w: in_window(s, w) and s.reason in reasons(w) and item_ok(s, w))
    for i, w in enumerate(wants):
        alts = _pending_alts(w)
        take(i, w, "hit", lambda s, w: in_window(s, w) and s.reason in reasons(w) and s.item is not None and any(
            s.item == item and (until is None or s.after_line < until) for item, until in alts), "on an also_pending item")
    for i, w in enumerate(wants):
        start = COVERED_FROM.get((fid, w["after_line"]))
        if start is not None and mode == "live":
            take(i, w, "hit", lambda s, w: start <= s.after_line <= w["by_line"] and s.item == w["item"],
                 "covered by the question already asked", reuse=True)
    for i, w in enumerate(wants):
        take(i, w, "late", lambda s, w: s.after_line > w["by_line"] and s.reason in reasons(w) and item_ok(s, w))
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
    q = f" | question: {s.question}" if s.question else ""
    return f"after {s.after_line}: {s.reason.value} {s.item.value if s.item else '-'} to {s.to.value} | {s.instruction}{q}"


def _carried(run, speak: JudgeSpeak, asked_at: int) -> bool:
    """The judge.speak carries the words of the line that asked Gawah."""
    asked = next(line["text"] for line in run.fixture["lines"] if line["line_no"] == asked_at)
    return bool(speak.question) and " ".join(asked.split()) in speak.question


async def score_set(name: str) -> dict:
    report = {}
    for calls in deals(SETS[name]):
        for variant in VARIANTS:
            mode = VARIANTS[variant][0]
            for run in await replay(calls, variant):
                fid = run.fixture["id"]
                entry = report.setdefault(fid, {"noise": run.fixture["noise"], "set": name})
                result = score(run, mode)
                print(f"\n=== [{name}] {fid} [{run.fixture['noise']}] {variant}")
                for j, s in enumerate(run.speaks):
                    print(f"  #{j} {_fmt(s)}")
                for row in result["rows"]:
                    w = row["want"]
                    req = "required" if w["required"] else "optional"
                    extra = ""
                    if row["speak"] is not None and w["reason"] == "question_to_gawah":
                        extra = f" [question carried: {_carried(run, run.speaks[row['speak']], w['after_line'])}]"
                    print(f"  {w['after_line']}-{w['by_line']} {w['reason']} {w['item']} ({req}, to {w['to']}): {row['verdict']}"
                          + (f" by #{row['speak']}" if row["speak"] is not None else "") + (f" [{row['detail']}]" if row["detail"] else "") + extra)
                for j, why in result["false"]:
                    print(f"  FALSE FIRE #{j} {why}")
                final = run.final if run.checklists else {}
                print("  final checklist:", "; ".join(
                    f"{k}={v.state.value}" + (f" ({v.value})" if v.value else "") + (f" [{v.note}]" if v.note else "") for k, v in final.items()))
                if variant == "live":
                    print("  memory terms at the end:")
                    for k, v in run.terms.items():
                        print(f"    {k}: {v}")
                    for c, fact in run.memory_conflicts:
                        cited = f"{fact.item.value if fact.item else '-'} '{fact.value}' (call {fact.call_no} line {fact.line_no})" if fact else "?"
                        print(f"  memory conflict line {c.line_no}: {c.explanation} | cites {cited}")
                if run.values.missing:
                    print("  MISSING recorded values:", run.values.missing)
                if run.missing_checks:
                    print("  MISSING recorded Scribe checks:", run.missing_checks)
                names = None
                if variant == "unnamed" and fid in HEARD:
                    got = {p.role.value: p.name for p in run.started[-1].people}
                    names = {role: (got.get(role), got.get(role) in HEARD[fid][role]) for role in ("hirer", "worker")}
                    print("  names learned:", names, "| call.started sent", len(run.started), "times")
                entry[variant] = {
                    "speaks": [_fmt(s) for s in run.speaks],
                    "rows": [{**r, "want": {k: r["want"][k] for k in ("after_line", "by_line", "reason", "item", "required")}} for r in result["rows"]],
                    "false": result["false"], "names": names, "missing": run.values.missing, "missing_checks": run.missing_checks,
                    "terms": run.terms, "conflicts": [(c.line_no, c.explanation) for c, _ in run.memory_conflicts],
                }
    return report


def summary(name: str, report: dict) -> None:
    print(f"\n=== summary [{name}]")
    for variant in VARIANTS:
        tot = {"required": 0, "hit": 0, "late": 0, "missed": 0, "wrong item": 0, "false": 0}
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
        rate = tot["hit"] / tot["required"] if tot["required"] else 0
        print(f"  {variant:8} TOTAL required {tot['required']} hit {tot['hit']} ({rate:.0%}) late {tot['late']} missed {tot['missed']} "
              f"wrong {tot['wrong item']} false fires {tot['false']} ({tot['false'] / len(report):.1f} per call)")


def score_main(which: str, out: str | None) -> None:
    names = list(SETS) if which == "all" else [which]
    full = {}
    for name in names:
        full[name] = asyncio.run(score_set(name))
    for name in names:
        summary(name, full[name])
    if out:
        Path(out).write_text(json.dumps(full, ensure_ascii=False, indent=1, default=str))
