"""Meta's WhatsApp Cloud API: send a message, show that Gawah is typing, download media a
person sent, check a webhook's signature and its verify handshake. The only file that
talks to Meta's Graph API."""

import hashlib
import hmac
import logging
import re

import httpx

from app.whatsapp.outgoing import Outgoing
from app.whatsapp.settings import WhatsAppSettings

GRAPH = "https://graph.facebook.com"
TIMEOUT = 15.0

# What a Graph error code means for Gawah, for the log.
HINTS = {
    131047: "more than 24 hours since this person last wrote to Gawah: they must send a message first",
    131030: "this number is not in the test number's list of allowed recipients",  # not in Meta's list today
    131009: "a reaction to a message more than 30 days old, deleted, or itself a reaction",
    131026: "the message could not be delivered to this number",
    131056: "too many messages to this person in a short time",
    130429: "the number's sending rate limit was hit",
    190: "the access token has expired or is wrong: make a new one",
    100: "a parameter in the message was refused",
}

logging.getLogger("httpx").setLevel(logging.WARNING)  # it logs every URL, phone number ids included


class MetaError(Exception):
    """Meta said no. Carries Graph's error code and message, with any phone number in the
    message cut to its last 4 digits, and what the code means for us."""

    def __init__(self, status: int, code: int | None, message: str = "") -> None:
        message = re.sub(r"\+?\d{7,}", lambda m: f"***{m.group()[-4:]}", message)
        hint = f" ({HINTS[code]})" if code in HINTS else ""
        super().__init__(f"meta http {status} code {code}: {message}{hint}")
        self.status, self.code = status, code


def signature(app_secret: str, body: bytes) -> str:
    """What Meta puts in X-Hub-Signature-256: HMAC-SHA256 of the raw body, keyed with the
    app secret, as 'sha256=' and lower-case hex."""
    return "sha256=" + hmac.new(app_secret.encode(), body, hashlib.sha256).hexdigest()


def payload(out: Outgoing) -> dict:
    """The JSON body of one message to Graph's /messages."""
    body: dict = {"messaging_product": "whatsapp", "recipient_type": "individual", "to": out.to.lstrip("+")}
    kind = (out.media_type or "").split("/")[0]
    if out.react_to:
        body |= {"type": "reaction", "reaction": {"message_id": out.react_to, "emoji": out.text}}
    elif out.media_url and kind == "audio":
        # No caption on audio. An OGG/Opus file can be shown as a voice note with a play button.
        audio = {"link": out.media_url} | ({"voice": True} if out.media_type == "audio/ogg" else {})
        body |= {"type": "audio", "audio": audio}
    elif out.media_url and kind in ("image", "video"):
        body |= {"type": kind, kind: _drop_none({"link": out.media_url, "caption": out.text})}
    elif out.media_url:
        body |= {"type": "document", "document": _drop_none(
            {"link": out.media_url, "caption": out.text, "filename": out.filename}
        )}
    elif out.buttons:
        body |= {"type": "interactive", "interactive": {
            "type": "button", "body": {"text": out.text},
            "action": {"buttons": [{"type": "reply", "reply": {"id": b.id, "title": b.title[:20]}} for b in out.buttons]},
        }}
    elif out.link and out.link_label:
        body |= {"type": "interactive", "interactive": {
            "type": "cta_url", "body": {"text": out.body_without_link()},
            "action": {"name": "cta_url", "parameters": {"display_text": out.link_label[:20], "url": out.link}},
        }}
    else:
        body |= {"type": "text", "text": {"body": out.text, "preview_url": False}}
    return body


def _drop_none(fields: dict) -> dict:
    return {k: v for k, v in fields.items() if v}


class Meta:
    rich = True  # buttons, link buttons, reactions, captions, typing
    # Meta allows 80 messages a second per number, and to one person about one every six
    # seconds with short bursts allowed. One at a time keeps them in order; a short gap is
    # all the pacing they need.
    spacing_seconds = 1.0

    def __init__(self, settings: WhatsAppSettings, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._settings, self._transport = settings, transport
        self.api = f"{GRAPH}/{settings.meta_graph_version}"

    def media_url(self, media_id: str) -> str:
        """The address of a file a person sent: Graph's own, so only the token opens it."""
        return f"{self.api}/{media_id}"

    def signed_by_meta(self, body: bytes, given: str | None) -> bool:
        if not given or not self._settings.meta_app_secret:
            return False
        return hmac.compare_digest(signature(self._settings.require("meta_app_secret"), body), given)

    def verify(self, mode: str | None, token: str | None, challenge: str | None) -> str | None:
        """The webhook handshake: the challenge to echo, or None if the token is wrong."""
        expected = self._settings.meta_verify_token
        if mode != "subscribe" or not token or not expected or challenge is None:
            return None
        return challenge if hmac.compare_digest(token, expected.get_secret_value()) else None

    async def send(self, out: Outgoing) -> str:
        """Send one message from the business number. Returns Meta's message id (a wamid)."""
        response = await self._request("POST", self._messages(), json=payload(out))
        return response.json()["messages"][0]["id"]

    async def typing(self, message_id: str) -> None:
        """Mark the person's message read and show 'typing...' until Gawah answers (or 25 s)."""
        await self._request("POST", self._messages(), json={
            "messaging_product": "whatsapp", "status": "read", "message_id": message_id,
            "typing_indicator": {"type": "text"},
        })

    async def fetch_media(self, url: str) -> tuple[bytes, str | None]:
        """Download a file a person sent. Graph gives a short-lived address for a media id,
        and that address also needs the token. Any other link (a local test image) is
        fetched as it is."""
        if not url.startswith(self.api + "/"):
            response = await self._request("GET", url, auth=False)
            return response.content, response.headers.get("content-type")
        about = (await self._request("GET", url)).json()
        response = await self._request("GET", about["url"])
        return response.content, about.get("mime_type") or response.headers.get("content-type")

    def _messages(self) -> str:
        return f"{self.api}/{self._settings.require('meta_phone_number_id')}/messages"

    async def _request(self, method: str, url: str, auth: bool = True, **kwargs) -> httpx.Response:
        headers = {"Authorization": f"Bearer {self._settings.require('meta_whatsapp_token')}"} if auth else {}
        async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True, transport=self._transport) as client:
            for attempt in (1, 2):
                try:
                    response = await client.request(method, url, headers=headers, **kwargs)
                except httpx.TransportError:
                    if attempt == 2:
                        raise
                    continue
                if response.status_code < 500 or attempt == 2:
                    break
        if response.status_code >= 400:
            error = {}
            if response.headers.get("content-type", "").startswith(("application/json", "text/javascript")):
                error = response.json().get("error") or {}
            detail = (error.get("error_data") or {}).get("details") or error.get("message", "")
            raise MetaError(response.status_code, error.get("code"), detail)
        return response
