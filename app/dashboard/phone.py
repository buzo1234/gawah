"""The second phone: plays a person who has no real phone. Its page is /dashboard/phone,
shown on the board in a phone-shaped frame.

A message typed on the phone is posted to the WhatsApp webhook path as the form the
provider (Twilio) sends for an inbound WhatsApp message, so it goes through the real
intake. Nothing here publishes an event: the whatsapp stream does that for every message.

The post is made inside this process (no network), straight into the app's own routes.
"""

import base64
import hashlib
import hmac
import re
import tempfile
from pathlib import Path
from uuid import uuid4

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

from app.contracts import NO_DEAL, WHATSAPP_WEBHOOK_PATH
from app.log import deal_log, mask_phone

log = deal_log("gawah.dashboard", NO_DEAL)

PAGE = Path(__file__).parent / "phone.html"
MEDIA_DIR = Path(tempfile.gettempdir()) / "gawah-second-phone"
MEDIA_TYPES = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}
MEDIA_NAME = re.compile(r"[0-9a-f]{32}\.(jpg|png|webp)")
MAX_MEDIA_BYTES = 16 * 1024 * 1024  # WhatsApp's own limit
_PROXY_HEADERS = ("cf-connecting-ip", "x-forwarded-for")


class Outgoing(BaseModel):
    phone: str
    text: str = ""
    media_url: str | None = None
    media_type: str | None = None
    profile_name: str = "Second phone"


def provider_form(msg: Outgoing, to: str, account_sid: str) -> dict[str, str]:
    """The fields Twilio posts for an inbound WhatsApp message."""
    digits = re.sub(r"\D", "", msg.phone)
    if not digits:
        raise ValueError("the phone number has no digits")
    sid = ("MM" if msg.media_url else "SM") + uuid4().hex
    form = {
        "MessageSid": sid,
        "SmsSid": sid,
        "SmsMessageSid": sid,
        "AccountSid": account_sid,
        "From": f"whatsapp:+{digits}",
        "To": to if to.startswith("whatsapp:") else f"whatsapp:{to}",
        "Body": msg.text,
        "NumMedia": "1" if msg.media_url else "0",
        "NumSegments": "1",
        "ProfileName": msg.profile_name,
        "WaId": digits,
        "SmsStatus": "received",
        "ApiVersion": "2010-04-01",
        "MessageType": "image" if msg.media_url else "text",
    }
    if msg.media_url:
        form["MediaUrl0"] = msg.media_url
        form["MediaContentType0"] = msg.media_type or "image/jpeg"
    return form


def signature(url: str, form: dict[str, str], auth_token: str) -> str:
    """X-Twilio-Signature: HMAC-SHA1 of the url followed by each field's name and value,
    in name order, keyed with the account's auth token."""
    signed = url + "".join(k + form[k] for k in sorted(form))
    return base64.b64encode(hmac.new(auth_token.encode(), signed.encode(), hashlib.sha1).digest()).decode()


def register(app: FastAPI) -> None:
    settings = app.state.settings

    def local_only(request: Request) -> None:
        if any(h in request.headers for h in _PROXY_HEADERS):
            raise HTTPException(403, "local only")

    @app.get("/dashboard/phone", response_class=HTMLResponse)
    async def page() -> str:
        return PAGE.read_text()

    @app.post("/dashboard/media")
    async def upload(request: Request) -> dict[str, str]:
        """Keep an attached image and give it an address, as the provider would."""
        local_only(request)
        content_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
        if content_type not in MEDIA_TYPES:
            raise HTTPException(415, "attach a JPEG, PNG, or WebP image")
        body = await request.body()
        if not body or len(body) > MAX_MEDIA_BYTES:
            raise HTTPException(413, "the image is empty or larger than 16 MB")
        name = f"{uuid4().hex}.{MEDIA_TYPES[content_type]}"
        MEDIA_DIR.mkdir(exist_ok=True)
        (MEDIA_DIR / name).write_bytes(body)
        return {"url": str(request.base_url).rstrip("/") + f"/dashboard/media/{name}", "content_type": content_type}

    @app.get("/dashboard/media/{name}")
    async def media(name: str) -> FileResponse:
        if not MEDIA_NAME.fullmatch(name) or not (MEDIA_DIR / name).is_file():
            raise HTTPException(404)
        return FileResponse(MEDIA_DIR / name)

    @app.post("/dashboard/phone/send")
    async def send(msg: Outgoing, request: Request) -> dict:
        local_only(request)
        if not msg.text.strip() and not msg.media_url:
            raise HTTPException(422, "nothing to send")
        try:
            form = provider_form(
                msg,
                to=settings.twilio_whatsapp_number or "+10000000000",
                account_sid=settings.require("twilio_account_sid") if settings.twilio_account_sid else "AC" + "0" * 32,
            )
        except ValueError as e:
            raise HTTPException(422, str(e)) from e
        base = str(request.base_url).rstrip("/")
        headers = {}
        if settings.twilio_auth_token:
            # Twilio signs the public address it was given, so the intake checks against that.
            public = (settings.public_base_url or base).rstrip("/")
            headers["X-Twilio-Signature"] = signature(
                public + WHATSAPP_WEBHOOK_PATH, form, settings.require("twilio_auth_token")
            )
        transport = httpx.ASGITransport(app=request.app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url=base, timeout=20.0) as client:
            response = await client.post(WHATSAPP_WEBHOOK_PATH, data=form, headers=headers)
        log.info(
            "second phone %s sent %s to %s: %s",
            mask_phone(form["WaId"]), form["MessageType"], WHATSAPP_WEBHOOK_PATH, response.status_code,
        )
        return {"status": response.status_code, "path": WHATSAPP_WEBHOOK_PATH, "form": form}
