"""The human check: one room, the agent, the call page behind a cloudflared quick tunnel, two links.

  ./start.sh          open a room, print the two links, wait for keys
  ./start.sh --dry    no room: only check that the page loads over https through the tunnel

Keys (then Enter):  1 short question   2 two-totals question   3 long read-back (talk over this one)
                    s stop Gawah       q quit and close the room      any other text = spoken as the instruction
The room closes itself after 10 minutes.
"""

import asyncio
import re
import sys

import lk
from agent import Agent
from autotest import ASKS, READ_BACK
from lk import OUT, now
from server import PORT, build, serve

MAX_SECONDS = 600
PRESETS = {"1": ASKS[0], "2": ASKS[2], "3": READ_BACK}


async def tunnel() -> tuple[asyncio.subprocess.Process, str]:
    proc = await asyncio.create_subprocess_exec(
        "cloudflared", "tunnel", "--url", f"http://127.0.0.1:{PORT}", "--no-autoupdate",
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
    )
    url = None
    while line := await asyncio.wait_for(proc.stderr.readline(), 40):
        if found := re.search(rb"https://[a-z0-9-]+\.trycloudflare\.com", line):
            url = found.group().decode()
        # The address is printed before the tunnel is up. Asking for it too early makes macOS
        # remember "no such host" for a while, so wait until cloudflared says it is connected.
        if url and b"Registered tunnel connection" in line:
            asyncio.create_task(proc.stderr.read())  # keep draining so cloudflared never blocks
            await asyncio.sleep(4)
            return proc, url
    raise RuntimeError("cloudflared did not bring a tunnel up")


async def page_loads(url: str) -> bool:
    """Fetch the page through the tunnel. Uses curl with DNS-over-HTTPS so this check never
    touches the system resolver (see the note in tunnel())."""
    for _ in range(10):
        proc = await asyncio.create_subprocess_exec(
            "curl", "-s", "-m", "8", "--doh-url", "https://cloudflare-dns.com/dns-query", url,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        )
        body, _ = await proc.communicate()
        if b"Gawah call" in body:
            return True
        await asyncio.sleep(2)
    return False


async def status_loop(agent: Agent, app) -> None:
    seen: dict[str, str] = {}
    while True:
        await asyncio.sleep(3)
        parts = []
        for who, person in agent.people.items():
            report = app.state.reports.get(who, {})
            if who not in seen and report:
                seen[who] = report.get("ua", "")
                print(f"\n[{who}] browser: {seen[who]}\n[{who}] secure page: {report.get('secure')}  mic on: {report.get('mic')}  mic error: {report.get('micError')}")
            hears = ",".join(k for k, v in report.get("hears", {}).items() if v.get("packets", 0) > 0) or "-"
            mic = "MIC ERROR" if report.get("micError") else ("speaking" if person.speaking else "quiet")
            parts.append(f"{who}: {person.db:6.1f} dB {mic}, receives audio from [{hears}]")
        gawah = "SPEAKING" if agent.mouth.speaking else "silent"
        print(f"[{now():6.1f}s] gawah {gawah} | " + " | ".join(parts or ["nobody has joined yet"]), flush=True)


async def keys(agent: Agent) -> None:
    loop = asyncio.get_running_loop()
    while True:
        line = (await loop.run_in_executor(None, sys.stdin.readline)).strip()
        if line == "q":
            return
        if line == "s":
            await agent.mouth.stop("manual")
        elif line:
            instruction = PRESETS.get(line, line)
            if agent.mouth.speaking:
                print("Gawah is still speaking; wait or press s")
                continue
            before = len(agent.barge_ins)
            u = await agent.mouth.say(instruction)
            print(f">>> triggered: {instruction[:70]}")
            asyncio.create_task(after(agent, u, before))


async def after(agent: Agent, u: dict, barges_before: int) -> None:
    await agent.mouth.wait_done(90)
    await asyncio.sleep(0.3)
    first = round((u["t_first_frame"] - u["t_trigger"]) * 1000) if "t_first_frame" in u else None
    cut = f"CUT OFF by {agent.barge_ins[-1]['who']} after {u['played_ms']} ms of speech" if len(agent.barge_ins) > barges_before else "finished its sentence"
    print(f"<<< Gawah said: {u.get('said')!r}\n<<< first audio published {first} ms after the trigger; {cut}", flush=True)


async def main(dry: bool) -> None:
    room = None if dry else await lk.open_room("human")
    agent = None if dry else Agent(room, OUT / "human")
    app = build(room or "dry", agent)
    server, server_task = await serve(app)
    proc = None
    try:
        proc, base = await tunnel()
        ok = await page_loads(f"{base}/?room={room or 'dry'}&name=check")
        print(f"\nTunnel: {base}\nPage loads over https: {'YES' if ok else 'NO - wait 20 seconds and try the links anyway; if they still fail, quit (q) and start again'}")
        if dry:
            return
        await agent.start()
        print(
            f"\nRoom {room} is open for at most 10 minutes.\n\n"
            f"  PHONE  (send this link to yourself on WhatsApp and tap it there):\n    {base}/?room={room}&name=sunita\n\n"
            f"  LAPTOP (open in Chrome, earphones in):\n    {base}/?room={room}&name=ramesh\n"
            f"    (if that link will not load on the laptop: http://127.0.0.1:{PORT}/?room={room}&name=ramesh)\n\n"
            "Keys, then Enter:  1 short question | 2 two-totals question | 3 long read-back (talk over it) | s stop | q quit\n"
        )
        status = asyncio.create_task(status_loop(agent, app))
        try:
            await asyncio.wait_for(keys(agent), MAX_SECONDS)
        except asyncio.TimeoutError:
            print("10 minutes are up: closing the room.")
        status.cancel()
    finally:
        if proc and proc.returncode is None:
            proc.terminate()
        if agent:
            seconds = agent.seconds_by_identity() if agent.joined_at else {}
            await agent.stop()
            await lk.close_room(room)
            minutes = lk.log_usage(room, "human", seconds)
            await asyncio.sleep(2)
            print(f"\nRoom closed. LiveKit participant-minutes used: {minutes}. Rooms still open: {await lk.list_rooms()}")
            print(f"Barge-ins: {[(b['who'], b['db']) for b in agent.barge_ins]}")
            print(f"Recordings of each person (local only, not committed): {OUT / 'human'}")
        server.should_exit = True
        await server_task


if __name__ == "__main__":
    asyncio.run(main("--dry" in sys.argv))
