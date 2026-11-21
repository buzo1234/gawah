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

import boto3
import httpx
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.call.livekit import LiveKit  # noqa: E402
from app.config import Settings  # noqa: E402
from app.contract.pdf import find_chrome  # noqa: E402
from app.contracts import WHATSAPP_WEBHOOK_PATH  # noqa: E402

RUNS = ROOT / "runs"  # git-ignored: each run's database and server log
TIMEOUT = 10.0
TUNNEL = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")


# ---------- the checks: each returns (ok, what it found) ----------


async def check_openai(s: Settings) -> tuple[bool, str]:
    async with httpx.AsyncClient(timeout=TIMEOUT) as http:
        r = await http.get("https://api.openai.com/v1/models", headers={"Authorization": f"Bearer {s.require('openai_api_key')}"})
    return (True, "key works") if r.is_success else (False, f"HTTP {r.status_code}: {_reason(r)}")


async def check_sage(s: Settings) -> tuple[bool, str]:
    # An empty question: Sage2 checks the key first (401 if wrong), then refuses the empty
    # body (400) without deciding anything, so nothing is billed.
    async with httpx.AsyncClient(timeout=TIMEOUT) as http:
        r = await http.post("https://sage.levanto.ai/decide", json={}, headers={"Authorization": f"Bearer {s.require('sage_api_key')}"})
    if r.status_code in (400, 422):
        return True, "key works (free usage left is not shown: see the Levanto dashboard)"
    return False, f"HTTP {r.status_code}: {_reason(r)}"


async def check_livekit(s: Settings) -> tuple[bool, str]:
    rooms = await open_rooms(s)
    if rooms:
        return True, f"key works, but {len(rooms)} room(s) open: {', '.join(rooms)}. Each one costs minutes."
    return True, "key works, no rooms open"


async def check_twilio(s: Settings) -> tuple[bool, str]:
    sid, token = s.require("twilio_account_sid"), s.require("twilio_auth_token")
    s.require("twilio_whatsapp_number")
    async with httpx.AsyncClient(timeout=TIMEOUT, auth=(sid, token)) as http:
        r = await http.get(f"https://api.twilio.com/2010-04-01/Accounts/{sid}.json")
    if not r.is_success:
        return False, f"HTTP {r.status_code}: {_reason(r)}"
    account = r.json()
    if account.get("status") != "active":
        return False, f"account is {account.get('status')}"
    return True, f"key works ({account.get('type', '').lower()} account)"


async def check_s3(s: Settings) -> tuple[bool, str]:
    client = boto3.client(
        "s3", region_name=s.aws_default_region,
        aws_access_key_id=s.require("aws_access_key_id"), aws_secret_access_key=s.require("aws_secret_access_key"),
        aws_session_token=s.aws_session_token.get_secret_value() if s.aws_session_token else None,
        config=Config(connect_timeout=TIMEOUT, read_timeout=TIMEOUT, retries={"max_attempts": 1}),
    )
    try:
        await asyncio.to_thread(client.list_objects_v2, Bucket=s.require("s3_bucket"), MaxKeys=1)
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        if code in ("ExpiredToken", "TokenRefreshRequired", "RequestExpired"):
            return False, "the AWS keys have EXPIRED. Put new ones in .env: all three together (key id, secret, session token)"
        if code in ("InvalidAccessKeyId", "SignatureDoesNotMatch", "InvalidToken"):
            return False, f"the AWS keys are wrong ({code}). Put new ones in .env: all three together"
        return False, code or type(e).__name__
    except BotoCoreError as e:
        return False, type(e).__name__
    return True, "keys work, bucket readable"


async def check_chrome(s: Settings) -> tuple[bool, str]:
    found = find_chrome()
    return (True, Path(found).name) if found else (False, "no Chrome, Chromium, Edge or Brave: the contract PDF cannot be printed")


CHECKS = {
    "OpenAI": check_openai, "Sage2": check_sage, "LiveKit": check_livekit,
    "Twilio": check_twilio, "S3": check_s3, "Chrome (PDF)": check_chrome,
}


def _reason(r: httpx.Response) -> str:
    """Only the service's own error message: never the request, which carries the key."""
    try:
        body = r.json()
    except ValueError:
        return r.reason_phrase
    error = body.get("error") if isinstance(body, dict) else None
    message = (error.get("message") if isinstance(error, dict) else error) or body.get("message") or body.get("detail")
    return str(message or r.reason_phrase)[:160]


async def run_checks(s: Settings) -> bool:
    async def one(name, check):
        try:
            async with asyncio.timeout(TIMEOUT + 5):
                return name, *(await check(s))
        except RuntimeError as e:  # settings.require: a key missing from .env
            return name, False, str(e)
        except TimeoutError:
            return name, False, "no answer in time (network down?)"
        except Exception as e:
            return name, False, f"{type(e).__name__}: {str(e)[:160]}"

    results = await asyncio.gather(*(one(n, c) for n, c in CHECKS.items()))
    for name, ok, said in results:
        print(f"  {'OK  ' if ok else 'FAIL'}  {name:<13} {said}")
    if not s.verified_number_list:
        print("  WARN  VERIFIED_NUMBERS is empty: every phone is simulated, nothing reaches a real WhatsApp")
    return all(ok for _, ok, _ in results)


async def open_rooms(s: Settings) -> list[str]:
    livekit = LiveKit(s)
    try:
        return await livekit.list_rooms()
    finally:
        await livekit.close()


async def delete_rooms(s: Settings, names: list[str]) -> None:
    livekit = LiveKit(s)
    try:
        for name in names:
            await livekit.delete_room(name)
    finally:
        await livekit.close()


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

What to do first:
  1. Paste the address above into Twilio and save.
  2. From your phone, send any short message (like "hi") to the sandbox number.
     Gawah should answer within a few seconds. If it does not, the address is wrong.
  3. Then follow tools/DEMO-RUN.md from step 2.

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
        if not wait_for(f"{public}/health", 30):
            print("WARN  the public address does not answer yet. A new tunnel can take a minute to be found.")
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
