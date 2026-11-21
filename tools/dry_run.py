"""A rehearsal of the two-call demo with no person (tools/DEMO-RUN.md, fixtures/demo/).

    uv run python tools/demo.py                  (in one terminal: the real services)
    uv run python tools/dry_run.py               (in another)
    uv run python tools/dry_run.py --offline     (alone: tests/offline.py in this process, nothing outside)
    uv run python tools/dry_run.py --from call2  (carry on the server's latest deal from call 2)

Day 1: Sunita sends "hi" and Ramesh's number on WhatsApp; both open their call link and
the deal call plays out (fixtures/demo/call_1.json); each confirms on their own call-back;
version 1 of the agreement arrives; Sunita's advance screenshot is logged and both are told
what is still owed. Day 5: Ramesh opens a new call from his link, Sunita is told on WhatsApp
and joins, and call 2 plays out (call_2.json): the contradiction with its clip, and a change
both agree by voice; version 2 arrives. Day 7: Ramesh says the work is done, Sunita says
haan, and after the Sentinel's delay she is reminded of the balance.

Both phones are simulated (numbers not in VERIFIED_NUMBERS): nothing is sent on real
WhatsApp. Each line is said only once Gawah is quiet, and where a line's "then" says Gawah
should speak, the next line waits for it (up to "within_s"). --from call2 or --from day7
starts from that step on the server's latest deal, so a broken step can be retried.

Live it uses about: call 1 of 4 to 5 minutes and call 2 of about 3 (4 in each room: two
people, the listener and Gawah), two call-backs of 2 to 3 minutes (2 in the room): about
45 LiveKit participant-minutes; two Sage2 calls (about 35 updates); OpenAI transcription,
Gawah's realtime sessions, the Scribe, two contract versions and their spoken summaries;
4 S3 recordings and 4 contract files. Writes every event, the steps, and dashboard
screenshots to runs/dry-<time>/.
"""

import argparse
import asyncio
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools import demo_story as story  # noqa: E402
from tools.dry_events import Run  # noqa: E402
from tools.dry_players import ROLES, LivePlayers, OfflinePlayers  # noqa: E402

GAP_S = 1.0  # between one person's line and the next
QUIET_S = 1.5  # Gawah silent this long before a person speaks
DONE_QUIET_S = 3.0  # after Gawah has said something, silent this long: it has finished
STAGES = ("call1", "call2", "day7")


async def wait_quiet(run: Run, players, cap: float = 40.0) -> None:
    quiet_since, end = time.monotonic(), time.monotonic() + cap
    while time.monotonic() < end:
        if await players.gawah_talking():
            quiet_since = time.monotonic()
        elif time.monotonic() - quiet_since >= (0 if players.offline else QUIET_S):
            return
        await asyncio.sleep(0.25)


async def gawah_moment(run: Run, players, call_no: int, line: dict) -> dict:
    """Wait for Gawah to speak where the script says it should, and to finish."""
    then, t0 = line["then"], time.monotonic()
    heard = lambda: run.gawah_said(after=t0)  # noqa: E731
    started = None
    while time.monotonic() - t0 < then["within_s"]:
        if heard() or await players.gawah_talking():
            started = time.monotonic()
            break
        await asyncio.sleep(0.25)
    if started:
        quiet_since, cap = time.monotonic(), time.monotonic() + 90
        while time.monotonic() < cap:
            if await players.gawah_talking():
                quiet_since = time.monotonic()
            quiet = time.monotonic() - quiet_since
            if (heard() and quiet >= (0.5 if players.offline else DONE_QUIET_S)) or quiet >= 10:
                break
            await asyncio.sleep(0.25)
    said = heard()
    result = "worked" if said else ("optional, nothing said" if then.get("optional") else "broke")
    return run.step(f"call {call_no} line {line['line_no']}: Gawah {then['gawah']}", result,
                    started_after_s=round(started - t0, 1) if started else None, said=said,
                    asked=run.speaks_since(t0))


async def deal_call(run: Run, players, call_no: int) -> None:
    fixture = story.call(call_no)
    if call_no == 1:
        for role in ROLES:
            await players.join(role, run.link(role, "call"))
    else:
        sent = len(run.sent_to("hirer"))
        await players.join("worker", run.link("worker", "call"))
        opened = await run.until(lambda: run.of("call.opened", call_no=call_no), 20)
        told = await run.until(lambda: [t for t in run.sent_to("hirer")[sent:] if "/call/" in t], 30)
        run.step("call 2: Ramesh opens it from his link, Sunita is told on WhatsApp", "worked" if opened and told else "broke",
                 told=told[:1] if told else None)
        if not told:
            return
        await players.join("hirer", re.search(r"https?://\S+/call/\S+", told[0]).group())
    started = await run.until(lambda: run.of("call.started", kind="deal", call_no=call_no), 40)
    run.step(f"call {call_no}: both in, call.started", "worked" if started else "broke")
    if not started:
        return
    t_start = time.monotonic()
    opening = await run.until(lambda: [e for e in run.of("judge.spoke") if not e.get("speak_id") and run.at(e) >= t_start - 2], 40)
    run.step(f"call {call_no}: Gawah's opening line, asks names", "worked" if opening else "broke",
             said=opening[0]["text"] if opening else None, after_s=round(run.at(opening[0]) - t_start, 1) if opening else None)
    await asyncio.sleep(2 if not players.offline else 0)
    for line in fixture["lines"]:
        await wait_quiet(run, players)
        await players.say(call_no, line)
        await players.after_line(call_no, line, run.deal_id)
        await asyncio.sleep(GAP_S if not players.offline else 0.2)
        if line.get("then"):
            moment = await gawah_moment(run, players, call_no, line)
            if call_no == 1 and "advance" in line["then"]["gawah"]:
                await run.shot("1-gawah-answers-the-question")
            if call_no == 2 and "plays" in line["then"]["gawah"]:
                await run.shot("2-contradiction-with-the-clip")
                moment["clip"] = [e.get("text") for e in run.of("agent.note", agent="gawah") if "clip" in e.get("text", "").lower()][-3:]
    await wait_quiet(run, players, 20)
    await players.leave()
    ended = await run.until(lambda: run.of("call.ended", kind="deal", call_no=call_no), 60)
    lines = run.of("transcript.line", kind="deal", call_no=call_no)
    run.step(f"call {call_no}: ended", "worked" if ended else "broke", minutes=round((time.monotonic() - t_start) / 60, 1),
             lines={r: sum(1 for x in lines if x["speaker"] == r) for r in ROLES}, played=len(fixture["lines"]),
             recordings=sorted((ended[0].get("recording_keys") or {})) if ended else None)
    checklist = run.of("checklist.updated")
    if checklist:
        run.step(f"call {call_no}: checklist at the end", "seen",
                 items={i["key"]: (i["state"], i.get("value")) for i in checklist[-1]["items"]})


async def call_backs(run: Run, players, since: dict[str, int], expect: bool) -> None:
    """since: for each person, how many messages they had before the call ended; links sent after count."""
    def found() -> list[str]:
        return [link for r in ROLES if (link := run.link(r, "callback", since=since[r]))]

    links = await run.until(found, 30 if expect else 20)
    run.step("call-back links sent", "worked" if links or not expect else "broke", to=len(links or []))
    for link in links or []:
        role = link.rstrip("/").rsplit("/", 1)[-1].split("?")[0]
        before, opened = len(run.of("call.ended", kind="callback")), time.monotonic()
        await players.call_back(link)
        done = await run.until(lambda: len(run.of("call.ended", kind="callback")) > before, 240)
        players.end_call_back()
        confirmed = [e for e in run.of("terms.confirmed") if e["person"] == role and run.at(e) >= opened]
        disputed = [e for e in run.of("terms.disputed") if e["person"] == role and run.at(e) >= opened]
        run.step(f"call-back {role}", "worked" if confirmed and done else ("disputed" if disputed else "broke"),
                 seconds=round(time.monotonic() - opened), disputed=[d.get("item") for d in disputed])


async def contract(run: Run, version: int) -> None:
    ready = await run.until(lambda: len(run.of("contract.ready")) >= version and run.of("contract.ready"), 240)
    run.step(f"agreement version {version}: contract.ready", "worked" if ready else "broke")
    if ready:
        await asyncio.sleep(4)
        if version == 2:
            await run.shot("4-version-2-arrives")
        run.step(f"agreement version {version} on WhatsApp", "seen",
                 hirer=run.shown(run.sent_to("hirer")[-3:]), worker=run.shown(run.sent_to("worker")[-3:]))


async def day1(run: Run, players) -> None:
    await run.phone("hirer", "hi")
    hello = await run.until(lambda: run.sent_to("hirer"), 20)
    run.step("day 1: Sunita says hi, Gawah answers", "worked" if hello else "broke", said=hello[:1] if hello else None)
    await run.phone("hirer", story.NUMBER_TEXT)
    links = await run.until(lambda: all(run.link(r, "call") for r in ROLES), 30)
    run.step("day 1: Sunita sends Ramesh's number, both get a call link", "worked" if links else "broke")
    if not links:
        raise SystemExit("no call links")
    run.deal_id = run.of("deal.requested")[0]["deal_id"]
    await deal_call(run, players, 1)
    await call_backs(run, players, since={r: 0 for r in ROLES}, expect=True)
    await contract(run, 1)
    url = await run.upload(story.SCREENSHOT)
    owed_before = len(run.sent_to("hirer"))
    await run.phone("hirer", story.SCREENSHOT_CAPTION, media_url=url, media_type="image/png")
    logged = await run.until(lambda: [e for e in run.of("record.received") if e["record"].get("media_url")], 40)
    owed = await run.until(lambda: [t for t in run.sent_to("hirer")[owed_before:] if "baaki" in t.lower()], 40)
    run.step("day 1: the advance screenshot is logged, both told what is owed", "worked" if logged and owed else "broke",
             record={k: logged[0]["record"].get(k) for k in ("kind", "backing", "amount")} if logged else None,
             told_hirer=run.shown(run.sent_to("hirer")[owed_before:]), told_worker=run.shown(run.sent_to("worker")[-1:]))


async def day5(run: Run, players) -> None:
    contracts = len(run.of("contract.ready"))
    await deal_call(run, players, 2)
    sent = {r: len(run.sent_to(r)) for r in ROLES}
    changed = run.of("fact.changed", status="confirmed_both")
    run.step("call 2: the change, confirmed by both", "worked" if changed else "broke",
             steps=[(e["status"], e.get("new_value"), e.get("confirmed_by")) for e in run.of("fact.changed")])
    await call_backs(run, players, since=sent, expect=False)
    await contract(run, contracts + 1)


async def day7(run: Run, players) -> None:
    await run.phone("worker", story.WORK_DONE)
    asked = await run.until(lambda: [e for e in run.of("record.confirm_requested") if e.get("confirm_by") == "hirer"], 40)
    run.step("day 7: Ramesh says the work is done, Sunita is asked", "worked" if asked else "broke",
             question=asked[-1].get("question") if asked else None)
    if not asked:
        return
    await run.phone("hirer", story.YES)
    done = await run.until(lambda: [t for t in run.sent_to("worker") if t.startswith("Kaam poora ho gaya")], 40)
    run.step("day 7: Sunita says haan, both told it is done and what is owed", "worked" if done else "broke", said=done[-1:] if done else None)
    reminded = await run.until(lambda: [t for t in run.sent_to("hirer") if t.startswith("Yaad dila raha hoon")], 150)
    told = await run.until(lambda: [t for t in run.sent_to("worker") if t.startswith("Gawah ne")], 20)
    run.step("day 7: after the delay, Sunita is reminded of the balance", "worked" if reminded and told else "broke",
             hirer=reminded[-1:] if reminded else None, worker=told[-1:] if told else None)


async def main(args) -> None:
    out = ROOT / "runs" / f"dry-{datetime.now():%Y%m%d-%H%M%S}{'-offline' if args.offline else ''}"
    out.mkdir(parents=True)
    if args.offline:
        players = OfflinePlayers(out, args.port)
        await players.start()
        url = players.url
    else:
        from app.config import get_settings

        key = get_settings().openai_api_key
        speech = {no: await story.speech(story.call(no)["lines"], key) for no in (1, 2)}
        players, url = LivePlayers(out, speech), args.url
    run = Run(url, out)
    await run.begin()
    try:
        if args.start != "call1":
            await run.load_past()
        if args.start == "call1":
            await day1(run, players)
        if args.start in ("call1", "call2"):
            await day5(run, players)
        await day7(run, players)
        await run.shot("5-the-end")
    finally:
        players.close()
        run.usage["people's browser participant-minutes"] = round(players.minutes, 1)
        await run.end()
        if args.offline:
            await players.stop()
        print(f"written to {out.relative_to(ROOT)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Walk the two-call demo once with no person.")
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument("--offline", action="store_true", help="the offline app in this process: nothing outside is called")
    parser.add_argument("--port", type=int, default=8077, help="--offline: where to serve the offline app")
    parser.add_argument("--from", dest="start", choices=STAGES, default="call1",
                        help="start from this step, on the server's latest deal")
    asyncio.run(main(parser.parse_args()))
