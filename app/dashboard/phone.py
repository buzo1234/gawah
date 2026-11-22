"""The second phone: plays a person who has no real phone. Its page is /dashboard/phone,
shown on the board in a phone-shaped frame.

A message typed on the phone is posted to the WhatsApp webhook path as the form the
provider (Twilio) sends for an inbound WhatsApp message, so it goes through the real
intake. A reply button tapped on the phone is posted as Meta sends a tapped button (an
interactive button_reply carrying the button's id), since only Meta shows reply buttons,
signed with META_APP_SECRET when it is set, as Meta signs. Nothing here publishes an event: the whatsapp stream does that for every message.

The post is made inside this process (no network), straight into the app's own routes.
"""

import base64
import hashlib
import hmac
import json
import re
import time
import tempfile
from pathlib import Path
from uuid import uuid4

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, SecretStr

from app.access import local_or_keyed
from app.config import Settings
from app.contracts import NO_DEAL, WHATSAPP_WEBHOOK_PATH
from app.log import deal_log, mask_phone

log = deal_log("gawah.dashboard", NO_DEAL)

PAGE = Path(__file__).parent / "phone.html"
MEDIA_DIR = Path(tempfile.gettempdir()) / "gawah-second-phone"
MEDIA_TYPES = {
    "image/jpeg": "jpg", "image/png": "png", "image/webp": "webp",
    # a voice note, in the types WhatsApp and a browser's recorder give
    "audio/ogg": "ogg", "audio/mpeg": "mp3", "audio/mp4": "m4a", "audio/x-m4a": "m4a", "audio/amr": "amr",
    "audio/webm": "webm", "audio/wav": "wav", "audio/x-wav": "wav",
}
MEDIA_NAME = re.compile(r"[0-9a-f]{32}\.(jpg|png|webp|ogg|mp3|m4a|amr|webm|wav)")
MAX_MEDIA_BYTES = 16 * 1024 * 1024  # WhatsApp's own limit


class PhoneSettings(Settings):
    """Meta's app secret, read from the same .env as the whatsapp stream reads it, to sign a
    tap as Meta would. Shared values are kept as given."""

    meta_app_secret: SecretStr | None = None


def phone_settings(settings: Settings) -> PhoneSettings:
    if isinstance(settings, PhoneSettings) or hasattr(settings, "meta_app_secret"):
        return settings
    return PhoneSettings(**{name: getattr(settings, name) for name in Settings.model_fields})


class Tap(BaseModel):
    id: str  # the button's id, as the question was sent with it ("yes:<record id>")
    title: str


class Outgoing(BaseModel):
    phone: str
    text: str = ""
    media_url: str | None = None
    media_type: str | None = None
    profile_name: str = ""  # no name: the call fills it in, as for a WhatsApp profile with none
    button: Tap | None = None  # a reply button tapped, instead of words typed


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
        "MessageType": ("audio" if (msg.media_type or "").startswith("audio/") else "image") if msg.media_url else "text",
    }
    if msg.media_url:
        form["MediaUrl0"] = msg.media_url
        form["MediaContentType0"] = msg.media_type or "image/jpeg"
    return form


def meta_tap(msg: Outgoing) -> dict:
    """The payload Meta posts when a person taps a reply button."""
    digits = re.sub(r"\D", "", msg.phone)
    if not digits:
        raise ValueError("the phone number has no digits")
    tapped = {
        "from": digits, "id": f"wamid.{uuid4().hex}", "timestamp": str(int(time.time())), "type": "interactive",
        "interactive": {"type": "button_reply", "button_reply": {"id": msg.button.id, "title": msg.button.title}},
    }
    value = {
        "messaging_product": "whatsapp", "metadata": {"display_phone_number": "", "phone_number_id": "0"},
        "contacts": [{"wa_id": digits, "profile": {"name": msg.profile_name}}], "messages": [tapped],
    }
    return {"object": "whatsapp_business_account", "entry": [{"id": "0", "changes": [{"field": "messages", "value": value}]}]}


def meta_signature(app_secret: str, body: bytes) -> str:
    """X-Hub-Signature-256: HMAC-SHA256 of the raw body, keyed with the app secret."""
    return "sha256=" + hmac.new(app_secret.encode(), body, hashlib.sha256).hexdigest()


def signature(url: str, form: dict[str, str], auth_token: str) -> str:
    """X-Twilio-Signature: HMAC-SHA1 of the url followed by each field's name and value,
    in name order, keyed with the account's auth token."""
    signed = url + "".join(k + form[k] for k in sorted(form))
    return base64.b64encode(hmac.new(auth_token.encode(), signed.encode(), hashlib.sha1).digest()).decode()


def register(app: FastAPI) -> None:
    settings = phone_settings(app.state.settings)

    @app.get("/dashboard/phone", response_class=HTMLResponse)
    async def page() -> str:
        return PAGE.read_text()

    @app.post("/dashboard/media")
    async def upload(request: Request) -> dict[str, str]:
        """Keep an attached image or voice note and give it an address, as the provider would."""
        local_or_keyed(request)
        content_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
        if content_type not in MEDIA_TYPES:
            raise HTTPException(415, "attach a JPEG, PNG, or WebP image, or a voice note")
        body = await request.body()
        if not body or len(body) > MAX_MEDIA_BYTES:
            raise HTTPException(413, "the file is empty or larger than 16 MB")
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
        local_or_keyed(request)
        if not msg.text.strip() and not msg.media_url and not msg.button:
            raise HTTPException(422, "nothing to send")
        base = str(request.base_url).rstrip("/")
        transport = httpx.ASGITransport(app=request.app, raise_app_exceptions=False)
        if msg.button:
            try:
                body = json.dumps(meta_tap(msg)).encode()
            except ValueError as e:
                raise HTTPException(422, str(e)) from e
            headers = {"content-type": "application/json"}
            if settings.meta_app_secret:
                headers["X-Hub-Signature-256"] = meta_signature(settings.require("meta_app_secret"), body)
            async with httpx.AsyncClient(transport=transport, base_url=base, timeout=20.0) as client:
                response = await client.post(WHATSAPP_WEBHOOK_PATH, content=body, headers=headers)
            log.info("second phone %s tapped %s: %s", mask_phone(msg.phone), msg.button.title, response.status_code)
            return {"status": response.status_code, "path": WHATSAPP_WEBHOOK_PATH, "payload": json.loads(body)}
        try:
            form = provider_form(
                msg,
                to=settings.twilio_whatsapp_number or "+10000000000",
                account_sid=settings.require("twilio_account_sid") if settings.twilio_account_sid else "AC" + "0" * 32,
            )
        except ValueError as e:
            raise HTTPException(422, str(e)) from e
        headers = {}
        if settings.twilio_auth_token:
            # Twilio signs the public address it was given, so the intake checks against that.
            public = (settings.public_base_url or base).rstrip("/")
            headers["X-Twilio-Signature"] = signature(
                public + WHATSAPP_WEBHOOK_PATH, form, settings.require("twilio_auth_token")
            )
        async with httpx.AsyncClient(transport=transport, base_url=base, timeout=20.0) as client:
            response = await client.post(WHATSAPP_WEBHOOK_PATH, data=form, headers=headers)
        log.info(
            "second phone %s sent %s to %s: %s",
            mask_phone(form["WaId"]), form["MessageType"], WHATSAPP_WEBHOOK_PATH, response.status_code,
        )
        return {"status": response.status_code, "path": WHATSAPP_WEBHOOK_PATH, "form": form}
