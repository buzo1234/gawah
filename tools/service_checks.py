"""The outside services a real run needs, each checked with one cheap read-only call.
Used by tools/run_live.py. Nothing here sends a message, opens a room, or is billed."""

import asyncio
from pathlib import Path

import boto3
import httpx
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from app.call.livekit import LiveKit
from app.config import Settings
from app.contract.pdf import find_chrome

TIMEOUT = 10.0


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
