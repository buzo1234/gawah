"""One command for a real run: a fresh database, a public tunnel, the server, and a check
of every outside service it will use.

    uv run python tools/demo.py            start everything; Ctrl-C stops it all
    uv run python tools/demo.py --check    only check the services, then exit

Each check is one cheap read-only call. Nothing here sends a message or opens a room.
On Ctrl-C the server shuts down (which closes any call in progress), the tunnel stops,
and any LiveKit room that was not open before this run is deleted.
"""

import argparse
import asyncio
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import Settings  # noqa: E402
from app.contracts import WHATSAPP_WEBHOOK_PATH  # noqa: E402
from tools.service_checks import delete_rooms, open_rooms, run_checks  # noqa: E402

RUNS = ROOT / "runs"  # git-ignored: each run's database and server log
TUNNEL = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")


# ---------- starting and stopping ----------


def start_tunnel(port: int, log: Path) -> tuple[subprocess.Popen, str]:
    if not shutil.which("cloudflared"):
        raise SystemExit("cloudflared is not installed: brew install cloudflared")
    out = log.open("w")
    tunnel = subprocess.Popen(
        ["cloudflared", "tunnel", "--no-autoupdate", "--url", f"http://localhost:{port}"],
        stdout=out, stderr=subprocess.STDOUT, start_new_session=True,
    )
    deadline = time.monotonic() + 40
    while time.monotonic() < deadline:
        found = TUNNEL.search(log.read_text())
        if found:
            return tunnel, found.group()
        if tunnel.poll() is not None:
            break
        time.sleep(0.3)
    stop(tunnel)
    raise SystemExit(f"cloudflared gave no address. Its log: {log}")


def start_server(port: int, env: dict, log: Path) -> subprocess.Popen:
    # Without --reload: a restart drops WhatsApp's open questions (open item 57).
    return subprocess.Popen(
        ["uv", "run", "uvicorn", "app.main:app", "--port", str(port)],
        cwd=ROOT, env=env, stdout=log.open("w"), stderr=subprocess.STDOUT, start_new_session=True,
    )


def wait_for(url: str, seconds: float, process: subprocess.Popen | None = None) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if process is not None and process.poll() is not None:
            return False
        try:
            if httpx.get(url, timeout=3).is_success:
                return True
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    return False


def wait_for_tunnel(public: str, seconds: float = 90) -> bool:
    """Wait until the tunnel answers, asking Cloudflare's DNS directly (DNS over HTTPS).
    Asked through the laptop's own resolver before the new name exists, the "no such
    name" answer is cached, and asking again every few seconds keeps it cached: the
    laptop's browser then cannot open the call link while the phone can."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        code = subprocess.run(
            ["curl", "-s", "-m", "5", "-o", "/dev/null", "-w", "%{http_code}", "--doh-url", "https://1.1.1.1/dns-query", f"{public}/health"],
            capture_output=True, text=True,
        ).stdout
        if code == "200":
            return True
        time.sleep(3)
    return False


def stop(process: subprocess.Popen | None, seconds: float = 20) -> None:
    """Ctrl-C to the process, as a terminal would send it; harder only if it hangs."""
    if process is None or process.poll() is not None:
        return
    process.send_signal(signal.SIGINT)
    try:
        process.wait(seconds)
    except subprocess.TimeoutExpired:
        process.terminate()
        process.wait(5)


def banner(public: str, port: int, db: Path, server_log: Path, ok: bool) -> None:
    line = "-" * 72
    print(f"""
{line}
Gawah is running{'' if ok else ' (BUT A CHECK ABOVE FAILED: fix it or expect that part to break)'}.

Dashboard (open on the laptop):   http://localhost:{port}/dashboard
Public address of this run:       {public}

Paste this into the Twilio WhatsApp sandbox settings, "When a message comes in" (POST).
It changes on every start:

    {public}{WHATSAPP_WEBHOOK_PATH}

  Twilio console > Messaging > Try it out > Send a WhatsApp message > Sandbox settings

What to do first (tools/DEMO-RUN.md has every step):
  1. Paste the address above into Twilio and save.               (step 2)
  2. Open the dashboard on the laptop.                           (step 3)
  3. From your phone, send "hi" to the sandbox number. It should
     show on the dashboard within a few seconds.                 (step 4)
  4. Go on from step 5.

Database for this run: {db.relative_to(ROOT)}
Server log:            {server_log.relative_to(ROOT)}   (tail -f it in another terminal)
Ctrl-C here stops everything and deletes any room this run opened.
{line}
""", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Start Gawah for a real run, or only check the services.")
    parser.add_argument("--check", action="store_true", help="only check the outside services, then exit")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    settings = Settings()

    if args.check:
        print("Checking the outside services:")
        raise SystemExit(0 if asyncio.run(run_checks(settings)) else 1)

    if wait_for(f"http://localhost:{args.port}/health", 1):
        raise SystemExit(f"Something already answers on port {args.port}. Stop it first, or use --port.")
    RUNS.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    db, server_log = RUNS / f"gawah-{stamp}.db", RUNS / f"server-{stamp}.log"
    try:
        rooms_before = set(asyncio.run(open_rooms(settings)))
    except Exception as e:
        rooms_before = set()
        print(f"Could not list LiveKit rooms ({type(e).__name__}); rooms will not be cleaned up at the end.")

    tunnel = server = None
    try:
        print("Starting the tunnel ...", flush=True)
        tunnel, public = start_tunnel(args.port, RUNS / f"tunnel-{stamp}.log")
        print(f"Starting the server on port {args.port} with a fresh database ...", flush=True)
        env = {**os.environ, "DATABASE_PATH": str(db), "PUBLIC_BASE_URL": public}
        server = start_server(args.port, env, server_log)
        if not wait_for(f"http://localhost:{args.port}/health", 60, server):
            raise SystemExit(f"The server did not start. Its log: {server_log}")
        if not wait_for_tunnel(public):
            print("WARN  the public address does not answer. Stop (Ctrl-C) and start again for a new tunnel.")
        elif not wait_for(f"{public}/health", 5):
            print("WARN  this laptop cannot find the public address yet (the phone can). Wait a minute before\n"
                  "      opening a link on the laptop, or run: sudo killall -HUP mDNSResponder")
        print("Checking the outside services:")
        ok = asyncio.run(run_checks(settings))
        banner(public, args.port, db, server_log, ok)
        while server.poll() is None and tunnel.poll() is None:
            time.sleep(1)
        print("The server stopped by itself." if server.poll() is not None else "The tunnel stopped by itself.",
              f"See {server_log.relative_to(ROOT)}.")
    except KeyboardInterrupt:
        print("\nStopping ...", flush=True)
    finally:
        signal.signal(signal.SIGINT, signal.SIG_IGN)  # a second Ctrl-C must not cut the clean-up short
        stop(server)
        stop(tunnel)
        try:
            left = [r for r in asyncio.run(open_rooms(settings)) if r not in rooms_before]
            if left:
                asyncio.run(delete_rooms(settings, left))
                print(f"Deleted {len(left)} room(s) this run opened: {', '.join(left)}")
            still = asyncio.run(open_rooms(settings))
            print(f"LiveKit rooms open now: {', '.join(still) if still else 'none'}")
        except Exception as e:
            print(f"Could not check LiveKit rooms ({type(e).__name__}). Check the LiveKit dashboard.")
        print("Stopped.")


if __name__ == "__main__":
    main()
